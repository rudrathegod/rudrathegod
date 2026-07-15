"""Portfolio state manager.

Bridges strategy signals and the broker: opens/closes positions, tracks the
logical stop and high-water mark for each open position (the broker doesn't
store these), and writes trade logs.
"""
from __future__ import annotations

import math
from typing import Optional

from config import POSITION_STATE_FILE

from . import risk_manager as rm
from .broker import Broker
from .logger import log_trade
from .signals import Action, Position, Signal
from .state_store import load_json, save_json


class Portfolio:
    def __init__(self, broker: Broker):
        self.broker = broker
        # Our logical view of positions, keyed by symbol. Seeded from the broker
        # so restarts don't lose track of open trades (stops re-derived below).
        self.positions: dict[str, Position] = broker.open_positions()
        self.pending_symbols = broker.open_order_symbols()
        saved = load_json(POSITION_STATE_FILE, {})
        if isinstance(saved, dict):
            for symbol, position in self.positions.items():
                state = saved.get(symbol)
                if not isinstance(state, dict) or not self._state_matches(position, state):
                    continue
                try:
                    stop_price = float(state["stop_price"])
                    high_water = float(state["high_water"])
                    entry_atr = float(state["entry_atr"])
                except (KeyError, TypeError, ValueError):
                    continue
                if stop_price > 0 and entry_atr > 0:
                    position.stop_price = stop_price
                    position.high_water = high_water
                    position.entry_atr = entry_atr

    # -- queries --------------------------------------------------------------
    def get(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    def equity(self) -> float:
        return self.broker.equity()

    def has_pending_order(self, symbol: str) -> bool:
        return symbol in self.pending_symbols

    def gross_notional(self) -> float:
        return sum(abs(pos.qty * pos.entry_price) for pos in self.positions.values())

    def persist_state(self) -> None:
        save_json(
            POSITION_STATE_FILE,
            {
                symbol: {
                    "side": pos.side,
                    "qty": pos.qty,
                    "entry_price": pos.entry_price,
                    "stop_price": pos.stop_price,
                    "high_water": pos.high_water,
                    "entry_atr": pos.entry_atr,
                }
                for symbol, pos in self.positions.items()
                if (
                    math.isfinite(pos.stop_price)
                    and pos.stop_price > 0
                    and math.isfinite(pos.entry_atr)
                    and pos.entry_atr > 0
                )
            },
        )

    def reconcile(self) -> None:
        """Refresh broker-authoritative positions without discarding risk state."""
        broker_positions = self.broker.open_positions()
        for symbol, broker_position in broker_positions.items():
            local = self.positions.get(symbol)
            if local is None or not self._positions_match(local, broker_position):
                continue
            broker_position.stop_price = local.stop_price
            broker_position.high_water = local.high_water
            broker_position.entry_atr = local.entry_atr
        self.positions = broker_positions
        self.pending_symbols = self.broker.open_order_symbols()
        self.persist_state()

    # -- mutations ------------------------------------------------------------
    def open(self, signal: Signal, qty: float, allow_fractional: bool) -> bool:
        if qty <= 0 or self.has_pending_order(signal.symbol):
            return False
        side = "long" if signal.action == Action.LONG else "short"
        order_side = "buy" if side == "long" else "sell"
        order = self.broker.submit_market_order(signal.symbol, qty, order_side)

        status = self._order_status(order)
        if status != "filled":
            if status in {"canceled", "expired", "rejected", "suspended", "stopped"}:
                raise RuntimeError(
                    f"{signal.symbol} entry order ended with status {status}"
                )
            self.pending_symbols.add(signal.symbol)
            return False

        filled_qty = float(getattr(order, "filled_qty", 0.0) or 0.0)
        filled_price = float(getattr(order, "filled_avg_price", 0.0) or 0.0)
        if filled_qty <= 0 or filled_price <= 0:
            raise RuntimeError(f"{signal.symbol} filled entry has invalid fill details")
        filled_signal = Signal(
            symbol=signal.symbol,
            action=signal.action,
            price=filled_price,
            atr=signal.atr,
            stop_distance=signal.stop_distance,
            reason=signal.reason,
        )
        stop = rm.stop_price_for(filled_signal)
        self.positions[signal.symbol] = Position(
            symbol=signal.symbol,
            side=side,
            qty=filled_qty,
            entry_price=filled_price,
            stop_price=stop,
            high_water=filled_price,
            entry_atr=signal.atr,
        )
        self.pending_symbols.discard(signal.symbol)
        self.persist_state()
        log_trade(
            instrument=signal.symbol,
            direction=side,
            entry_price=filled_price,
            exit_price=None,
            profit_loss=None,
            position_size=filled_qty,
            reason=f"ENTRY [broker_fill]: {signal.reason}",
        )
        return True

    def close(self, symbol: str, exit_price: float, reason: str) -> bool:
        pos = self.positions.get(symbol)
        if pos is None or self.has_pending_order(symbol):
            return False
        order = self.broker.close_position(symbol)

        status = self._order_status(order)
        if status != "filled":
            if status in {"canceled", "expired", "rejected", "suspended", "stopped"}:
                raise RuntimeError(f"{symbol} close order ended with status {status}")
            self.pending_symbols.add(symbol)
            return False

        filled_qty = float(getattr(order, "filled_qty", 0.0) or 0.0)
        filled_price = float(getattr(order, "filled_avg_price", 0.0) or 0.0)
        if filled_qty <= 0 or filled_price <= 0:
            raise RuntimeError(f"{symbol} filled close has invalid fill details")
        closed_qty = min(pos.qty, filled_qty)
        pnl = self._pnl(pos, filled_price, closed_qty)
        log_trade(
            instrument=symbol,
            direction=f"exit_{pos.side}",
            entry_price=pos.entry_price,
            exit_price=filled_price,
            profit_loss=pnl,
            position_size=closed_qty,
            reason=f"EXIT [broker_fill]: {reason}",
        )
        del self.positions[symbol]
        self.pending_symbols.discard(symbol)
        self.persist_state()
        return True

    @staticmethod
    def _order_status(order: object) -> str:
        status = getattr(order, "status", "")
        return str(getattr(status, "value", status))

    @staticmethod
    def _positions_match(left: Position, right: Position) -> bool:
        if left.side != right.side:
            return False
        entry_scale = max(abs(left.entry_price), abs(right.entry_price), 1.0)
        qty_scale = max(abs(left.qty), abs(right.qty), 1.0)
        return (
            abs(left.entry_price - right.entry_price) / entry_scale <= 0.01
            and abs(left.qty - right.qty) / qty_scale <= 0.02
        )

    @staticmethod
    def _state_matches(position: Position, state: dict) -> bool:
        try:
            stored = Position(
                symbol=position.symbol,
                side=str(state["side"]),
                qty=float(state["qty"]),
                entry_price=float(state["entry_price"]),
                stop_price=0.0,
                high_water=0.0,
                entry_atr=0.0,
            )
        except (KeyError, TypeError, ValueError):
            return False
        return Portfolio._positions_match(position, stored)

    @staticmethod
    def _pnl(pos: Position, exit_price: float, qty: float | None = None) -> float:
        quantity = pos.qty if qty is None else qty
        if pos.side == "long":
            return (exit_price - pos.entry_price) * quantity
        return (pos.entry_price - exit_price) * quantity
