"""Continuous live/paper trading loop.

Run from the project root with:

    python -m bot.main

The loop wakes every LOOP_INTERVAL_SECONDS. For each instrument it only acts
when a NEW candle of that instrument's timeframe has closed, then:
  1) fetches recent bars,
  2) checks the logical hard/trailing stop,
  3) asks the strategy for a signal,
  4) applies the correlation filter + ATR sizing,
  5) executes via the broker and logs the trade.

A portfolio drawdown breaker closes everything and halts if equity falls
MAX_PORTFOLIO_DRAWDOWN from its peak.
"""

from __future__ import annotations

import atexit
import logging
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import config
from . import risk_manager as rm
from .ai_signals import approve_entry
from .broker import Broker
from .data import get_bars
from .logger import log_daily_pnl
from .portfolio import Portfolio
from .signals import Action, Signal
from .strategies import get_strategy
from .trading_controls import cooldown_active, record_stop_cooldown

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bot")

# How many bars of history to pull each cycle. Must exceed the longest indicator
# window in use (currently the 750-bar trend MA on the 1-min mean-reversion names).
_HISTORY_BARS = 900

# Timeframe -> candle length, for "has a new candle closed?" and history window.
_TF_MINUTES = {"1Min": 1, "5Min": 5, "15Min": 15, "1Hour": 60, "4Hour": 240}

# Regular-hours minutes per equity trading day (used to translate an intraday bar
# count into a wall-clock lookback that survives overnight/weekend gaps).
_RTH_MINUTES_PER_DAY = 390


def _history_start(timeframe: str, asset_class: str = "equity") -> datetime:
    minutes = _TF_MINUTES[timeframe]
    if minutes < 60 and asset_class == "equity":
        # Intraday equity minute bars only exist during the ~6.5h session, so a
        # plain wall-clock span badly under-counts. Convert bars -> trading days,
        # then pad (x2 + 4 calendar days) to clear weekends/holidays.
        bars_per_day = _RTH_MINUTES_PER_DAY / minutes
        days = (_HISTORY_BARS / bars_per_day) * 2 + 4
        return datetime.now(timezone.utc) - timedelta(days=days)
    # Crypto (24/7) or hourly/daily bars: a padded wall-clock span is sufficient
    # since bars exist continuously.
    span = timedelta(minutes=minutes * _HISTORY_BARS * 2)
    return datetime.now(timezone.utc) - span


def _last_bar_time(df) -> datetime | None:
    return df.index[-1].to_pydatetime() if len(df) else None


def _sleep_until_next_minute(buffer_seconds: float) -> None:
    """Sleep until `buffer_seconds` past the next minute boundary.

    This lands each loop a few seconds after a candle closes, so the bot reacts
    to fresh candles with minimal lag instead of a random 0-60s offset.
    """
    now = datetime.now(timezone.utc)
    secs_into_minute = now.second + now.microsecond / 1e6
    sleep_for = (60 - secs_into_minute) + buffer_seconds
    time.sleep(max(sleep_for, 0.0))


def _benchmark_regime(frames: dict[str, object]) -> bool | None:
    """True only when both benchmark closes are above their trend averages."""
    try:
        from .indicators import sma

        positive = []
        for symbol in config.EQUITY_REGIME_SYMBOLS:
            frame = frames.get(symbol)
            if frame is None or len(frame) < config.EQUITY_REGIME_TREND_MA:
                return None
            trend = float(sma(frame["close"], config.EQUITY_REGIME_TREND_MA).iloc[-1])
            if not math.isfinite(trend):
                return None
            positive.append(float(frame["close"].iloc[-1]) >= trend)
        return all(positive)
    except (KeyError, TypeError, ValueError):
        return None


def process_instrument(
    inst, df, portfolio: Portfolio, broker: Broker, benchmarks_positive: bool | None
) -> None:
    price = float(df["close"].iloc[-1])
    high = float(df["high"].iloc[-1])
    low = float(df["low"].iloc[-1])

    position = portfolio.get(inst.symbol)
    if portfolio.has_pending_order(inst.symbol):
        log.info("%s: order pending; skipping new action", inst.symbol)
        return

    params = {**inst.params, "symbol": inst.symbol}

    if position is not None and (
        not math.isfinite(position.stop_price)
        or position.stop_price <= 0
        or not math.isfinite(position.entry_atr)
        or position.entry_atr <= 0
    ):
        recovery_signal = get_strategy(inst.strategy)(df, params, position)
        if recovery_signal.atr <= 0 or recovery_signal.stop_distance <= 0:
            log.error("%s: cannot safely restore position risk state", inst.symbol)
            return
        position.entry_atr = recovery_signal.atr
        if position.side == "long":
            position.stop_price = position.entry_price - recovery_signal.stop_distance
            position.high_water = max(position.entry_price, high)
        else:
            position.stop_price = position.entry_price + recovery_signal.stop_distance
            position.high_water = min(position.entry_price, low)
        portfolio.persist_state()

    # 1) Stop management first (protective).
    if position is not None:
        # Always track the best (most favorable) price since entry so the
        # profit-lock exit has a high-water mark to measure pullbacks against.
        if position.side == "long":
            position.high_water = max(position.high_water, high)
        else:
            position.high_water = min(position.high_water, low)
        trail_mult = float(inst.params.get("trail_atr_mult", 0.0))
        if trail_mult > 0 and position.entry_atr > 0:
            rm.update_trailing_stop(position, high, low, position.entry_atr, trail_mult)
        portfolio.persist_state()
        if rm.stop_hit(position, high, low):
            log.info("%s: STOP HIT at ~%.2f", inst.symbol, position.stop_price)
            if portfolio.close(inst.symbol, position.stop_price, "hard/trailing stop"):
                record_stop_cooldown(
                    inst.symbol,
                    int(inst.params.get("stop_cooldown_minutes", 0)),
                )
            return

    # 2) Strategy signal.
    signal: Signal = get_strategy(inst.strategy)(df, params, position)

    if signal.action == Action.HOLD:
        return

    if signal.action == Action.EXIT:
        portfolio.close(inst.symbol, price, signal.reason)
        return

    # 3) Entry: only when flat (strategies return EXIT before flipping).
    if position is not None:
        return

    if not inst.entry_enabled:
        log.info("%s: entry disabled; retaining exit-only management", inst.symbol)
        return
    if cooldown_active(inst.symbol):
        log.info("%s: blocked by post-stop cooldown", inst.symbol)
        return

    # Some accounts/asset classes can't take the short side (cash accounts have
    # no margin; Alpaca crypto is spot/long-only everywhere) — skip cleanly
    # instead of letting the order get rejected downstream.
    if signal.action == Action.SHORT and not broker.can_short(inst.asset_class):
        log.info("%s: short blocked (shorting unavailable for this account/asset)", inst.symbol)
        return

    # 4) AI confirmation may only veto this existing strategy entry. It never
    # affects exits, stops, quantities, or the deterministic controls below.
    ai_decision = approve_entry(inst, df, signal)
    if not ai_decision.approved:
        log.info("%s: AI entry gate blocked (%s)", inst.symbol, ai_decision.reason)
        return

    # 5) Correlation filter.
    if not rm.passes_correlation_filter(signal, portfolio.positions):
        log.info("%s: blocked by correlation filter", inst.symbol)
        return

    # 6) Size and execute.
    regime_multiplier = rm.entry_regime_multiplier(
        inst.asset_class, signal.action, benchmarks_positive
    )
    if regime_multiplier <= 0:
        log.info("%s: blocked by benchmark regime", inst.symbol)
        return
    equity = portfolio.equity()
    # Crypto is always fractional; equity LONGs can use fractional shares too
    # (Alpaca requires whole shares for shorts, but all our tickers here support
    # fractional buys) — this matters most on small accounts where a single
    # share of a $500+ stock would otherwise blow past the position size cap.
    allow_fractional = inst.asset_class == "crypto" or signal.action == Action.LONG
    proposed_qty = (
        rm.position_size(equity, signal, allow_fractional) * regime_multiplier
    )
    current_gross = portfolio.gross_notional()
    gross_capacity = max(
        equity * config.MAX_GROSS_EXPOSURE_PCT - current_gross,
        0.0,
    )
    available_notional = gross_capacity
    if inst.asset_class == "crypto":
        crypto_buying_power = broker.non_marginable_buying_power()
        available_notional = min(
            available_notional,
            crypto_buying_power * (1.0 - config.CRYPTO_BUYING_POWER_BUFFER_PCT),
        )
    qty = rm.cap_size_to_available_notional(
        proposed_qty,
        signal.price,
        available_notional,
        allow_fractional,
    )
    if qty <= 0:
        log.info("%s: computed qty 0 (stop_dist=%.4f)", inst.symbol, signal.stop_distance)
        return

    log.info("%s: %s qty=%s @ ~%.2f (%s)", inst.symbol, signal.action.value, qty, price, signal.reason)
    portfolio.open(signal, qty, allow_fractional)


_HEARTBEAT_FILE = os.path.join("logs", "heartbeat.txt")


def _write_heartbeat() -> None:
    """Touch a timestamp file every loop pass so an external watchdog can tell
    a genuine freeze (process alive but stuck on a blocking call) apart from
    a quiet market with nothing to trade."""
    try:
        os.makedirs("logs", exist_ok=True)
        with open(_HEARTBEAT_FILE, "w") as f:
            f.write(datetime.now(timezone.utc).isoformat())
    except OSError:
        pass


_LOCK_FILE = "bot.lock"


def _pid_alive(pid: int) -> bool:
    """Cross-platform check whether a PID is running.

    NOTE: on Windows, os.kill(pid, 0) actually TERMINATES the process, so we must
    use OpenProcess/GetExitCodeProcess instead of the Unix signal-0 trick.
    """
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k = ctypes.windll.kernel32
        handle = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        k.GetExitCodeProcess(handle, ctypes.byref(code))
        k.CloseHandle(handle)
        return code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned by another user
    return True


def _acquire_lock() -> None:
    """Refuse to start if another instance is already running (prevents double orders)."""
    if os.path.exists(_LOCK_FILE):
        try:
            with open(_LOCK_FILE) as f:
                other = int(f.read().strip())
        except (ValueError, OSError):
            other = None
        if other is not None and _pid_alive(other):
            log.error("Another bot instance is already running (pid %s). Exiting.", other)
            sys.exit(1)
    with open(_LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    atexit.register(lambda: os.path.exists(_LOCK_FILE) and os.remove(_LOCK_FILE))


def run() -> None:
    config.validate_credentials()
    _acquire_lock()
    broker = Broker()
    portfolio = Portfolio(broker)

    start_equity = portfolio.equity()
    guard = rm.DrawdownGuard(start_equity)
    log.info(
        "Started in %s mode. Equity=$%.2f. Instruments: %s",
        "PAPER" if broker.is_paper else "LIVE",
        start_equity,
        ", ".join(i.symbol for i in config.INSTRUMENTS),
    )

    # Track the last processed candle time per symbol to avoid acting twice per bar.
    last_seen: dict[str, datetime | None] = {i.symbol: None for i in config.INSTRUMENTS}
    day_start_equity = start_equity
    current_day = datetime.now(timezone.utc).date()

    while True:
        try:
            _write_heartbeat()
            portfolio.reconcile()
            equity = portfolio.equity()

            # Drawdown circuit breaker.
            if guard.check(equity):
                log.error(
                    "DRAWDOWN BREAKER TRIPPED (%.1f%% from peak $%.2f). Closing all, halting.",
                    guard.drawdown(equity) * 100,
                    guard.peak,
                )
                broker.close_all()
                portfolio.positions.clear()
                # Exit code 42 signals "halted by breaker" so the run wrapper
                # knows NOT to auto-restart (halt until manual review).
                sys.exit(42)

            # Daily P&L rollover.
            today = datetime.now(timezone.utc).date()
            if today != current_day:
                daily_pnl = equity - day_start_equity
                pct = daily_pnl / day_start_equity if day_start_equity else 0.0
                log_daily_pnl(equity, daily_pnl, pct)
                current_day = today
                day_start_equity = equity

            equity_open = broker.is_equity_market_open()
            benchmark_frames = {}
            for benchmark in config.EQUITY_REGIME_SYMBOLS:
                benchmark_inst = config.INSTRUMENTS_BY_SYMBOL[benchmark]
                try:
                    benchmark_df = get_bars(
                        benchmark,
                        benchmark_inst.asset_class,
                        benchmark_inst.timeframe,
                        _history_start(
                            benchmark_inst.timeframe, benchmark_inst.asset_class
                        ),
                    )
                    duration = timedelta(
                        minutes=_TF_MINUTES[benchmark_inst.timeframe]
                    )
                    benchmark_df = benchmark_df[
                        benchmark_df.index + duration <= datetime.now(timezone.utc)
                    ]
                    if not benchmark_df.empty:
                        benchmark_frames[benchmark] = benchmark_df
                except Exception as e:  # noqa: BLE001
                    log.warning("%s: benchmark data fetch failed: %s", benchmark, e)
            benchmarks_positive = _benchmark_regime(benchmark_frames)

            for inst in config.INSTRUMENTS:
                # Equities only trade during market hours; crypto is 24/7.
                if inst.asset_class == "equity" and not equity_open:
                    continue

                try:
                    df = get_bars(
                        inst.symbol, inst.asset_class, inst.timeframe,
                        _history_start(inst.timeframe, inst.asset_class),
                    )
                except Exception as e:  # noqa: BLE001
                    log.warning("%s: data fetch failed: %s", inst.symbol, e)
                    continue

                if df.empty:
                    log.warning("%s: no data returned", inst.symbol)
                    continue

                observed_at = datetime.now(timezone.utc)
                bar_duration = timedelta(minutes=_TF_MINUTES[inst.timeframe])
                df = df[df.index + bar_duration <= observed_at]
                if df.empty:
                    log.warning("%s: no closed data returned", inst.symbol)
                    continue

                # Only act once per closed candle.
                lbt = _last_bar_time(df)
                if lbt is not None and last_seen[inst.symbol] == lbt:
                    continue
                last_seen[inst.symbol] = lbt

                try:
                    process_instrument(
                        inst, df, portfolio, broker, benchmarks_positive
                    )
                except Exception as e:  # noqa: BLE001
                    # Don't let one bad order/position mismatch abort the scan
                    # for every remaining instrument this pass.
                    log.exception("%s: process_instrument failed: %s", inst.symbol, e)

        except KeyboardInterrupt:
            log.info("Interrupted by user. Positions left OPEN (close manually if desired).")
            break
        except Exception as e:  # noqa: BLE001 - keep the loop alive through API hiccups
            log.exception("Loop error (continuing): %s", e)

        if getattr(config, "ALIGN_TO_CANDLE_CLOSE", False):
            _sleep_until_next_minute(config.CANDLE_CLOSE_BUFFER_SECONDS)
        else:
            time.sleep(config.LOOP_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()
