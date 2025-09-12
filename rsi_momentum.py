import pandas_ta as ta
from .base import Strategy

class RSIMomentumStrategy(Strategy):
    def __init__(self, period=14, oversold=30, overbought=70):
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def name(self):
        return f"RSI Momentum ({self.period})"

    def analyze(self, df):
        df.ta.rsi(length=self.period, append=True)
        rsi = df[f"RSI_{self.period}"].iloc[-1]

        if rsi < self.oversold:
            return "BUY"
        elif rsi > self.overbought:
            return "SELL"
        else:
            return "HOLD"
