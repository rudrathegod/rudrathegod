"""Fill-based closed-trade analytics for research and human review.

The live entry gate intentionally does not consume this module yet. It provides
an auditable per-symbol sample before any automatic strategy disablement.
"""
from __future__ import annotations

import csv
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

import config


@dataclass(frozen=True)
class ClosedTrade:
    symbol: str
    side: str
    entry_time: str
    exit_time: str
    qty: float
    entry_price: float
    exit_price: float
    net_pnl: float
    initial_risk: float
    r_multiple: float
    entry_reason: str
    exit_reason: str


def closed_trades_from_events(path: str | Path | None = None) -> list[ClosedTrade]:
    """Pair confirmed fill rows in the legacy event journal FIFO by symbol/side."""
    path = Path(path or config.TRADES_CSV)
    if not path.exists():
        return []
    entries: dict[tuple[str, str], deque[dict]] = defaultdict(deque)
    closed: list[ClosedTrade] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            direction = row.get("direction", "")
            symbol = row.get("instrument", "")
            if direction in {"long", "short"}:
                if "[broker_fill]" not in row.get("reason", ""):
                    continue
                entries[(symbol, direction)].append(row)
                continue
            if direction not in {"exit_long", "exit_short"}:
                continue
            if "[broker_fill]" not in row.get("reason", ""):
                continue
            side = direction.removeprefix("exit_")
            if not entries[(symbol, side)]:
                continue
            entry = entries[(symbol, side)].popleft()
            try:
                qty = min(float(entry["position_size"]), float(row["position_size"]))
                entry_price = float(entry["entry_price"])
                exit_price = float(row["exit_price"])
            except (KeyError, TypeError, ValueError):
                continue
            pnl = (
                (exit_price - entry_price) * qty
                if side == "long"
                else (entry_price - exit_price) * qty
            )
            initial_risk = qty * max(
                entry_price * config.MIN_STOP_DISTANCE_PCT, 1e-9
            )
            closed.append(
                ClosedTrade(
                    symbol=symbol,
                    side=side,
                    entry_time=entry["timestamp"],
                    exit_time=row["timestamp"],
                    qty=qty,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    net_pnl=pnl,
                    initial_risk=initial_risk,
                    r_multiple=pnl / initial_risk,
                    entry_reason=entry.get("reason", ""),
                    exit_reason=row.get("reason", ""),
                )
            )
    return closed


def write_closed_trade_journal(trades: list[ClosedTrade]) -> None:
    path = Path(config.CLOSED_TRADES_CSV)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "symbol", "side", "entry_time", "exit_time", "qty",
                "entry_fill_price", "exit_fill_price", "net_pnl",
                "initial_risk", "r_multiple", "entry_reason", "exit_reason",
            ]
        )
        for trade in trades:
            writer.writerow(
                [
                    trade.symbol, trade.side, trade.entry_time, trade.exit_time,
                    trade.qty, trade.entry_price, trade.exit_price, trade.net_pnl,
                    trade.initial_risk, trade.r_multiple, trade.entry_reason,
                    trade.exit_reason,
                ]
            )


def symbol_expectancy(trades: list[ClosedTrade]) -> dict[str, dict[str, float | int | bool]]:
    grouped: dict[str, list[ClosedTrade]] = defaultdict(list)
    for trade in trades:
        grouped[trade.symbol].append(trade)
    result: dict[str, dict[str, float | int | bool]] = {}
    for symbol, symbol_trades in grouped.items():
        window = symbol_trades[-config.EXPECTANCY_WINDOW_TRADES :]
        expectancy_r = sum(t.r_multiple for t in window) / len(window)
        result[symbol] = {
            "closed_trades": len(symbol_trades),
            "window_trades": len(window),
            "net_pnl": sum(t.net_pnl for t in window),
            "expectancy_r": expectancy_r,
            "manual_disable_candidate": (
                len(symbol_trades) >= config.EXPECTANCY_MIN_CLOSED_TRADES
                and expectancy_r < config.EXPECTANCY_DISABLE_BELOW_R
            ),
        }
    return result


def refresh_performance() -> dict[str, dict[str, float | int | bool]]:
    trades = closed_trades_from_events()
    write_closed_trade_journal(trades)
    return symbol_expectancy(trades)


def expectancy_frame() -> pd.DataFrame:
    stats = refresh_performance()
    if not stats:
        return pd.DataFrame()
    return pd.DataFrame.from_dict(stats, orient="index").sort_index()
