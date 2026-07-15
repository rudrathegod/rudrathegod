"""Risk management: position sizing, stops, correlation filter, drawdown breaker.

This module is intentionally pure/stateless (aside from the peak-equity tracker)
so it behaves identically live and in backtests.
"""
from __future__ import annotations

import math
from typing import Optional

from config import (
    CORRELATION_FILTER,
    DRAWDOWN_STATE_FILE,
    MAX_PORTFOLIO_DRAWDOWN,
    MAX_POSITION_NOTIONAL_PCT,
    MIN_STOP_DISTANCE_PCT,
    RISK_PER_TRADE,
    RISK_ON_SHORT_SIZE_MULT,
    ROUND_UP_TO_ONE_SHARE_MAX_NOTIONAL_PCT,
)
from .signals import Action, Position, Signal
from .state_store import load_json, save_json


def position_size(equity: float, signal: Signal, allow_fractional: bool) -> float:
    """Size a position so that a move of `stop_distance` against us == RISK_PER_TRADE of equity.

    qty = (equity * risk%) / stop_distance_per_unit

    Two guards keep this sane on short timeframes where ATR is tiny:
    1. The stop distance is floored at MIN_STOP_DISTANCE_PCT of price.
    2. The resulting notional (qty * price) is capped at MAX_POSITION_NOTIONAL_PCT
       of equity, so a single order can never blow past buying power.

    Equities are rounded down to whole shares; crypto allows fractional units.
    """
    if signal.stop_distance <= 0 or equity <= 0 or signal.price <= 0:
        return 0.0
    # Guard 1: don't let a noise-level (tiny) stop distance explode the size.
    stop_distance = max(signal.stop_distance, signal.price * MIN_STOP_DISTANCE_PCT)
    risk_dollars = equity * RISK_PER_TRADE
    qty = risk_dollars / stop_distance
    # Guard 2: hard cap on position notional as a fraction of equity.
    max_qty_by_notional = (equity * MAX_POSITION_NOTIONAL_PCT) / signal.price
    qty = min(qty, max_qty_by_notional)
    if not allow_fractional:
        qty = float(int(qty))  # floor to whole shares
        # Guard 2 can floor a pricier stock straight to 0 shares (whole-share-only
        # orders, e.g. shorts, can't split a share). Rather than silently skip
        # the trade forever, take exactly 1 share if that alone still respects a
        # wider single-position ceiling.
        if qty == 0 and signal.price <= equity * ROUND_UP_TO_ONE_SHARE_MAX_NOTIONAL_PCT:
            qty = 1.0
    return max(qty, 0.0)


def cap_size_to_available_notional(
    qty: float,
    price: float,
    available_notional: float,
    allow_fractional: bool,
) -> float:
    """Reduce a proposed quantity to fit an aggregate/funds notional budget."""
    if qty <= 0 or price <= 0 or available_notional <= 0:
        return 0.0
    capped = min(qty, available_notional / price)
    if not allow_fractional:
        capped = float(math.floor(capped))
    return max(capped, 0.0)


def stop_price_for(signal: Signal) -> float:
    """Initial hard stop price, `stop_distance` away from entry in the adverse direction."""
    if signal.action == Action.LONG:
        return signal.price - signal.stop_distance
    if signal.action == Action.SHORT:
        return signal.price + signal.stop_distance
    return 0.0


def passes_correlation_filter(
    signal: Signal, open_positions: dict[str, Position]
) -> bool:
    """Return False if opening this signal would violate a correlation rule.

    Rule (risk_on): if all trigger symbols are already long, block new LONGs on
    the blocked symbols.
    """
    if signal.action != Action.LONG:
        return True
    for rule in CORRELATION_FILTER.values():
        if signal.symbol not in rule["block"]:
            continue
        triggers = rule["trigger"]
        all_triggers_long = all(
            sym in open_positions and open_positions[sym].side == "long"
            for sym in triggers
        )
        if all_triggers_long:
            return False
    return True


def entry_regime_multiplier(
    asset_class: str,
    action: Action,
    benchmarks_positive: bool | None,
) -> float:
    """Return the permitted fraction of a new entry under the market regime."""
    if asset_class != "equity":
        return 1.0
    # Missing or stale benchmark data is not a safe condition for a new equity
    # position. Existing positions continue to receive stop and exit handling.
    if benchmarks_positive is None:
        return 0.0
    if action == Action.LONG:
        return 1.0 if benchmarks_positive else 0.0
    if action == Action.SHORT and benchmarks_positive:
        return RISK_ON_SHORT_SIZE_MULT
    return 1.0


class DrawdownGuard:
    """Tracks peak equity and trips a circuit breaker on excessive drawdown."""

    def __init__(self, starting_equity: float, persist: bool = True):
        self.persist = persist
        state = load_json(DRAWDOWN_STATE_FILE, {}) if persist else {}
        persisted_peak = float(state.get("peak", 0.0)) if isinstance(state, dict) else 0.0
        self.loaded_persisted_state = persisted_peak > 0
        self.peak = max(starting_equity, persisted_peak)
        self.tripped = bool(state.get("tripped", False)) if isinstance(state, dict) else False
        self._persist()

    def _persist(self) -> None:
        if not self.persist:
            return
        save_json(
            DRAWDOWN_STATE_FILE,
            {"peak": self.peak, "tripped": self.tripped},
        )

    def update(self, equity: float) -> None:
        if equity > self.peak:
            self.peak = equity
            self._persist()

    def drawdown(self, equity: float) -> float:
        if self.peak <= 0:
            return 0.0
        return (self.peak - equity) / self.peak

    def check(self, equity: float) -> bool:
        """Update peak and return True if the breaker is (now) tripped."""
        self.update(equity)
        if self.drawdown(equity) >= MAX_PORTFOLIO_DRAWDOWN:
            self.tripped = True
            self._persist()
        return self.tripped


def stop_hit(position: Position, high: float, low: float) -> bool:
    """Whether the hard stop was breached by this bar's range."""
    if not math.isfinite(position.stop_price) or position.stop_price <= 0:
        return False
    if position.side == "long":
        return low <= position.stop_price
    return high >= position.stop_price


def update_trailing_stop(
    position: Position, high: float, low: float, current_atr: float, trail_mult: float
) -> None:
    """Ratchet the stop in the favorable direction only (never widened)."""
    if trail_mult <= 0 or current_atr <= 0:
        return
    if position.side == "long":
        position.high_water = max(position.high_water, high)
        new_stop = position.high_water - trail_mult * current_atr
        position.stop_price = max(position.stop_price, new_stop)
    else:
        position.high_water = min(position.high_water, low)
        new_stop = position.high_water + trail_mult * current_atr
        position.stop_price = min(position.stop_price, new_stop)
