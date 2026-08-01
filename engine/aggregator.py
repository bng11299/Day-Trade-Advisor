import pandas as pd
from dataclasses import dataclass
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
    RSI acts as a hard veto — blocks trades when price is already extended.
    UVXY acts as a soft regime filter — raises the confidence threshold when
    market fear is elevated, but never fully blocks a high-conviction signal.
    Final signal requires confidence > effective threshold to act.
    """

    WEIGHTS = {
        "ORB": 0.40,
        "VWAP": 0.35,
        "EMA": 0.25,
    }
    CONFIDENCE_THRESHOLD = 0.65

    def __init__(self, long_only: bool = False):
        self.long_only = long_only
        self.orb = ORBStrategy()
        self.vwap = VWAPStrategy()
        self.ema = EMACrossoverStrategy()
        self.rsi = RSIFilter()

    @staticmethod
    def _uvxy_threshold_bump(uvxy_pct: float) -> float:
        """
        Returns how much to raise the confidence threshold based on UVXY's
        intraday % change from previous close. Only activates when UVXY is up.

        Tiers:
          ≤ +2%  → no change   (normal daily noise)
          +2–5%  → +0.03       (mild caution)
          +5–10% → +0.06       (elevated fear)
          > +10% → +0.10       (fear spike — max threshold 0.75)
        """
        if uvxy_pct <= 2.0:
            return 0.0
        elif uvxy_pct <= 5.0:
            return 0.03
        elif uvxy_pct <= 10.0:
            return 0.06
        else:
            return 0.10

    def analyze(self, df: pd.DataFrame, uvxy_pct: float = 0.0) -> AggregatedSignal:
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

        # UVXY regime filter: raises threshold during fear, never fully blocks.
        # A signal that clears the bumped threshold still trades.
        bump = self._uvxy_threshold_bump(uvxy_pct)
        effective_threshold = self.CONFIDENCE_THRESHOLD + bump

        if not agg.vetoed and agg.confidence < effective_threshold:
            agg.direction = Direction.HOLD
            # Only label UVXY as the deciding factor when it was actually the
            # difference — i.e. confidence cleared the base threshold but not the bump.
            if bump > 0 and agg.confidence >= self.CONFIDENCE_THRESHOLD:
                agg.vetoed = True
                agg.veto_reason = f"UVXY regime (+{uvxy_pct:.1f}%, threshold {effective_threshold:.2f})"

        return agg
