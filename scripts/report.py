"""
DayTradeBot report generator.

Reads the signal CSVs, actual trade CSVs, and 30-day summary to produce
a plain-text daily report and a running 30-day scorecard.

Usage:
    python scripts/report.py              # report for the most recent day
    python scripts/report.py --day 3      # report for a specific day number
    python scripts/report.py --all        # full 30-day scorecard only
    python scripts/report.py --save       # also write report to backtest/reports/
"""

import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT        = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "backtest" / "daily"
SUMMARY_FILE = ROOT / "backtest" / "30day_summary.csv"
REPORTS_DIR = ROOT / "backtest" / "reports"
ET          = ZoneInfo("America/New_York")
SGT         = ZoneInfo("Asia/Singapore")

SEP  = "-" * 60
SEP2 = "=" * 60


# ── data loaders ─────────────────────────────────────────────────────────────

def load_signals(day_num: int = None, date_str: str = None) -> tuple[list[dict], str]:
    """Return (rows, filename) for a day's signal CSV."""
    files = sorted(RESULTS_DIR.glob("*_signals.csv"))
    if not files:
        return [], ""

    if day_num is not None:
        matches = [f for f in files if f.name.startswith(f"day{day_num:02d}_")]
        f = matches[-1] if matches else None
    elif date_str:
        matches = [f for f in files if date_str in f.name]
        f = matches[0] if matches else None
    else:
        f = files[-1]   # most recent

    if not f or not f.exists():
        return [], ""

    with open(f, newline="") as fh:
        return list(csv.DictReader(fh)), f.name


def load_actual(signals_filename: str) -> list[dict]:
    """Load actual trades file matching the signals filename."""
    actual_name = signals_filename.replace("_signals.csv", "_actual.csv")
    p = RESULTS_DIR / actual_name
    if not p.exists():
        return []
    with open(p, newline="") as fh:
        return list(csv.DictReader(fh))


def load_summary() -> list[dict]:
    if not SUMMARY_FILE.exists():
        return []
    with open(SUMMARY_FILE, newline="") as fh:
        return list(csv.DictReader(fh))


# ── report sections ───────────────────────────────────────────────────────────

def _pct(n, d):
    return f"{n/d*100:.0f}%" if d else "N/A"


def _fmt_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso).astimezone(ET)
        return dt.strftime("%H:%M ET")
    except Exception:
        return iso


def daily_report(signals: list[dict], actual: list[dict], filename: str) -> str:
    if not signals:
        return "No signal data found.\n"

    lines = []

    # extract date from filename e.g. day01_2026-06-15_signals.csv
    parts    = filename.replace("_signals.csv", "").split("_")
    day_num  = parts[0].replace("day", "")
    date_str = parts[1] if len(parts) > 1 else "unknown"
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_pretty = dt.strftime("%A, %B %d %Y")
    except Exception:
        date_pretty = date_str

    lines.append(SEP2)
    lines.append(f"  DAY {day_num} REPORT  |  {date_pretty}")
    lines.append(SEP2)

    # ── overall signal counts ─────────────────────────────────────────────────
    total_bars   = len(signals)
    buy_signals  = [s for s in signals if s["signal"] == "BUY"  and s.get("would_entry")]
    sell_signals = [s for s in signals if s["signal"] == "SELL" and s.get("would_entry")]
    hold_signals = [s for s in signals if s["signal"] == "HOLD"]
    vetoed       = [s for s in signals if "VETOED" in s.get("reason", "")]

    lines.append(f"\n  Bars processed : {total_bars:,}")
    lines.append(f"  BUY signals    : {len(buy_signals)}")
    lines.append(f"  SELL signals   : {len(sell_signals)}")
    lines.append(f"  HOLDs          : {len(hold_signals)}")
    lines.append(f"  RSI vetoes     : {len(vetoed)}")

    # ── per-symbol breakdown ──────────────────────────────────────────────────
    by_sym = defaultdict(lambda: {"bars": 0, "buys": 0, "sells": 0, "holds": 0,
                                   "max_conf": 0.0, "best_reason": ""})
    for s in signals:
        sym  = s["symbol"]
        conf = float(s.get("confidence", 0))
        by_sym[sym]["bars"]  += 1
        by_sym[sym]["max_conf"] = max(by_sym[sym]["max_conf"], conf)
        if s["signal"] == "BUY"  and s.get("would_entry"):
            by_sym[sym]["buys"]  += 1
            if conf >= by_sym[sym]["max_conf"]:
                by_sym[sym]["best_reason"] = s.get("reason", "")
        elif s["signal"] == "SELL" and s.get("would_entry"):
            by_sym[sym]["sells"] += 1
        else:
            by_sym[sym]["holds"] += 1

    lines.append(f"\n{SEP}")
    lines.append("  SYMBOL BREAKDOWN")
    lines.append(SEP)
    lines.append(f"  {'Symbol':<8}  {'Bars':>5}  {'BUY':>4}  {'SELL':>5}  {'Peak conf':>9}")
    lines.append(f"  {'-'*8}  {'-'*5}  {'-'*4}  {'-'*5}  {'-'*9}")
    for sym in sorted(by_sym):
        d = by_sym[sym]
        marker = " <-- signal" if d["buys"] or d["sells"] else ""
        lines.append(
            f"  {sym:<8}  {d['bars']:>5}  {d['buys']:>4}  {d['sells']:>5}"
            f"  {d['max_conf']:>8.0%}{marker}"
        )

    # ── top BUY signals ───────────────────────────────────────────────────────
    if buy_signals:
        top = sorted(buy_signals, key=lambda s: float(s.get("confidence", 0)), reverse=True)[:5]
        lines.append(f"\n{SEP}")
        lines.append("  TOP BUY SIGNALS (by confidence)")
        lines.append(SEP)
        for s in top:
            conf  = float(s.get("confidence", 0))
            entry = s.get("would_entry", "")
            stop  = s.get("would_stop", "")
            tgt   = s.get("would_target", "")
            lines.append(
                f"  {_fmt_time(s['time'])}  {s['symbol']:<6}  conf={conf:.0%}"
                f"  entry=${entry}  stop=${stop}  target=${tgt}"
            )
            lines.append(f"    {s.get('reason','')}")

    # ── RSI vetoes ────────────────────────────────────────────────────────────
    if vetoed:
        lines.append(f"\n{SEP}")
        lines.append("  RSI VETOES (trades blocked)")
        lines.append(SEP)
        shown = set()
        for s in vetoed[:10]:
            key = (s["symbol"], s["signal"])
            if key in shown:
                continue
            shown.add(key)
            lines.append(f"  {_fmt_time(s['time'])}  {s['symbol']:<6}  {s.get('reason','')}")

    # ── actual trades comparison ──────────────────────────────────────────────
    lines.append(f"\n{SEP}")
    lines.append("  LIVE BOT vs SHADOW")
    lines.append(SEP)
    actual_buys  = [t for t in actual if t.get("side") == "buy"]
    actual_sells = [t for t in actual if t.get("side") == "sell"]
    lines.append(f"  Shadow called  : BUY {len(buy_signals)}   SELL {len(sell_signals)}")
    lines.append(f"  Bot executed   : BUY {len(actual_buys)}   SELL {len(actual_sells)}")

    if buy_signals + sell_signals:
        matched = min(len(buy_signals), len(actual_buys)) + min(len(sell_signals), len(actual_sells))
        total   = max(len(buy_signals) + len(sell_signals), len(actual_buys) + len(actual_sells))
        alignment = f"{matched/total:.0%}" if total else "N/A"
        lines.append(f"  Alignment      : {alignment}")

    if actual:
        lines.append("")
        for t in actual:
            price = t.get("fill_price", "?")
            lines.append(f"  {_fmt_time(t.get('time',''))}  {t['side'].upper():<4}  {t['symbol']:<6}  {t['qty']} shares @ ${price}")
    else:
        lines.append("  (no paper orders filled today)")

    lines.append(f"\n{SEP2}\n")
    return "\n".join(lines)


def scorecard_report(summary_rows: list[dict]) -> str:
    if not summary_rows:
        return "No 30-day summary data yet.\n"

    lines = []
    lines.append(SEP2)
    lines.append("  30-DAY SHADOW SCORECARD")
    lines.append(SEP2)

    total_signals = sum(int(r.get("shadow_signals", 0)) for r in summary_rows)
    total_actual  = sum(int(r.get("actual_trades",  0)) for r in summary_rows)
    active_days   = sum(1 for r in summary_rows if int(r.get("shadow_signals", 0)) > 0)
    days_run      = len(summary_rows)

    lines.append(f"\n  Period     : {summary_rows[0].get('date','')}  to  {summary_rows[-1].get('date','')}")
    lines.append(f"  Days run   : {days_run} / 30")
    lines.append(f"  Active days: {active_days}  (market sessions with signals)")
    lines.append(f"  Signals    : {total_signals} total  ({total_signals/max(active_days,1):.1f}/day avg)")
    lines.append(f"  Bot trades : {total_actual} total")
    if total_signals:
        lines.append(f"  Overall alignment: {_pct(min(total_actual, total_signals), max(total_actual, total_signals))}")

    lines.append(f"\n{SEP}")
    lines.append(f"  {'Day':<5}  {'Date':<12}  {'Signals':>8}  {'Trades':>7}  {'Align':>7}  {'Bars':>6}")
    lines.append(f"  {'-'*5}  {'-'*12}  {'-'*8}  {'-'*7}  {'-'*7}  {'-'*6}")
    for r in summary_rows:
        sigs = int(r.get("shadow_signals", 0))
        flag = "  *" if sigs > 0 else ""
        lines.append(
            f"  {r.get('day',''):<5}  {r.get('date',''):<12}  {sigs:>8}"
            f"  {r.get('actual_trades','0'):>7}  {r.get('alignment','N/A'):>7}"
            f"  {r.get('total_bars','0'):>6}{flag}"
        )

    lines.append(f"\n  * = active trading day")
    lines.append(f"\n{SEP2}\n")
    return "\n".join(lines)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="DayTradeBot report generator")
    parser.add_argument("--day",  type=int, help="Day number to report on")
    parser.add_argument("--date", type=str, help="Date to report on (YYYY-MM-DD)")
    parser.add_argument("--all",  action="store_true", help="Show 30-day scorecard only")
    parser.add_argument("--save", action="store_true", help="Save report to backtest/reports/")
    args = parser.parse_args()

    output = []

    if not args.all:
        signals, fname = load_signals(day_num=args.day, date_str=args.date)
        if not signals:
            print("No signal data found. Has the shadow runner completed a full day?")
            print(f"Looking in: {RESULTS_DIR}")
            sys.exit(1)
        actual = load_actual(fname)
        output.append(daily_report(signals, actual, fname))

    summary = load_summary()
    output.append(scorecard_report(summary))

    report_text = "\n".join(output)
    print(report_text)

    if args.save:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts   = datetime.now().strftime("%Y-%m-%d_%H%M")
        path = REPORTS_DIR / f"report_{ts}.txt"
        with open(path, "w") as f:
            f.write(report_text)
        print(f"Saved to: {path}")


if __name__ == "__main__":
    main()
