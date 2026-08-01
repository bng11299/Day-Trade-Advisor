# DayTradeBot — Chat Handoff Summary

Paste this into a new chat to resume work with full context. Last updated: 2026-07-30 (30-day shadow period complete).

---

## What This Project Is

A rule-based day trading bot that removes emotional decision-making. It uses a weighted combination of three intraday strategies to generate signals, executes paper trades through Alpaca's API, and enforces strict risk controls. The goal was 30 days of paper trading validation before switching to live money — **that period is now complete (see Results below).**

**Repo:** https://github.com/bng11299/Day-Trade-Advisor
**Local path:** `C:\Users\Browndan\Documents\DayTradeBot`
**Active branch:** `feature/orb-vwap-ema-alpaca-rewrite`

---

## Tech Stack

- **Python 3.13** (Windows)
- **alpaca-py >= 0.26** — trading execution + data (replaced yfinance entirely)
- **pandas >= 2.0**, **numpy >= 1.26**
- **Alpaca paper trading account** — ~$300,000 virtual balance
- **Windows Task Scheduler** — screener at 9:15pm SGT, shadow runner at 9:25pm SGT (weekday market hours)
- **gh CLI** located at `C:\Program Files\GitHub CLI\gh.exe` (not on PATH — use full path or restart terminal)

---

## Alpaca Credentials

> **Security:** Never commit real keys. Keep them in a gitignored `.env` (see
> `.env.example`) or the shell environment. Keys previously pasted here in
> plaintext have been rotated and revoked. Paper trading is the default
> (`paper=True` in `broker/alpaca.py`); data feed is `DataFeed.IEX`
> (free tier — change to `DataFeed.SIP` with a paid plan).

Set in PowerShell before running anything (values from your `.env`, not hard-coded):
```powershell
$env:ALPACA_API_KEY = "${ALPACA_API_KEY}"
$env:ALPACA_SECRET_KEY = "${ALPACA_SECRET_KEY}"
```

---

## Project Structure

```
DayTradeBot/
├── main.py                      # Live bot — event-driven via Alpaca WebSocket
├── strategies/
│   ├── base.py                  # Signal(direction, confidence, reason) + Strategy ABC
│   ├── orb.py                   # Opening Range Breakout — 40% weight
│   ├── vwap.py                  # VWAP crossover + mean reversion — 35% weight
│   ├── ema_crossover.py         # EMA 9/21 + volume — 25% weight
│   └── rsi_filter.py            # RSI as veto gate (not a signal)
├── engine/
│   ├── aggregator.py            # Weighted vote, RSI veto, UVXY regime bump, confidence threshold (0.65)
│   └── risk.py                  # ATR stop loss, 2:1 RR, 1% position sizing, min ATR ($0.50, calibrated for 5m bars)
├── broker/
│   ├── alpaca.py                # submit_order, get_positions, close_all_positions
│   └── data.py                  # LiveBarStream (1m→5m aggregated WebSocket) + fetch_bars (REST/IEX) + fetch_prev_close
├── backtest/
│   ├── runner.py                # Walk-forward backtester — CLI tool
│   └── daily/                   # Per-day CSVs from shadow runner (days 1-30, complete)
├── scripts/
│   ├── daily_backtest.py        # Shadow runner — 1m→5m aggregation, UVXY tracking
│   ├── historical_backtest.py   # Standalone historical backtest script
│   ├── screener.py              # Morning symbol screener (20-stock universe, sector diversity)
│   ├── schedule.ps1             # Registers Windows Task Scheduler jobs
│   ├── state.json               # Tracks day N of 30 (now complete)
│   └── daily_backtest.log       # Append-only log
├── watchlist.json               # Gitignored — persisted symbol list
└── requirements.txt
```

---

## How the Signal Stack Works

Every 5-minute bar (1-minute Alpaca bars aggregated into clock-aligned 5m windows) goes through this pipeline:

```
Bar → ORB.analyze(df)  → Signal(BUY/SELL/HOLD, confidence)  ┐
    → VWAP.analyze(df) → Signal(BUY/SELL/HOLD, confidence)  ├→ Weighted score
    → EMA.analyze(df)  → Signal(BUY/SELL/HOLD, confidence)  ┘
    → RSI.analyze(df)  → veto gate (blocks overbought buys / oversold sells)
    → UVXY intraday move bumps the effective threshold (fear regime filter)
    → if confidence > threshold AND not vetoed AND not long_only blocking:
        → RiskManager.calculate() → TradeParams(entry, stop, target, shares)
        → AlpacaBroker.submit_order(params)
```

**Weights:** ORB=0.40, VWAP=0.35, EMA=0.25
**Base confidence threshold:** 0.65 (raised from 0.55 after backtest analysis), bumped up to 0.75 during UVXY fear spikes
**long_only=True** — SELL signals suppressed (bull market config)

**Watchlist (curated, active since Day 7):** `NVDA, TSLA, AMD, META, AAPL, MSFT, AMZN, GOOGL, PLTR, NFLX, MU, AVGO, SMCI, JPM, BAC, XOM, CVX, LLY, COIN, C` — replaced an earlier list of slow consumer-staples/financials/oil-services names. The morning screener's universe was expanded (PLTR/SMCI/COIN added, `DEFAULT_TOP_N=20`, `max_per_sector=3`) so it no longer overwrites this list with weaker picks.

**UVXY regime filter:** UVXY (VIX fear ETF) is streamed but never traded. Its intraday % move from prior close bumps the confidence threshold before each signal evaluates:

| UVXY move | Threshold bump | Effective threshold |
|-----------|---------------|---------------------|
| ≤ +2% | +0.00 | 0.65 (normal) |
| +2–5% | +0.03 | 0.68 |
| +5–10% | +0.06 | 0.71 |
| > +10% | +0.10 | 0.75 (max) |

A strong signal (conf=0.80) still trades through a fear spike (threshold=0.75) — UVXY raises the bar, it doesn't lock the door. Vetoes log as `[VETOED: UVXY regime (+6.3%, threshold 0.71)]`.

---

## Risk Controls

| Control | Value | Where |
|---|---|---|
| Risk per trade | 1% of account | `engine/risk.py` → `risk_pct=0.01` |
| Stop loss | 1.5x ATR | `atr_stop_multiplier=1.5` |
| Take profit | 3.0x ATR (2:1 RR) | `reward_ratio=2.0` |
| Min ATR filter | $0.50 (5-minute bars) | `min_atr=0.50` (skips quiet stocks) |
| Daily loss halt | 2% | `main.py` → `DAILY_LOSS_LIMIT_PCT=0.02` |
| EOD force close | 3:45pm ET | `main.py` → `EOD_CLOSE_UTC_HOUR=20, MINUTE=45` |

---

## Historical Backtest Results (Jan–Jun 2024, 5m bars, AAPL/TSLA/NVDA, $10k)

| Metric | v1 (before) | v2 (after risk controls) |
|---|---|---|
| Trades | 1,317 | 229 |
| Win rate | 33.9% | 41.0% |
| Total return | +21% | +43% |
| Max drawdown | 51.5% | **10.4%** |
| Sharpe ratio | 0.18 | **1.9** |

Key changes that drove improvement:
- Confidence threshold 0.55 → 0.65 (cut 83% of noise trades)
- `--long-only` flag (eliminated -$1,731 losing short side in bull market)
- Daily loss halt + EOD close (contained Jan 17 blowup cluster)
- Min-ATR filter (AAPL dropped from 455 trades to 15 — correctly flagged as too quiet)

---

## 30-Day Shadow Runner — Results (Complete)

**What it does:** Runs during market hours alongside the live bot. Subscribes to the same Alpaca stream, logs what the strategy WOULD signal on each bar, then compares to actual Alpaca fills at close. The "alignment %" shows if the live bot is faithfully executing the strategy.

**Outputs per day:**
- `backtest/daily/dayNN_YYYY-MM-DD_signals.csv` — every bar's signal
- `backtest/daily/dayNN_YYYY-MM-DD_actual.csv` — every Alpaca fill (from Day 17, once trades started firing)
- `backtest/30day_summary.csv` — rolling totals

**Final result:** Trading began Day 17 (2026-07-06) once the 1m/5m bar-aggregation fix and min-ATR calibration let signals actually clear the threshold. Equity went from $300,000.00 → **$297,351.54** (-0.88%) across days 17-30.

**Go-live criteria (Day 30 check):**
- Sharpe > 1.0 — not computed/likely not met given net loss
- Max drawdown < 15% — met
- Net profitable — **not met** (-0.88% over the trading window)

**Verdict: do not flip `paper=False` yet.** The strategy is executing faithfully (bars are firing, signals are aligning with fills), but it isn't yet profitable. Days 1-16 were mostly signal-starved (a real bug, since fixed: see Known Issues); only ~2 weeks of actual trading data exists. Recommend either extending the shadow period now that signals fire correctly, or revisiting the strategy/threshold before another live-money decision.

**Useful commands:**
```powershell
# Watch live log
Get-Content scripts\daily_backtest.log -Tail 50 -Wait

# View 30-day scorecard
Import-Csv backtest\30day_summary.csv | Format-Table

# Force manual run
Start-ScheduledTask -TaskName "DayTradeBot-DailyBacktest"
```

---

## How to Run Things

**Live paper bot:**
```powershell
cd C:\Users\Browndan\Documents\DayTradeBot
$env:ALPACA_API_KEY = "${ALPACA_API_KEY}"
$env:ALPACA_SECRET_KEY = "${ALPACA_SECRET_KEY}"
python main.py
# then: add NVDA, add TSLA
```

**Historical backtest:**
```powershell
python -m backtest.runner --symbols NVDA TSLA --start 2024-01-01 --end 2024-06-01 --interval 5m --long-only
```

**Re-register Task Scheduler (new machine or after reinstall):**
```powershell
powershell -ExecutionPolicy Bypass -File "scripts\schedule.ps1"
```

**Create a PR (gh CLI):**
```powershell
& "C:\Program Files\GitHub CLI\gh.exe" pr create --title "..." --body "..." --base main
```

---

## Known Issues / Gotchas

| Issue | Status | Notes |
|---|---|---|
| Streaming 1-min bars failed `min_atr=$0.50` filter, so `would_entry` never fired | **Fixed** | Both `broker/data.py` and `scripts/daily_backtest.py` now aggregate 1-min bars into clock-aligned 5-min windows before handing off to strategies |
| Shadow runner CSVs all named `day01_*` regardless of actual day | **Fixed** | A stray Unicode dash crashed `compare_and_report` after writing the signal CSV but before `save_state`; renamed the affected files and fixed the crash |
| `30day_summary.csv` had backtester's column schema instead of shadow runner's | **Fixed** | Replaced with correct schema, backfilled days 1-3 |
| VWAP confidence floor (fixed 0.45 when price is above/below VWAP without a crossover) | **Open** | Caps composite confidence around ~0.557 without a crossover event; worth revisiting if signal frequency needs to increase |
| 105-min warmup silence at market open | **Fixed** | Lowered EMA-21 warmup requirement from 30 to 21 bars |
| `gh` not on PATH after winget install | Open | Restart PowerShell or use full path `C:\Program Files\GitHub CLI\gh.exe` |
| IEX feed has lower volume coverage than SIP | By design | Upgrade to `DataFeed.SIP` if Alpaca plan upgraded |
| Shadow runner gets 0 bars if market closed | By design | The IEX stream only fires during market hours |
| `call_soon_threadsafe` needed for `add_symbol` | Fixed | `subscribe_bars` is sync, not a coroutine |
| `StockDataStream._run()` → `.run()` | Fixed | Public method, not private |

---

## What's Next (Priority Order)

1. **VWAP confidence floor** — investigate whether 0.45 should scale with distance from VWAP instead of being a flat floor
2. **Go-live decision** — shadow period is complete but net-negative; decide whether to extend paper trading now that signals fire correctly, or revisit strategy/threshold first
3. **Regime filter** — UVXY soft threshold-bump is in place; consider extending to a broader SPY trend/chop detector
4. **Performance dashboard** — equity curve, signal heatmap, alignment % chart
5. **Multi-position support** — scale into high-conviction signals
