"""Historical + latest bar data via alpaca-py.

Returns tidy pandas DataFrames indexed by timestamp with columns:
    open, high, low, close, volume
Used by both the live loop and the backtester.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from alpaca.data.historical import (
    CryptoHistoricalDataClient,
    StockHistoricalDataClient,
)
from alpaca.data.enums import DataFeed
from alpaca.data.requests import CryptoBarsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from config import ALPACA_API_KEY, ALPACA_DATA_FEED, ALPACA_SECRET_KEY

from .http_utils import harden

_stock_client: StockHistoricalDataClient | None = None
_crypto_client: CryptoHistoricalDataClient | None = None


def _stock() -> StockHistoricalDataClient:
    global _stock_client
    if _stock_client is None:
        _stock_client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
        harden(_stock_client)
    return _stock_client


def _crypto() -> CryptoHistoricalDataClient:
    global _crypto_client
    if _crypto_client is None:
        # Crypto data is public; keys are optional but harmless.
        _crypto_client = CryptoHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
        harden(_crypto_client)
    return _crypto_client


def to_timeframe(tf: str) -> TimeFrame:
    mapping = {
        "1Min": TimeFrame(1, TimeFrameUnit.Minute),
        "5Min": TimeFrame(5, TimeFrameUnit.Minute),
        "15Min": TimeFrame(15, TimeFrameUnit.Minute),
        "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
        "4Hour": TimeFrame(4, TimeFrameUnit.Hour),
        "1Day": TimeFrame(1, TimeFrameUnit.Day),
    }
    if tf not in mapping:
        raise ValueError(f"Unsupported timeframe '{tf}'")
    return mapping[tf]


def _normalize(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Alpaca returns a multi-index (symbol, timestamp) DataFrame; flatten it."""
    if df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")
    df = df[["open", "high", "low", "close", "volume"]].copy()
    df.index = pd.to_datetime(df.index, utc=True)
    return df.sort_index()


def get_bars(
    symbol: str,
    asset_class: str,
    timeframe: str,
    start: datetime,
    end: datetime | None = None,
) -> pd.DataFrame:
    """Fetch historical bars for one symbol between start and end (UTC)."""
    end = end or datetime.now(timezone.utc)
    tf = to_timeframe(timeframe)

    if asset_class == "crypto":
        req = CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start, end=end)
        bars = _crypto().get_crypto_bars(req)
    else:
        feed = DataFeed(ALPACA_DATA_FEED) if ALPACA_DATA_FEED else None
        req = StockBarsRequest(
            symbol_or_symbols=symbol, timeframe=tf, start=start, end=end, feed=feed
        )
        bars = _stock().get_stock_bars(req)

    return _normalize(bars.df, symbol)
