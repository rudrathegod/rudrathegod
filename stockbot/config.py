"""Central configuration for the trading bot.

All strategy parameters, instrument mappings, and risk limits live here so the
live bot and the backtester read from a single source of truth.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Credentials / environment
# ---------------------------------------------------------------------------
# Accept both this project's names and Alpaca's canonical env vars
# (APCA_API_KEY_ID / APCA_API_SECRET_KEY / APCA_API_BASE_URL) so that following
# either Alpaca's docs or this README works out of the box.
def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


ALPACA_API_KEY = _env("ALPACA_API_KEY", "APCA_API_KEY_ID")
ALPACA_SECRET_KEY = _env("ALPACA_SECRET_KEY", "APCA_API_SECRET_KEY")
ALPACA_BASE_URL = _env(
    "ALPACA_BASE_URL", "APCA_API_BASE_URL", default="https://paper-api.alpaca.markets"
)
ALLOW_LIVE = os.getenv("ALLOW_LIVE", "false").strip().lower() == "true"

IS_PAPER = "paper-api.alpaca.markets" in ALPACA_BASE_URL

# Optional Telegram delivery for daily briefings.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Stock market-data feed. Free Alpaca accounts must use "iex"; the default "sip"
# feed rejects recent data with a subscription error. Upgrade to "sip" only if
# your account has the paid data subscription.
ALPACA_DATA_FEED = os.getenv("ALPACA_DATA_FEED", "iex").strip().lower()

# Dual-provider AI entry filter. "paper_mock" exercises the exact approval path
# without network calls or pretending to have model-generated advice. Switch to
# "providers" only after supplying both API keys; any provider failure denies
# the entry. "disabled" bypasses this optional filter entirely.
AI_SIGNAL_MODE = os.getenv("AI_SIGNAL_MODE", "paper_mock").strip().lower()
AI_SIGNAL_ALLOWED_MODES = frozenset({"disabled", "paper_mock", "providers"})
AI_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
AI_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
AI_ANTHROPIC_MODEL = os.getenv(
    "AI_ANTHROPIC_MODEL", "claude-sonnet-4-20250514"
).strip()
AI_OPENAI_MODEL = os.getenv("AI_OPENAI_MODEL", "gpt-4.1-mini").strip()
AI_SIGNAL_TIMEOUT_SECONDS = float(os.getenv("AI_SIGNAL_TIMEOUT_SECONDS", "5"))
# 0 means unlimited. This is intentional only because the operator explicitly
# selected no application-level daily request limit.
AI_SIGNAL_DAILY_DECISION_LIMIT = int(os.getenv("AI_SIGNAL_DAILY_DECISION_LIMIT", "0"))

# ---------------------------------------------------------------------------
# Global risk limits (non-negotiable)
# ---------------------------------------------------------------------------
# AGGRESSIVE MODE: sizing knobs turned up on purpose (2x-3x normal) for more
# eventful paper trading. MAX_PORTFOLIO_DRAWDOWN stays untouched as the hard
# safety net regardless of how aggressive the per-trade sizing gets.
RISK_PER_TRADE = 0.02          # 2% of equity risked per trade (was 1%)
MAX_PORTFOLIO_DRAWDOWN = 0.10  # close everything and halt if equity falls 10% from peak
ATR_PERIOD = 14                # ATR lookback used for position sizing
SLIPPAGE_PCT = 0.0005          # 0.05% modeled slippage per fill (used in backtest)
EQUITY_SPREAD_BPS = 2.0
CRYPTO_SPREAD_BPS = 10.0
CRYPTO_TAKER_FEE_PCT = 0.0025
# Aggregate gross exposure is capped independently of each position's cap. Without
# this, 33 individually-valid 20% positions can consume several times account equity.
MAX_GROSS_EXPOSURE_PCT = 0.80
# Reserve room for crypto fees and adverse movement between sizing and a market fill.
CRYPTO_BUYING_POWER_BUFFER_PCT = 0.02
# Market orders normally fill quickly, but state must not be committed until Alpaca
# reports a terminal result.
ORDER_FILL_TIMEOUT_SECONDS = 15.0
# Cap any single position's notional at this fraction of equity. Critical on
# short (e.g. 1-min) timeframes where ATR is tiny: risk-based sizing would
# otherwise demand a gigantic share count and blow past buying power.
MAX_POSITION_NOTIONAL_PCT = 0.20  # was 0.10
# Also floor the stop distance at this fraction of price so 1-min noise-level
# ATR can't produce absurd size (keeps the 1%-risk math sane).
MIN_STOP_DISTANCE_PCT = 0.004  # 0.4% of price
# Shorts (and any other non-fractional order) must use whole shares. On a small
# account, MAX_POSITION_NOTIONAL_PCT alone can floor a $500+ stock to 0 shares,
# silently skipping every short signal on that name forever. As a bounded
# fallback, round a would-be-zero order UP to exactly 1 share if that single
# share still fits within this wider ceiling — never more than 1 share, and
# never above this % of equity in a single position.
ROUND_UP_TO_ONE_SHARE_MAX_NOTIONAL_PCT = 0.30  # was 0.20

# ---------------------------------------------------------------------------
# Strategy / instrument definitions
# ---------------------------------------------------------------------------
# Alpaca uses "BTC/USD" for crypto symbols and plain tickers for equities/ETFs.


@dataclass(frozen=True)
class InstrumentConfig:
    symbol: str
    asset_class: str          # "equity" or "crypto"
    strategy: str             # "mean_reversion" | "momentum_breakout" | "trend_following"
    timeframe: str            # human-readable, mapped to Alpaca TimeFrame in broker/data
    params: dict = field(default_factory=dict)
    entry_enabled: bool = True


INSTRUMENTS: list[InstrumentConfig] = [
    InstrumentConfig(
        symbol="SPY",
        asset_class="equity",
        strategy="mean_reversion",
        timeframe="1Min",
        # OPTIMIZED: only fade WITH the higher-timeframe trend (buy dips in an
        # uptrend / short rips in a downtrend) via trend_ma, and use a wider ATR
        # stop so normal noise doesn't stop us out before price reverts to mean.
        params={
            # 1-min bars: counts rescaled to keep the SAME time window as the old
            # 15-min setup (lookback 300min = 5h mean, trend_ma 750min = 12.5h trend).
            # Use only statistically larger deviations; 0.8σ entries generated
            # excessive churn on one-minute bars.
            # profit_lock_atr_mult widened 0.5->1.2 (let winners develop further
            # before banking, instead of bailing on the first tiny pullback).
            "lookback": 300,
            "entry_std": 1.3,
            "stop_atr_mult": 2.5,
            "trend_ma": 750,
            "profit_lock_atr_mult": 1.2,
            "stop_cooldown_minutes": 20,
        },
    ),
    InstrumentConfig(
        symbol="QQQ",
        asset_class="equity",
        strategy="mean_reversion",
        timeframe="1Min",
        params={
            "lookback": 300,
            "entry_std": 1.3,
            "stop_atr_mult": 2.5,
            "trend_ma": 750,
            "profit_lock_atr_mult": 1.2,
            "stop_cooldown_minutes": 20,
        },
    ),
    InstrumentConfig(
        symbol="GLD",
        asset_class="equity",
        strategy="trend_following",
        timeframe="4Hour",
        # OPTIMIZED: 20/50 EMA instead of 50/200. A 50/200 cross on 4h bars is far
        # too rare to fire within 6 months, so the original never traded. Faster
        # EMAs actually catch commodity trends (e.g. gold's uptrend).
        params={"fast_ema": 20, "slow_ema": 50, "trail_atr_mult": 3.0},
        entry_enabled=False,
    ),
    InstrumentConfig(
        symbol="USO",
        asset_class="equity",
        strategy="trend_following",
        timeframe="4Hour",
        params={"fast_ema": 20, "slow_ema": 50, "trail_atr_mult": 3.0},
        entry_enabled=False,
    ),
]

# ---------------------------------------------------------------------------
# Large-cap equity scan universe (same 1-min mean-reversion setup as SPY/QQQ).
# ---------------------------------------------------------------------------
# Add or remove tickers here to change what the bot scans. These are the most
# liquid mega-caps (tech-heavy) so IEX fills and data are reliable. All use the
# identical rescaled 1-min params: buy ~1.5-std dips WITH the ~12.5h trend, exit
# on reversion to the ~5h mean.
# The core entry universe is deliberately small and very liquid. Non-core
# instruments remain configured below only as exit-only positions so a held
# legacy position is never orphaned by a strategy rollout.
MEAN_REVERSION_UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMD"]
LEGACY_EXIT_ONLY_UNIVERSE = [
    "GOOGL", "AMZN", "META", "TSLA", "AVGO", "NFLX", "UNH", "JPM", "COST",
    "CRM", "ORCL", "MU", "INTC", "MRVL", "DDOG", "PANW", "CRWD", "AMAT",
    "LRCX", "TXN", "CSCO",
]

_MR_1MIN_PARAMS = {
    "lookback": 300,
    "entry_std": 1.3,
    "stop_atr_mult": 2.5,
    "trend_ma": 750,
    "profit_lock_atr_mult": 1.2,
    "stop_cooldown_minutes": 20,
}

INSTRUMENTS += [
    InstrumentConfig(
        symbol=_sym,
        asset_class="equity",
        strategy="mean_reversion",
        timeframe="1Min",
        params=dict(_MR_1MIN_PARAMS),
    )
    for _sym in MEAN_REVERSION_UNIVERSE
]

INSTRUMENTS += [
    InstrumentConfig(
        symbol=_sym,
        asset_class="equity",
        strategy="mean_reversion",
        timeframe="1Min",
        params=dict(_MR_1MIN_PARAMS),
        entry_enabled=False,
    )
    for _sym in LEGACY_EXIT_ONLY_UNIVERSE
]

# Crypto is enabled for paper-trading entries. Alpaca crypto is spot-only, so
# the existing shortability check continues to block crypto shorts.
CRYPTO_MEAN_REVERSION_UNIVERSE = [
    "BTC/USD",   # Bitcoin
    "AAVE/USD",  # Aave
    "SOL/USD",   # Solana
    "UNI/USD",   # Uniswap
]

INSTRUMENTS += [
    InstrumentConfig(
        symbol=_sym,
        asset_class="crypto",
        strategy="mean_reversion",
        timeframe="1Min",
        params=dict(_MR_1MIN_PARAMS),
    )
    for _sym in CRYPTO_MEAN_REVERSION_UNIVERSE
]

# Convenience lookup by symbol.
INSTRUMENTS_BY_SYMBOL = {i.symbol: i for i in INSTRUMENTS}

# ---------------------------------------------------------------------------
# Correlation filter groups
# ---------------------------------------------------------------------------
# If every symbol in a group's "trigger" set is already long, block new longs
# on the symbols in "block".
CORRELATION_FILTER = {}
EQUITY_REGIME_SYMBOLS = ("SPY", "QQQ")
EQUITY_REGIME_TREND_MA = 750
RISK_ON_SHORT_SIZE_MULT = 0.0  # block new equity shorts while both benchmarks trend up
STOP_COOLDOWN_STATE_FILE = "stop_cooldowns.json"
EXPECTANCY_MIN_CLOSED_TRADES = 30
EXPECTANCY_WINDOW_TRADES = 50
EXPECTANCY_DISABLE_BELOW_R = 0.0
CLOSED_TRADES_CSV = "closed_trades.csv"

# ---------------------------------------------------------------------------
# Loop cadence
# ---------------------------------------------------------------------------
# How often the main loop wakes up (seconds). Each strategy only acts when a new
# candle of its timeframe has closed, tracked in main.py. Used only when
# ALIGN_TO_CANDLE_CLOSE is False.
LOOP_INTERVAL_SECONDS = 60

# Instead of a fixed sleep at a random phase, wake a few seconds AFTER each minute
# boundary so we act on a freshly-closed candle within ~CANDLE_CLOSE_BUFFER_SECONDS
# (vs up to 60s of lag). All timeframes (1Min/1Hour/4Hour) close on minute
# boundaries, so minute alignment covers them all. No extra API load.
ALIGN_TO_CANDLE_CLOSE = True
CANDLE_CLOSE_BUFFER_SECONDS = 3  # let Alpaca finish aggregating the just-closed bar

# File outputs
TRADES_CSV = "trades.csv"
DAILY_PNL_CSV = "daily_pnl.csv"
BACKTEST_CHART = "backtest_results.png"
POSITION_STATE_FILE = "position_state.json"
DRAWDOWN_STATE_FILE = "drawdown_state.json"
AI_DECISIONS_JSONL = "ai_decisions.jsonl"


def validate_credentials() -> None:
    """Raise a clear error if keys are missing or live trading is unsafely enabled."""
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        raise RuntimeError(
            "Missing ALPACA_API_KEY / ALPACA_SECRET_KEY. "
            "Copy .env.example to .env and fill in your keys."
        )
    if not IS_PAPER and not ALLOW_LIVE:
        raise RuntimeError(
            "LIVE endpoint detected but ALLOW_LIVE is not 'true'. Refusing to trade "
            "real money. Set ALLOW_LIVE=true in .env only after successful paper trading."
        )
    if AI_SIGNAL_MODE not in AI_SIGNAL_ALLOWED_MODES:
        raise RuntimeError(
            f"AI_SIGNAL_MODE must be one of {sorted(AI_SIGNAL_ALLOWED_MODES)}, "
            f"got {AI_SIGNAL_MODE!r}."
        )
    if AI_SIGNAL_MODE == "providers" and (
        not AI_ANTHROPIC_API_KEY or not AI_OPENAI_API_KEY
    ):
        raise RuntimeError(
            "AI_SIGNAL_MODE=providers requires ANTHROPIC_API_KEY and OPENAI_API_KEY."
        )
