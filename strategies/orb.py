import pandas as pd
from .base import Strategy, Signal, Direction


class ORBStrategy(Strategy):
    """
    Opening Range Breakout: first `orb_minutes` bars define the range.
    A close beyond that range with volume confirmation triggers a signal.
    """

    def __init__(self, orb_minutes: int = 15, volume_multiplier: float = 1.5):
        self.orb_minutes = orb_minutes
        self.volume_multiplier = volume_multiplier

    @property
    def name(self) -> str:
        return f"ORB({self.orb_minutes}m)"

    def analyze(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.orb_minutes + 1:
            return Signal(Direction.HOLD, 0.0, "insufficient data")

        opening_range = df.iloc[: self.orb_minutes]
        orb_high = opening_range["High"].max()
        orb_low = opening_range["Low"].min()

        # Use remaining bars (post-opening-range)
        rest = df.iloc[self.orb_minutes :]
        if rest.empty:
            return Signal(Direction.HOLD, 0.0, "still in opening range")

        avg_volume = df["Volume"].mean()
        current = rest.iloc[-1]
        current_close = float(current["Close"])
        current_volume = float(current["Volume"])

        volume_ok = current_volume >= avg_volume * self.volume_multiplier

        orb_range = orb_high - orb_low
        if orb_range == 0:
            return Signal(Direction.HOLD, 0.0, "zero ORB range")

        if current_close > orb_high:
            # Confidence scales with how far above the high and whether volume confirms
            breakout_strength = min((current_close - orb_high) / orb_range, 1.0)
            confidence = 0.5 + 0.3 * breakout_strength + (0.2 if volume_ok else 0.0)
            return Signal(Direction.BUY, round(confidence, 2), f"broke ORB high {orb_high:.2f}")

        if current_close < orb_low:
            breakout_strength = min((orb_low - current_close) / orb_range, 1.0)
            confidence = 0.5 + 0.3 * breakout_strength + (0.2 if volume_ok else 0.0)
            return Signal(Direction.SELL, round(confidence, 2), f"broke ORB low {orb_low:.2f}")

        return Signal(Direction.HOLD, 0.0, "inside opening range")
