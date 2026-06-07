import pandas as pd
from .base import Strategy, Signal, Direction


class VWAPStrategy(Strategy):
    """
    VWAP-based signal:
    - Price crossing VWAP in the direction of trend → momentum trade
    - Price far from VWAP (>2 std bands) → mean reversion trade
    """

    def __init__(self, std_bands: float = 2.0):
        self.std_bands = std_bands

    @property
    def name(self) -> str:
        return "VWAP"

    def _compute_vwap(self, df: pd.DataFrame) -> pd.Series:
        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        cumulative_tpv = (typical * df["Volume"]).cumsum()
        cumulative_vol = df["Volume"].cumsum()
        return cumulative_tpv / cumulative_vol

    def analyze(self, df: pd.DataFrame) -> Signal:
        if len(df) < 20:
            return Signal(Direction.HOLD, 0.0, "insufficient data for VWAP")

        vwap = self._compute_vwap(df)
        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        std = (typical - vwap).std()

        current_vwap = float(vwap.iloc[-1])
        current_close = float(df["Close"].iloc[-1])
        prev_close = float(df["Close"].iloc[-2])
        prev_vwap = float(vwap.iloc[-2])

        deviation = current_close - current_vwap
        bands = std * self.std_bands

        # Mean reversion: price stretched beyond 2-std band
        if deviation > bands:
            confidence = min(0.5 + 0.5 * ((deviation - bands) / bands), 0.95)
            return Signal(Direction.SELL, round(confidence, 2), f"price {deviation:.2f} above VWAP+{self.std_bands}σ")

        if deviation < -bands:
            confidence = min(0.5 + 0.5 * ((-deviation - bands) / bands), 0.95)
            return Signal(Direction.BUY, round(confidence, 2), f"price {-deviation:.2f} below VWAP-{self.std_bands}σ")

        # Momentum: fresh VWAP crossover
        crossed_up = prev_close < prev_vwap and current_close > current_vwap
        crossed_down = prev_close > prev_vwap and current_close < current_vwap

        if crossed_up:
            return Signal(Direction.BUY, 0.65, "bullish VWAP crossover")

        if crossed_down:
            return Signal(Direction.SELL, 0.65, "bearish VWAP crossover")

        # Price above/below VWAP with momentum
        if current_close > current_vwap:
            return Signal(Direction.BUY, 0.45, f"price above VWAP ({current_vwap:.2f})")

        return Signal(Direction.SELL, 0.45, f"price below VWAP ({current_vwap:.2f})")
