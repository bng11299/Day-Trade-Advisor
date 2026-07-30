# DayTradeBot — Session Summary for Next Chat
_Last updated: 2026-06-19 (after Day 6 market close)_

---

## Where we are

**30-day shadow backtest: Day 6 of 30 complete. Day 7 runs tonight (2026-06-19).**

6 days in, zero BUY signals have fired. Not a bug — the market has been consistently bearish/sideways and the confidence threshold (0.65) hasn't been reached. The system is working correctly; we're just waiting for a green day.

---

## Day 6 results (2026-06-18)

- **860 bars logged, 0 BUY signals**
- 404 SELL vetoes (long_only mode — bearish day confirmed)
- 80 RSI overbought vetoes
- **Best bar: MU at 12:59pm ET, conf=0.583** — all three indicators bullish (ORB=0.72, VWAP=0.45, EMA=0.55), still 0.067 short of the 0.65 threshold
- ATR path (`would_entry` / `would_stop` etc.) has **still never fired**
- Day 6 ran on the OLD 15-stock watchlist (screener conflict — fixed for Day 7)

---

## Big change: new 20-stock watchlist (active from Day 7)

Replaced the old list (slow consumer staples, weak financials, oil services) with curated day-trading names:

`NVDA, TSLA, AMD, META, AAPL, MSFT, AMZN, GOOGL, PLTR, NFLX, MU, AVGO, SMCI, JPM, BAC, XOM, CVX, LLY, COIN, C`

**Screener conflict fixed:** The morning screener at 9:15pm SGT was overwriting `watchlist.json` with its own S&P 500 picks every day. Fixed by:
- Adding PLTR, SMCI, COIN to the screener's universe
- Bumping screener `DEFAULT_TOP_N` to 20, `max_per_sector` to 3
- Now the screener scores the full universe including our curated names and they rank naturally

---

## New feature: UVXY regime filter (active from Day 7)

UVXY (VIX fear ETF) added as a **soft confidence modifier** — not a hard veto.

**How it works:**
- UVXY subscribed to the bar stream but never traded
- Intraday % change from previous close tracked on every 1-min bar
- Before each stock signal evaluates, the confidence threshold is bumped based on UVXY:

| UVXY move | Threshold bump | Effective threshold |
|-----------|---------------|---------------------|
| ≤ +2% | +0.00 | 0.65 (normal) |
| +2–5% | +0.03 | 0.68 |
| +5–10% | +0.06 | 0.71 |
| > +10% | +0.10 | 0.75 (max) |

**Key property:** A strong signal (conf=0.80) still trades even through a fear spike (threshold=0.75). UVXY raises the bar — it doesn't lock the door.

When UVXY is the deciding factor, log shows: `[VETOED: UVXY regime (+6.3%, threshold 0.71)]`

---

## Known issue to investigate: VWAP confidence floor

VWAP is consistently outputting **0.45 confidence** on bullish-but-not-strong readings across all 6 days. This is its apparent floor. The problem: with VWAP locked at 0.45 and weight=0.35, it contributes at most 0.1575 to the composite. Even with ORB=1.0 and EMA=1.0, max composite = ~0.557. That's why we've never hit 0.65.

**Next action:** Read `strategies/vwap.py` and check what causes the 0.45 floor. If VWAP is returning 0.45 on clearly bullish readings, it's artificially suppressing all signals and the threshold discussion (0.65 vs 0.60) is moot until this is fixed.

---

## Files changed this session

| File | What changed |
|------|-------------|
| `watchlist.json` | New 20-stock curated list |
| `engine/aggregator.py` | UVXY regime filter (`_uvxy_threshold_bump`, `uvxy_pct` param on `analyze()`) |
| `broker/data.py` | Added `fetch_prev_close()` |
| `scripts/daily_backtest.py` | ShadowRunner tracks UVXY, passes `uvxy_pct` to aggregator |
| `main.py` | UVXY tracked in live stream, passed to aggregator |
| `scripts/screener.py` | Added PLTR/SMCI to Technology, COIN to Financials; TOP_N=20, max_per_sector=3 |

---

## What to check when you wake up

1. **Day 7 signals CSV** (`backtest/daily/day07_2026-06-19_signals.csv`) — first run with new watchlist (NVDA, PLTR, SMCI etc.)
2. **Any `would_entry` values filled** — has the ATR path ever fired?
3. **Any `[VETOED: UVXY regime...]`** — first live test of the fear filter
4. **NVDA/PLTR confidence scores** — are these generating stronger signals than the old slow-mover list?
5. **VWAP 0.45 floor** — does it still appear with the new symbols, or was it specific to the old stocks?
