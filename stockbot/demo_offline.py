"""Offline demo: run the REAL backtest engine on SYNTHETIC data (no API keys).

This exists only to prove the pipeline works end to end without Alpaca
credentials. It monkeypatches the data source with generated OHLCV bars, then
calls the exact same run_backtest / print_report / plot_equity_curve used for
real data.

    python demo_offline.py

IMPORTANT: the numbers this produces are MEANINGLESS for trading decisions —
they come from random synthetic prices, not the market. Use real paper data
(with keys in .env) before drawing any conclusion.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import bot.backtest as bt
import config

_FREQ = {"15Min": "15min", "1Hour": "1h", "4Hour": "4h"}
_BASE_PRICE = {"SPY": 500.0, "QQQ": 430.0, "BTC/USD": 60000.0, "GLD": 190.0, "USO": 75.0}
_N_BARS = 1000  # keeps the O(n^2) replay fast while exercising the 200-EMA path


def _synth(symbol: str, timeframe: str, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = _N_BARS
    t = np.arange(n)
    p0 = _BASE_PRICE[symbol]

    # Blend a slow trend, a mean-reverting oscillation, and gaussian noise so
    # that trend/mean-reversion/momentum strategies all have something to act on.
    vol = 0.004
    trend = 0.0002 * np.sin(t / 220.0)                 # slow regime changes
    oscill = 0.01 * np.sin(t / 18.0)                    # short-term reversion
    noise = rng.normal(0, vol, n)
    log_price = np.cumsum(trend + noise) + oscill
    close = p0 * np.exp(log_price)

    intrabar = close * vol * 1.5
    high = close + np.abs(rng.normal(0, 1, n)) * intrabar
    low = close - np.abs(rng.normal(0, 1, n)) * intrabar
    open_ = np.concatenate([[close[0]], close[:-1]])
    volume = rng.lognormal(mean=10, sigma=0.5, size=n)
    # Inject occasional volume spikes so momentum breakouts can confirm.
    spikes = rng.random(n) < 0.05
    volume[spikes] *= 3.0

    idx = pd.date_range("2025-01-01", periods=n, freq=_FREQ[timeframe], tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def main() -> None:
    dfs = {
        inst.symbol: _synth(inst.symbol, inst.timeframe, seed=i)
        for i, inst in enumerate(config.INSTRUMENTS)
    }

    def fake_get_bars(symbol, asset_class, timeframe, start, end=None):
        return dfs[symbol]

    # Patch the data source used inside the backtest engine.
    bt.get_bars = fake_get_bars

    print("=== OFFLINE DEMO (synthetic data, NOT real market results) ===\n")
    result = bt.run_backtest(months=6, start_equity=100_000.0)
    bt.print_report(result)
    bt.plot_equity_curve(result, config.BACKTEST_CHART)


if __name__ == "__main__":
    main()
