"""
Backtest runner — replays historical intraday data through the full signal stack.

Data source: Alpaca historical bars API (years of data, no rolling-window limits).

Supported intervals: 1m, 5m, 15m, 1h (default: 5m)

Usage:
    python -m backtest.runner --symbols AAPL TSLA --start 2024-01-01 --end 2024-06-01 --account 10000
    python -m backtest.runner --symbols AAPL --start 2023-01-01 --end 2024-01-01 --interval 1h

Output:
    - Per-trade log (CSV)
    - Summary: total return, win rate, max drawdown, Sharpe ratio
"""

import argparse
import csv
import math
import os
from datetime import datetime

import pandas as pd

from broker.data import fetch_bars
from engine.aggregator import SignalAggregator
from engine.risk import RiskManager
from strategies.base import Direction


def run_backtest(symbol: str, df: pd.DataFrame, account: float, lookback: int = 60) -> list[dict]:
    """
    Walk forward through the intraday bars.
    At each bar, feed the last `lookback` bars into the aggregator.
    """
    aggregator = SignalAggregator()
    risk_mgr = RiskManager(account_value=account)

    trades = []
    open_trade = None

    for i in range(lookback, len(df)):
        window = df.iloc[i - lookback : i].copy()
        current_bar = df.iloc[i]
        current_price = float(current_bar["Close"])
        ts = df.index[i]

        # Check open trade stop/target
        if open_trade is not None:
            direction = open_trade["direction"]
            if direction == Direction.BUY:
                hit_tp = current_price >= open_trade["take_profit"]
                hit_sl = current_price <= open_trade["stop_loss"]
            else:
                hit_tp = current_price <= open_trade["take_profit"]
                hit_sl = current_price >= open_trade["stop_loss"]

            if hit_tp or hit_sl:
                exit_price = open_trade["take_profit"] if hit_tp else open_trade["stop_loss"]
                pnl = (exit_price - open_trade["entry"]) * open_trade["shares"]
                if direction == Direction.SELL:
                    pnl = -pnl
                account += pnl
                open_trade["exit_price"] = exit_price
                open_trade["exit_time"] = ts
                open_trade["pnl"] = round(pnl, 2)
                open_trade["result"] = "TP" if hit_tp else "SL"
                open_trade["account_after"] = round(account, 2)
                trades.append(open_trade)
                open_trade = None
            continue  # only one position at a time

        agg = aggregator.analyze(window)
        if agg.direction == Direction.HOLD:
            continue

        risk_mgr.account_value = account
        params = risk_mgr.calculate(symbol, window, agg.direction)
        if params is None:
            continue

        open_trade = {
            "symbol": symbol,
            "entry_time": ts,
            "direction": params.direction,
            "entry": params.entry,
            "stop_loss": params.stop_loss,
            "take_profit": params.take_profit,
            "shares": params.shares,
            "confidence": agg.confidence,
            "exit_price": None,
            "exit_time": None,
            "pnl": None,
            "result": None,
            "account_after": None,
        }

    # Close any open trade at last bar
    if open_trade is not None:
        exit_price = float(df["Close"].iloc[-1])
        pnl = (exit_price - open_trade["entry"]) * open_trade["shares"]
        if open_trade["direction"] == Direction.SELL:
            pnl = -pnl
        account += pnl
        open_trade["exit_price"] = exit_price
        open_trade["exit_time"] = df.index[-1]
        open_trade["pnl"] = round(pnl, 2)
        open_trade["result"] = "EOD"
        open_trade["account_after"] = round(account, 2)
        trades.append(open_trade)

    return trades


def summarize(trades: list[dict], initial_account: float) -> dict:
    if not trades:
        return {"trades": 0}

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total_pnl = sum(pnls)

    # Max drawdown
    equity = initial_account
    peak = equity
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        dd = (peak - equity) / peak
        max_dd = max(max_dd, dd)

    # Sharpe (daily, simplified)
    if len(pnls) > 1:
        mean_pnl = sum(pnls) / len(pnls)
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
        std_pnl = math.sqrt(variance) if variance > 0 else 1e-9
        sharpe = (mean_pnl / std_pnl) * math.sqrt(252)
    else:
        sharpe = 0.0

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades), 3),
        "total_pnl": round(total_pnl, 2),
        "total_return_pct": round(total_pnl / initial_account * 100, 2),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe": round(sharpe, 2),
    }


def save_trades(trades: list[dict], path: str):
    if not trades:
        print("No trades to save.")
        return
    keys = [k for k in trades[0].keys() if k != "direction"]
    keys.insert(2, "direction")
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for t in trades:
            row = dict(t)
            row["direction"] = t["direction"].value
            writer.writerow(row)
    print(f"Trade log saved: {path}")


def main():
    parser = argparse.ArgumentParser(description="Day Trade Bot Backtester")
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--account", type=float, default=10000.0)
    parser.add_argument("--output", default="backtest_results.csv")
    parser.add_argument(
        "--interval",
        default="5m",
        choices=["1m", "5m", "15m", "1h"],
        help="Bar interval (default: 5m)",
    )
    args = parser.parse_args()

    api_key = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        print("ERROR: Set ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables.")
        raise SystemExit(1)

    print(f"Using interval: {args.interval} | Data source: Alpaca")

    all_trades = []
    account = args.account

    for symbol in args.symbols:
        print(f"\nFetching {symbol} {args.start} -> {args.end} ...")
        try:
            df = fetch_bars(symbol, args.start, args.end, interval=args.interval,
                            api_key=api_key, secret_key=secret_key)
        except Exception as e:
            print(f"  Error fetching {symbol}: {e}")
            continue
        if df.empty:
            print(f"  No data for {symbol}, skipping.")
            continue
        print(f"  {len(df)} bars loaded.")
        trades = run_backtest(symbol, df, account)
        all_trades.extend(trades)
        print(f"  {len(trades)} trades generated.")

    print("\n=== BACKTEST SUMMARY ===")
    summary = summarize(all_trades, args.account)
    for k, v in summary.items():
        print(f"  {k}: {v}")

    save_trades(all_trades, args.output)


if __name__ == "__main__":
    main()
