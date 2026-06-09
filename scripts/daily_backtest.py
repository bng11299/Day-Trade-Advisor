"""
Live shadow runner — runs during market hours alongside the live bot.

For each bar received from the Alpaca stream, it runs the full strategy stack
and logs what it WOULD do. At market close it pulls actual paper trades from
Alpaca and compares signal vs execution, exposing slippage, missed fills, or
strategy drift. Results are saved per-day and rolled into a 30-day summary.

Triggered at 9:30am ET by Task Scheduler (see scripts/schedule.ps1).
Runs until market close (~4pm ET), then saves the day's report and exits.

Run manually (will wait for market hours if run early):
    python scripts/daily_backtest.py
"""

import json
import os
import sys
import csv
import math
import time
import threading
from collections import deque
from datetime import datetime, timedelta, date, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alpaca.data.live import StockDataStream
from alpaca.data.enums import DataFeed
from alpaca.trading.client import TradingClient
from engine.aggregator import SignalAggregator
from engine.risk import RiskManager
from backtest.runner import summarize
from strategies.base import Direction
import pandas as pd

# ── configuration ─────────────────────────────────────────────────────────────
_WATCHLIST_FILE = ROOT / "watchlist.json"
_FALLBACK_SYMBOLS = ["NVDA", "TSLA"]

def _load_symbols() -> list[str]:
    if _WATCHLIST_FILE.exists():
        with open(_WATCHLIST_FILE) as f:
            syms = json.load(f)
        if syms:
            return syms
    return _FALLBACK_SYMBOLS

SYMBOLS     = _load_symbols()
ACCOUNT     = 100_000.0
LONG_ONLY   = True
PERIOD_DAYS = 30
BAR_BUFFER  = 120   # rolling bars kept per symbol for strategy lookback

ET = ZoneInfo("America/New_York")
MARKET_OPEN  = (9, 30)   # ET hour, minute
MARKET_CLOSE = (16, 0)

STATE_FILE   = ROOT / "scripts" / "state.json"
RESULTS_DIR  = ROOT / "backtest" / "daily"
SUMMARY_FILE = ROOT / "backtest" / "30day_summary.csv"


# ── state helpers ─────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def today_et() -> date:
    return datetime.now(ET).date()


def now_et() -> datetime:
    return datetime.now(ET)


def is_market_open() -> bool:
    now = now_et()
    if now.weekday() >= 5:
        return False
    after_open  = (now.hour, now.minute) >= MARKET_OPEN
    before_close = (now.hour, now.minute) < MARKET_CLOSE
    return after_open and before_close


def wait_for_market_open():
    """Block until market opens. Prints a countdown."""
    while not is_market_open():
        now = now_et()
        if now.weekday() >= 5:
            print(f"  Weekend — market opens Monday. Checking again in 1 hour.")
            time.sleep(3600)
            continue
        open_today = now.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0)
        if now < open_today:
            wait_sec = int((open_today - now).total_seconds())
            print(f"  Market opens at 9:30am ET. Waiting {wait_sec // 60}m {wait_sec % 60}s ...")
            time.sleep(min(wait_sec, 60))
        else:
            # Past close for today
            print("  Market is closed for today. Exiting.")
            sys.exit(0)


# ── shadow signal logger ──────────────────────────────────────────────────────

class ShadowRunner:
    """
    Subscribes to the same Alpaca bar stream as the live bot.
    On every bar: runs the strategy, logs the signal and what trade it would place.
    Does NOT submit orders — observation only.
    """

    def __init__(self, api_key: str, secret_key: str):
        self.api_key    = api_key
        self.secret_key = secret_key
        self.aggregator = SignalAggregator(long_only=LONG_ONLY)
        self.risk_mgr   = RiskManager(account_value=ACCOUNT)
        self.buffers: dict[str, deque] = {s: deque(maxlen=BAR_BUFFER) for s in SYMBOLS}
        self.signal_log: list[dict] = []
        self._stream: StockDataStream | None = None
        self._thread: threading.Thread | None = None
        self._loop = None

    async def _on_bar(self, bar):
        sym = bar.symbol
        if sym not in self.buffers:
            return

        row = {
            "Open":   bar.open,
            "High":   bar.high,
            "Low":    bar.low,
            "Close":  bar.close,
            "Volume": bar.volume,
        }
        self.buffers[sym].append((bar.timestamp, row))

        if len(self.buffers[sym]) < 30:
            return  # need enough history for strategies

        df = pd.DataFrame(
            [r for _, r in self.buffers[sym]],
            index=pd.DatetimeIndex([t for t, _ in self.buffers[sym]]),
        )

        agg = self.aggregator.analyze(df)
        params = None
        if agg.direction != Direction.HOLD:
            self.risk_mgr.account_value = ACCOUNT
            params = self.risk_mgr.calculate(sym, df, agg.direction)

        entry = {
            "time":       bar.timestamp.isoformat(),
            "symbol":     sym,
            "close":      bar.close,
            "signal":     agg.direction.value,
            "confidence": agg.confidence,
            "reason":     str(agg),
            "would_entry":     params.entry      if params else None,
            "would_stop":      params.stop_loss  if params else None,
            "would_target":    params.take_profit if params else None,
            "would_shares":    params.shares     if params else None,
            "would_risk":      params.risk_amount if params else None,
        }
        self.signal_log.append(entry)

        tag = f"[{agg.direction.value}]" if agg.direction != Direction.HOLD else "[----]"
        print(f"  {bar.timestamp.astimezone(ET).strftime('%H:%M')} {sym} {tag} conf={agg.confidence:.2f}  close={bar.close:.2f}", flush=True)

    def _run(self):
        import asyncio
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stream = StockDataStream(self.api_key, self.secret_key, feed=DataFeed.IEX)
        self._stream.subscribe_bars(self._on_bar, *SYMBOLS)
        self._loop.run_until_complete(self._stream.run())

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"  Shadow stream started. Watching: {SYMBOLS}")

    def stop(self):
        if self._stream and self._loop:
            self._loop.call_soon_threadsafe(
                lambda: self._loop.create_task(self._stream.stop_ws())
            )


# ── alpaca trade fetcher ──────────────────────────────────────────────────────

def fetch_actual_trades(api_key: str, secret_key: str, target_date: date) -> list[dict]:
    """Pull completed paper orders from Alpaca for the given date."""
    client = TradingClient(api_key, secret_key, paper=True)
    try:
        orders = client.get_orders()
    except Exception as e:
        print(f"  Could not fetch orders: {e}")
        return []

    trades = []
    for o in orders:
        if not o.filled_at:
            continue
        filled_date = o.filled_at.astimezone(ET).date()
        if filled_date != target_date:
            continue
        trades.append({
            "time":      o.filled_at.isoformat(),
            "symbol":    o.symbol,
            "side":      o.side.value,
            "qty":       float(o.qty),
            "fill_price": float(o.filled_avg_price) if o.filled_avg_price else None,
            "status":    o.status.value,
        })
    return trades


# ── comparison report ─────────────────────────────────────────────────────────

def compare_and_report(signal_log: list[dict], actual_trades: list[dict],
                       day_num: int, target_date: date) -> dict:
    """
    Compare what the shadow strategy signalled vs what the live bot actually traded.
    Returns a summary dict for the 30-day roll-up.
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Save signal log
    sig_file = RESULTS_DIR / f"day{day_num:02d}_{target_date}_signals.csv"
    if signal_log:
        with open(sig_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=signal_log[0].keys())
            writer.writeheader()
            writer.writerows(signal_log)

    # Save actual trades
    act_file = RESULTS_DIR / f"day{day_num:02d}_{target_date}_actual.csv"
    if actual_trades:
        with open(act_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=actual_trades[0].keys())
            writer.writeheader()
            writer.writerows(actual_trades)

    # Count shadow signals that called a trade
    shadow_buys  = sum(1 for s in signal_log if s["signal"] == "BUY"  and s["would_entry"])
    shadow_sells = sum(1 for s in signal_log if s["signal"] == "SELL" and s["would_entry"])
    actual_buys  = sum(1 for t in actual_trades if t["side"] == "buy")
    actual_sells = sum(1 for t in actual_trades if t["side"] == "sell")

    alignment = "N/A"
    if shadow_buys + shadow_sells > 0:
        matched = min(shadow_buys, actual_buys) + min(shadow_sells, actual_sells)
        total   = max(shadow_buys + shadow_sells, actual_buys + actual_sells)
        alignment = f"{matched / total:.0%}" if total else "N/A"

    print(f"\n  {'─'*45}")
    print(f"  Day {day_num} wrap-up  |  {target_date.strftime('%A %b %d')}")
    print(f"  {'─'*45}")
    print(f"  Shadow signals  — BUY: {shadow_buys}  SELL: {shadow_sells}")
    print(f"  Live bot trades — BUY: {actual_buys}  SELL: {actual_sells}")
    print(f"  Signal alignment: {alignment}")
    print(f"  Signal log  → {sig_file.name}")
    print(f"  Actual trades → {act_file.name}")

    return {
        "day":           day_num,
        "date":          target_date.isoformat(),
        "shadow_signals": shadow_buys + shadow_sells,
        "actual_trades":  actual_buys + actual_sells,
        "alignment":      alignment,
        "total_bars":     len(signal_log),
    }


# ── 30-day summary ────────────────────────────────────────────────────────────

def append_to_summary(row: dict):
    SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_header = not SUMMARY_FILE.exists()
    with open(SUMMARY_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def print_30day_report():
    if not SUMMARY_FILE.exists():
        print("No summary data yet.")
        return

    with open(SUMMARY_FILE) as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return

    total_signals = sum(int(r["shadow_signals"]) for r in rows)
    total_actual  = sum(int(r["actual_trades"])  for r in rows)
    active_days   = sum(1 for r in rows if int(r["shadow_signals"]) > 0)

    print("\n" + "=" * 55)
    print("       30-DAY LIVE SHADOW BACKTEST — FINAL REPORT")
    print("=" * 55)
    print(f"  Period:           {rows[0]['date']}  →  {rows[-1]['date']}")
    print(f"  Active days:      {active_days} / {len(rows)}")
    print(f"  Total signals:    {total_signals}")
    print(f"  Total live trades:{total_actual}")
    print(f"  Avg signals/day:  {total_signals / max(active_days, 1):.1f}")
    print("=" * 55)
    print(f"\nFull breakdown: {SUMMARY_FILE}")
    print("Per-day signals + actual trades: backtest/daily/")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    api_key    = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        print("ERROR: Set ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables.")
        sys.exit(1)

    state   = load_state()
    today   = today_et()

    # ── guard: skip weekends ──────────────────────────────────────────────────
    if today.weekday() >= 5:
        print(f"Today is a weekend. No market. Exiting.")
        return

    # ── guard: already ran today ──────────────────────────────────────────────
    if state.get("last_run") == today.isoformat():
        print(f"Shadow runner already completed for {today}. Exiting.")
        if state.get("completed"):
            print_30day_report()
        return

    # ── guard: 30-day period complete ─────────────────────────────────────────
    if state.get("completed"):
        print("30-day period complete.")
        print_30day_report()
        return

    # ── initialize ────────────────────────────────────────────────────────────
    if not state:
        state = {"start_date": today.isoformat(), "current_day": 1,
                 "last_run": None, "completed": False}
        print(f"Starting 30-day live shadow period. Day 1 of {PERIOD_DAYS}.")

    day_num = state["current_day"]
    print(f"\n{'='*55}")
    print(f" Day {day_num} of {PERIOD_DAYS}  |  {today.strftime('%A, %B %d %Y')}")
    print(f"{'='*55}")

    # ── wait for market open ──────────────────────────────────────────────────
    print("\nWaiting for market open (9:30am ET)...")
    wait_for_market_open()
    print(f"Market is open. Shadow runner active. Watching: {SYMBOLS}\n")

    # ── start shadow stream ───────────────────────────────────────────────────
    runner = ShadowRunner(api_key, secret_key)
    runner.start()

    # ── run until market close ────────────────────────────────────────────────
    while is_market_open():
        time.sleep(15)

    print("\nMarket closed. Stopping stream...")
    runner.stop()
    time.sleep(3)  # let final bars flush

    # ── fetch actual live bot trades from Alpaca ──────────────────────────────
    print("Fetching actual paper trades from Alpaca...")
    actual_trades = fetch_actual_trades(api_key, secret_key, today)
    print(f"  {len(actual_trades)} order(s) filled today.")

    # ── compare and save ──────────────────────────────────────────────────────
    summary_row = compare_and_report(runner.signal_log, actual_trades, day_num, today)
    append_to_summary(summary_row)

    # ── update state ──────────────────────────────────────────────────────────
    state["last_run"]    = today.isoformat()
    state["current_day"] = day_num + 1

    if day_num >= PERIOD_DAYS:
        state["completed"] = True
        save_state(state)
        print_30day_report()
    else:
        save_state(state)
        print(f"\n  {PERIOD_DAYS - day_num} day(s) remaining. See you tomorrow at market open.")


if __name__ == "__main__":
    main()
