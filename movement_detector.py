import yfinance as yf
import pandas as pd

def has_high_movement(ticker, lookback_days=5, threshold=0.03):
    """
    Returns True if the average daily % change over last `lookback_days`
    exceeds the threshold (e.g. 3%).
    """
    df = yf.download(ticker, period=f"{lookback_days+5}d", auto_adjust=True, progress=False)

    if df.empty or len(df) < lookback_days:
        return False

    df['pct_change'] = df['Close'].pct_change()
    recent_volatility = df['pct_change'].tail(lookback_days).abs().mean()

    return recent_volatility >= threshold
