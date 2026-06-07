from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import pandas as pd


class Direction(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Signal:
    direction: Direction
    confidence: float  # 0.0 – 1.0
    reason: str

    def __repr__(self):
        return f"Signal({self.direction.value}, conf={self.confidence:.2f}, '{self.reason}')"


class Strategy(ABC):
    """All strategies receive a 1-minute intraday DataFrame and return a Signal."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def analyze(self, df: pd.DataFrame) -> Signal:
        """
        df: yfinance 1m intraday data for the current session.
            Columns: Open, High, Low, Close, Volume (MultiIndex ticker stripped by caller).
        Returns a Signal.
        """
        pass
