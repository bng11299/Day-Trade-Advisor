import pandas_ta as ta
from .base import Strategy

class MovingAverageStrategy(Strategy):
    def __init__(self, short=20, long=50):
        self.short = short
        self.long = long

    def name(self):
        return f"SMA Crossover ({self.short}/{self.long})"

    def analyze(self, df):
        df.ta.sma(length=self.short, append=True)
        df.ta.sma(length=self.long, append=True)

        short_sma = df[f"SMA_{self.short}"].iloc[-1]
        long_sma = df[f"SMA_{self.long}"].iloc[-1]
        price = df["Close"].iloc[-1]

        if short_sma > long_sma and price > short_sma:
            return "BUY"
        elif short_sma < long_sma and price < short_sma:
            return "SELL"
        else:
            return "HOLD"
