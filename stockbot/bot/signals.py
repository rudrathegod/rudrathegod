"""Shared signal / position types used across strategies, risk, and execution."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Action(str, Enum):
    LONG = "long"       # open (or flip to) a long position
    SHORT = "short"     # open (or flip to) a short position
    EXIT = "exit"       # close any open position
    HOLD = "hold"       # do nothing


@dataclass
class Signal:
    """A strategy's decision for one instrument at one point in time."""
    symbol: str
    action: Action
    price: float               # reference price (last close) used for sizing
    atr: float                 # current ATR, used for sizing and stop distance
    stop_distance: float       # dollar distance from entry to stop (per unit)
    reason: str = ""           # human-readable explanation for logs/briefings

    @property
    def is_entry(self) -> bool:
        return self.action in (Action.LONG, Action.SHORT)


@dataclass
class Position:
    """A currently open position (mirrors what the broker reports)."""
    symbol: str
    side: str                  # "long" or "short"
    qty: float
    entry_price: float
    stop_price: float          # hard stop; never widened
    high_water: float          # best price seen (for trailing stops)
    entry_atr: float
