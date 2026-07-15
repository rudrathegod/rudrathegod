"""CSV trade + daily P&L logging."""
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

from config import DAILY_PNL_CSV, TRADES_CSV

_TRADE_HEADER = [
    "timestamp",
    "instrument",
    "direction",
    "entry_price",
    "exit_price",
    "profit_loss",
    "position_size",
    "reason",
]
_PNL_HEADER = ["date", "equity", "daily_pnl", "daily_pnl_pct"]


def _ensure_header(path: str, header: list[str]) -> None:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "w", newline="") as f:
            csv.writer(f).writerow(header)


def log_trade(
    instrument: str,
    direction: str,
    entry_price: float,
    exit_price: float | None,
    profit_loss: float | None,
    position_size: float,
    reason: str = "",
) -> None:
    _ensure_header(TRADES_CSV, _TRADE_HEADER)
    with open(TRADES_CSV, "a", newline="") as f:
        csv.writer(f).writerow(
            [
                datetime.now(timezone.utc).isoformat(),
                instrument,
                direction,
                f"{entry_price:.4f}" if entry_price is not None else "",
                f"{exit_price:.4f}" if exit_price is not None else "",
                f"{profit_loss:.2f}" if profit_loss is not None else "",
                f"{position_size:.6f}",
                reason,
            ]
        )


def log_daily_pnl(equity: float, daily_pnl: float, daily_pnl_pct: float) -> None:
    _ensure_header(DAILY_PNL_CSV, _PNL_HEADER)
    with open(DAILY_PNL_CSV, "a", newline="") as f:
        csv.writer(f).writerow(
            [
                datetime.now(timezone.utc).date().isoformat(),
                f"{equity:.2f}",
                f"{daily_pnl:.2f}",
                f"{daily_pnl_pct:.4f}",
            ]
        )
