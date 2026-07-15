"""Momentum breakout strategy (BTC/USD) on 1-hour candles.

Logic:
- Track the `lookback`-period high and low (excluding the current bar).
- Break above the prior high WITH volume >= vol_mult * avg volume -> go long.
- Break below the prior low WITH the same volume confirmation -> go short.
- Trailing stop of `trail_atr_mult` * ATR (managed by the risk manager / broker).

Stop distance for initial sizing is trail_atr_mult * ATR.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from config import ATR_PERIOD

from ..indicators import atr, ema, rolling_high, rolling_low, sma
from ..signals import Action, Position, Signal


def generate_signal(
    df: pd.DataFrame, params: dict, position: Optional[Position]
) -> Signal:
    lookback = int(params.get("lookback", 20))
    vol_mult = float(params.get("vol_mult", 1.5))
    trail_mult = float(params.get("trail_atr_mult", 2.0))
    trend_ema_period = int(params.get("trend_ema", 0))  # 0 disables the filter
    symbol = params["symbol"]

    need = max(lookback, ATR_PERIOD, trend_ema_period) + 2
    if len(df) < need:
        return Signal(symbol, Action.HOLD, df["close"].iloc[-1], 0.0, 0.0, "insufficient data")

    close = df["close"]
    # Prior high/low: shift by 1 so the current bar's own extreme doesn't count.
    prior_high = rolling_high(df["high"], lookback).shift(1)
    prior_low = rolling_low(df["low"], lookback).shift(1)
    avg_vol = sma(df["volume"], lookback).shift(1)
    cur_atr = atr(df, ATR_PERIOD)

    price = float(close.iloc[-1])
    ph = float(prior_high.iloc[-1])
    pl = float(prior_low.iloc[-1])
    av = float(avg_vol.iloc[-1])
    vol = float(df["volume"].iloc[-1])
    a = float(cur_atr.iloc[-1])

    if any(pd.isna(x) for x in (ph, pl, av, a)) or a == 0:
        return Signal(symbol, Action.HOLD, price, 0.0, 0.0, "indicators not ready")

    stop_distance = trail_mult * a
    vol_ok = av > 0 and vol >= vol_mult * av

    # Exit / reversal logic when in a position.
    if position is not None:
        if position.side == "long" and price < pl:
            return Signal(symbol, Action.EXIT, price, a, stop_distance, "broke below 20-low (long exit)")
        if position.side == "short" and price > ph:
            return Signal(symbol, Action.EXIT, price, a, stop_distance, "broke above 20-high (short exit)")
        return Signal(symbol, Action.HOLD, price, a, stop_distance, "in trend, trailing stop active")

    # Trend-alignment filter: only take breakouts in the direction of the EMA
    # trend, which cuts the false counter-trend breakouts that bled the account.
    trend_up = trend_dn = True
    if trend_ema_period > 0:
        te = float(ema(close, trend_ema_period).iloc[-1])
        if pd.isna(te):
            return Signal(symbol, Action.HOLD, price, a, stop_distance, "trend EMA not ready")
        trend_up = price >= te
        trend_dn = price <= te

    # Entry logic when flat.
    if price > ph and vol_ok and trend_up:
        return Signal(symbol, Action.LONG, price, a, stop_distance, f"breakout > {ph:.2f}, vol {vol:.0f}")
    if price < pl and vol_ok and trend_dn:
        return Signal(symbol, Action.SHORT, price, a, stop_distance, f"breakdown < {pl:.2f}, vol {vol:.0f}")

    return Signal(symbol, Action.HOLD, price, a, stop_distance, "no aligned breakout / volume")
