import pandas as pd
from .base import Strategy, Signal, Direction


class RSIFilter(Strategy):
    """
    RSI acts as a gate, not a primary signal.
    Returns BUY only when oversold, SELL only when overbought, HOLD otherwise.
    Used by the aggregator to veto conflicting signals.
    """

    def __init__(self, period: int = 14, oversold: float = 30.0, overbought: float = 70.0):
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    @property
    def name(self) -> str:
        return f"RSI({self.period})"

    def analyze(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.period + 1:
            return Signal(Direction.HOLD, 0.0, "insufficient data for RSI")

        close = df["Close"]
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(self.period).mean()
        loss = (-delta.clip(upper=0)).rolling(self.period).mean()

        rs = gain / loss.replace(0, float("inf"))
        rsi = 100 - (100 / (1 + rs))
        current_rsi = float(rsi.iloc[-1])

        if current_rsi < self.oversold:
            confidence = round((self.oversold - current_rsi) / self.oversold, 2)
            return Signal(Direction.BUY, confidence, f"RSI oversold ({current_rsi:.1f})")

        if current_rsi > self.overbought:
            confidence = round((current_rsi - self.overbought) / (100 - self.overbought), 2)
            return Signal(Direction.SELL, confidence, f"RSI overbought ({current_rsi:.1f})")

        return Signal(Direction.HOLD, 0.5, f"RSI neutral ({current_rsi:.1f})")

    def is_overbought(self, df: pd.DataFrame) -> bool:
        return self.analyze(df).direction == Direction.SELL

    def is_oversold(self, df: pd.DataFrame) -> bool:
        return self.analyze(df).direction == Direction.BUY
