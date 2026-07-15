"""Generate morning/evening briefing text from the logs + live account.

This produces the raw data + a plain-text summary. Point Claude Cowork (or any
scheduler) at it to format/send to Telegram/Slack, or wire in a webhook below.

    python -m bot.briefing morning
    python -m bot.briefing evening
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

import pandas as pd

import config
from .broker import Broker
from .performance import expectancy_frame


def _load_csv(path: str) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def _recent_win_rate(trades: pd.DataFrame, days: int = 7) -> float | None:
    if trades.empty or "profit_loss" not in trades:
        return None
    closed = trades.dropna(subset=["profit_loss"])
    closed = closed[closed["profit_loss"] != ""]
    if closed.empty:
        return None
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
    closed = closed.copy()
    closed["timestamp"] = pd.to_datetime(closed["timestamp"], utc=True, errors="coerce")
    recent = closed[closed["timestamp"] >= cutoff]
    if recent.empty:
        return None
    pnl = pd.to_numeric(recent["profit_loss"], errors="coerce").dropna()
    if pnl.empty:
        return None
    return float((pnl > 0).mean())


def morning() -> str:
    broker = Broker()
    positions = broker.open_positions()
    equity = broker.equity()
    trades = _load_csv(config.TRADES_CSV)
    pnl_df = _load_csv(config.DAILY_PNL_CSV)

    lines = [f"MORNING BRIEFING — {datetime.now(timezone.utc):%Y-%m-%d}"]
    lines.append(f"Equity: ${equity:,.2f}")

    if positions:
        lines.append("Open positions:")
        for sym, p in positions.items():
            lines.append(f"  {sym} {p.side} qty {p.qty:g} @ {p.entry_price:.2f}")
    else:
        lines.append("Open positions: none")

    if not pnl_df.empty:
        last = pnl_df.iloc[-1]
        lines.append(f"Yesterday P&L: ${float(last['daily_pnl']):+,.2f} ({float(last['daily_pnl_pct'])*100:+.2f}%)")

    wr = _recent_win_rate(trades, 7)
    if wr is not None:
        lines.append(f"7-day win rate: {wr*100:.0f}%")

    expectancy = expectancy_frame()
    if not expectancy.empty:
        lines.append("Fill-based expectancy (research only):")
        for symbol, stat in expectancy.iterrows():
            progress = f"{int(stat['closed_trades'])}/{config.EXPECTANCY_MIN_CLOSED_TRADES}"
            candidate = " manual-disable candidate" if stat["manual_disable_candidate"] else ""
            lines.append(
                f"  {symbol}: {stat['expectancy_r']:+.2f}R "
                f"({progress}, window {int(stat['window_trades'])}){candidate}"
            )

    return "\n".join(lines)


def evening() -> str:
    broker = Broker()
    equity = broker.equity()
    trades = _load_csv(config.TRADES_CSV)
    pnl_df = _load_csv(config.DAILY_PNL_CSV)

    today = datetime.now(timezone.utc).date().isoformat()
    lines = [f"EVENING REPORT — {today}"]
    lines.append(f"Current equity: ${equity:,.2f}")

    if not trades.empty:
        t = trades.copy()
        t["timestamp"] = pd.to_datetime(t["timestamp"], utc=True, errors="coerce")
        today_trades = t[t["timestamp"].dt.date.astype(str) == today]
        lines.append(f"Trades today: {len(today_trades)}")
        closed = today_trades.copy()
        closed["profit_loss"] = pd.to_numeric(closed["profit_loss"], errors="coerce")
        closed = closed.dropna(subset=["profit_loss"])
        if not closed.empty:
            best = closed.loc[closed["profit_loss"].idxmax()]
            worst = closed.loc[closed["profit_loss"].idxmin()]
            lines.append(f"Best: {best['instrument']} ${float(best['profit_loss']):+,.2f}")
            lines.append(f"Worst: {worst['instrument']} ${float(worst['profit_loss']):+,.2f}")

    if not pnl_df.empty and pnl_df.iloc[-1]["date"] == today:
        last = pnl_df.iloc[-1]
        lines.append(f"Today P&L: ${float(last['daily_pnl']):+,.2f} ({float(last['daily_pnl_pct'])*100:+.2f}%)")

    expectancy = expectancy_frame()
    if not expectancy.empty:
        candidates = expectancy[expectancy["manual_disable_candidate"]]
        lines.append("Fill-based expectancy: research-only; no automatic entry gate.")
        for symbol, stat in expectancy.iterrows():
            lines.append(
                f"  {symbol}: {stat['expectancy_r']:+.2f}R over "
                f"{int(stat['window_trades'])} closed fill-paired trades"
            )
        if not candidates.empty:
            lines.append(
                "Manual-disable candidates: " + ", ".join(candidates.index.tolist())
            )

    return "\n".join(lines)


def send_telegram(text: str) -> bool:
    """Send `text` to Telegram if credentials are configured. Returns True on success."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False
    import requests

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text},
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"(Telegram send failed: {e})")
        return False


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "morning"
    text = morning() if which == "morning" else evening()
    print(text)
    if send_telegram(text):
        print("\n(sent to Telegram)")


if __name__ == "__main__":
    main()
