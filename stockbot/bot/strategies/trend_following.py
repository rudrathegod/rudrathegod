"""Trend following strategy (GLD, USO) on 4-hour candles.

Logic:
- Compute fast (50) and slow (200) EMAs.
- Golden cross (fast crosses ABOVE slow) -> go long.
- Death cross (fast crosses BELOW slow) -> exit / go short.
- Trailing stop of `trail_atr_mult` * ATR (managed by risk manager / broker).
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from config import ATR_PERIOD

from ..indicators import atr, ema
from ..signals import Action, Position, Signal


def generate_signal(
    df: pd.DataFrame, params: dict, position: Optional[Position]
) -> Signal:
    fast_p = int(params.get("fast_ema", 50))
    slow_p = int(params.get("slow_ema", 200))
    trail_mult = float(params.get("trail_atr_mult", 3.0))
    symbol = params["symbol"]

    if len(df) < slow_p + 1:
        return Signal(symbol, Action.HOLD, df["close"].iloc[-1], 0.0, 0.0, "insufficient data")

    close = df["close"]
    fast = ema(close, fast_p)
    slow = ema(close, slow_p)
    cur_atr = atr(df, ATR_PERIOD)

    price = float(close.iloc[-1])
    a = float(cur_atr.iloc[-1])

    fast_now, fast_prev = float(fast.iloc[-1]), float(fast.iloc[-2])
    slow_now, slow_prev = float(slow.iloc[-1]), float(slow.iloc[-2])

    if any(pd.isna(x) for x in (fast_now, fast_prev, slow_now, slow_prev, a)) or a == 0:
        return Signal(symbol, Action.HOLD, price, 0.0, 0.0, "indicators not ready")

    stop_distance = trail_mult * a
    crossed_up = fast_prev <= slow_prev and fast_now > slow_now
    crossed_down = fast_prev >= slow_prev and fast_now < slow_now

    if position is not None:
        if position.side == "long" and crossed_down:
            return Signal(symbol, Action.EXIT, price, a, stop_distance, "death cross (long exit)")
        if position.side == "short" and crossed_up:
            return Signal(symbol, Action.EXIT, price, a, stop_distance, "golden cross (short exit)")
        return Signal(symbol, Action.HOLD, price, a, stop_distance, "riding trend")

    if crossed_up:
        return Signal(symbol, Action.LONG, price, a, stop_distance, "golden cross 50>200")
    if crossed_down:
        return Signal(symbol, Action.SHORT, price, a, stop_distance, "death cross 50<200")

    return Signal(symbol, Action.HOLD, price, a, stop_distance, "no crossover")
