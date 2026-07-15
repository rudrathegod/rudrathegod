"""Strategy modules.

Every strategy exposes:

    generate_signal(df: pd.DataFrame, params: dict, position: Position | None) -> Signal

`df` is a bar DataFrame indexed by timestamp with columns:
    open, high, low, close, volume
The last row is the most recently *closed* candle. Strategies must never peek
past the last row (no look-ahead), which keeps live and backtest logic identical.
"""
from __future__ import annotations

from . import mean_reversion, momentum_breakout, trend_following

STRATEGY_REGISTRY = {
    "mean_reversion": mean_reversion.generate_signal,
    "momentum_breakout": momentum_breakout.generate_signal,
    "trend_following": trend_following.generate_signal,
}


def get_strategy(name: str):
    if name not in STRATEGY_REGISTRY:
        raise KeyError(f"Unknown strategy '{name}'. Known: {list(STRATEGY_REGISTRY)}")
    return STRATEGY_REGISTRY[name]
