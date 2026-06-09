"""
Daily backtest script — runs automatically after market close each day.

Tracks a 30-day paper-trading period:
  - Day 1: establishes the baseline
  - Each subsequent day: appends one more day of results
  - Day 30: prints a full 30-day performance report and marks the period complete

State is persisted in scripts/state.json so the script picks up where it left off
if the machine was off or the script missed a run.

Run manually:
    python scripts/daily_backtest.py

Scheduled automatically via scripts/schedule.ps1 (runs at 5:00pm ET on weekdays).
"""

import json
import os
import sys
import csv
import math
from datetime import datetime, timedelta, date, timezone
from pathlib import Path

# ── resolve project root regardless of where script is called from ────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backtest.runner import run_backtest, summarize, save_trades
from broker.data import fetch_bars
from strategies.base import Direction

# ── configuration ─────────────────────────────────────────────────────────────
SYMBOLS       = ["NVDA", "TSLA"]          # symbols to track
INTERVAL      = "5m"                      # bar resolution
ACCOUNT       = 100_000.0                 # match Alpaca paper account
LONG_ONLY     = True                      # match live bot config
PERIOD_DAYS   = 30                        # total tracking period

STATE_FILE    = ROOT / "scripts" / "state.json"
RESULTS_DIR   = ROOT / "backtest" / "daily"
SUMMARY_FILE  = ROOT / "backtest" / "30day_summary.csv"


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def is_weekday(d: date) -> bool:
    return d.weekday() < 5  # Mon–Fri


def last_trading_day() -> date:
    """Most recent weekday on or before today."""
    d = date.today()
    while not is_weekday(d):
        d -= timedelta(days=1)
    return d


def fetch_day(symbol: str, target_date: date, api_key: str, secret_key: str):
    """Fetch one day of intraday bars for a symbol."""
    start = target_date.strftime("%Y-%m-%d")
    end   = (target_date + timedelta(days=1)).strftime("%Y-%m-%d")
    return fetch_bars(symbol, start, end, interval=INTERVAL,
                      api_key=api_key, secret_key=secret_key)


def run_day(target_date: date, api_key: str, secret_key: str) -> tuple[list[dict], dict]:
    """Run backtest for a single trading day across all symbols. Returns trades + summary."""
    all_trades = []
    account = ACCOUNT

    for symbol in SYMBOLS:
        print(f"  Fetching {symbol} for {target_date} ...")
        try:
            df = fetch_day(symbol, target_date, api_key, secret_key)
        except Exception as e:
            print(f"    Error: {e}")
            continue

        if df.empty or len(df) < 30:
            print(f"    {symbol}: no data (market closed or holiday).")
            continue

        print(f"    {len(df)} bars loaded.")
        trades = run_backtest(symbol, df, account, long_only=LONG_ONLY)
        all_trades.extend(trades)
        if trades:
            account = trades[-1]["account_after"]
        print(f"    {len(trades)} trades → account ${account:,.2f}")

    summary = summarize(all_trades, ACCOUNT)
    return all_trades, summary


def append_to_summary(day_num: int, target_date: date, summary: dict, num_trades: int):
    """Append one row to the running 30-day CSV summary."""
    SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_header = not SUMMARY_FILE.exists()

    with open(SUMMARY_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow([
                "day", "date", "trades", "wins", "losses", "win_rate",
                "daily_pnl", "daily_return_pct", "avg_win", "avg_loss",
                "max_drawdown_pct", "sharpe"
            ])
        writer.writerow([
            day_num,
            target_date.isoformat(),
            summary.get("trades", 0),
            summary.get("wins", 0),
            summary.get("losses", 0),
            summary.get("win_rate", 0),
            summary.get("total_pnl", 0),
            summary.get("total_return_pct", 0),
            summary.get("avg_win", 0),
            summary.get("avg_loss", 0),
            summary.get("max_drawdown_pct", 0),
            summary.get("sharpe", 0),
        ])


def print_30day_report():
    """Read the 30-day summary CSV and print a final report."""
    if not SUMMARY_FILE.exists():
        print("No summary data found.")
        return

    rows = []
    with open(SUMMARY_FILE) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return

    total_trades = sum(int(r["trades"]) for r in rows)
    total_wins   = sum(int(r["wins"]) for r in rows)
    total_pnl    = sum(float(r["daily_pnl"]) for r in rows)
    trading_days = sum(1 for r in rows if int(r["trades"]) > 0)
    win_rate     = total_wins / total_trades if total_trades else 0

    daily_pnls = [float(r["daily_pnl"]) for r in rows]
    equity = ACCOUNT
    peak = equity
    max_dd = 0.0
    for pnl in daily_pnls:
        equity += pnl
        peak = max(peak, equity)
        dd = (peak - equity) / peak
        max_dd = max(max_dd, dd)

    if len(daily_pnls) > 1:
        mean = sum(daily_pnls) / len(daily_pnls)
        var  = sum((p - mean) ** 2 for p in daily_pnls) / (len(daily_pnls) - 1)
        std  = math.sqrt(var) if var > 0 else 1e-9
        sharpe = (mean / std) * math.sqrt(252)
    else:
        sharpe = 0.0

    print("\n" + "=" * 55)
    print("       30-DAY PAPER TRADING BACKTEST — FINAL REPORT")
    print("=" * 55)
    print(f"  Period:          {rows[0]['date']}  →  {rows[-1]['date']}")
    print(f"  Active days:     {trading_days} / {len(rows)}")
    print(f"  Total trades:    {total_trades}")
    print(f"  Win rate:        {win_rate:.1%}")
    print(f"  Total P&L:       ${total_pnl:,.2f}")
    print(f"  Total return:    {total_pnl / ACCOUNT * 100:.2f}%")
    print(f"  Max drawdown:    {max_dd * 100:.2f}%")
    print(f"  Sharpe ratio:    {sharpe:.2f}")
    print("=" * 55)
    print(f"\nFull daily breakdown saved to: {SUMMARY_FILE}")

    if total_pnl > 0 and max_dd < 0.15 and sharpe > 1.0:
        print("\n✅ Results look solid. Consider switching to live trading.")
        print("   In broker/alpaca.py: change paper=True to paper=False.")
    else:
        print("\n⚠️  Results need more tuning before going live.")
        if max_dd >= 0.15:
            print(f"   Max drawdown {max_dd*100:.1f}% is above 15% target.")
        if sharpe < 1.0:
            print(f"   Sharpe {sharpe:.2f} is below 1.0 target.")
        if total_pnl <= 0:
            print("   Strategy was not profitable over this period.")


def main():
    api_key    = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        print("ERROR: Set ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables.")
        sys.exit(1)

    state = load_state()
    today = last_trading_day()

    # ── initialize on first run ───────────────────────────────────────────────
    if not state:
        state = {
            "start_date": today.isoformat(),
            "current_day": 1,
            "last_run": None,
            "completed": False,
        }
        print(f"Starting 30-day paper trading backtest period. Day 1 of {PERIOD_DAYS}.")
        print(f"Start date: {today}\n")

    if state.get("completed"):
        print("30-day period already completed. See backtest/30day_summary.csv for results.")
        print_30day_report()
        return

    # ── skip if already ran today ─────────────────────────────────────────────
    if state.get("last_run") == today.isoformat():
        print(f"Already ran for {today}. Next run tomorrow.")
        return

    day_num = state["current_day"]
    print(f"{'='*55}")
    print(f" Day {day_num} of {PERIOD_DAYS}  |  {today.strftime('%A, %B %d %Y')}")
    print(f"{'='*55}")

    # ── run the backtest for today ────────────────────────────────────────────
    trades, summary = run_day(today, api_key, secret_key)

    # ── save per-day trade log ────────────────────────────────────────────────
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    day_file = RESULTS_DIR / f"day{day_num:02d}_{today.isoformat()}.csv"
    save_trades(trades, str(day_file))

    # ── print today's summary ─────────────────────────────────────────────────
    print(f"\n  Day {day_num} results:")
    for k, v in summary.items():
        print(f"    {k}: {v}")

    # ── append to running summary ─────────────────────────────────────────────
    append_to_summary(day_num, today, summary, len(trades))

    # ── update state ──────────────────────────────────────────────────────────
    state["last_run"]   = today.isoformat()
    state["current_day"] = day_num + 1

    if day_num >= PERIOD_DAYS:
        state["completed"] = True
        save_state(state)
        print_30day_report()
    else:
        save_state(state)
        remaining = PERIOD_DAYS - day_num
        print(f"\n  {remaining} day(s) remaining in the 30-day period.")
        print(f"  Next run: tomorrow after market close.")


if __name__ == "__main__":
    main()
