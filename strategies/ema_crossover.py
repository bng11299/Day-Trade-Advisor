import pandas as pd
from .base import Strategy, Signal, Direction


class EMACrossoverStrategy(Strategy):
    """
    EMA 9/21 crossover with volume confirmation.
    Golden cross (9 over 21) + volume spike → BUY.
    Death cross (9 under 21) + volume spike → SELL.
    """

    def __init__(self, fast: int = 9, slow: int = 21, volume_multiplier: float = 1.3):
        self.fast = fast
        self.slow = slow
        self.volume_multiplier = volume_multiplier

    @property
    def name(self) -> str:
        return f"EMA({self.fast}/{self.slow})"

    def analyze(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.slow + 2:
            return Signal(Direction.HOLD, 0.0, "insufficient data for EMA")

        close = df["Close"]
        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()

        cur_fast = float(ema_fast.iloc[-1])
        cur_slow = float(ema_slow.iloc[-1])
        prev_fast = float(ema_fast.iloc[-2])
        prev_slow = float(ema_slow.iloc[-2])

        avg_volume = float(df["Volume"].mean())
        cur_volume = float(df["Volume"].iloc[-1])
        volume_ok = cur_volume >= avg_volume * self.volume_multiplier

        just_crossed_up = prev_fast <= prev_slow and cur_fast > cur_slow
        just_crossed_down = prev_fast >= prev_slow and cur_fast < cur_slow

        spread = abs(cur_fast - cur_slow) / cur_slow  # relative spread

        if just_crossed_up:
            confidence = 0.7 + (0.2 if volume_ok else 0.0)
            return Signal(Direction.BUY, round(confidence, 2), f"golden cross EMA{self.fast}>{self.slow}")

        if just_crossed_down:
            confidence = 0.7 + (0.2 if volume_ok else 0.0)
            return Signal(Direction.SELL, round(confidence, 2), f"death cross EMA{self.fast}<{self.slow}")

        # Trend continuation (already crossed, price aligned)
        if cur_fast > cur_slow:
            confidence = min(0.4 + spread * 100, 0.65)
            return Signal(Direction.BUY, round(confidence, 2), f"uptrend EMA spread={spread:.4f}")

        confidence = min(0.4 + spread * 100, 0.65)
        return Signal(Direction.SELL, round(confidence, 2), f"downtrend EMA spread={spread:.4f}")
