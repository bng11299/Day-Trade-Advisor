import yfinance as yf
import pandas_ta as ta
from strategies.base import Strategy

class MovingAverageStrategy(Strategy):
    def analyze(self, ticker):
        print(f"\n📊 Analyzing {ticker} with SMA Strategy...")

        df = yf.download(ticker, period="6mo", auto_adjust=True, progress=False)
        if df.empty: 
            return

        df.ta.sma(length=20, append=True)
        df.ta.sma(length=50, append=True)

        if df['Close'].iloc[-1] > df['SMA_20'].iloc[-1] > df['SMA_50'].iloc[-1]:
            print(f"✅ {ticker} is in an Uptrend")
        elif df['Close'].iloc[-1] < df['SMA_20'].iloc[-1] < df['SMA_50'].iloc[-1]:
            print(f"⚠️ {ticker} is in a Downtrend")
        else:
            print(f"➖ {ticker} is moving Sideways")

