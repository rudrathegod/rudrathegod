# Multi-Strategy Alpaca Trading Bot

A Python bot that trades **5 instruments simultaneously**, each with a strategy
matched to how that market behaves, plus centralized ATR-based risk management.
It runs 24/7, logs every trade to CSV, and can emit morning/evening briefings.

> **This is educational software, not financial advice.** Trading involves real
> risk of loss. Most retail traders lose money. Paper trade for weeks and start
> with money you can afford to lose entirely. See [Disclaimers](#disclaimers).

---

## Strategies

| Instrument | Class  | Strategy          | Timeframe | Key params |
|------------|--------|-------------------|-----------|------------|
| SPY        | equity | Mean reversion    | 15 min    | 20-SMA, ±1.5σ |
| QQQ        | equity | Mean reversion    | 15 min    | 20-SMA, ±1.8σ |
| BTC/USD    | crypto | Momentum breakout | 1 hour    | 20-hi/lo, 1.5× vol, 2×ATR trail |
| GLD        | equity | Trend following   | 4 hour    | 50/200 EMA, 3×ATR trail |
| USO        | equity | Trend following   | 4 hour    | 50/200 EMA, 3×ATR trail |

## Risk rules (enforced in `bot/risk_manager.py`)

- **1% risk per trade** — position size is derived from the stop distance so a
  1×ATR (mean reversion) / trailing-ATR (momentum & trend) move against you
  equals exactly 1% of equity. Volatile instruments get smaller positions.
- **Hard stops, never widened** — trailing stops only ratchet in your favor.
- **Correlation filter** — if SPY *and* QQQ are both long, new BTC/USD longs are blocked.
- **Drawdown circuit breaker** — if equity falls 10% from its peak, the bot
  closes everything and halts until you restart it manually.

---

## Setup

Requires **Python 3.10+**.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # then edit .env with your Alpaca keys
```

Get free **paper trading** keys at <https://app.alpaca.markets> → "Paper Trading".
`.env` defaults to the paper endpoint and refuses live trading unless you
explicitly set `ALLOW_LIVE=true`.

> ⚠️ The guide's `alpaca-trade-api` package is deprecated. This project uses
> Alpaca's current SDK, `alpaca-py`.
>
> ⚠️ Free Alpaca accounts must use the **IEX** stock data feed (`ALPACA_DATA_FEED=iex`,
> the default). The paid `sip` feed rejects recent data with a subscription error,
> which would make the equity strategies (SPY/QQQ/GLD/USO) silently return no data.

---

## 1. Backtest first

```bash
python -m bot.backtest                 # 6 months, $100k (matches paper default)
python -m bot.backtest --months 12 --equity 25000
```

> Alpaca paper accounts start at **$100k** by default (resettable in the paper
> dashboard). The backtest defaults to $100k to match; the live/paper bot always
> sizes from your account's *actual* equity.

Prints per-instrument stats (trades, win rate, avg win/loss, profit factor),
combined portfolio return / max drawdown / Sharpe, and saves
`backtest_results.png`. **Adjust parameters in `config.py` if any strategy shows
a negative Sharpe or portfolio max drawdown > 15%.**

## 2. Paper trade (minimum 2 weeks)

With paper keys in `.env`:

```bash
python -m bot.main
```

Watch `trades.csv` and `daily_pnl.csv`. Confirm entries/exits, position sizing
scaling with volatility, stops triggering, and the correlation filter working
before risking anything.

## 3. Daily briefings

```bash
python -m bot.briefing morning
python -m bot.briefing evening
```

These print the summary and, if `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` are set
in `.env`, **send it to Telegram** automatically. (Create a bot with
[@BotFather](https://t.me/BotFather); get your chat id from `@userinfobot`.)
You can also point Claude Cowork at these commands to format/deliver them.

Schedule them at 7am + 9pm via cron, or via the included PM2 config (below):

```cron
0 7 * * *  cd /path/to/bigballing && .venv/bin/python -m bot.briefing morning
0 21 * * * cd /path/to/bigballing && .venv/bin/python -m bot.briefing evening
```

## 4. Go live (only after successful paper trading)

In `.env`, switch to live keys and endpoint, then **explicitly** unlock it:

```env
ALPACA_BASE_URL=https://api.alpaca.markets
ALLOW_LIVE=true
```

Run on a 24/7 VPS with a process manager so it restarts on crash. Three options:

**PM2** (recommended, also schedules the briefings) — see `ecosystem.config.js`:

```bash
npm install -g pm2
pm2 start ecosystem.config.js
pm2 save && pm2 startup      # survive reboots
pm2 logs trading-bot
```

**Docker** — see `Dockerfile`:

```bash
docker build -t trading-bot .
docker run -d --restart unless-stopped --name trading-bot \
  --env-file .env -v "$PWD":/app trading-bot
```

**systemd**:

```ini
[Unit]
Description=Trading bot
After=network-online.target

[Service]
WorkingDirectory=/path/to/bigballing
ExecStart=/path/to/bigballing/.venv/bin/python -m bot.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## Project structure

```
config.py                 # all params, instruments, risk limits, safety lock
.env.example              # credentials template
bot/
  indicators.py           # SMA/EMA/ATR/std/rolling hi-lo
  signals.py              # Signal / Position / Action types
  strategies/
    mean_reversion.py     # SPY, QQQ
    momentum_breakout.py  # BTC/USD
    trend_following.py    # GLD, USO
  risk_manager.py         # sizing, stops, correlation filter, drawdown guard
  data.py                 # Alpaca historical bars -> DataFrames
  broker.py               # Alpaca TradingClient wrapper (paper/live lock)
  portfolio.py            # open/close positions, stop tracking, logging
  logger.py               # trades.csv + daily_pnl.csv
  main.py                 # continuous live/paper loop
  backtest.py             # event-driven backtest + metrics + chart
  briefing.py             # morning/evening summaries (+ Telegram delivery)
ecosystem.config.js       # PM2: run bot 24/7 + cron the briefings
Dockerfile                # containerized 24/7 deployment
```

---

## Disclaimers

Educational only; **not financial advice**. The strategies are simplified
examples, not a substitute for professional quantitative research. Past
performance (including backtests) does not guarantee future results. Any income
figures cited in videos/guides are not typical. Never trade money you cannot
afford to lose, never use borrowed money, and never remove your stops.
