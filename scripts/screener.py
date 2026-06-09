"""
Morning symbol screener -- finds the top 10 high-ATR, high-volume S&P 500 stocks
to watch each trading day. Run before market open (Task Scheduler fires at 9:15am ET).

Output: overwrites watchlist.json with the top-N symbols, sector-diversified,
ranked by ATR x relative-volume score.

Usage:
    python scripts/screener.py                      # screen and update watchlist
    python scripts/screener.py --dry-run            # print results without saving
    python scripts/screener.py --top 5              # override top-N
    python scripts/screener.py --min-atr 1.00       # stricter ATR floor
    python scripts/screener.py --max-per-sector 1   # tighter sector cap
"""

import argparse
import math
import os
import sys
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.enums import DataFeed

# ── GICS sector map (S&P 500 constituents grouped by sector) ─────────────────
# Used for diversity enforcement: max N symbols per sector in the final watchlist.
SECTORS = {
    "Technology": [
        "AAPL","MSFT","NVDA","AMD","INTC","AVGO","QCOM","AMAT","LRCX","MU",
        "KLAC","ADBE","CRM","ORCL","CSCO","TXN","NXPI","MCHP","ON","ADI",
        "SNPS","CDNS","FTNT","PANW","NOW","INTU","IBM","HPQ","HPE","WDC",
        "STX","NTAP","CDW","KEYS","JNPR","FFIV","AKAM","MPWR","ENPH","FSLR",
        "GLW","TEL","APH","MSI","IT","GDDY","EPAM","CTSH","ACN",
    ],
    "Communication Services": [
        "GOOGL","META","NFLX","DIS","CMCSA","T","VZ","TMUS","EA","TTWO",
        "NDAQ","WBD","PARA","FOX","FOXA","LYV","MTCH","ZM","SNAP",
    ],
    "Consumer Discretionary": [
        "AMZN","TSLA","HD","MCD","NKE","LOW","TJX","SBUX","BKNG","MAR",
        "HLT","MGM","LVS","WYNN","F","GM","APTV","EBAY","ROST","DG",
        "DLTR","AZO","ORLY","TSCO","BBY","TPR","RL","PVH","DECK","LULU",
        "RCL","CCL","NCLH","DRI","YUM","CMG","MCD","PHM","DHI","LEN",
        "NVR","POOL","WHR","HAS","MAT",
    ],
    "Consumer Staples": [
        "PG","KO","PEP","COST","WMT","PM","MO","MDLZ","KHC","KMB",
        "CL","GIS","CPB","SJM","HSY","K","MKC","CAG","TSN","HRL",
        "TAP","STZ","BF.B","MNST","KDP","EL","COTY",
    ],
    "Health Care": [
        "JNJ","UNH","LLY","ABBV","PFE","MRK","BMY","AMGN","GILD","REGN",
        "VRTX","ISRG","TMO","DHR","ABT","MDT","BSX","SYK","ZBH","BDX",
        "CI","CVS","HUM","MOH","ELV","IDXX","IQV","DXCM","ILMN","MRNA",
        "BIIB","HOLX","ALGN","TECH","RMD","GEHC","RVTY","CTLT","MTD",
        "WAT","A","COO","BAX","TFX","HSIC","INCY","HCA","CRL",
    ],
    "Financials": [
        "JPM","BAC","WFC","GS","MS","C","BLK","AXP","V","MA",
        "PYPL","COF","USB","TFC","PNC","SCHW","BX","CB","MET","PRU",
        "AFL","ALL","AIG","BEN","IVZ","TROW","BRK.B","ICE","CME","CBOE",
        "SPGI","MCO","FI","FIS","FISV","PAYX","ADP","RJF","MKTX",
        "HIG","L","GL","RHI","AIZ","AJG","MMC","WTW","CINF","PFG",
        "FRT","CMA","HBAN","KEY","RF","STT","MTB","CFG","FITB","ZION",
    ],
    "Industrials": [
        "HON","GE","MMM","CAT","DE","BA","LMT","RTX","NOC","GD",
        "LHX","TDG","ITW","EMR","ETN","ROK","PH","IR","OTIS","CARR",
        "AME","ROP","FAST","CTAS","PCAR","DAL","UAL","AAL","LUV","CSX",
        "NSC","UNP","UPS","FDX","GWW","CHRW","EXPD","WAB","LDOS","AXON",
        "J","JBHT","SNA","SWK","TT","TXT","HWM","HII","BWA","DAY",
        "ODFL","RSG","WM","BR","PAYC","AOS","DOV","HUBB","PNR","XYL",
    ],
    "Energy": [
        "XOM","CVX","COP","EOG","SLB","HAL","BKR","DVN","APA","MRO",
        "OXY","FANG","PSX","VLO","MPC","KMI","WMB","OKE","TRGP","LNG",
        "CF","MOS","NRG","CEG","VST",
    ],
    "Materials": [
        "LIN","APD","ECL","SHW","DD","DOW","LYB","NUE","STLD","FCX",
        "NEM","ALB","CE","EMN","PPG","VMC","MLM","AVY","PKG","IP",
        "AMCR","BLL","WRK","SEE","FMC","MOS","CF",
    ],
    "Utilities": [
        "NEE","DUK","SO","D","EXC","AEP","SRE","XEL","WEC","ES",
        "ETR","FE","AES","CMS","NI","LNT","EVRG","AEE","CNP","PPL","PNW",
    ],
    "Real Estate": [
        "AMT","PLD","EQIX","CCI","SPG","O","PSA","EQR","AVB","DLR",
        "ARE","BXP","INVH","EXR","WELL","VTR","CBRE","VICI","IRM","WY",
        "CPT","DEI","HST","SLG","UDR","REG",
    ],
}

# Flat list of all symbols (remove any with dots -- IEX rejects them)
SP500 = sorted(set(
    s for syms in SECTORS.values() for s in syms if "." not in s
))

# Reverse lookup: symbol -> sector
SYMBOL_SECTOR = {s: sec for sec, syms in SECTORS.items() for s in syms}

# ── screening parameters ──────────────────────────────────────────────────────
DEFAULT_TOP_N           = 15
DEFAULT_MAX_PER_SECTOR  = 2      # diversity cap: at most this many per sector
DEFAULT_MIN_ATR         = 0.75   # dollars
DEFAULT_MIN_VOLUME      = 500_000
DEFAULT_MIN_PRICE       = 10.0
DEFAULT_MAX_PRICE       = 1500.0
PRICE_SANITY_HIGH       = 2.5    # skip if last close > 2.5x 20-day median (likely bad data)
PRICE_SANITY_LOW        = 0.4    # skip if last close < 0.4x 20-day median
LOOKBACK_DAYS           = 20
BATCH_SIZE              = 50
BATCH_DELAY_SEC         = 0.5


def _fetch_daily_bars_batch(
    symbols: list[str],
    start: str,
    end: str,
    client: StockHistoricalDataClient,
) -> dict[str, pd.DataFrame]:
    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame(1, TimeFrameUnit.Day),
        start=datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc),
        end=datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc),
        feed=DataFeed.IEX,
    )
    bars = client.get_stock_bars(request)
    df_all = bars.df

    result = {}
    if df_all.empty:
        return result

    if isinstance(df_all.index, pd.MultiIndex):
        for sym in symbols:
            try:
                df = df_all.xs(sym, level="symbol").copy()
                df.columns = [c.capitalize() for c in df.columns]
                keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
                if len(df) >= 5:
                    result[sym] = df[keep]
            except KeyError:
                pass
    return result


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    high  = df["High"]
    low   = df["Low"]
    close = df["Close"]
    prev  = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return float(tr.tail(period).mean())


def _relative_volume(df: pd.DataFrame) -> float:
    avg = df["Volume"].mean()
    return float(df["Volume"].iloc[-1] / avg) if avg > 0 else 0.0


def _price_is_sane(df: pd.DataFrame) -> tuple[bool, str]:
    """Return (True, '') if the last close looks consistent with recent history."""
    median_close = float(df["Close"].median())
    last_close   = float(df["Close"].iloc[-1])
    if median_close <= 0:
        return False, "zero median"
    ratio = last_close / median_close
    if ratio > PRICE_SANITY_HIGH:
        return False, f"last close ${last_close:.2f} is {ratio:.1f}x 20-day median ${median_close:.2f} -- possible bad data"
    if ratio < PRICE_SANITY_LOW:
        return False, f"last close ${last_close:.2f} is {ratio:.2f}x 20-day median ${median_close:.2f} -- possible bad data"
    return True, ""


def screen(
    top_n: int = DEFAULT_TOP_N,
    max_per_sector: int = DEFAULT_MAX_PER_SECTOR,
    min_atr: float = DEFAULT_MIN_ATR,
    min_volume: int = DEFAULT_MIN_VOLUME,
    min_price: float = DEFAULT_MIN_PRICE,
    max_price: float = DEFAULT_MAX_PRICE,
    verbose: bool = True,
) -> list[dict]:
    """
    Screen the S&P 500 universe and return a sector-diversified ranked list.
    Returns dicts with: symbol, sector, atr, avg_volume, rel_volume, last_close, score.
    """
    api_key    = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise EnvironmentError("Set ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables.")

    client   = StockHistoricalDataClient(api_key, secret_key)
    end_dt   = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=LOOKBACK_DAYS * 2)
    start    = start_dt.strftime("%Y-%m-%d")
    end      = end_dt.strftime("%Y-%m-%d")

    if verbose:
        print(f"Screening {len(SP500)} symbols  |  lookback {start} to {end}")
        print(f"Filters: ATR>=${min_atr:.2f}  avgVol>={min_volume:,}  price ${min_price}-${max_price}  max {max_per_sector}/sector")

    all_data: dict[str, pd.DataFrame] = {}
    batches = [SP500[i:i+BATCH_SIZE] for i in range(0, len(SP500), BATCH_SIZE)]
    skipped_data = []

    for i, batch in enumerate(batches):
        if verbose:
            print(f"  Fetching batch {i+1}/{len(batches)} ({len(batch)} symbols)...", end="\r")
        try:
            batch_data = _fetch_daily_bars_batch(batch, start, end, client)
            all_data.update(batch_data)
        except Exception as e:
            print(f"\n  [warn] batch {i+1} failed: {e}")
        if i < len(batches) - 1:
            time.sleep(BATCH_DELAY_SEC)

    if verbose:
        print(f"\n  Got data for {len(all_data)} / {len(SP500)} symbols")

    candidates = []
    for sym, df in all_data.items():
        if len(df) < 10:
            continue

        last_close = float(df["Close"].iloc[-1])
        avg_vol    = float(df["Volume"].mean())

        # Price range filter
        if last_close < min_price or last_close > max_price:
            continue

        # Data sanity check
        sane, reason = _price_is_sane(df)
        if not sane:
            skipped_data.append((sym, reason))
            continue

        atr_val = _atr(df)
        rel_vol = _relative_volume(df)

        if avg_vol < min_volume:
            continue
        if atr_val < min_atr:
            continue

        score = atr_val * math.log10(max(avg_vol, 1)) * max(rel_vol, 0.5)

        candidates.append({
            "symbol":     sym,
            "sector":     SYMBOL_SECTOR.get(sym, "Unknown"),
            "atr":        round(atr_val, 3),
            "avg_volume": int(avg_vol),
            "rel_volume": round(rel_vol, 2),
            "last_close": round(last_close, 2),
            "score":      round(score, 3),
        })

    if verbose and skipped_data:
        print(f"\n  Skipped {len(skipped_data)} symbol(s) with inconsistent price data:")
        for sym, reason in skipped_data[:10]:
            print(f"    {sym}: {reason}")

    # Sort all candidates by score descending
    candidates.sort(key=lambda x: x["score"], reverse=True)

    # Apply sector diversity cap: pick top_n respecting max_per_sector
    sector_counts: dict[str, int] = {}
    diversified = []
    for c in candidates:
        sec = c["sector"]
        if sector_counts.get(sec, 0) < max_per_sector:
            diversified.append(c)
            sector_counts[sec] = sector_counts.get(sec, 0) + 1
        if len(diversified) == top_n:
            break

    return diversified


def print_results(results: list[dict]):
    if not results:
        print("No symbols passed the screener filters.")
        return
    header = f"{'#':>3}  {'Symbol':<8}  {'Sector':<26}  {'ATR':>6}  {'AvgVol':>10}  {'RelVol':>7}  {'Close':>8}  {'Score':>7}"
    div = "=" * len(header)
    print(f"\n{div}")
    print("  SCREENER RESULTS")
    print(div)
    print(header)
    print("-" * len(header))
    for i, r in enumerate(results, 1):
        print(
            f"  {i:>1}.  {r['symbol']:<8}  {r['sector']:<26}  ${r['atr']:>5.2f}  "
            f"{r['avg_volume']:>10,}  {r['rel_volume']:>6.2f}x  "
            f"${r['last_close']:>7.2f}  {r['score']:>7.2f}"
        )
    print(div)
    sectors_used = sorted(set(r["sector"] for r in results))
    print(f"  Sectors: {', '.join(sectors_used)}")


def save_to_watchlist(symbols: list[str]):
    watchlist_path = ROOT / "watchlist.json"
    with open(watchlist_path, "w") as f:
        json.dump(symbols, f, indent=2)
    print(f"\nWatchlist updated: {watchlist_path}")
    print(f"Symbols: {', '.join(symbols)}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Morning symbol screener for DayTradeBot")
    parser.add_argument("--dry-run",        action="store_true", help="Print results without updating watchlist")
    parser.add_argument("--top",            type=int,   default=DEFAULT_TOP_N,          metavar="N",   help=f"Symbols to output (default: {DEFAULT_TOP_N})")
    parser.add_argument("--max-per-sector", type=int,   default=DEFAULT_MAX_PER_SECTOR, metavar="N",   help=f"Sector cap (default: {DEFAULT_MAX_PER_SECTOR})")
    parser.add_argument("--min-atr",        type=float, default=DEFAULT_MIN_ATR,        metavar="ATR", help=f"Min ATR in dollars (default: {DEFAULT_MIN_ATR})")
    parser.add_argument("--min-vol",        type=int,   default=DEFAULT_MIN_VOLUME,     metavar="VOL", help=f"Min avg daily volume (default: {DEFAULT_MIN_VOLUME:,})")
    parser.add_argument("--min-price",      type=float, default=DEFAULT_MIN_PRICE,      metavar="PX",  help=f"Min price (default: {DEFAULT_MIN_PRICE})")
    parser.add_argument("--max-price",      type=float, default=DEFAULT_MAX_PRICE,      metavar="PX",  help=f"Max price (default: {DEFAULT_MAX_PRICE})")
    args = parser.parse_args()

    try:
        results = screen(
            top_n=args.top,
            max_per_sector=args.max_per_sector,
            min_atr=args.min_atr,
            min_volume=args.min_vol,
            min_price=args.min_price,
            max_price=args.max_price,
        )
    except EnvironmentError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print_results(results)

    if not results:
        sys.exit(0)

    if args.dry_run:
        print("\n[dry-run] Watchlist not updated.")
    else:
        symbols = [r["symbol"] for r in results]
        save_to_watchlist(symbols)
        print("\nRun the live bot next:  python main.py")


if __name__ == "__main__":
    main()
