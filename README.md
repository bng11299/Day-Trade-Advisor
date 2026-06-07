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
main.py
│
├── broker/data.py         ← Alpaca WebSocket stream (live) / historical bars API (backtest)
│
├── engine/aggregator.py   ← Combines strategy signals into one BUY/SELL/HOLD decision
│   ├── strategies/orb.py       (40% weight)
│   ├── strategies/vwap.py      (35% weight)
│   ├── strategies/ema_crossover.py  (25% weight)
│   └── strategies/rsi_filter.py    (veto gate)
│
├── engine/risk.py         ← Calculates entry, stop loss, take profit, and position size
│
└── broker/alpaca.py       ← Submits orders, tracks positions, closes trades
```

**Data flow on each bar:**
1. Alpaca streams a new 1-minute bar for a subscribed symbol
2. The last 120 bars are fed into all three strategies simultaneously
3. Each strategy returns a `Signal(direction, confidence, reason)`
4. The aggregator combines them into a weighted score; RSI can veto the result
5. If the final confidence exceeds the threshold (0.65), a trade is triggered
6. The risk manager calculates stop loss, take profit, and share count
7. A market order is submitted to Alpaca paper trading

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

1. **Momentum (crossover):** Price crosses from below VWAP to above → BUY (confidence 0.65). Price crosses from above to below → SELL (confidence 0.65). This catches early trend shifts.

2. **Mean reversion (stretched):** If price is more than 2 standard deviations above VWAP, it's likely to revert → SELL. More than 2σ below → BUY. Confidence scales with how far the stretch is.

3. **Trend continuation:** If price is above/below VWAP but hasn't just crossed, a weaker signal (0.45) is emitted in the direction of the trend.

**Why it works:** VWAP resets each day, so it's a pure intraday tool. Market makers constantly reference it, which makes it self-fulfilling as a support/resistance level.

**Key parameters** (`strategies/vwap.py`):
```python
std_bands = 2.0  # standard deviation multiplier for mean-reversion trigger
```

---

### EMA Crossover

**Weight: 25%**

Uses Exponential Moving Averages (EMA) rather than Simple Moving Averages because EMAs weight recent prices more heavily, making them faster to react to intraday moves.

**Logic:**
- EMA(9) crossing above EMA(21) = "golden cross" → BUY (confidence 0.70 base, +0.20 if volume confirms)
- EMA(9) crossing below EMA(21) = "death cross" → SELL
- If already crossed (trend continuation), emits a weaker directional signal (0.40–0.65) scaled by the spread between the two EMAs

**Why it works:** The 9/21 EMA pair is one of the most widely-watched intraday indicators. When a cross happens with volume, it signals a genuine shift in short-term momentum.

**Key parameters** (`strategies/ema_crossover.py`):
```python
fast = 9
slow = 21
volume_multiplier = 1.3  # required volume for max confidence on a fresh cross
```

---

### RSI Filter

**Not a signal — a veto gate.**

RSI (Relative Strength Index) measures how overbought or oversold a stock is on a 0–100 scale.

**Role in the system:**
- If the aggregator wants to BUY but RSI > 70 (overbought) → trade is blocked
- If the aggregator wants to SELL but RSI < 30 (oversold) → trade is blocked
- Otherwise, RSI has no effect on the decision

**Why a veto and not a signal:** RSI alone has a poor standalone track record for day trading. But it is very good at flagging exhausted moves — buying into an overbought stock is a common way to get chopped. Using it only to block bad entries keeps its value while avoiding its weaknesses.

**Key parameters** (`strategies/rsi_filter.py`):
```python
period = 14
oversold = 30
overbought = 70
```

---

### Signal Aggregator

**File:** `engine/aggregator.py`

Combines all three strategy signals into a single decision.

**Weighted scoring:**
```
score = (ORB_confidence × 0.40 × direction)
      + (VWAP_confidence × 0.35 × direction)
      + (EMA_confidence  × 0.25 × direction)
```
Where direction is +1 for BUY and -1 for SELL.

**Decision logic:**
1. Compute weighted score
2. Apply RSI veto if applicable → direction becomes HOLD
3. If final confidence < 0.65 threshold → direction becomes HOLD
4. If `long_only=True` and direction is SELL → direction becomes HOLD

**Example output:**
```
[BUY conf=0.71] ORB=BUY(1.00), VWAP=BUY(0.65), EMA=HOLD(0.00)
[HOLD conf=0.58] ORB=SELL(0.80), VWAP=BUY(0.75), EMA=SELL(0.45) [VETOED: RSI oversold (28.3)]
```

**Key parameters** (`engine/aggregator.py`):
```python
CONFIDENCE_THRESHOLD = 0.65  # minimum score to act (raised from 0.55 after backtest)
long_only = False             # set True in bull markets to suppress SELL signals
```

---

## Risk Management

**File:** `engine/risk.py`

Every trade that passes the signal check goes through the risk manager before an order is placed.

### ATR-Based Stop Loss

ATR (Average True Range) measures how much a stock typically moves per bar. Using ATR for stops means stops are sized to the stock's actual volatility — wide for volatile stocks, tight for quiet ones.

```
stop_distance = ATR(14) × 1.5
stop_loss  = entry - stop_distance   (for BUY)
take_profit = entry + stop_distance × 2.0  (2:1 reward ratio)
```

### Position Sizing

Sized so that hitting the stop loss costs exactly 1% of the account:
```
risk_dollars = account_equity × 0.01
shares = risk_dollars / stop_distance
```

This means a single bad trade can never cost more than 1% of capital, regardless of the stock price or volatility.

### Minimum ATR Filter

If ATR < $0.50, the symbol is skipped entirely. Low-volatility stocks generate noise signals that aren't tradeable — the stop and target would be too close together to survive normal price fluctuations.

### Daily Loss Halt

If the account loses more than 2% in a single day, the bot stops entering new trades for the rest of that day. This prevents a bad morning from snowballing into a catastrophic day.

### EOD Force Close

All open positions are automatically closed at 3:45pm ET (20:45 UTC) regardless of P&L. Day trading positions should never be held overnight — gap risk is unpredictable and outside the model's design.

**Key parameters** (`engine/risk.py`):
```python
risk_pct = 0.01              # 1% of account risked per trade
atr_period = 14
atr_stop_multiplier = 1.5
reward_ratio = 2.0
min_atr = 0.50               # minimum ATR to trade the symbol
```

---

## Data Layer

**File:** `broker/data.py`

All market data comes from Alpaca — the same broker used for execution. This eliminates the delay and reliability issues that come with using a separate data provider (like yfinance).

### Live Trading: `LiveBarStream`

Uses Alpaca's WebSocket API (`StockDataStream`) to receive real-time 1-minute bars as they close. Each bar fires a callback with the rolling 120-bar DataFrame, which is immediately analyzed by the strategy stack.

- **No polling** — the stream pushes data as it becomes available
- **Rolling buffer** — maintains the last 120 bars per symbol in memory
- **Dynamic subscription** — symbols can be added/removed while the stream is running

### Backtest: `fetch_bars`

Uses Alpaca's REST API (`StockHistoricalDataClient`) to pull historical bars for any date range. Supports 1m, 5m, 15m, and 1h intervals. Alpaca provides years of historical data — far beyond the 7-day/60-day limits of yfinance's free tier.

---

## Broker Integration

**File:** `broker/alpaca.py`

Wraps the `alpaca-py` SDK. Paper trading is on by default (`paper=True`).

| Method | What it does |
|---|---|
| `get_account()` | Returns equity, cash, buying power |
| `submit_order(params)` | Places a market order (day order, expires at close) |
| `get_positions()` | Returns all open positions with unrealized P&L |
| `close_position(symbol)` | Closes one position at market |
| `close_all_positions()` | Closes everything and cancels open orders |

---

## Usage

### Setup

**1. Clone and install dependencies:**
```powershell
git clone https://github.com/bng11299/Day-Trade-Advisor.git
cd Day-Trade-Advisor
pip install -r requirements.txt
```

**2. Get Alpaca paper trading API keys:**
- Sign up at [alpaca.markets](https://alpaca.markets)
- Go to Paper Trading → API Keys → Generate

**3. Set environment variables** (run in PowerShell before starting the bot):
```powershell
$env:ALPACA_API_KEY = "your_api_key"
$env:ALPACA_SECRET_KEY = "your_secret_key"
```

---

### Running the Live Bot

```powershell
python main.py
```

**What you'll see on startup:**
```
Day Trade Bot started (paper trading, real-time stream)
Account equity: $100000.00
Watchlist: (empty — use add SYMBOL)
Commands: add SYMBOL | remove SYMBOL | list | status | quit

Waiting for market-hours bars... (no output outside market hours)
[stream] Connected. Subscribed to: []
```

**Terminal commands while running:**

| Command | Action |
|---|---|
| `add NVDA` | Subscribe to NVDA and start watching it |
| `remove NVDA` | Unsubscribe and stop watching |
| `list` | Show current watchlist and open positions |
| `status` | Show current account equity and buying power |
| `quit` | Close all open positions and stop the bot |

**What happens during market hours:**

Every time a 1-minute bar closes for a subscribed symbol, you'll see:
```
[bar] NVDA: [BUY conf=0.71] ORB=BUY(1.00), VWAP=BUY(0.65), EMA=HOLD(0.00)
  TRADE -> BUY 34x NVDA @ $875.20 | SL=$869.80 TP=$886.00 | Risk=$99.80
  Order submitted: abc123 | BUY 34x NVDA
```

Or if no trade is triggered:
```
[bar] NVDA: [HOLD conf=0.52] ORB=HOLD(0.00), VWAP=BUY(0.75), EMA=BUY(0.45)
```

**Automatic behaviors:**
- At **3:45pm ET**: all positions are force-closed
- If **daily loss > 2%**: no new trades for the rest of the day, all positions closed
- At **`quit`**: all positions closed before exiting

**Monitor trades in real time:**
Open [app.alpaca.markets](https://app.alpaca.markets) → Paper Trading → Orders / Positions tabs.

---

### Running a Backtest

The backtester replays historical data through the exact same strategy stack used in live trading.

**Basic usage:**
```powershell
python -m backtest.runner --symbols NVDA TSLA --start 2024-01-01 --end 2024-06-01
```

**With all options:**
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
| `--account` | `10000` | Starting account value in dollars |
| `--long-only` | off | Suppress all SELL signals (recommended for bull markets) |
| `--output` | `backtest_results.csv` | Output CSV file path |

**Sample output:**
```
Using interval: 5m | Data source: Alpaca

Fetching NVDA 2024-01-01 -> 2024-06-01 ...
  19822 bars loaded.
  157 trades generated.

=== BACKTEST SUMMARY ===
  trades: 157
  wins: 72
  losses: 85
  win_rate: 0.459
  total_pnl: 3841.22
  total_return_pct: 38.41
  avg_win: 198.30
  avg_loss: -103.15
  max_drawdown_pct: 9.82
  sharpe: 2.1
Trade log saved: backtest_results.csv
```

**Reading the CSV output:**

Each row is one completed trade with these columns:

| Column | Description |
|---|---|
| `symbol` | Ticker |
| `entry_time` | Bar timestamp when the trade was entered |
| `direction` | BUY or SELL |
| `entry` | Entry price |
| `stop_loss` | Stop loss price (1.5x ATR from entry) |
| `take_profit` | Take profit price (3.0x ATR from entry, 2:1 RR) |
| `shares` | Number of shares (sized to 1% account risk) |
| `confidence` | Aggregated signal confidence at entry (0.0–1.0) |
| `exit_price` | Actual exit price |
| `exit_time` | Timestamp of exit |
| `pnl` | Profit/loss in dollars |
| `result` | `TP` (take profit hit), `SL` (stop loss hit), or `EOD` (force-closed at end of day) |
| `account_after` | Running account balance after this trade |

---

## Configuration Reference

All tunable parameters and where to find them:

| Parameter | File | Default | Effect |
|---|---|---|---|
| `CONFIDENCE_THRESHOLD` | `engine/aggregator.py` | `0.65` | Raise to trade less/higher quality; lower to trade more |
| `long_only` | `engine/aggregator.py` | `True` | Suppress SELL signals in bull markets |
| `orb_minutes` | `strategies/orb.py` | `15` | Opening range window length |
| `orb.volume_multiplier` | `strategies/orb.py` | `1.5` | Volume confirmation required for ORB |
| `vwap.std_bands` | `strategies/vwap.py` | `2.0` | VWAP deviation bands for mean-reversion trigger |
| `ema.fast / slow` | `strategies/ema_crossover.py` | `9 / 21` | EMA crossover periods |
| `risk_pct` | `engine/risk.py` | `0.01` | Fraction of account risked per trade |
| `atr_stop_multiplier` | `engine/risk.py` | `1.5` | Stop distance as multiple of ATR |
| `reward_ratio` | `engine/risk.py` | `2.0` | Take profit = stop × this value |
| `min_atr` | `engine/risk.py` | `0.50` | Minimum ATR to trade a symbol |
| `DAILY_LOSS_LIMIT_PCT` | `main.py` | `0.02` | Halt trading after losing 2% in a day |
| `EOD_CLOSE_UTC_HOUR` | `main.py` | `20` | Force-close hour in UTC (20:45 = 3:45pm ET) |
| `SCAN_INTERVAL` (backtest) | `backtest/runner.py` | — | Walk-forward step is one bar at a time |

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

**Key findings from the analysis:**
- NVDA drove most of the profit — high volatility suits the strategy well
- SELL signals were a net loser in the 2024 bull market — long-only mode fixed this
- The confidence threshold cut 83% of trades while keeping the quality ones
- Avg win ($197) is consistently ~2x avg loss ($105) — the 2:1 reward ratio is holding

---

## Project Structure

```
DayTradeBot/
│
├── main.py                  # Entry point — live paper trading bot
│
├── strategies/
│   ├── base.py              # Signal dataclass and Strategy abstract base class
│   ├── orb.py               # Opening Range Breakout (40% weight)
│   ├── vwap.py              # VWAP crossover + mean reversion (35% weight)
│   ├── ema_crossover.py     # EMA 9/21 crossover + volume (25% weight)
│   └── rsi_filter.py        # RSI overbought/oversold veto gate
│
├── engine/
│   ├── aggregator.py        # Weighted signal voting + RSI veto + confidence threshold
│   └── risk.py              # ATR stops, position sizing, min-ATR filter
│
├── broker/
│   ├── alpaca.py            # Alpaca order execution and position management
│   └── data.py              # Live WebSocket stream + historical bars fetcher
│
├── backtest/
│   └── runner.py            # Walk-forward backtester with CSV output
│
├── watchlist.py             # JSON-backed watchlist (add/remove/load/save)
├── requirements.txt         # Python dependencies
└── .gitignore
```

**Dependencies** (`requirements.txt`):
```
yfinance>=0.2.40      # kept for reference; data layer uses Alpaca
pandas>=2.0
numpy>=1.26
alpaca-py>=0.26       # Alpaca trading + data SDK
```

---

## What's Next

Planned improvements in priority order:

1. **Performance tracking dashboard** — pull live paper trade history from Alpaca API and compare against backtest predictions day by day
2. **Symbol screener** — automatically find high-ATR, high-volume stocks each morning rather than manually adding them
3. **Regime filter** — detect whether the broader market (SPY) is in a trending or choppy day, and adjust strategy weights accordingly
4. **Multi-position support** — currently holds one position per symbol; allow scaling in on conviction
5. **Live trading** — switch `paper=False` in `AlpacaBroker` once paper results are consistently positive for 30+ days
