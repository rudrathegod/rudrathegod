"""Fail-closed dual-provider approval for deterministic strategy entries."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

from .signals import Action, Signal

log = logging.getLogger("bot")
_VALID_ACTIONS = {Action.LONG.value, Action.SHORT.value}
_REASON_CODE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_PROMPT_VERSION = "dual-entry-filter-v1"


@dataclass(frozen=True)
class ProviderProposal:
    provider: str
    model: str
    symbol: str
    bar_timestamp: str
    action: str
    allow_entry: bool
    reason_code: str
    latency_ms: int


@dataclass(frozen=True)
class AIDecision:
    approved: bool
    mode: str
    reason: str
    context_hash: str
    proposals: tuple[ProviderProposal, ...] = ()


def _bar_timestamp(df: Any) -> str:
    timestamp = df.index[-1].to_pydatetime()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat()


def _context(inst: Any, df: Any, signal: Signal) -> dict[str, Any]:
    """Build a bounded, JSON-safe context using only closed bars."""
    bars = []
    for timestamp, row in df.tail(20).iterrows():
        date = timestamp.to_pydatetime()
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        bars.append(
            {
                "timestamp": date.astimezone(timezone.utc).isoformat(),
                "open": round(float(row["open"]), 6),
                "high": round(float(row["high"]), 6),
                "low": round(float(row["low"]), 6),
                "close": round(float(row["close"]), 6),
                "volume": round(float(row["volume"]), 2),
            }
        )
    return {
        "prompt_version": _PROMPT_VERSION,
        "symbol": signal.symbol,
        "asset_class": inst.asset_class,
        "bar_timestamp": _bar_timestamp(df),
        "proposed_action": signal.action.value,
        "reference_price": round(float(signal.price), 6),
        "atr": round(float(signal.atr), 6),
        "stop_distance": round(float(signal.stop_distance), 6),
        "strategy_reason": signal.reason[:200],
        "closed_bars": bars,
    }


def _context_hash(context: dict[str, Any]) -> str:
    encoded = json.dumps(context, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _prompt(context: dict[str, Any]) -> str:
    return (
        "You are a restrictive paper-trading entry filter. Assess only this "
        "already-proposed entry from closed market bars. You cannot change side, "
        "size, stops, or create an exit. Return exactly one JSON object, no markdown: "
        '{"symbol":"...", "bar_timestamp":"...", "action":"long|short", '
        '"allow_entry":true|false, "reason_code":"safe_code"}. Use false if '
        "uncertain. Copy symbol, timestamp, and action exactly from the proposal.\n"
        + json.dumps(context, separators=(",", ":"))
    )


def _parse(
    provider: str, model: str, raw: str, expected: dict[str, Any], latency_ms: int
) -> ProviderProposal | None:
    try:
        payload = json.loads(raw.strip())
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or set(payload) != {
        "symbol", "bar_timestamp", "action", "allow_entry", "reason_code"
    }:
        return None
    symbol = payload.get("symbol")
    timestamp = payload.get("bar_timestamp")
    action = payload.get("action")
    allowed = payload.get("allow_entry")
    reason = payload.get("reason_code")
    if (
        not isinstance(symbol, str)
        or not isinstance(timestamp, str)
        or not isinstance(action, str)
        or type(allowed) is not bool
        or not isinstance(reason, str)
        or not _REASON_CODE.fullmatch(reason)
        or action not in _VALID_ACTIONS
        or symbol != expected["symbol"]
        or timestamp != expected["bar_timestamp"]
        or action != expected["proposed_action"]
    ):
        return None
    return ProviderProposal(
        provider, model, symbol, timestamp, action, allowed, reason, latency_ms
    )


def _ask_anthropic(prompt: str) -> str:
    from anthropic import Anthropic

    client = Anthropic(
        api_key=config.AI_ANTHROPIC_API_KEY,
        timeout=config.AI_SIGNAL_TIMEOUT_SECONDS,
        max_retries=0,
    )
    response = client.messages.create(
        model=config.AI_ANTHROPIC_MODEL,
        max_tokens=150,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _ask_openai(prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI(
        api_key=config.AI_OPENAI_API_KEY,
        timeout=config.AI_SIGNAL_TIMEOUT_SECONDS,
        max_retries=0,
    )
    response = client.chat.completions.create(
        model=config.AI_OPENAI_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


def _daily_limit_reached(now: datetime) -> bool:
    limit = config.AI_SIGNAL_DAILY_DECISION_LIMIT
    if limit <= 0:
        return False
    path = Path(config.AI_DECISIONS_JSONL)
    if not path.exists():
        return False
    try:
        with path.open(encoding="utf-8") as journal:
            count = sum(
                1
                for line in journal
                if json.loads(line).get("timestamp", "").startswith(
                    now.date().isoformat()
                )
            )
        return count >= limit
    except (OSError, ValueError, TypeError):
        return True


def _journal(decision: AIDecision) -> None:
    """Append sanitized decision metadata; never include prompts, keys, or errors."""
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "approved": decision.approved,
        "mode": decision.mode,
        "reason": decision.reason,
        "context_hash": decision.context_hash,
        "proposals": [asdict(p) for p in decision.proposals],
    }
    try:
        with Path(config.AI_DECISIONS_JSONL).open("a", encoding="utf-8") as journal:
            journal.write(json.dumps(event, separators=(",", ":")) + "\n")
    except OSError:
        log.exception("Could not write AI decision journal")


def _mock_proposal(provider: str, model: str, context: dict[str, Any]) -> ProviderProposal:
    return ProviderProposal(
        provider=provider,
        model=model,
        symbol=context["symbol"],
        bar_timestamp=context["bar_timestamp"],
        action=context["proposed_action"],
        allow_entry=True,
        reason_code="paper_mock",
        latency_ms=0,
    )


def approve_entry(inst: Any, df: Any, signal: Signal) -> AIDecision:
    """Approve only matching valid provider decisions; journal every decision."""
    context = _context(inst, df, signal)
    context_hash = _context_hash(context)
    mode = config.AI_SIGNAL_MODE
    if mode == "disabled":
        decision = AIDecision(True, mode, "disabled", context_hash)
    elif signal.action.value not in _VALID_ACTIONS:
        decision = AIDecision(False, mode, "not_entry", context_hash)
    elif _daily_limit_reached(datetime.now(timezone.utc)):
        decision = AIDecision(False, mode, "daily_limit", context_hash)
    elif mode == "paper_mock":
        proposals = (
            _mock_proposal("anthropic_mock", config.AI_ANTHROPIC_MODEL, context),
            _mock_proposal("openai_mock", config.AI_OPENAI_MODEL, context),
        )
        decision = AIDecision(True, mode, "paper_mock", context_hash, proposals)
    elif mode != "providers" or not (
        config.AI_ANTHROPIC_API_KEY and config.AI_OPENAI_API_KEY
    ):
        decision = AIDecision(False, mode, "provider_config", context_hash)
    else:
        prompt = _prompt(context)
        calls = (
            ("anthropic", config.AI_ANTHROPIC_MODEL, _ask_anthropic),
            ("openai", config.AI_OPENAI_MODEL, _ask_openai),
        )
        proposals: list[ProviderProposal] = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [(provider, model, executor.submit(call, prompt)) for provider, model, call in calls]
            for provider, model, future in futures:
                started = time.monotonic()
                try:
                    raw = future.result(timeout=config.AI_SIGNAL_TIMEOUT_SECONDS + 1)
                    parsed = _parse(
                        provider, model, raw, context, round((time.monotonic() - started) * 1000)
                    )
                    if parsed is not None:
                        proposals.append(parsed)
                except Exception:
                    log.warning("%s AI proposal unavailable", provider)
        approved = len(proposals) == 2 and all(p.allow_entry for p in proposals)
        decision = AIDecision(
            approved,
            mode,
            "provider_agreement" if approved else "provider_disagreement_or_invalid",
            context_hash,
            tuple(proposals),
        )
    _journal(decision)
    return decision
