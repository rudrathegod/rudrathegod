"""Mean reversion strategy (SPY, QQQ) on 15-minute candles.

Logic:
- Compute a `lookback`-period SMA and standard deviation of close.
- If price is more than `entry_std` std devs BELOW the mean -> go long (expect revert up).
- If price is more than `entry_std` std devs ABOVE the mean -> go short (expect revert down).
- Exit when price returns to (crosses back to) the moving average.

Stop distance is 1 ATR; the risk manager converts that into a 1%-equity position size.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from config import ATR_PERIOD

from ..indicators import atr, rolling_std, sma
from ..signals import Action, Position, Signal


def generate_signal(
    df: pd.DataFrame, params: dict, position: Optional[Position]
) -> Signal:
    lookback = int(params.get("lookback", 20))
    entry_std = float(params.get("entry_std", 1.5))
    stop_mult = float(params.get("stop_atr_mult", 1.0))
    trend_ma_period = int(params.get("trend_ma", 0))  # 0 disables the trend filter
    symbol = params["symbol"]

    need = max(lookback, ATR_PERIOD, trend_ma_period) + 1
    if len(df) < need:
        return Signal(symbol, Action.HOLD, df["close"].iloc[-1], 0.0, 0.0, "insufficient data")

    close = df["close"]
    mean = sma(close, lookback)
    std = rolling_std(close, lookback)
    cur_atr = atr(df, ATR_PERIOD)

    price = float(close.iloc[-1])
    m = float(mean.iloc[-1])
    s = float(std.iloc[-1])
    a = float(cur_atr.iloc[-1])

    if pd.isna(m) or pd.isna(s) or s == 0 or pd.isna(a) or a == 0:
        return Signal(symbol, Action.HOLD, price, 0.0, 0.0, "indicators not ready")

    z = (price - m) / s
    stop_distance = stop_mult * a

    # Exit logic (when holding a position).
    if position is not None:
        lock_mult = float(params.get("profit_lock_atr_mult", 0.0))
        # Profit-lock: if we're green and price has rolled over (pulled back
        # lock_mult ATRs from its best level since entry), bank the gain now
        # instead of waiting for full reversion to the mean.
        if lock_mult > 0 and a > 0:
            if position.side == "long" and price > position.entry_price:
                if (position.high_water - price) >= lock_mult * a:
                    return Signal(symbol, Action.EXIT, price, a, stop_distance, "profit-lock: long rolled over")
            if position.side == "short" and price < position.entry_price:
                if (price - position.high_water) >= lock_mult * a:
                    return Signal(symbol, Action.EXIT, price, a, stop_distance, "profit-lock: short rolled over")
        # Full target: close when price has reverted back through the mean.
        if position.side == "long" and price >= m:
            return Signal(symbol, Action.EXIT, price, a, stop_distance, "reverted to mean (long exit)")
        if position.side == "short" and price <= m:
            return Signal(symbol, Action.EXIT, price, a, stop_distance, "reverted to mean (short exit)")
        return Signal(symbol, Action.HOLD, price, a, stop_distance, f"holding, z={z:.2f}")

    # Trend-regime filter: only fade in the direction of the longer trend, i.e.
    # buy dips when above the trend MA, short rips when below it. This is the key
    # fix for mean reversion getting run over in persistent trends.
    trend_up = trend_dn = True
    if trend_ma_period > 0:
        tma = float(sma(close, trend_ma_period).iloc[-1])
        if pd.isna(tma):
            return Signal(symbol, Action.HOLD, price, a, stop_distance, "trend MA not ready")
        trend_up = price >= tma      # allow longs only in/above uptrend
        trend_dn = price <= tma      # allow shorts only in/below downtrend

    # Entry logic (only when flat).
    if z <= -entry_std and trend_up:
        return Signal(symbol, Action.LONG, price, a, stop_distance, f"dip z={z:.2f} in uptrend")
    if z >= entry_std and trend_dn:
        return Signal(symbol, Action.SHORT, price, a, stop_distance, f"rip z={z:.2f} in downtrend")

    return Signal(symbol, Action.HOLD, price, a, stop_distance, f"in band / filtered, z={z:.2f}")
