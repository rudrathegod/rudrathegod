"""Event-driven backtester.

Replays 6 months of historical bars across all 5 instruments on a single
merged timeline, using the SAME strategy functions and risk manager as the live
bot (so there is no logic drift). Models slippage; commission is $0 (Alpaca).

Run from the project root with:

    python -m bot.backtest            # 6 months, $100k (Alpaca paper default)
    python -m bot.backtest --months 12 --equity 25000

Outputs a per-instrument + portfolio summary table and an equity curve chart
(backtest_results.png).

This is an ungated deterministic baseline: it never calls AI providers. An
AI-gated historical replay requires recorded decisions available at each bar.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

import config
from . import risk_manager as rm
from .data import get_bars
from .signals import Action, Position, Signal
from .strategies import get_strategy


@dataclass
class Trade:
    symbol: str
    side: str
    entry: float
    exit: float
    qty: float
    pnl: float
    entry_time: pd.Timestamp | None = None
    exit_time: pd.Timestamp | None = None
    reason: str = ""
    costs: float = 0.0


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    start_equity: float = 0.0
    end_equity: float = 0.0


def _fill(price: float, buying: bool, asset_class: str) -> tuple[float, float]:
    """Apply adverse spread/slippage and return fill price plus per-unit fee."""
    spread = (
        config.CRYPTO_SPREAD_BPS if asset_class == "crypto" else config.EQUITY_SPREAD_BPS
    ) / 20_000
    impact = spread + config.SLIPPAGE_PCT
    fill = price * (1 + impact) if buying else price * (1 - impact)
    fee = fill * config.CRYPTO_TAKER_FEE_PCT if asset_class == "crypto" else 0.0
    return fill, fee


def _unrealized(pos: Position, last_price: float) -> float:
    if pos.side == "long":
        return (last_price - pos.entry_price) * pos.qty
    return (pos.entry_price - last_price) * pos.qty


def _benchmarks_positive(dfs: dict[str, pd.DataFrame], ts: pd.Timestamp) -> bool | None:
    """As-of benchmark regime; never reads a bar that has not closed at ``ts``."""
    from .indicators import sma

    flags: list[bool] = []
    for symbol in config.EQUITY_REGIME_SYMBOLS:
        df = dfs.get(symbol)
        if df is None:
            return None
        bars = df[df.index <= ts]
        if len(bars) < config.EQUITY_REGIME_TREND_MA:
            return None
        trend = float(sma(bars["close"], config.EQUITY_REGIME_TREND_MA).iloc[-1])
        if not np.isfinite(trend):
            return None
        flags.append(float(bars["close"].iloc[-1]) >= trend)
    return all(flags)


# Extra history fetched BEFORE the reporting window so slow indicators (e.g. the
# 200-EMA on 4h bars) are fully warmed up by the time trading starts. Without
# this, GLD/USO never accumulate enough 4h bars to produce a single crossover.
_WARMUP_DAYS = {"15Min": 30, "1Hour": 45, "4Hour": 300}


def run_backtest(
    months: int = 6, start_equity: float = 100_000.0, use_breaker: bool = True
) -> BacktestResult:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=months * 31)

    # 1) Fetch data for every instrument, reaching back past window_start by a
    #    timeframe-dependent warmup so indicators are ready at window_start.
    dfs: dict[str, pd.DataFrame] = {}
    for inst in config.INSTRUMENTS:
        warmup = _WARMUP_DAYS.get(inst.timeframe, 30)
        fetch_start = window_start - timedelta(days=warmup)
        df = get_bars(inst.symbol, inst.asset_class, inst.timeframe, fetch_start)
        if df.empty:
            print(f"WARNING: no data for {inst.symbol}, skipping.")
            continue
        dfs[inst.symbol] = df
        in_window = int((df.index >= window_start).sum())
        print(f"  {inst.symbol}: {len(df)} bars ({inst.timeframe}), {in_window} in reporting window")

    # 2) Build a merged, time-sorted event stream: (timestamp, symbol, bar_index).
    events: list[tuple[pd.Timestamp, str, int]] = []
    for symbol, df in dfs.items():
        for i in range(len(df)):
            events.append((df.index[i], symbol, i))
    events.sort(key=lambda e: e[0])

    positions: dict[str, Position] = {}
    last_price: dict[str, float] = {}
    realized = 0.0
    result = BacktestResult(start_equity=start_equity)
    curve_ts: list[pd.Timestamp] = []
    curve_eq: list[float] = []

    def portfolio_equity() -> float:
        unreal = sum(_unrealized(p, last_price.get(s, p.entry_price)) for s, p in positions.items())
        return start_equity + realized + unreal

    entry_metadata: dict[str, tuple[pd.Timestamp, float, str, str]] = {}
    cooldown_until: dict[str, pd.Timestamp] = {}
    pending_entries: dict[str, Signal] = {}
    pending_exits: dict[str, str] = {}

    def record_exit(
        pos: Position, exit_fill: float, exit_fee: float, ts: pd.Timestamp, reason: str
    ) -> None:
        nonlocal realized
        pnl = (
            (exit_fill - pos.entry_price) * pos.qty
            if pos.side == "long"
            else (pos.entry_price - exit_fill) * pos.qty
        )
        entry_ts, entry_fee, entry_reason, _ = entry_metadata.pop(
            pos.symbol, (ts, 0.0, "", "")
        )
        pnl -= (entry_fee + exit_fee) * pos.qty
        realized += pnl
        result.trades.append(
            Trade(
                pos.symbol, pos.side, pos.entry_price, exit_fill, pos.qty, pnl,
                entry_ts, ts, reason, (entry_fee + exit_fee) * pos.qty,
            )
        )

    # 3) Replay. `guard` mirrors the live 10%-drawdown circuit breaker so the
    #    backtest reflects what the running bot would actually do.
    guard = rm.DrawdownGuard(start_equity, persist=False)
    halted = False

    for ts, symbol, i in events:
        inst = config.INSTRUMENTS_BY_SYMBOL[symbol]
        df = dfs[symbol]
        bar = df.iloc[i]
        last_price[symbol] = float(bar["close"])
        slice_df = df.iloc[: i + 1]

        # Warmup bars: keep indicators updating (via slice) but do not trade.
        if ts < window_start or halted:
            continue

        # Drawdown circuit breaker: close everything and stop trading.
        if use_breaker and guard.check(portfolio_equity()):
            for s in list(positions.keys()):
                inst_for_pos = config.INSTRUMENTS_BY_SYMBOL[s]
                fill, fee = _fill(
                    last_price.get(s, positions[s].entry_price),
                    buying=positions[s].side == "short",
                    asset_class=inst_for_pos.asset_class,
                )
                record_exit(positions[s], fill, fee, ts, "drawdown breaker")
                del positions[s]
            halted = True
            curve_ts.append(ts)
            curve_eq.append(portfolio_equity())
            continue

        pos = positions.get(symbol)
        # Orders signalled on the prior closed bar execute at this bar's open.
        if symbol in pending_exits and pos is not None:
            fill, fee = _fill(
                float(bar["open"]), buying=pos.side == "short", asset_class=inst.asset_class
            )
            record_exit(pos, fill, fee, ts, pending_exits.pop(symbol))
            del positions[symbol]
            pos = None
        if symbol in pending_entries and pos is None:
            sig = pending_entries.pop(symbol)
            cooldown_expiry = cooldown_until.get(symbol)
            if inst.entry_enabled and (cooldown_expiry is None or ts >= cooldown_expiry):
                regime_ok = _benchmarks_positive(dfs, ts)
                multiplier = rm.entry_regime_multiplier(inst.asset_class, sig.action, regime_ok)
                qty = rm.position_size(portfolio_equity(), sig, sig.action == Action.LONG)
                gross = sum(abs(p.qty * p.entry_price) for p in positions.values())
                qty = rm.cap_size_to_available_notional(
                    qty * multiplier,
                    sig.price,
                    max(portfolio_equity() * config.MAX_GROSS_EXPOSURE_PCT - gross, 0.0),
                    sig.action == Action.LONG,
                )
                if qty > 0:
                    fill, fee = _fill(float(bar["open"]), sig.action == Action.LONG, inst.asset_class)
                    side = "long" if sig.action == Action.LONG else "short"
                    positions[symbol] = Position(
                        symbol, side, qty, fill,
                        fill - sig.stop_distance if side == "long" else fill + sig.stop_distance,
                        fill, sig.atr,
                    )
                    entry_metadata[symbol] = (ts, fee, sig.reason, "")
                    pos = positions[symbol]

        # -- stop management (uses this bar's range) --
        if pos is not None:
            trail_mult = float(inst.params.get("trail_atr_mult", 0.0))
            if trail_mult > 0 and pos.entry_atr > 0:
                rm.update_trailing_stop(pos, float(bar["high"]), float(bar["low"]), pos.entry_atr, trail_mult)
            if rm.stop_hit(pos, float(bar["high"]), float(bar["low"])):
                stop_fill, fee = _fill(
                    pos.stop_price, buying=pos.side == "short", asset_class=inst.asset_class
                )
                record_exit(pos, stop_fill, fee, ts, "hard/trailing stop")
                del positions[symbol]
                cooldown_until[symbol] = ts + pd.Timedelta(
                    minutes=int(inst.params.get("stop_cooldown_minutes", 0))
                )
                pos = None

        # -- strategy signal --
        params = {**inst.params, "symbol": symbol}
        sig: Signal = get_strategy(inst.strategy)(slice_df, params, pos)

        if sig.action == Action.EXIT and pos is not None:
            pending_exits[symbol] = sig.reason

        elif sig.is_entry and pos is None and inst.entry_enabled:
            if rm.passes_correlation_filter(sig, positions):
                pending_entries[symbol] = sig

        curve_ts.append(ts)
        curve_eq.append(portfolio_equity())

    if halted:
        print("\n[circuit breaker] Portfolio hit -10% drawdown; closed all and halted.")

    # Liquidate remaining exposure at the final available mark with modeled costs.
    if not halted and events:
        final_ts = events[-1][0]
        for symbol, pos in list(positions.items()):
            inst = config.INSTRUMENTS_BY_SYMBOL[symbol]
            fill, fee = _fill(
                last_price.get(symbol, pos.entry_price),
                buying=pos.side == "short",
                asset_class=inst.asset_class,
            )
            record_exit(pos, fill, fee, final_ts, "end of backtest")
            del positions[symbol]
        curve_ts.append(final_ts)
        curve_eq.append(portfolio_equity())

    result.equity_curve = pd.Series(curve_eq, index=pd.DatetimeIndex(curve_ts)).sort_index()
    # Collapse duplicate timestamps (multiple instruments) by taking the last.
    result.equity_curve = result.equity_curve[~result.equity_curve.index.duplicated(keep="last")]
    result.end_equity = float(result.equity_curve.iloc[-1]) if len(result.equity_curve) else start_equity
    return result


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def _per_instrument_stats(trades: list[Trade]) -> dict:
    by_symbol: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        by_symbol[t.symbol].append(t)

    stats = {}
    for symbol, ts in by_symbol.items():
        pnls = np.array([t.pnl for t in ts])
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        gross_win = wins.sum()
        gross_loss = -losses.sum()
        stats[symbol] = {
            "trades": len(ts),
            "win_rate": len(wins) / len(ts) if ts else 0.0,
            "avg_win": wins.mean() if len(wins) else 0.0,
            "avg_loss": losses.mean() if len(losses) else 0.0,
            "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
            "total_pnl": pnls.sum(),
        }
    return stats


def _max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max
    return float(dd.min())  # negative number


def _sharpe(equity: pd.Series, periods_per_year: int = 252) -> float:
    if equity.empty:
        return 0.0
    daily = equity.resample("1D").last().dropna()
    rets = daily.pct_change().dropna()
    if rets.std() == 0 or rets.empty:
        return 0.0
    return float((rets.mean() / rets.std()) * np.sqrt(periods_per_year))


def print_report(result: BacktestResult) -> None:
    stats = _per_instrument_stats(result.trades)

    print("\nNOTE: AI entry gate is not replayed; this is an ungated baseline.")
    print("\n" + "=" * 78)
    print("PER-INSTRUMENT PERFORMANCE")
    print("=" * 78)
    header = f"{'Symbol':<10}{'Trades':>7}{'WinRate':>9}{'AvgWin':>10}{'AvgLoss':>10}{'PF':>7}{'PnL$':>11}"
    print(header)
    print("-" * 78)
    for symbol in (i.symbol for i in config.INSTRUMENTS):
        if symbol not in stats:
            print(f"{symbol:<10}{'—':>7}{'(no trades)':>27}")
            continue
        s = stats[symbol]
        pf = "inf" if s["profit_factor"] == float("inf") else f"{s['profit_factor']:.2f}"
        print(
            f"{symbol:<10}{s['trades']:>7}{s['win_rate']*100:>8.1f}%"
            f"{s['avg_win']:>10.2f}{s['avg_loss']:>10.2f}{pf:>7}{s['total_pnl']:>11.2f}"
        )

    total_return = (result.end_equity / result.start_equity - 1) if result.start_equity else 0.0
    mdd = _max_drawdown(result.equity_curve)
    sharpe = _sharpe(result.equity_curve)

    print("\n" + "=" * 78)
    print("COMBINED PORTFOLIO (correlation filter active)")
    print("=" * 78)
    print(f"  Start equity     : ${result.start_equity:,.2f}")
    print(f"  End equity       : ${result.end_equity:,.2f}")
    print(f"  Total return     : {total_return*100:+.2f}%")
    print(f"  Max drawdown     : {mdd*100:.2f}%")
    print(f"  Sharpe (daily)   : {sharpe:.2f}")
    print(f"  Total trades     : {len(result.trades)}")

    # Flags per the spec.
    print("\nFLAGS")
    if sharpe < 0:
        print("  [!] Portfolio Sharpe is NEGATIVE — reconsider parameters before going live.")
    if abs(mdd) > 0.15:
        print(f"  [!] Max drawdown {abs(mdd)*100:.1f}% exceeds 15% — tighten risk / parameters.")
    for symbol, s in stats.items():
        # Rough per-instrument Sharpe proxy from trade pnls.
        pnls = np.array([t.pnl for t in result.trades if t.symbol == symbol])
        if len(pnls) > 1 and pnls.std() > 0:
            proxy = pnls.mean() / pnls.std()
            if proxy < 0:
                print(f"  [!] {symbol}: negative expectancy (mean/std {proxy:.2f}) — adjust parameters.")
    if sharpe >= 0 and abs(mdd) <= 0.15:
        print("  OK: no hard flags. Still paper trade 2+ weeks before risking real money.")


def plot_equity_curve(result: BacktestResult, path: str) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:  # noqa: BLE001
        print(f"(matplotlib unavailable, skipping chart: {e})")
        return

    if result.equity_curve.empty:
        print("(no equity curve to plot)")
        return

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(result.equity_curve.index, result.equity_curve.values, linewidth=1.3)
    ax.set_title("Backtest Equity Curve (portfolio, correlation filter on)")
    ax.set_xlabel("Date")
    ax.set_ylabel("Equity ($)")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    print(f"\nSaved equity curve -> {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the multi-strategy bot.")
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument(
        "--equity", type=float, default=100_000.0,
        help="Starting equity (default 100k to match Alpaca's paper account default).",
    )
    parser.add_argument(
        "--no-breaker", action="store_true",
        help="Research mode: disable the 10%% drawdown breaker to see full-period edge.",
    )
    args = parser.parse_args()

    config.validate_credentials()
    mode = " (no breaker / research)" if args.no_breaker else ""
    print(f"Backtesting {args.months} months, starting equity ${args.equity:,.0f}{mode}\nFetching data...")
    result = run_backtest(
        months=args.months, start_equity=args.equity, use_breaker=not args.no_breaker
    )
    print_report(result)
    plot_equity_curve(result, config.BACKTEST_CHART)


if __name__ == "__main__":
    main()
