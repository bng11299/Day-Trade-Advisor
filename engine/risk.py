import pandas as pd
from dataclasses import dataclass
from strategies.base import Direction


@dataclass
class TradeParams:
    symbol: str
    direction: Direction
    entry: float
    stop_loss: float
    take_profit: float
    shares: int
    risk_amount: float  # dollars at risk

    def __repr__(self):
        return (
            f"{self.direction.value} {self.shares}x {self.symbol} @ ${self.entry:.2f} | "
            f"SL=${self.stop_loss:.2f} TP=${self.take_profit:.2f} | "
            f"Risk=${self.risk_amount:.2f}"
        )


class RiskManager:
    """
    ATR-based stop loss and take profit.
    Position sized so that 1 stop-out = risk_pct of account.
    """

    def __init__(
        self,
        account_value: float,
        risk_pct: float = 0.01,   # risk 1% of account per trade
        atr_period: int = 14,
        atr_stop_multiplier: float = 1.5,
        reward_ratio: float = 2.0,
    ):
        self.account_value = account_value
        self.risk_pct = risk_pct
        self.atr_period = atr_period
        self.atr_stop_multiplier = atr_stop_multiplier
        self.reward_ratio = reward_ratio

    def _atr(self, df: pd.DataFrame) -> float:
        high = df["High"]
        low = df["Low"]
        prev_close = df["Close"].shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        return float(tr.rolling(self.atr_period).mean().iloc[-1])

    def calculate(self, symbol: str, df: pd.DataFrame, direction: Direction) -> TradeParams | None:
        if len(df) < self.atr_period + 1:
            return None

        atr = self._atr(df)
        entry = float(df["Close"].iloc[-1])
        stop_distance = atr * self.atr_stop_multiplier

        if direction == Direction.BUY:
            stop_loss = entry - stop_distance
            take_profit = entry + stop_distance * self.reward_ratio
        elif direction == Direction.SELL:
            stop_loss = entry + stop_distance
            take_profit = entry - stop_distance * self.reward_ratio
        else:
            return None

        risk_amount = self.account_value * self.risk_pct
        shares = max(1, int(risk_amount / stop_distance))

        return TradeParams(
            symbol=symbol,
            direction=direction,
            entry=entry,
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            shares=shares,
            risk_amount=round(shares * stop_distance, 2),
        )
