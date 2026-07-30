"""
Historical backtest replay — fills gaps in the 30-day shadow log.

Fetches 1-minute bars from Alpaca for each requested trading day, replays
them through the identical 1→5-min aggregation and SignalAggregator pipeline
used by the live shadow runner.  No future data is used: bars are fed in
chronological order into a rolling buffer that only ever sees the past.

UVXY prev-close is fetched from the day *before* each target date so the
regime filter uses only information that would have been available at open.

Usage:
    python scripts/historical_backtest.py [--dates 2026-06-19 2026-06-20] [--day-start 7]
    python scripts/historical_backtest.py           # auto-detect missing days
"""

import argparse
import csv
import json
import os
import sys
from collections import deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.enums import DataFeed

from engine.aggregator import SignalAggregator
from engine.risk import RiskManager
from broker.data import fetch_bars
from strategies.base import Direction

ET = ZoneInfo("America/New_York")
MARKET_OPEN_H, MARKET_OPEN_M   = 9, 30
MARKET_CLOSE_H, MARKET_CLOSE_M = 16,  0

WATCHLIST_FILE = ROOT / "watchlist.json"
FALLBACK_SYMBOLS = ["NVDA", "TSLA"]
RESULTS_DIR  = ROOT / "backtest" / "daily"
SUMMARY_FILE = ROOT / "backtest" / "30day_summary.csv"
STATE_FILE   = ROOT / "scripts" / "state.json"
BAR_BUFFER   = 120
ACCOUNT      = 100_000.0
LONG_ONLY    = True


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load_symbols() -> list[str]:
    if WATCHLIST_FILE.exists():
        syms = json.loads(WATCHLIST_FILE.read_text())
        if syms:
            return syms
    return FALLBACK_SYMBOLS


def _api_keys() -> tuple[str, str]:
    key    = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_SECRET_KEY")
    if not key or not secret:
        sys.exit("ERROR: Set ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables.")
    return key, secret


def _is_market_day(d: date) -> bool:
    return d.weekday() < 5  # Mon-Fri only; holiday check omitted (rare)


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _existing_days() -> set[str]:
    """Dates already covered in the 30-day summary."""
    if not SUMMARY_FILE.exists():
        return set()
    with open(SUMMARY_FILE) as f:
        return {row["date"] for row in csv.DictReader(f)}


def _fetch_1min_bars(
    symbol: str,
    target_date: date,
    api_key: str,
    secret_key: str,
) -> pd.DataFrame:
    """
    Pull 1-minute bars for *symbol* on *target_date*, market hours only (ET).
    Returns DataFrame indexed by UTC timestamp, columns Open/High/Low/Close/Volume.
    """
    client = StockHistoricalDataClient(api_key, secret_key)
    # Request the full calendar day; we'll filter to market hours below.
    start_utc = datetime(target_date.year, target_date.month, target_date.day,
                         tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
    end_utc   = start_utc + timedelta(days=1)

    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame(1, TimeFrameUnit.Minute),
        start=start_utc,
        end=end_utc,
        feed=DataFeed.IEX,
    )
    bars = client.get_stock_bars(req)
    df = bars.df
    if df.empty:
        return df

    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")

    df.index = pd.to_datetime(df.index, utc=True)
    df.columns = [c.capitalize() for c in df.columns]
    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[keep].dropna()

    # Filter to regular market hours in ET
    df_et = df.copy()
    df_et.index = df_et.index.tz_convert(ET)
    open_time  = df_et.index.time >= __import__("datetime").time(MARKET_OPEN_H,  MARKET_OPEN_M)
    close_time = df_et.index.time <  __import__("datetime").time(MARKET_CLOSE_H, MARKET_CLOSE_M)
    df = df[open_time & close_time]
    return df


def _fetch_uvxy_prev_close(target_date: date, api_key: str, secret_key: str) -> float | None:
    """
    Return UVXY's closing price from the trading day *before* target_date.
    This is exactly the information available at market open — no future data.
    """
    prev = target_date - timedelta(days=1)
    # Step back over weekends
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    try:
        df = fetch_bars(
            "UVXY",
            prev.strftime("%Y-%m-%d"),
            target_date.strftime("%Y-%m-%d"),   # exclusive end
            interval="1d",
            api_key=api_key,
            secret_key=secret_key,
        )
        return float(df["Close"].iloc[-1]) if not df.empty else None
    except Exception as e:
        print(f"  [UVXY prev-close] warning: {e}")
        return None


# ---------------------------------------------------------------------------
# per-day replay
# ---------------------------------------------------------------------------

def replay_day(
    target_date: date,
    day_num: int,
    symbols: list[str],
    api_key: str,
    secret_key: str,
) -> dict:
    """
    Replay one trading day historically through the full signal pipeline.
    Returns the summary row dict (same schema as the live shadow runner).
    """
    print(f"\n{'='*55}")
    print(f" Day {day_num} replay  |  {target_date.strftime('%A, %B %d %Y')}")
    print(f"{'='*55}")

    # Fetch UVXY prev-close so regime filter matches what the live runner would have seen
    uvxy_prev_close = _fetch_uvxy_prev_close(target_date, api_key, secret_key)
    print(f"  UVXY prev close: ${uvxy_prev_close:.2f}" if uvxy_prev_close else "  UVXY prev close: unavailable")

    # Fetch 1-min bars for every symbol + UVXY
    all_symbols = symbols + (["UVXY"] if "UVXY" not in symbols else [])
    print(f"  Fetching 1-min bars for {len(all_symbols)} symbols...", flush=True)

    bars_by_sym: dict[str, pd.DataFrame] = {}
    for sym in all_symbols:
        df = _fetch_1min_bars(sym, target_date, api_key, secret_key)
        bars_by_sym[sym] = df
        print(f"    {sym}: {len(df)} bars", flush=True)

    # Build a unified sorted timeline of (timestamp, symbol) events
    events: list[tuple] = []
    for sym, df in bars_by_sym.items():
        for ts in df.index:
            events.append((ts, sym))
    events.sort(key=lambda x: x[0])

    if not events:
        print("  No bars fetched — market may have been closed.")
        return {
            "day": day_num, "date": target_date.isoformat(),
            "shadow_signals": 0, "actual_trades": 0,
            "alignment": "N/A", "total_bars": 0,
        }

    # Rolling state per symbol
    aggregator = SignalAggregator(long_only=LONG_ONLY)
    risk_mgr   = RiskManager(account_value=ACCOUNT)
    buffers:   dict[str, deque] = {s: deque(maxlen=BAR_BUFFER) for s in symbols}
    bar_accum: dict[str, list]  = {s: [] for s in symbols}
    uvxy_pct = 0.0
    signal_log: list[dict] = []

    for ts, sym in events:
        row_raw = bars_by_sym[sym].loc[ts]
        minute  = ts.tz_convert(ET).minute

        # UVXY: update fear gauge only
        if sym == "UVXY":
            if uvxy_prev_close:
                uvxy_close = float(row_raw["Close"])
                uvxy_pct   = (uvxy_close - uvxy_prev_close) / uvxy_prev_close * 100
            continue

        if sym not in buffers:
            continue

        # 1-min → 5-min aggregation (same logic as live runner)
        if minute % 5 == 0:
            bar_accum[sym] = []

        bar_accum[sym].append({
            "open":   float(row_raw["Open"]),
            "high":   float(row_raw["High"]),
            "low":    float(row_raw["Low"]),
            "close":  float(row_raw["Close"]),
            "volume": float(row_raw["Volume"]),
        })

        if minute % 5 != 4:
            continue  # window not complete yet

        window = bar_accum[sym]
        five_min = {
            "Open":   window[0]["open"],
            "High":   max(b["high"]   for b in window),
            "Low":    min(b["low"]    for b in window),
            "Close":  window[-1]["close"],
            "Volume": sum(b["volume"] for b in window),
        }
        buffers[sym].append((ts, five_min))

        if len(buffers[sym]) < 21:
            continue  # need history for EMA-21

        df = pd.DataFrame(
            [r for _, r in buffers[sym]],
            index=pd.DatetimeIndex([t for t, _ in buffers[sym]]),
        )

        agg    = aggregator.analyze(df, uvxy_pct=uvxy_pct)
        params = None
        if agg.direction != Direction.HOLD:
            risk_mgr.account_value = ACCOUNT
            params = risk_mgr.calculate(sym, df, agg.direction)

        et_time = ts.tz_convert(ET).strftime("%H:%M")
        tag     = f"[{agg.direction.value}]" if agg.direction != Direction.HOLD else "[----]"
        close   = five_min["Close"]
        print(f"  {et_time} {sym} {tag} conf={agg.confidence:.2f}  close={close:.2f}", flush=True)

        signal_log.append({
            "time":         ts.isoformat(),
            "symbol":       sym,
            "close":        close,
            "signal":       agg.direction.value,
            "confidence":   agg.confidence,
            "reason":       str(agg),
            "would_entry":  params.entry       if params else None,
            "would_stop":   params.stop_loss   if params else None,
            "would_target": params.take_profit if params else None,
            "would_shares": params.shares      if params else None,
            "would_risk":   params.risk_amount if params else None,
        })

    # Save signal CSV
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    sig_file = RESULTS_DIR / f"day{day_num:02d}_{target_date}_signals.csv"
    if signal_log:
        with open(sig_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=signal_log[0].keys())
            writer.writeheader()
            writer.writerows(signal_log)

    shadow_buys  = sum(1 for s in signal_log if s["signal"] == "BUY"  and s["would_entry"])
    shadow_sells = sum(1 for s in signal_log if s["signal"] == "SELL" and s["would_entry"])

    print(f"\n  {'-'*45}")
    print(f"  Day {day_num} replay done  |  {target_date.strftime('%A %b %d')}")
    print(f"  {'-'*45}")
    print(f"  Shadow signals  - BUY: {shadow_buys}  SELL: {shadow_sells}")
    print(f"  Total bars logged: {len(signal_log)}")
    print(f"  Signal log -> {sig_file.name}")

    return {
        "day":            day_num,
        "date":           target_date.isoformat(),
        "shadow_signals": shadow_buys + shadow_sells,
        "actual_trades":  0,   # historical — no live trades to compare
        "alignment":      "N/A (historical)",
        "total_bars":     len(signal_log),
    }


# ---------------------------------------------------------------------------
# summary helpers
# ---------------------------------------------------------------------------

def _load_summary() -> list[dict]:
    if not SUMMARY_FILE.exists():
        return []
    with open(SUMMARY_FILE) as f:
        return list(csv.DictReader(f))


def _save_summary(rows: list[dict]):
    if not rows:
        return
    SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SUMMARY_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def _upsert_summary_row(new_row: dict):
    rows = _load_summary()
    # Replace existing row for same date, or append
    replaced = False
    for i, r in enumerate(rows):
        if r["date"] == new_row["date"]:
            rows[i] = new_row
            replaced = True
            break
    if not replaced:
        rows.append(new_row)
    rows.sort(key=lambda r: r["date"])
    _save_summary(rows)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Historical backtest replay")
    parser.add_argument(
        "--dates", nargs="+", metavar="YYYY-MM-DD",
        help="Specific dates to replay (default: auto-detect missing days)",
    )
    parser.add_argument(
        "--day-start", type=int, default=None,
        help="Day number to assign to the first replayed date (default: next after summary)",
    )
    args = parser.parse_args()

    api_key, secret_key = _api_keys()
    symbols = _load_symbols()
    print(f"Symbols ({len(symbols)}): {symbols}")

    existing = _existing_days()
    state    = _load_state()

    if args.dates:
        target_dates = [date.fromisoformat(d) for d in args.dates]
    else:
        # Auto-detect: find all missing weekdays between state start and yesterday
        start_str = state.get("start_date", "2026-06-11")
        start_d   = date.fromisoformat(start_str)
        yesterday = date.today() - timedelta(days=1)
        target_dates = []
        d = start_d
        while d <= yesterday:
            if _is_market_day(d) and d.isoformat() not in existing:
                target_dates.append(d)
            d += timedelta(days=1)

    if not target_dates:
        print("Nothing to replay — all days are already covered.")
        return

    print(f"\nDates to replay: {[d.isoformat() for d in target_dates]}")

    # Determine starting day number
    if args.day_start is not None:
        next_day = args.day_start
    else:
        summary_rows = _load_summary()
        next_day = max((int(r["day"]) for r in summary_rows), default=0) + 1

    for i, target_date in enumerate(target_dates):
        day_num = next_day + i
        row = replay_day(target_date, day_num, symbols, api_key, secret_key)
        _upsert_summary_row(row)

        # Keep state.json current_day in sync
        state["last_run"]    = target_date.isoformat()
        state["current_day"] = max(state.get("current_day", 1), day_num + 1)
        _save_state(state)

    print(f"\nReplay complete. {len(target_dates)} day(s) written to {SUMMARY_FILE}")


if __name__ == "__main__":
    main()
