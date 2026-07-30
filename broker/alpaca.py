import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest, LimitOrderRequest, StopLossRequest, TakeProfitRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest
from alpaca.data.enums import DataFeed
from engine.risk import TradeParams
from strategies.base import Direction


class AlpacaBroker:
    """
    Alpaca paper trading broker.
    Set ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables,
    or pass them directly. paper=True uses the paper trading endpoint.
    """

    def __init__(self, api_key: str = None, secret_key: str = None, paper: bool = True):
        self.api_key = api_key or os.environ["ALPACA_API_KEY"]
        self.secret_key = secret_key or os.environ["ALPACA_SECRET_KEY"]
        self.client = TradingClient(self.api_key, self.secret_key, paper=paper)
        self._data: StockHistoricalDataClient | None = None  # lazy, for bracket anchoring

    def _latest_price(self, symbol: str) -> float | None:
        """Last traded price. Used to anchor bracket legs; None if unavailable."""
        try:
            if self._data is None:
                self._data = StockHistoricalDataClient(self.api_key, self.secret_key)
            req = StockLatestTradeRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX)
            return float(self._data.get_stock_latest_trade(req)[symbol].price)
        except Exception:
            return None

    def get_account(self) -> dict:
        acct = self.client.get_account()
        return {
            "equity": float(acct.equity),
            "cash": float(acct.cash),
            "buying_power": float(acct.buying_power),
        }

    def submit_order(self, params: TradeParams, bracket: bool = True) -> dict:
        """
        Submit the entry. With bracket=True the ATR-derived stop-loss and take-profit
        are attached as OCO exit legs, so the position actually exits on stop/target
        instead of only at the end-of-day flatten.
        """
        side = OrderSide.BUY if params.direction == Direction.BUY else OrderSide.SELL
        stop_price = limit_price = None

        if not bracket:
            request = MarketOrderRequest(
                symbol=params.symbol,
                qty=params.shares,
                side=side,
                time_in_force=TimeInForce.DAY,
            )
        else:
            # risk.py derived the legs from the last 5-min close. Alpaca validates the
            # legs against the live entry price, and our stops are tight enough (~0.2%)
            # that a few seconds of drift would get the order rejected — so re-anchor to
            # the current price, preserving the ATR-derived distances.
            base = self._latest_price(params.symbol) or params.entry
            stop_dist = max(abs(params.entry - params.stop_loss), 0.01)
            tp_dist   = max(abs(params.take_profit - params.entry), 0.02)

            if side == OrderSide.BUY:
                stop_price, limit_price = round(base - stop_dist, 2), round(base + tp_dist, 2)
            else:
                stop_price, limit_price = round(base + stop_dist, 2), round(base - tp_dist, 2)

            if stop_price <= 0 or limit_price <= 0:
                raise ValueError(f"invalid bracket legs for {params.symbol}: SL={stop_price} TP={limit_price}")

            request = MarketOrderRequest(
                symbol=params.symbol,
                qty=params.shares,
                side=side,
                time_in_force=TimeInForce.DAY,
                order_class=OrderClass.BRACKET,
                stop_loss=StopLossRequest(stop_price=stop_price),
                take_profit=TakeProfitRequest(limit_price=limit_price),
            )

        order = self.client.submit_order(request)
        legs = f" | SL=${stop_price} TP=${limit_price}" if bracket else ""
        print(f"  Order submitted: {order.id} | {side.value} {params.shares}x {params.symbol}{legs}")
        return {"order_id": str(order.id), "status": str(order.status)}

    def get_positions(self) -> list[dict]:
        positions = self.client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "side": p.side,
                "avg_entry": float(p.avg_entry_price),
                "unrealized_pl": float(p.unrealized_pl),
            }
            for p in positions
        ]

    def close_position(self, symbol: str):
        self.client.close_position(symbol)
        print(f"  Closed position: {symbol}")

    def close_all_positions(self):
        self.client.close_all_positions(cancel_orders=True)
        print("  All positions closed.")
