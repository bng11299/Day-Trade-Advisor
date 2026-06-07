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

import watchlist
from engine.aggregator import SignalAggregator
from engine.risk import RiskManager
from broker.alpaca import AlpacaBroker
from broker.data import LiveBarStream
from strategies.base import Direction


def make_on_bar(broker: AlpacaBroker, aggregator: SignalAggregator, risk_mgr: RiskManager):
    """Returns a callback invoked on every real-time bar for a symbol."""

    def on_bar(symbol: str, df):
        acct = broker.get_account()
        risk_mgr.account_value = acct["equity"]
        open_positions = {p["symbol"] for p in broker.get_positions()}

        agg = aggregator.analyze(df)
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
    aggregator = SignalAggregator()
    acct = broker.get_account()
    risk_mgr = RiskManager(account_value=acct["equity"])

    stream = LiveBarStream(api_key=api_key, secret_key=secret_key, buffer=120)

    # Pre-load watchlist into stream
    symbols = watchlist.load()
    if symbols:
        stream.subscribe(symbols, make_on_bar(broker, aggregator, risk_mgr))
    else:
        # Still wire the callback so add_symbol works later
        stream.subscribe([], make_on_bar(broker, aggregator, risk_mgr))

    print(f"Day Trade Bot started (paper trading, real-time stream)")
    print(f"Account equity: ${acct['equity']:.2f}")
    print(f"Watchlist: {symbols or '(empty — use add SYMBOL)'}")
    print("Commands: add SYMBOL | remove SYMBOL | list | status | quit\n")
    print("Waiting for market-hours bars... (no output outside market hours)\n")

    stream.start()

    stop_event = threading.Event()
    input_loop(broker, stream, stop_event)

    print("Bot stopped.")


if __name__ == "__main__":
    main()
