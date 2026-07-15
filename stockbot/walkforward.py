"""Honest edge tests (real Alpaca data):

1. Buy-and-hold benchmark for each instrument over the same 6-month window.
2. Walk-forward: grid-search each strategy's parameters on the first 4 months
   (in-sample / IS), pick the IS-best config, then measure it on the last 2
   months it never saw (out-of-sample / OOS). If IS-best falls apart OOS, that is
   direct evidence the "edge" was curve-fit and won't survive live.

Vectorized indicators + a sequential position simulator (fast). Sizing uses a
constant 1%-of-start-equity risk per trade so combos are compared on equal
footing (non-compounding), with 0.05% slippage per fill.

    python walkforward.py
"""
from __future__ import annotations

import itertools
import argparse
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

import config
from bot.data import get_bars
from bot.indicators import atr, ema, rolling_high, rolling_low, rolling_std, sma

START_EQUITY = 100_000.0
RISK_DOLLARS = START_EQUITY * config.RISK_PER_TRADE
SLIP = config.SLIPPAGE_PCT
WARMUP_DAYS = {"15Min": 30, "1Hour": 45, "4Hour": 300}

# Parameter grids per strategy (kept modest but meaningful).
GRIDS = {
    "mean_reversion": [
        {"lookback": 20, "entry_std": es, "stop_atr_mult": sm, "trend_ma": tm}
        for es, sm, tm in itertools.product([1.5, 2.0, 2.5], [1.5, 2.5], [0, 100])
    ],
    "momentum_breakout": [
        {"lookback": lb, "vol_mult": 1.5, "trail_atr_mult": tr, "trend_ema": te}
        for lb, tr, te in itertools.product([20, 55], [2.0, 3.0], [0, 50])
    ],
    "trend_following": [
        {"fast_ema": f, "slow_ema": s, "trail_atr_mult": tr}
        for (f, s), tr in itertools.product([(10, 30), (20, 50), (50, 200)], [2.0, 3.0])
    ],
}


def _signals(df: pd.DataFrame, strategy: str, p: dict) -> dict:
    """Vectorized per-bar signal components for a strategy/param set."""
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    a = atr(df, config.ATR_PERIOD)
    n = len(df)
    out = {"atr": a.to_numpy(), "close": close.to_numpy(),
           "high": high.to_numpy(), "low": low.to_numpy()}

    if strategy == "mean_reversion":
        m = sma(close, p["lookback"])
        s = rolling_std(close, p["lookback"])
        z = (close - m) / s
        stop = p["stop_atr_mult"] * a
        if p["trend_ma"] > 0:
            tma = sma(close, p["trend_ma"])
            up = (close >= tma).to_numpy()
            dn = (close <= tma).to_numpy()
        else:
            up = dn = np.ones(n, dtype=bool)
        out["entry_long"] = ((z <= -p["entry_std"]) & up).to_numpy()
        out["entry_short"] = ((z >= p["entry_std"]) & dn).to_numpy()
        out["exit_long"] = (close >= m).to_numpy()
        out["exit_short"] = (close <= m).to_numpy()
        out["stop"] = stop.to_numpy()
        out["trail_mult"] = 0.0

    elif strategy == "momentum_breakout":
        ph = rolling_high(high, p["lookback"]).shift(1)
        pl = rolling_low(low, p["lookback"]).shift(1)
        av = sma(vol, p["lookback"]).shift(1)
        vol_ok = (av > 0) & (vol >= p["vol_mult"] * av)
        if p["trend_ema"] > 0:
            te = ema(close, p["trend_ema"])
            up = (close >= te).to_numpy()
            dn = (close <= te).to_numpy()
        else:
            up = dn = np.ones(n, dtype=bool)
        out["entry_long"] = ((close > ph) & vol_ok & up).to_numpy()
        out["entry_short"] = ((close < pl) & vol_ok & dn).to_numpy()
        out["exit_long"] = (close < pl).to_numpy()
        out["exit_short"] = (close > ph).to_numpy()
        out["stop"] = (p["trail_atr_mult"] * a).to_numpy()
        out["trail_mult"] = p["trail_atr_mult"]

    else:  # trend_following
        fast, slow = ema(close, p["fast_ema"]), ema(close, p["slow_ema"])
        cu = (fast.shift(1) <= slow.shift(1)) & (fast > slow)
        cd = (fast.shift(1) >= slow.shift(1)) & (fast < slow)
        out["entry_long"] = cu.to_numpy()
        out["entry_short"] = cd.to_numpy()
        out["exit_long"] = cd.to_numpy()
        out["exit_short"] = cu.to_numpy()
        out["stop"] = (p["trail_atr_mult"] * a).to_numpy()
        out["trail_mult"] = p["trail_atr_mult"]
    return out


def simulate(df, strategy, p, mask, allow_fractional) -> list[float]:
    """Next-bar-open sequential simulator for one candidate parameter set."""
    s = _signals(df, strategy, p)
    close, high, low, a, stop = s["close"], s["high"], s["low"], s["atr"], s["stop"]
    el, es_, xl, xs = s["entry_long"], s["entry_short"], s["exit_long"], s["exit_short"]
    trail = s["trail_mult"]

    pnls: list[float] = []
    side = None
    qty = entry = stop_px = hw = 0.0

    pending_entry = None
    pending_exit = False
    cooldown_until = -1
    for i in range(len(df)):
        if not mask[i]:
            continue
        if np.isnan(stop[i]) or stop[i] <= 0:
            continue

        # Orders generated from the previous closed bar fill at this bar's open.
        if side is not None and pending_exit:
            exit_px = df["open"].iloc[i] * (1 - SLIP if side == "long" else 1 + SLIP)
            pnls.append((exit_px - entry) * qty if side == "long" else (entry - exit_px) * qty)
            side = None
            pending_exit = False
        if side is None and pending_entry is not None and i >= cooldown_until:
            wanted_side, stop_distance = pending_entry
            entry = df["open"].iloc[i] * (1 + SLIP if wanted_side == "long" else 1 - SLIP)
            q = RISK_DOLLARS / stop_distance
            qty = q if allow_fractional or wanted_side == "long" else float(int(q))
            if qty > 0:
                side = wanted_side
                stop_px = entry - stop_distance if side == "long" else entry + stop_distance
                hw = entry
            pending_entry = None

        # Manage an already-open position using this completed bar's range.
        if side is not None:
            if trail > 0 and a[i] > 0:
                if side == "long":
                    hw = max(hw, high[i]); stop_px = max(stop_px, hw - trail * a[i])
                else:
                    hw = min(hw, low[i]); stop_px = min(stop_px, hw + trail * a[i])
            hit = low[i] <= stop_px if side == "long" else high[i] >= stop_px
            if hit:
                exit_px = stop_px
                pnls.append((exit_px - entry) * qty if side == "long" else (entry - exit_px) * qty)
                side = None
                cooldown_until = i + 20  # one-minute default cooldown
                continue
            # strategy exit
            if (side == "long" and xl[i]) or (side == "short" and xs[i]):
                pending_exit = True
                continue

        # entries only when flat
        if side is None:
            if el[i]:
                pending_entry = ("long", stop[i])
            elif es_[i]:
                pending_entry = ("short", stop[i])
    return pnls


def _metrics(pnls: list[float]) -> dict:
    arr = np.array(pnls) if pnls else np.array([])
    wins = arr[arr > 0]; losses = arr[arr < 0]
    gl = -losses.sum()
    return {
        "trades": len(arr),
        "pnl": float(arr.sum()) if len(arr) else 0.0,
        "win_rate": (len(wins) / len(arr)) if len(arr) else 0.0,
        "pf": (wins.sum() / gl) if gl > 0 else (float("inf") if len(wins) else 0.0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Rolling walk-forward parameter study.")
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--train-months", type=int, default=4)
    parser.add_argument("--test-months", type=int, default=2)
    args = parser.parse_args()
    config.validate_credentials()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(
        days=(args.train_months + args.test_months * args.folds) * 31
    )
    split = now - timedelta(days=args.test_months * 31)
    print(
        f"Window: {window_start.date()} -> {now.date()} | "
        f"{args.folds} rolling folds ({args.train_months}m train/{args.test_months}m test)\n"
    )

    # ---- 1) Buy-and-hold benchmark ----
    print("=" * 72)
    print("1) BUY & HOLD BENCHMARK (return over full 6-month window)")
    print("=" * 72)
    data: dict[str, pd.DataFrame] = {}
    for inst in config.INSTRUMENTS:
        warmup = WARMUP_DAYS.get(inst.timeframe, 30)
        df = get_bars(inst.symbol, inst.asset_class, inst.timeframe, window_start - timedelta(days=warmup))
        if df.empty:
            print(f"  {inst.symbol}: no data"); continue
        data[inst.symbol] = df
        win = df[df.index >= window_start]
        if len(win) >= 2:
            r = win["close"].iloc[-1] / win["close"].iloc[0] - 1
            oos = df[df.index >= split]
            r_oos = oos["close"].iloc[-1] / oos["close"].iloc[0] - 1 if len(oos) >= 2 else float("nan")
            print(f"  {inst.symbol:<8} full: {r*100:+7.2f}%   last-2mo (OOS): {r_oos*100:+7.2f}%")

    # ---- 2) Rolling walk-forward ----
    print("\n" + "=" * 72)
    print("2) WALK-FORWARD  (tune on first 4mo IS, test on last 2mo OOS)")
    print("=" * 72)
    print(f"{'Symbol':<8}{'IS pnl':>13}{'rolling OOS pnl':>20}{'OOS trades':>12}")
    print("-" * 72)

    total_oos = 0.0
    folds = [
        (
            now - timedelta(days=(args.train_months + args.test_months * (fold + 1)) * 31),
            now - timedelta(days=args.test_months * (args.folds - fold - 1) * 31),
        )
        for fold in range(args.folds)
    ]
    for inst in config.INSTRUMENTS:
        if not inst.entry_enabled:
            continue
        if inst.symbol not in data:
            continue
        df = data[inst.symbol]
        idx = df.index
        # Score each candidate across rolling folds, selecting only from each
        # fold's earlier training data and reporting its later test result.
        allow_frac = inst.asset_class == "crypto"
        grid = GRIDS[inst.strategy]
        fold_results = []
        for train_start, test_start in folds:
            train_mask = np.asarray((idx >= train_start) & (idx < test_start))
            test_mask = np.asarray(
                (idx >= test_start) & (idx < test_start + timedelta(days=args.test_months * 31))
            )
            scored = [
                (
                    _metrics(simulate(df, inst.strategy, p, train_mask, allow_frac))["pnl"],
                    _metrics(simulate(df, inst.strategy, p, test_mask, allow_frac)),
                    p,
                )
                for p in grid
            ]
            fold_results.append(max(scored, key=lambda item: item[0]))
        is_pnl = sum(item[0] for item in fold_results)
        oos_m = {
            "pnl": sum(item[1]["pnl"] for item in fold_results),
            "trades": sum(item[1]["trades"] for item in fold_results),
        }
        total_oos += oos_m["pnl"]
        print(f"{inst.symbol:<8}{is_pnl:>13,.0f}{oos_m['pnl']:>20,.0f}{oos_m['trades']:>12}")

    print("-" * 72)
    print(f"{'TOTAL OOS pnl (IS-best configs)':<40}{total_oos:>15,.0f}")
    print("\nEach fold selects from its preceding training window only; negative")
    print("rolling OOS P&L is evidence the in-sample edge did not generalize.")


if __name__ == "__main__":
    main()
