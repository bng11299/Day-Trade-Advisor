import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
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

    def get_account(self) -> dict:
        acct = self.client.get_account()
        return {
            "equity": float(acct.equity),
            "cash": float(acct.cash),
            "buying_power": float(acct.buying_power),
        }

    def submit_order(self, params: TradeParams) -> dict:
        side = OrderSide.BUY if params.direction == Direction.BUY else OrderSide.SELL
        request = MarketOrderRequest(
            symbol=params.symbol,
            qty=params.shares,
            side=side,
            time_in_force=TimeInForce.DAY,
        )
        order = self.client.submit_order(request)
        print(f"  Order submitted: {order.id} | {side.value} {params.shares}x {params.symbol}")
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
