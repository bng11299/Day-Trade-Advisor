# DayTradeBot — Chat Handoff Summary

Paste this into a new chat to resume work with full context. Last updated: 2026-06-10.

---

## What This Project Is

A rule-based day trading bot that removes emotional decision-making. It uses a weighted combination of three intraday strategies to generate signals, executes paper trades through Alpaca's API, and enforces strict risk controls. The goal is 30 days of paper trading validation before switching to live money.

**Repo:** https://github.com/bng11299/Day-Trade-Advisor
**Local path:** `C:\Users\Browndan\Documents\DayTradeBot`
**Active branch:** `feature/orb-vwap-ema-alpaca-rewrite`
**PR:** https://github.com/bng11299/Day-Trade-Advisor/pull/3

---

## Tech Stack

- **Python 3.13** (Windows)
- **alpaca-py >= 0.26** — trading execution + data (replaced yfinance entirely)
- **pandas >= 2.0**, **numpy >= 1.26**
- **Alpaca paper trading account** — $100,000 virtual balance
- **Windows Task Scheduler** — runs shadow runner daily at 9:25am ET
- **gh CLI** located at `C:\Program Files\GitHub CLI\gh.exe` (not on PATH — use full path or restart terminal)

---

## Alpaca Credentials

> **Security:** Never commit real keys. Keep them in a gitignored `.env` (see
> `.env.example`) or the shell environment. The keys that were previously
> pasted here in plaintext have been rotated and revoked. Paper trading is the
> default (`paper=True` in `broker/alpaca.py`); data feed is `DataFeed.IEX`
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
│   ├── aggregator.py            # Weighted vote, RSI veto, confidence threshold (0.65)
│   └── risk.py                  # ATR stop loss, 2:1 RR, 1% position sizing, min ATR
├── broker/
│   ├── alpaca.py                # submit_order, get_positions, close_all_positions
│   └── data.py                  # LiveBarStream (WebSocket) + fetch_bars (REST/IEX)
├── backtest/
│   ├── runner.py                # Walk-forward backtester — CLI tool
│   └── daily/                   # Per-day CSVs from shadow runner
├── scripts/
│   ├── daily_backtest.py        # Shadow runner — runs during market hours
│   ├── schedule.ps1             # Registers Windows Task Scheduler job
│   ├── state.json               # Tracks day N of 30
│   └── daily_backtest.log       # Append-only log
├── watchlist.json               # Gitignored — persisted symbol list
└── requirements.txt
```

---

## How the Signal Stack Works

Every 1-minute bar goes through this pipeline:

```
Bar → ORB.analyze(df)  → Signal(BUY/SELL/HOLD, confidence)  ┐
    → VWAP.analyze(df) → Signal(BUY/SELL/HOLD, confidence)  ├→ Weighted score
    → EMA.analyze(df)  → Signal(BUY/SELL/HOLD, confidence)  ┘
    → RSI.analyze(df)  → veto gate (blocks overbought buys / oversold sells)
    → if confidence > 0.65 AND not vetoed AND not long_only blocking:
        → RiskManager.calculate() → TradeParams(entry, stop, target, shares)
        → AlpacaBroker.submit_order(params)
```

**Weights:** ORB=0.40, VWAP=0.35, EMA=0.25
**Confidence threshold:** 0.65 (raised from 0.55 after backtest analysis)
**long_only=True** — SELL signals suppressed (bull market config)

---

## Risk Controls

| Control | Value | Where |
|---|---|---|
| Risk per trade | 1% of account | `engine/risk.py` → `risk_pct=0.01` |
| Stop loss | 1.5x ATR | `atr_stop_multiplier=1.5` |
| Take profit | 3.0x ATR (2:1 RR) | `reward_ratio=2.0` |
| Min ATR filter | $0.50 | `min_atr=0.50` (skips quiet stocks) |
| Daily loss halt | 2% | `main.py` → `DAILY_LOSS_LIMIT_PCT=0.02` |
| EOD force close | 3:45pm ET | `main.py` → `EOD_CLOSE_UTC_HOUR=20, MINUTE=45` |

---

## Backtest Results (Jan–Jun 2024, 5m bars, AAPL/TSLA/NVDA, $10k)

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

## 30-Day Shadow Runner (Currently Running)

**What it does:** Runs during market hours alongside the live bot. Subscribes to the same Alpaca stream, logs what the strategy WOULD signal on each bar, then compares to actual Alpaca fills at close. The "alignment %" shows if the live bot is faithfully executing the strategy.

**Schedule:** Windows Task Scheduler → weekdays 9:25am ET → runs until 4pm ET
**State file:** `scripts/state.json` (tracks day N of 30)
**Outputs per day:**
- `backtest/daily/dayNN_YYYY-MM-DD_signals.csv` — every bar's signal
- `backtest/daily/dayNN_YYYY-MM-DD_actual.csv` — every Alpaca fill
- `backtest/30day_summary.csv` — rolling totals

**Go-live criteria (Day 30 auto-check):**
- Sharpe > 1.0
- Max drawdown < 15%
- Net profitable

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
| `gh` not on PATH after winget install | Open | Restart PowerShell or use full path `C:\Program Files\GitHub CLI\gh.exe` |
| IEX feed has lower volume coverage than SIP | By design | Upgrade to `DataFeed.SIP` if Alpaca plan upgraded |
| Shadow runner gets 0 bars if market closed | By design | The IEX stream only fires during market hours |
| `call_soon_threadsafe` needed for `add_symbol` | Fixed | `subscribe_bars` is sync, not a coroutine |
| `StockDataStream._run()` → `.run()` | Fixed | Public method, not private |

---

## What's Next (Priority Order)

1. **Symbol screener** — auto-find high-ATR, high-volume names each morning
2. **Regime filter** — detect SPY trending vs choppy, adjust weights
3. **Performance dashboard** — equity curve, signal heatmap, alignment % chart
4. **Multi-position support** — scale into high-conviction signals
5. **Go live** — flip `paper=False` after 30-day evaluation passes
