"""Durable entry controls shared by live trading and research."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config import STOP_COOLDOWN_STATE_FILE
from .state_store import load_json, save_json


def record_stop_cooldown(symbol: str, minutes: int, now: datetime | None = None) -> None:
    if minutes <= 0:
        return
    now = now or datetime.now(timezone.utc)
    state = load_json(STOP_COOLDOWN_STATE_FILE, {})
    if not isinstance(state, dict):
        state = {}
    state[symbol] = (now + timedelta(minutes=minutes)).isoformat()
    save_json(STOP_COOLDOWN_STATE_FILE, state)


def cooldown_active(symbol: str, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    state = load_json(STOP_COOLDOWN_STATE_FILE, {})
    if not isinstance(state, dict):
        return False
    raw_expiry = state.get(symbol)
    if not raw_expiry:
        return False
    try:
        expiry = datetime.fromisoformat(raw_expiry)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return False
    return now < expiry
