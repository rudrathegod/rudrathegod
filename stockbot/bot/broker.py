"""Thin wrapper around Alpaca's TradingClient for order execution and account state.

Keeps the rest of the bot decoupled from alpaca-py specifics and makes the
paper/live safety lock impossible to bypass.
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderStatus, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from config import (
    ALLOW_LIVE,
    ALPACA_API_KEY,
    ALPACA_SECRET_KEY,
    INSTRUMENTS_BY_SYMBOL,
    IS_PAPER,
    ORDER_FILL_TIMEOUT_SECONDS,
    validate_credentials,
)
from .http_utils import harden
from .signals import Position


_TERMINAL_ORDER_STATUSES = {
    OrderStatus.FILLED,
    OrderStatus.CANCELED,
    OrderStatus.EXPIRED,
    OrderStatus.REJECTED,
    OrderStatus.SUSPENDED,
    OrderStatus.DONE_FOR_DAY,
    OrderStatus.STOPPED,
}
_CANONICAL_CRYPTO_SYMBOLS = {
    symbol.replace("/", ""): symbol
    for symbol in INSTRUMENTS_BY_SYMBOL
    if "/" in symbol
}


class Broker:
    def __init__(self) -> None:
        validate_credentials()
        self.client = TradingClient(
            ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=IS_PAPER
        )
        # Without this, a stalled network read blocks forever (no exception,
        # no timeout) — see bot/http_utils.py for why this matters.
        harden(self.client)
        # Cash accounts (no margin) can't short at all; detect this dynamically
        # so the bot self-adapts instead of erroring out on every rip signal.
        self.shorting_enabled = bool(
            getattr(self.client.get_account(), "shorting_enabled", False)
        )
        self.is_paper = IS_PAPER
        if not IS_PAPER and not ALLOW_LIVE:
            # Defense in depth; validate_credentials already covers this.
            raise RuntimeError("Live trading blocked (ALLOW_LIVE != true).")

    # -- account --------------------------------------------------------------
    def equity(self) -> float:
        return float(self.client.get_account().equity)

    def cash(self) -> float:
        return float(self.client.get_account().cash)

    def non_marginable_buying_power(self) -> float:
        account = self.client.get_account()
        value = getattr(account, "non_marginable_buying_power", None)
        if value is None:
            value = account.cash
        return max(float(value), 0.0)

    # -- positions ------------------------------------------------------------
    def open_positions(self) -> dict[str, Position]:
        result: dict[str, Position] = {}
        for p in self.client.get_all_positions():
            side = "long" if float(p.qty) > 0 else "short"
            entry = float(p.avg_entry_price)
            canonical_symbol = _from_alpaca_symbol(p.symbol)
            result[canonical_symbol] = Position(
                symbol=canonical_symbol,
                side=side,
                qty=abs(float(p.qty)),
                entry_price=entry,
                stop_price=0.0,       # broker doesn't track our logical stop
                high_water=entry,
                entry_atr=0.0,
            )
        return result

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.open_positions().get(symbol)

    def open_order_symbols(self) -> set[str]:
        return {
            _from_alpaca_symbol(order.symbol)
            for order in self.client.get_orders()
            if order.status not in _TERMINAL_ORDER_STATUSES
        }

    # -- orders ---------------------------------------------------------------
    def submit_market_order(self, symbol: str, qty: float, side: str) -> object:
        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        # Crypto trades 24/7 and requires GTC; equities use DAY.
        tif = TimeInForce.GTC if "/" in symbol else TimeInForce.DAY
        req = MarketOrderRequest(
            symbol=_to_alpaca_symbol(symbol),
            qty=qty,
            side=order_side,
            time_in_force=tif,
            client_order_id=f"bigballing-{uuid.uuid4().hex[:20]}",
        )
        try:
            order = self.client.submit_order(req)
        except Exception as submit_error:
            try:
                order = self.client.get_order_by_client_id(req.client_order_id)
            except Exception:
                raise submit_error
        return self._wait_for_terminal_order(order)

    def close_position(self, symbol: str) -> object:
        # The /positions/{symbol} endpoint chokes on the "/" in "BTC/USD"
        # (it gets parsed as an extra path segment -> 404 Not Found).
        # Orders accept the slash form; positions need it stripped.
        order = self.client.close_position(_to_position_symbol(symbol))
        return self._wait_for_terminal_order(order)

    def close_all(self) -> object:
        responses = self.client.close_all_positions(cancel_orders=True)
        deadline = time.monotonic() + ORDER_FILL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if not self.client.get_all_positions():
                return responses
            time.sleep(0.2)
        remaining = [position.symbol for position in self.client.get_all_positions()]
        raise RuntimeError(f"Close-all did not flatten positions: {remaining}")

    def _wait_for_terminal_order(self, order: object) -> object:
        deadline = time.monotonic() + ORDER_FILL_TIMEOUT_SECONDS
        current = order
        while getattr(current, "status", None) not in _TERMINAL_ORDER_STATUSES:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.2)
            current = self.client.get_order_by_id(current.id)
        return current

    # -- market clock ---------------------------------------------------------
    def is_equity_market_open(self) -> bool:
        return bool(self.client.get_clock().is_open)

    # -- capability checks ------------------------------------------------------
    def can_short(self, asset_class: str) -> bool:
        # Alpaca crypto is spot/long-only for every account, no exceptions.
        if asset_class == "crypto":
            return False
        return self.shorting_enabled


def _to_alpaca_symbol(symbol: str) -> str:
    # alpaca-py trading uses "BTC/USD" for crypto already; equities unchanged.
    return symbol


def _to_position_symbol(symbol: str) -> str:
    # The positions endpoint uses the no-slash form ("BTCUSD"), unlike orders.
    return symbol.replace("/", "")


def _from_alpaca_symbol(symbol: str) -> str:
    # Positions API may return "BTCUSD" for crypto; normalize back to slash form.
    return _CANONICAL_CRYPTO_SYMBOLS.get(symbol, symbol)
