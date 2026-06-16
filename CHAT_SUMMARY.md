# DayTradeBot — Chat Handoff Summary

Paste this into a new chat to resume work with full context. Last updated: 2026-06-16.

---

## What This Project Is

A rule-based day trading bot that removes emotional decision-making. It uses a weighted combination of three intraday strategies to generate signals, executes paper trades through Alpaca's API, and enforces strict risk controls. The goal is 30 days of paper trading validation before switching to live money.

**Repo:** https://github.com/bng11299/Day-Trade-Advisor
**Local path:** `C:\Users\Browndan\Documents\DayTradeBot`
**Active branch:** `feature/orb-vwap-ema-alpaca-rewrite`
**PR:** https://github.com/bng11299/Day-Trade-Advisor/pull/3

---

## Tech Stack

- **Python 3.13** at `C:\Users\Browndan\AppData\Local\Programs\Python\Python313\python.exe`
  - This is the ONLY Python with packages installed. Task Scheduler must use this path.
  - Python 3.12 and Python 3.14 also exist on this machine but lack pandas/alpaca-py.
- **alpaca-py >= 0.26** — trading execution + data (replaced yfinance entirely)
- **pandas >= 2.0**, **numpy >= 1.26**
- **Alpaca paper trading account** — $100,000 virtual balance
- **Windows Task Scheduler** — runs screener + shadow runner daily
- **User is in Singapore (SGT = UTC+8)** — all Task Scheduler times are in SGT
- **gh CLI** at `C:\Program Files\GitHub CLI\gh.exe` (not on PATH — use full path)

---

## Alpaca Credentials

```
ALPACA_API_KEY    = PKTEOT5NNUQTGYLAAEKJ3YIPCV
ALPACA_SECRET_KEY = CxTGPWTVKcdpNR3bWkjgsWUy7FGEskyGXSaJ9eKWMJSa
Paper trading:      paper=True (default in broker/alpaca.py)
Data feed:          DataFeed.IEX (free tier)
```

Set in PowerShell before running anything:
```powershell
$env:ALPACA_API_KEY = "PKTEOT5NNUQTGYLAAEKJ3YIPCV"
$env:ALPACA_SECRET_KEY = "CxTGPWTVKcdpNR3bWkjgsWUy7FGEskyGXSaJ9eKWMJSa"
```

---

## Project Structure

```
DayTradeBot/
├── main.py                      # Live bot -- event-driven via Alpaca WebSocket
├── strategies/
│   ├── base.py                  # Signal(direction, confidence, reason) + Strategy ABC
│   ├── orb.py                   # Opening Range Breakout -- 40% weight
│   ├── vwap.py                  # VWAP crossover + mean reversion -- 35% weight
│   ├── ema_crossover.py         # EMA 9/21 + volume -- 25% weight
│   └── rsi_filter.py            # RSI as veto gate (not a signal)
├── engine/
│   ├── aggregator.py            # Weighted vote, RSI veto, confidence threshold (0.65)
│   └── risk.py                  # ATR stop loss, 2:1 RR, 1% position sizing, min ATR
├── broker/
│   ├── alpaca.py                # submit_order, get_positions, close_all_positions
│   └── data.py                  # LiveBarStream (WebSocket) + fetch_bars (REST/IEX)
├── backtest/
│   ├── runner.py                # Walk-forward backtester -- CLI tool
│   ├── daily/                   # Per-day CSVs from shadow runner
│   └── reports/                 # Saved text reports (from scripts/report.py --save)
├── scripts/
│   ├── screener.py              # Morning S&P 500 screener -- writes watchlist.json
│   ├── daily_backtest.py        # Shadow runner -- runs during market hours
│   ├── report.py                # Human-readable report generator
│   ├── schedule.ps1             # Registers Windows Task Scheduler jobs
│   ├── state.json               # Tracks day N of 30
│   ├── screener.log             # Screener output log
│   └── daily_backtest.log       # Shadow runner append-only log
├── watchlist.json               # Gitignored -- written by screener each morning
└── requirements.txt
```

---

## How the Signal Stack Works

Every 1-minute bar goes through this pipeline:

```
Bar -> ORB.analyze(df)  -> Signal(BUY/SELL/HOLD, confidence)  +
    -> VWAP.analyze(df) -> Signal(BUY/SELL/HOLD, confidence)  +--> Weighted score
    -> EMA.analyze(df)  -> Signal(BUY/SELL/HOLD, confidence)  +
    -> RSI.analyze(df)  -> veto gate (blocks overbought buys / oversold sells)
    -> if confidence > 0.65 AND not vetoed AND not long_only blocking:
        -> RiskManager.calculate() -> TradeParams(entry, stop, target, shares)
        -> AlpacaBroker.submit_order(params)
```

**Weights:** ORB=0.40, VWAP=0.35, EMA=0.25
**Confidence threshold:** 0.65
**long_only=True** -- SELL signals suppressed (bull market config)

---

## Risk Controls

| Control | Value | Where |
|---|---|---|
| Risk per trade | 1% of account | `engine/risk.py` |
| Stop loss | 1.5x ATR | `atr_stop_multiplier=1.5` |
| Take profit | 3.0x ATR (2:1 RR) | `reward_ratio=2.0` |
| Min ATR filter | $0.50 | `min_atr=0.50` |
| Daily loss halt | 2% | `main.py` |
| EOD force close | 3:45pm ET | `main.py` |

---

## Symbol Screener

Runs every morning before market open via Task Scheduler.

**How it works:**
- Screens 401 S&P 500 symbols (dots removed for IEX compatibility)
- Fetches last 20 trading days of daily bars in batches of 50
- Filters: ATR >= $0.75, avg daily volume >= 500k, price $10-$1500
- Price sanity check: skips if last close is >2.5x or <0.4x the 20-day median
- Scores: `ATR x log10(avg_volume) x relative_volume`
- Sector diversity cap: max 2 symbols per GICS sector
- Outputs top 15 to `watchlist.json`

**Key file:** `scripts/screener.py`

**Run manually:**
```powershell
python scripts/screener.py             # screen and update watchlist
python scripts/screener.py --dry-run   # print without saving
python scripts/screener.py --top 10    # override count
```

---

## 30-Day Shadow Runner

**What it does:** Watches the same Alpaca stream as the live bot during market hours.
Logs what the strategy WOULD signal on each bar (no orders placed).
At market close, pulls actual paper fills from Alpaca and compares.

**Schedule (SGT = UTC+8):**
```
9:15pm SGT  -- Screener fires, writes watchlist.json
9:25pm SGT  -- Shadow runner fires, loads watchlist, waits for open
9:30pm SGT  -- Market opens, bars start streaming
4:00am SGT  -- Market closes, end-of-day report saved, task exits
```

**Task Scheduler jobs:**
- `DayTradeBot-Screener` -- 9:15pm SGT weekdays
- `DayTradeBot-DailyBacktest` -- 9:25pm SGT weekdays, 600-min timeout

**Outputs per day:**
- `backtest/daily/dayNN_YYYY-MM-DD_signals.csv` -- every bar's signal + what trade it would place
- `backtest/daily/dayNN_YYYY-MM-DD_actual.csv` -- every Alpaca fill that day
- `backtest/30day_summary.csv` -- rolling totals (appended each day)
- `scripts/daily_backtest.log` -- full stdout (append-only)

**State tracking:** `scripts/state.json` -- tracks current day number and last run date.
If this file is missing, the runner resets to Day 1. Current state: Day 4, started 2026-06-11.

**Go-live criteria (Day 30 auto-check):**
- Sharpe > 1.0
- Max drawdown < 15%
- Net profitable

---

## Report Generator

**File:** `scripts/report.py`

Reads signal CSVs and the 30-day summary to produce a plain-text report.

```powershell
python scripts/report.py              # most recent day + scorecard
python scripts/report.py --day 3      # specific day
python scripts/report.py --all        # scorecard only
python scripts/report.py --save       # also write to backtest/reports/
```

**Daily report shows:**
- Bars processed, BUY/SELL/HOLD counts, RSI veto count
- Per-symbol breakdown with peak confidence
- Top BUY signals with entry/stop/target
- RSI vetoes with reason
- Shadow vs actual trade comparison

---

## How to Run Things

**Live paper bot:**
```powershell
$env:ALPACA_API_KEY = "PKTEOT5NNUQTGYLAAEKJ3YIPCV"
$env:ALPACA_SECRET_KEY = "CxTGPWTVKcdpNR3bWkjgsWUy7FGEskyGXSaJ9eKWMJSa"
python main.py
# then: add NVDA, add TSLA
```

**Run screener now:**
```powershell
python scripts/screener.py
```

**Start shadow runner now (via Task Scheduler):**
```powershell
Start-ScheduledTask -TaskName "DayTradeBot-DailyBacktest"
```

**Watch live log:**
```powershell
Get-Content scripts\daily_backtest.log -Tail 50 -Wait
```

**Check task status:**
```powershell
Get-ScheduledTask -TaskName "DayTradeBot-Screener","DayTradeBot-DailyBacktest" | Get-ScheduledTaskInfo | Select-Object TaskName,LastRunTime,LastTaskResult,NextRunTime | Format-List
```

**Generate today's report:**
```powershell
python scripts/report.py
```

**Historical backtest:**
```powershell
python -m backtest.runner --symbols NVDA TSLA --start 2024-01-01 --end 2024-06-01 --interval 5m --long-only
```

**Re-register Task Scheduler (after changes to schedule.ps1):**
```powershell
powershell -ExecutionPolicy Bypass -File "scripts\schedule.ps1"
```

---

## Known Issues / Gotchas

| Issue | Status | Notes |
|---|---|---|
| Multiple Python installs on machine | Fixed | Hardcoded Python313 path in schedule.ps1 |
| Unicode chars crash Windows console | Fixed | All box-drawing chars replaced with ASCII in daily_backtest.py and screener.py |
| state.json missing resets day count | Fixed | state.json recreated; daily_backtest.py saves it at end of each day |
| 30day_summary.csv had duplicate Day 1 zeros | Known | Was caused by Unicode crash before append_to_summary ran. Will self-correct as new days complete. |
| Shadow runner timeout too short | Fixed | Bumped to 600 min (10 hrs) |
| `gh` not on PATH after winget install | Open | Use full path `C:\Program Files\GitHub CLI\gh.exe` |
| IEX feed lower volume coverage than SIP | By design | Upgrade to DataFeed.SIP with paid Alpaca plan |
| MU ticker shows ~$900-1000 price | Real data | Micron has had a large bull run; price sanity filter confirmed data is consistent |

---

## Backtest Results (Jan-Jun 2024, 5m bars, AAPL/TSLA/NVDA, $10k)

| Metric | v1 (before) | v2 (after risk controls) |
|---|---|---|
| Trades | 1,317 | 229 |
| Win rate | 33.9% | 41.0% |
| Total return | +21% | +43% |
| Max drawdown | 51.5% | 10.4% |
| Sharpe ratio | 0.18 | 1.9 |

---

## What's Next (Priority Order)

1. **Regime filter** -- detect SPY trending vs choppy, adjust confidence weights accordingly
2. **Performance dashboard** -- equity curve and signal heatmap from the 30-day CSVs
3. **Multi-position support** -- currently one position per symbol; scale into high-conviction signals
4. **Go live** -- flip `paper=False` after 30-day evaluation passes (Day 30 = ~2026-07-21)
5. **Upgrade to SIP feed** -- more volume coverage if upgrading Alpaca plan
