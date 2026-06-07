"""
Alpaca data layer — historical bars for backtest, streaming bars for live trading.
Replaces yfinance entirely so both paths use the same data source.
"""

import os
import asyncio
import threading
from datetime import datetime, timezone
from collections import deque
from typing import Callable

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.live import StockDataStream


def _timeframe(interval: str) -> TimeFrame:
    mapping = {
        "1m":  TimeFrame(1,  TimeFrameUnit.Minute),
        "5m":  TimeFrame(5,  TimeFrameUnit.Minute),
        "15m": TimeFrame(15, TimeFrameUnit.Minute),
        "1h":  TimeFrame(1,  TimeFrameUnit.Hour),
        "1d":  TimeFrame(1,  TimeFrameUnit.Day),
    }
    if interval not in mapping:
        raise ValueError(f"Unsupported interval '{interval}'. Choose from: {list(mapping)}")
    return mapping[interval]


def fetch_bars(
    symbol: str,
    start: str,
    end: str,
    interval: str = "5m",
    api_key: str = None,
    secret_key: str = None,
) -> pd.DataFrame:
    """
    Fetch historical bars from Alpaca for backtesting.
    Returns a DataFrame with columns: Open, High, Low, Close, Volume.
    Alpaca free tier provides years of historical data.
    """
    api_key = api_key or os.environ["ALPACA_API_KEY"]
    secret_key = secret_key or os.environ["ALPACA_SECRET_KEY"]
    client = StockHistoricalDataClient(api_key, secret_key)

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=_timeframe(interval),
        start=datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc),
        end=datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc),
    )
    bars = client.get_stock_bars(request)
    df = bars.df

    # Alpaca returns a MultiIndex (symbol, timestamp) — flatten to timestamp index
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")

    df.index = pd.to_datetime(df.index, utc=True)
    df.columns = [c.capitalize() for c in df.columns]

    # Keep only OHLCV
    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    return df[keep].dropna()


class LiveBarStream:
    """
    Real-time 1-minute bar stream from Alpaca WebSocket.
    Maintains a rolling DataFrame of the last `buffer` bars per symbol.
    Call `subscribe(symbols, callback)` then `start()`.

    callback(symbol: str, df: pd.DataFrame) is called on each new bar.
    df contains the rolling window so strategies can analyze it immediately.
    """

    def __init__(
        self,
        api_key: str = None,
        secret_key: str = None,
        buffer: int = 120,
    ):
        self.api_key = api_key or os.environ["ALPACA_API_KEY"]
        self.secret_key = secret_key or os.environ["ALPACA_SECRET_KEY"]
        self.buffer = buffer
        self._buffers: dict[str, deque] = {}
        self._callback: Callable | None = None
        self._stream: StockDataStream | None = None
        self._thread: threading.Thread | None = None

    def subscribe(self, symbols: list[str], callback: Callable):
        for sym in symbols:
            if sym not in self._buffers:
                self._buffers[sym] = deque(maxlen=self.buffer)
        self._callback = callback

    def add_symbol(self, symbol: str):
        if symbol not in self._buffers:
            self._buffers[symbol] = deque(maxlen=self.buffer)
            if self._stream:
                asyncio.run_coroutine_threadsafe(
                    self._stream.subscribe_bars(self._on_bar, symbol),
                    self._loop,
                )

    def remove_symbol(self, symbol: str):
        self._buffers.pop(symbol, None)

    async def _on_bar(self, bar):
        sym = bar.symbol
        if sym not in self._buffers:
            return

        row = {
            "Open": bar.open,
            "High": bar.high,
            "Low": bar.low,
            "Close": bar.close,
            "Volume": bar.volume,
        }
        self._buffers[sym].append((bar.timestamp, row))

        if self._callback and len(self._buffers[sym]) >= 30:
            df = pd.DataFrame(
                [r for _, r in self._buffers[sym]],
                index=pd.DatetimeIndex([t for t, _ in self._buffers[sym]]),
            )
            try:
                self._callback(sym, df)
            except Exception as e:
                print(f"  [stream callback error] {sym}: {e}")

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stream = StockDataStream(self.api_key, self.secret_key)
        symbols = list(self._buffers.keys())
        if symbols:
            self._stream.subscribe_bars(self._on_bar, *symbols)
        self._loop.run_until_complete(self._stream.run())

    def start(self):
        """Start streaming in a background thread (non-blocking)."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[stream] Connected. Subscribed to: {list(self._buffers.keys())}")

    def stop(self):
        if self._stream:
            asyncio.run_coroutine_threadsafe(self._stream.stop_ws(), self._loop)
