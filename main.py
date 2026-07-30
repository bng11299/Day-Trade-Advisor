"""
Day Trade Bot — live paper trading mode (real-time Alpaca stream).

Prerequisites:
    Set environment variables:
        ALPACA_API_KEY=<your key>
        ALPACA_SECRET_KEY=<your secret>

Usage:
    python main.py

Commands (typed while running):
    add SYMBOL     — subscribe to ticker and add to watchlist
    remove SYMBOL  — unsubscribe and remove
    list           — show watchlist + open positions
    status         — show account equity
    quit           — close all positions and exit
"""

import os
import sys
import threading
import time
from datetime import datetime, timezone

import watchlist
from engine.aggregator import SignalAggregator
from engine.risk import RiskManager
from broker.alpaca import AlpacaBroker
from broker.data import LiveBarStream, fetch_prev_close
from strategies.base import Direction

EOD_CLOSE_UTC_HOUR = 20   # 3:45pm ET = 20:45 UTC
EOD_CLOSE_UTC_MINUTE = 45
DAILY_LOSS_LIMIT_PCT = 0.02


def eod_monitor(broker: AlpacaBroker, stop_event: threading.Event, start_equity: float):
    """Background thread: force-closes all positions at EOD and enforces daily loss limit."""
    halted = False
    last_halt_date = None

    while not stop_event.is_set():
        now = datetime.now(timezone.utc)
        today = now.date()

        # Reset halt each new trading day
        if last_halt_date != today:
            halted = False

        if not halted:
            # Daily loss limit check
            try:
                acct = broker.get_account()
                daily_loss = (acct["equity"] - start_equity) / start_equity
                if daily_loss < -DAILY_LOSS_LIMIT_PCT:
                    print(f"\n[risk] Daily loss limit hit ({daily_loss:.1%}). Closing all positions.")
                    broker.close_all_positions()
                    halted = True
                    last_halt_date = today
            except Exception:
                pass

        # EOD force-close
        past_eod = now.hour > EOD_CLOSE_UTC_HOUR or (
            now.hour == EOD_CLOSE_UTC_HOUR and now.minute >= EOD_CLOSE_UTC_MINUTE
        )
        if past_eod:
            try:
                positions = broker.get_positions()
                if positions:
                    print(f"\n[EOD] Market close — closing {len(positions)} position(s).")
                    broker.close_all_positions()
            except Exception:
                pass

        time.sleep(30)


def make_on_bar(
    broker: AlpacaBroker,
    aggregator: SignalAggregator,
    risk_mgr: RiskManager,
    uvxy_state: dict,
):
    """Returns a callback invoked on every real-time bar for a symbol."""

    def on_bar(symbol: str, df):
        # UVXY regime tracker — update fear gauge, don't evaluate as a trade
        if symbol == "UVXY":
            prev = uvxy_state.get("prev_close")
            if prev:
                current = float(df["Close"].iloc[-1])
                uvxy_state["pct"] = (current - prev) / prev * 100
                bump = SignalAggregator._uvxy_threshold_bump(uvxy_state["pct"])
                if bump > 0:
                    print(f"\n[UVXY] {uvxy_state['pct']:+.1f}%  → confidence threshold +{bump:.2f}", flush=True)
            return

        acct = broker.get_account()
        risk_mgr.account_value = acct["equity"]
        open_positions = {p["symbol"] for p in broker.get_positions()}

        agg = aggregator.analyze(df, uvxy_pct=uvxy_state.get("pct", 0.0))
        print(f"\n[bar] {symbol}: {agg}")

        if agg.direction == Direction.HOLD:
            return

        if symbol in open_positions:
            print(f"  Already holding {symbol}, skipping.")
            return

        params = risk_mgr.calculate(symbol, df, agg.direction)
        if params is None:
            print(f"  Risk calc failed for {symbol}")
            return

        print(f"  TRADE -> {params}")
        try:
            result = broker.submit_order(params)
            print(f"  Order: {result}")
        except Exception as e:
            print(f"  Order failed: {e}")

    return on_bar


def input_loop(broker: AlpacaBroker, stream: LiveBarStream, stop_event: threading.Event):
    while not stop_event.is_set():
        try:
            raw = input().strip()
        except (EOFError, KeyboardInterrupt):
            break

        parts = raw.split()
        if not parts:
            continue
        cmd = parts[0].lower()

        if cmd == "add" and len(parts) > 1:
            sym = parts[1].upper()
            stream.add_symbol(sym)
            if watchlist.add(sym):
                print(f"Added {sym} — streaming bars.")
            else:
                print(f"{sym} already in watchlist.")

        elif cmd == "remove" and len(parts) > 1:
            sym = parts[1].upper()
            stream.remove_symbol(sym)
            if watchlist.remove(sym):
                print(f"Removed {sym}.")
            else:
                print(f"{sym} not in watchlist.")

        elif cmd == "list":
            print(f"Watchlist: {watchlist.load()}")
            print(f"Positions: {broker.get_positions()}")

        elif cmd == "status":
            print(f"Account: {broker.get_account()}")

        elif cmd == "quit":
            print("Closing all positions and exiting...")
            broker.close_all_positions()
            stream.stop()
            stop_event.set()
            break

        else:
            print("Commands: add SYMBOL | remove SYMBOL | list | status | quit")


def main():
    api_key = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        print("ERROR: Set ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables.")
        sys.exit(1)

    broker = AlpacaBroker(api_key=api_key, secret_key=secret_key, paper=True)
    aggregator = SignalAggregator(long_only=True)  # matches backtest config
    acct = broker.get_account()
    risk_mgr = RiskManager(account_value=acct["equity"])

    # UVXY regime tracker state — shared across all bar callbacks
    uvxy_prev = fetch_prev_close("UVXY", api_key, secret_key)
    uvxy_state = {"prev_close": uvxy_prev, "pct": 0.0}
    if uvxy_prev:
        print(f"UVXY prev close: ${uvxy_prev:.2f}  (fear gauge active)")

    stream = LiveBarStream(api_key=api_key, secret_key=secret_key, buffer=120)

    # Pre-load watchlist + UVXY into stream (UVXY gated out of order logic)
    symbols = watchlist.load()
    stream_symbols = symbols + (["UVXY"] if "UVXY" not in symbols else [])
    callback = make_on_bar(broker, aggregator, risk_mgr, uvxy_state)
    stream.subscribe(stream_symbols, callback)

    print(f"Day Trade Bot started (paper trading, real-time stream)")
    print(f"Account equity: ${acct['equity']:.2f}")
    print(f"Watchlist: {symbols or '(empty — use add SYMBOL)'}")
    print("Commands: add SYMBOL | remove SYMBOL | list | status | quit\n")
    print("Waiting for market-hours bars... (no output outside market hours)\n")

    stream.start()

    stop_event = threading.Event()
    threading.Thread(
        target=eod_monitor, args=(broker, stop_event, acct["equity"]), daemon=True
    ).start()

    input_loop(broker, stream, stop_event)

    print("Bot stopped.")


if __name__ == "__main__":
    main()
