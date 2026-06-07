import pandas as pd
from dataclasses import dataclass
from typing import Optional
from strategies.base import Signal, Direction
from strategies.orb import ORBStrategy
from strategies.vwap import VWAPStrategy
from strategies.ema_crossover import EMACrossoverStrategy
from strategies.rsi_filter import RSIFilter


@dataclass
class AggregatedSignal:
    direction: Direction
    confidence: float
    components: dict  # strategy name → Signal
    vetoed: bool = False
    veto_reason: str = ""

    def __repr__(self):
        comp = ", ".join(f"{k}={v.direction.value}({v.confidence:.2f})" for k, v in self.components.items())
        veto = f" [VETOED: {self.veto_reason}]" if self.vetoed else ""
        return f"[{self.direction.value} conf={self.confidence:.2f}] {comp}{veto}"


class SignalAggregator:
    """
    Weighted vote across ORB, VWAP, EMA.
    RSI acts as a veto gate — blocks trades when market is already extended.
    Final signal requires confidence > threshold to act.
    """

    WEIGHTS = {
        "ORB": 0.40,
        "VWAP": 0.35,
        "EMA": 0.25,
    }
    CONFIDENCE_THRESHOLD = 0.65  # raised from 0.55 — filters low-conviction noise

    def __init__(self, long_only: bool = False):
        self.long_only = long_only  # suppress SELL signals in bull-trend markets
        self.orb = ORBStrategy()
        self.vwap = VWAPStrategy()
        self.ema = EMACrossoverStrategy()
        self.rsi = RSIFilter()

    def analyze(self, df: pd.DataFrame) -> AggregatedSignal:
        signals = {
            "ORB": self.orb.analyze(df),
            "VWAP": self.vwap.analyze(df),
            "EMA": self.ema.analyze(df),
        }
        rsi_signal = self.rsi.analyze(df)

        # Weighted score: BUY=+1, SELL=-1, HOLD=0
        score = 0.0
        for key, sig in signals.items():
            weight = self.WEIGHTS[key]
            if sig.direction == Direction.BUY:
                score += weight * sig.confidence
            elif sig.direction == Direction.SELL:
                score -= weight * sig.confidence

        # Determine direction and raw confidence from score
        if score > 0:
            direction = Direction.BUY
            confidence = score
        elif score < 0:
            direction = Direction.SELL
            confidence = abs(score)
        else:
            direction = Direction.HOLD
            confidence = 0.0

        agg = AggregatedSignal(direction=direction, confidence=round(confidence, 3), components=signals)

        # long_only mode: suppress all SELL signals
        if self.long_only and direction == Direction.SELL:
            agg.vetoed = True
            agg.veto_reason = "long_only mode"
            agg.direction = Direction.HOLD

        # RSI veto: block BUY if overbought, block SELL if oversold
        if not agg.vetoed:
            if direction == Direction.BUY and rsi_signal.direction == Direction.SELL:
                agg.vetoed = True
                agg.veto_reason = rsi_signal.reason
                agg.direction = Direction.HOLD
            elif direction == Direction.SELL and rsi_signal.direction == Direction.BUY:
                agg.vetoed = True
                agg.veto_reason = rsi_signal.reason
                agg.direction = Direction.HOLD

        # Below threshold → hold
        if not agg.vetoed and agg.confidence < self.CONFIDENCE_THRESHOLD:
            agg.direction = Direction.HOLD

        return agg
