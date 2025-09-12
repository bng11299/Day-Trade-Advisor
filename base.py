from abc import ABC, abstractmethod

class Strategy(ABC):
    """Base class for all trading strategies."""

    @abstractmethod
    def analyze(self, df):
        """Takes a DataFrame and returns a trading signal (BUY/SELL/HOLD)."""
        pass

    @abstractmethod
    def name(self):
        """Returns the strategy name."""
        pass
