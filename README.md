# Day Trade Bot

A rule-based, emotion-free day trading bot built in Python. Uses a weighted combination of Opening Range Breakout, VWAP, and EMA strategies to generate BUY/SELL signals, executes trades through Alpaca's paper/live trading API, and enforces strict risk controls to protect capital.

---

## Table of Contents

1. [Philosophy](#philosophy)
2. [Architecture Overview](#architecture-overview)
3. [Strategies](#strategies)
   - [Opening Range Breakout (ORB)](#opening-range-breakout-orb)
   - [VWAP](#vwap)
   - [EMA Crossover](#ema-crossover)
   - [RSI Filter](#rsi-filter)
   - [Signal Aggregator](#signal-aggregator)
4. [Risk Management](#risk-management)
5. [Data Layer](#data-layer)
6. [Broker Integration](#broker-integration)
7. [Usage](#usage)
   - [Setup](#setup)
   - [Running the Live Bot](#running-the-live-bot)
   - [Running a Backtest](#running-a-backtest)
   - [30-Day Live Shadow Runner](#30-day-live-shadow-runner)
8. [Configuration Reference](#configuration-reference)
9. [Backtest Results](#backtest-results)
10. [Project Structure](#project-structure)
11. [What's Next](#whats-next)

---

## Philosophy

Most retail traders lose money not because their strategy is wrong, but because emotions override their rules. This bot removes that variable entirely:

- **Rule-based**: every decision is deterministic — the same market conditions always produce the same action
- **No overrides**: the bot either trades or it doesn't; there is no "maybe" or "gut feel"
- **Risk-first**: position sizing, stop losses, and daily loss limits are enforced on every single trade
- **Consistent**: it will grind through a losing streak without panic and through a winning streak without greed

The edge comes from discipline and consistency, not from predicting the market.

---

## Architecture Overview

```
main.py  (live bot)                     daily_backtest.py  (shadow runner)
│                                        │
├── broker/data.py  ←─── Alpaca WebSocket stream (same feed, same bars) ───┘
│       (LiveBarStream)
│
├── engine/aggregator.py   ← Combines strategy signals into one BUY/SELL/HOLD decision
│   ├── strategies/orb.py            (40% weight)
│   ├── strategies/vwap.py           (35% weight)
│   ├── strategies/ema_crossover.py  (25% weight)
│   └── strategies/rsi_filter.py     (veto gate)
│
├── engine/risk.py         ← Entry, stop loss, take profit, position size
│
└── broker/alpaca.py       ← Submits real paper orders to Alpaca
```

**Data flow on each bar:**
1. Alpaca streams a new 1-minute bar for a subscribed symbol
2. The last 120 bars are fed into all three strategies simultaneously
3. Each strategy returns a `Signal(direction, confidence, reason)`
4. The aggregator combines them into a weighted score; RSI can veto the result
5. If confidence > 0.65, a trade is triggered
6. The risk manager calculates stop loss, take profit, and share count
7. A market order is submitted to Alpaca paper trading

**Simultaneously**, the shadow runner watches the same stream, logs what the strategy signals, and compares against actual fills at end of day.

---

## Strategies

All strategies implement the same interface:

```python
def analyze(self, df: pd.DataFrame) -> Signal
# df: DataFrame with columns Open, High, Low, Close, Volume (1-minute bars)
# Signal: dataclass with direction (BUY/SELL/HOLD), confidence (0.0–1.0), reason (str)
```

### Opening Range Breakout (ORB)

**Weight: 40%** — the primary signal driver.

**Logic:**
- The first 15 minutes of the trading session define the "opening range" (high and low)
- If price breaks above the range high → BUY signal
- If price breaks below the range low → SELL signal
- Volume must be at least 1.5x the session average to confirm the breakout

**Confidence scaling:**
- Starts at 0.5 (bare breakout)
- +0.3 scaled by how far price has moved beyond the range boundary
- +0.2 bonus if volume confirms

**Why it works:** The opening range captures early institutional order flow and news-driven momentum. A breakout with volume means large players are committed to a direction.

**Key parameters** (`strategies/orb.py`):
```python
orb_minutes = 15        # length of opening range window
volume_multiplier = 1.5 # required volume vs session average
```

---

### VWAP

**Weight: 35%**

Volume Weighted Average Price is the benchmark institutional traders use to measure execution quality. Retail traders can use it as a dynamic support/resistance level.

**Two modes:**

1. **Momentum (crossover):** Price crosses from below VWAP to above → BUY (confidence 0.65). Price crosses from above to below → SELL (confidence 0.65).

2. **Mean reversion (stretched):** If price is more than 2 standard deviations above VWAP → SELL. More than 2σ below → BUY. Confidence scales with stretch distance.

3. **Trend continuation:** If price is above/below VWAP but no fresh cross, weaker signal (0.45) in the trend direction.

**Why it works:** VWAP resets each day, so it's a pure intraday tool. Market makers constantly reference it, making it self-fulfilling as support/resistance.

**Key parameters** (`strategies/vwap.py`):
```python
std_bands = 2.0  # standard deviation multiplier for mean-reversion trigger
```

---

### EMA Crossover

**Weight: 25%**

Uses Exponential Moving Averages rather than Simple Moving Averages because EMAs weight recent prices more heavily, reacting faster to intraday moves.

**Logic:**
- EMA(9) crossing above EMA(21) = "golden cross" → BUY (confidence 0.70 base, +0.20 if volume confirms)
- EMA(9) crossing below EMA(21) = "death cross" → SELL
- Trend continuation emits weaker directional signal (0.40–0.65) scaled by EMA spread

**Key parameters** (`strategies/ema_crossover.py`):
```python
fast = 9
slow = 21
volume_multiplier = 1.3
```

---

### RSI Filter

**Not a signal — a veto gate.**

RSI (Relative Strength Index) measures overbought/oversold conditions on a 0–100 scale.

- If aggregator wants to BUY but RSI > 70 (overbought) → trade is blocked
- If aggregator wants to SELL but RSI < 30 (oversold) → trade is blocked
- Otherwise RSI has no effect

**Why a veto and not a signal:** RSI alone has poor standalone track record for day trading. But it reliably flags exhausted moves — buying into an overbought stock is a common losing pattern.

**Key parameters** (`strategies/rsi_filter.py`):
```python
period = 14
oversold = 30
overbought = 70
```

---

### Signal Aggregator

**File:** `engine/aggregator.py`

**Weighted scoring:**
```
score = (ORB_confidence × 0.40 × direction)
      + (VWAP_confidence × 0.35 × direction)
      + (EMA_confidence  × 0.25 × direction)
```
Where direction is +1 for BUY, -1 for SELL.

**Decision logic:**
1. Compute weighted score
2. Apply `long_only` filter (suppress SELL in bull markets)
3. Apply RSI veto if applicable
4. If confidence < 0.65 → HOLD

**Example output:**
```
[BUY conf=0.71] ORB=BUY(1.00), VWAP=BUY(0.65), EMA=HOLD(0.00)
[HOLD conf=0.58] ORB=SELL(0.80), VWAP=BUY(0.75), EMA=SELL(0.45) [VETOED: RSI oversold (28.3)]
```

**Key parameters:**
```python
CONFIDENCE_THRESHOLD = 0.65  # minimum weighted score to place a trade
long_only = True              # suppress SELL signals (set in bull markets)
```

---

## Risk Management

**File:** `engine/risk.py`

Every trade that passes the signal check goes through the risk manager before an order is placed.

### ATR-Based Stop Loss

ATR (Average True Range) measures how much a stock typically moves per bar. Stops are sized to the stock's actual volatility.

```
stop_distance  = ATR(14) × 1.5
stop_loss      = entry − stop_distance        (for BUY)
take_profit    = entry + stop_distance × 2.0  (2:1 reward ratio)
```

### Position Sizing

Sized so that hitting the stop loss costs exactly 1% of the account:
```
shares = (account_equity × 0.01) / stop_distance
```

A single bad trade can never cost more than 1% of capital.

### Minimum ATR Filter

If ATR < $0.50, the symbol is skipped. Low-volatility stocks generate noise signals the strategy can't act on cleanly.

### Daily Loss Halt

If the account loses more than 2% in a single day, the bot stops entering new trades for the rest of that day.

### EOD Force Close

All open positions are automatically closed at 3:45pm ET. Day trading positions are never held overnight.

**Key parameters:**
```python
risk_pct = 0.01              # 1% of account risked per trade
atr_stop_multiplier = 1.5
reward_ratio = 2.0
min_atr = 0.50
```

---

## Data Layer

**File:** `broker/data.py`

All market data comes from Alpaca — the same broker used for execution. Uses the **IEX feed** (free-tier compatible).

> To upgrade to full SIP data, change `feed=DataFeed.IEX` → `feed=DataFeed.SIP` in `broker/data.py` (requires Alpaca paid plan).

### Live Trading: `LiveBarStream`

Uses Alpaca's WebSocket API (`StockDataStream`) to receive real-time 1-minute bars. Each bar fires a callback with the rolling 120-bar DataFrame for immediate strategy analysis.

- No polling — stream pushes data as it arrives
- Rolling buffer — last 120 bars per symbol kept in memory
- Dynamic subscription — symbols added/removed while running via `call_soon_threadsafe`

### Backtest: `fetch_bars`

Uses Alpaca's REST API (`StockHistoricalDataClient`) for historical bars. Supports 1m, 5m, 15m, 1h intervals. Years of history available — no rolling-window limit.

---

## Broker Integration

**File:** `broker/alpaca.py`

Wraps `alpaca-py` SDK. Paper trading is on by default (`paper=True`).

| Method | What it does |
|---|---|
| `get_account()` | Returns equity, cash, buying power |
| `submit_order(params)` | Places a market order (day order) |
| `get_positions()` | Returns open positions with unrealized P&L |
| `close_position(symbol)` | Closes one position at market |
| `close_all_positions()` | Closes everything and cancels open orders |

---

## Usage

### Setup

**1. Clone and install:**
```powershell
git clone https://github.com/bng11299/Day-Trade-Advisor.git
cd Day-Trade-Advisor
pip install -r requirements.txt
```

**2. Get Alpaca paper trading keys:**
- Sign up at [alpaca.markets](https://alpaca.markets)
- Go to Paper Trading → API Keys → Generate

**3. Set environment variables:**
```powershell
$env:ALPACA_API_KEY = "your_api_key"
$env:ALPACA_SECRET_KEY = "your_secret_key"
```

---

### Running the Live Bot

```powershell
python main.py
```

**Startup output:**
```
Day Trade Bot started (paper trading, real-time stream)
Account equity: $100000.00
Watchlist: (empty — use add SYMBOL)
Commands: add SYMBOL | remove SYMBOL | list | status | quit

Waiting for market-hours bars... (no output outside market hours)
[stream] Connected. Subscribed to: []
```

**Terminal commands:**

| Command | Action |
|---|---|
| `add NVDA` | Subscribe to NVDA and start watching it |
| `remove NVDA` | Unsubscribe and stop watching |
| `list` | Show watchlist and open positions |
| `status` | Show current account equity |
| `quit` | Close all positions and stop the bot |

**What you'll see during market hours:**
```
[bar] NVDA: [BUY conf=0.71] ORB=BUY(1.00), VWAP=BUY(0.65), EMA=HOLD(0.00)
  TRADE -> BUY 34x NVDA @ $875.20 | SL=$869.80 TP=$886.00 | Risk=$99.80
  Order submitted: abc123 | BUY 34x NVDA

[bar] NVDA: [HOLD conf=0.52] ORB=HOLD(0.00), VWAP=BUY(0.75), EMA=BUY(0.45)
```

**Automatic behaviors:**
- **3:45pm ET**: all positions force-closed
- **Daily loss > 2%**: trading halts for the rest of the day
- **`quit`**: all positions closed before exit

Monitor live at [app.alpaca.markets](https://app.alpaca.markets) → Paper Trading.

---

### Running a Backtest

Replays historical data through the exact same strategy stack used live.

```powershell
python -m backtest.runner --symbols NVDA TSLA --start 2024-01-01 --end 2024-06-01
```

**All options:**
```powershell
python -m backtest.runner `
  --symbols NVDA TSLA AAPL `
  --start 2024-01-01 `
  --end 2024-06-01 `
  --interval 5m `
  --account 10000 `
  --long-only `
  --output my_results.csv
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--symbols` | required | One or more ticker symbols |
| `--start` | required | Start date (YYYY-MM-DD) |
| `--end` | required | End date (YYYY-MM-DD) |
| `--interval` | `5m` | Bar size: `1m`, `5m`, `15m`, `1h` |
| `--account` | `10000` | Starting account value ($) |
| `--long-only` | off | Suppress SELL signals (recommended for bull markets) |
| `--output` | `backtest_results.csv` | Output CSV path |

**Sample output:**
```
=== BACKTEST SUMMARY ===
  trades: 157
  win_rate: 0.459
  total_pnl: 3841.22
  total_return_pct: 38.41
  max_drawdown_pct: 9.82
  sharpe: 2.1
```

**CSV trade log columns:**

| Column | Description |
|---|---|
| `symbol` | Ticker |
| `entry_time` | Bar timestamp of entry |
| `direction` | BUY or SELL |
| `entry` | Entry price |
| `stop_loss` | Stop loss price (1.5x ATR from entry) |
| `take_profit` | Take profit price (2:1 reward ratio) |
| `shares` | Shares traded (1% account risk) |
| `confidence` | Aggregated signal confidence at entry |
| `exit_price` | Actual exit price |
| `pnl` | Profit/loss in dollars |
| `result` | `TP`, `SL`, or `EOD` (force-closed) |
| `account_after` | Running account balance after trade |

---

### 30-Day Live Shadow Runner

The shadow runner is the **validation layer** — it runs alongside the live bot during market hours, processes the same real-time bars, and compares what the strategy *signals* versus what Alpaca *actually executed*. This catches slippage, missed fills, or strategy drift before they affect real money.

#### How it works

```
9:25am  Task Scheduler starts daily_backtest.py
9:30am  Market opens
        ├── main.py            → places real paper orders
        └── daily_backtest.py  → watches same bars, logs signals only (no orders)
              ↓ every bar:
        10:32 NVDA [BUY] conf=0.71  close=131.40
        10:33 NVDA [----] conf=0.48  close=131.55
              ...
4:00pm  Market closes
        → pulls actual Alpaca fills, compares to shadow log
        Shadow signals  — BUY: 4  SELL: 0
        Live bot trades — BUY: 3  SELL: 0
        Signal alignment: 75%
```

The **alignment %** is the key metric. If shadow says BUY 4 times and the live bot only traded 3, something caused a missed fill — timing, slippage, or a bug. Alignment consistently below ~80% means the live bot is drifting from the strategy.

#### Files produced each day

```
backtest/daily/
├── day01_2026-06-11_signals.csv   ← every bar: signal, confidence, would-trade params
├── day01_2026-06-11_actual.csv    ← every Alpaca order filled that day
backtest/30day_summary.csv         ← running totals: signals, trades, alignment % per day
scripts/daily_backtest.log         ← full stdout from every scheduled run
```

#### Automatic scheduling

The shadow runner is registered in Windows Task Scheduler and fires automatically every weekday at 9:25am ET. To set it up on a new machine:

```powershell
powershell -ExecutionPolicy Bypass -File "scripts\schedule.ps1"
```

#### Manual commands

```powershell
# Force a run right now (for testing)
Start-ScheduledTask -TaskName "DayTradeBot-DailyBacktest"

# Watch the live log
Get-Content scripts\daily_backtest.log -Tail 50 -Wait

# View the 30-day summary
Import-Csv backtest\30day_summary.csv | Format-Table

# Check task status
Get-ScheduledTask -TaskName "DayTradeBot-DailyBacktest"

# Remove the task
Unregister-ScheduledTask -TaskName "DayTradeBot-DailyBacktest" -Confirm:$false
```

#### Day 30 final report

On the last day the script prints a go/no-go verdict:
- ✅ **Ready for live** if: Sharpe > 1.0, max drawdown < 15%, consistently profitable
- ⚠️ **Keep tuning** with specific reasons if thresholds aren't met

---

## Configuration Reference

| Parameter | File | Default | Effect |
|---|---|---|---|
| `CONFIDENCE_THRESHOLD` | `engine/aggregator.py` | `0.65` | Raise = fewer, higher-quality trades |
| `long_only` | `engine/aggregator.py` | `True` | Suppress SELL signals in bull markets |
| `orb_minutes` | `strategies/orb.py` | `15` | Opening range window length |
| `orb.volume_multiplier` | `strategies/orb.py` | `1.5` | Volume required to confirm ORB breakout |
| `vwap.std_bands` | `strategies/vwap.py` | `2.0` | VWAP deviation bands for mean-reversion |
| `ema.fast / slow` | `strategies/ema_crossover.py` | `9 / 21` | EMA crossover periods |
| `risk_pct` | `engine/risk.py` | `0.01` | Fraction of account risked per trade |
| `atr_stop_multiplier` | `engine/risk.py` | `1.5` | Stop distance as ATR multiple |
| `reward_ratio` | `engine/risk.py` | `2.0` | Take profit = stop × this |
| `min_atr` | `engine/risk.py` | `0.50` | Skip symbols quieter than this |
| `DAILY_LOSS_LIMIT_PCT` | `main.py` | `0.02` | Halt after losing 2% in a day |
| `EOD_CLOSE_UTC_HOUR` | `main.py` | `20` | Force-close at 3:45pm ET (20:45 UTC) |
| `SYMBOLS` | `scripts/daily_backtest.py` | `["NVDA","TSLA"]` | Symbols shadow runner watches |
| `feed` | `broker/data.py` | `DataFeed.IEX` | Change to `DataFeed.SIP` with paid plan |

---

## Backtest Results

Tested on AAPL, TSLA, NVDA — January through June 2024 — using 5-minute bars.

### Before risk controls (v1)

| Metric | Value |
|---|---|
| Trades | 1,317 |
| Win rate | 33.9% |
| Total return | +21% |
| Max drawdown | **51.5%** |
| Sharpe ratio | 0.18 |

### After risk controls (v2, long-only)

| Metric | Value |
|---|---|
| Trades | 229 |
| Win rate | 41.0% |
| Total return | **+43%** |
| Max drawdown | **10.4%** |
| Sharpe ratio | **1.9** |

**Key findings:**
- NVDA drove most profit — high volatility suits the strategy well
- SELL signals were a net loser in the 2024 bull market → long-only mode fixed this
- Raising confidence threshold 0.55 → 0.65 cut 83% of trades, kept quality ones
- Avg win ($197) is consistently ~2x avg loss ($105) — 2:1 reward ratio holding
- AAPL barely traded (only 15 trades vs 455 before) — min-ATR filter working

---

## Project Structure

```
DayTradeBot/
│
├── main.py                      # Live paper trading bot (event-driven stream)
│
├── strategies/
│   ├── base.py                  # Signal dataclass + Strategy abstract class
│   ├── orb.py                   # Opening Range Breakout (40% weight)
│   ├── vwap.py                  # VWAP crossover + mean reversion (35% weight)
│   ├── ema_crossover.py         # EMA 9/21 + volume confirmation (25% weight)
│   └── rsi_filter.py            # RSI overbought/oversold veto gate
│
├── engine/
│   ├── aggregator.py            # Weighted vote + RSI veto + confidence threshold
│   └── risk.py                  # ATR stops, 1% position sizing, min-ATR filter
│
├── broker/
│   ├── alpaca.py                # Order execution and position management
│   └── data.py                  # LiveBarStream (WebSocket) + fetch_bars (REST)
│
├── backtest/
│   ├── runner.py                # Walk-forward backtester with CSV output
│   └── daily/                   # Per-day signal logs + actual trade CSVs
│       └── 30day_summary.csv
│
├── scripts/
│   ├── daily_backtest.py        # Live shadow runner (market hours, 30-day period)
│   ├── schedule.ps1             # One-time Task Scheduler registration
│   ├── state.json               # Tracks current day in 30-day period
│   └── daily_backtest.log       # Append-only log from scheduled runs
│
├── watchlist.json               # Persisted symbol list (gitignored)
├── requirements.txt
└── .gitignore
```

**Dependencies:**
```
pandas>=2.0
numpy>=1.26
alpaca-py>=0.26      # trading + data SDK (replaces yfinance)
```

---

## What's Next

Planned improvements in priority order:

1. **Symbol screener** — automatically find high-ATR, high-volume stocks each morning rather than manually adding them
2. **Regime filter** — detect whether SPY is trending or choppy and adjust strategy weights accordingly
3. **Performance dashboard** — visualize the 30-day shadow log: equity curve, signal heatmap, alignment % over time
4. **Multi-position support** — currently one position per symbol; allow scaling in on high-conviction signals
5. **Live trading** — flip `paper=False` in `AlpacaBroker` once paper results pass the 30-day evaluation
