# 🚀 Bybit Scalper — BSB/USDT

High-frequency scalping bot for Bybit Spot trading.

## Strategy

| Component | Description |
|-----------|-------------|
| **Spread Capture** | Enter when bid-ask spread > 0.1% |
| **Momentum Filter** | Trade with short-term trend (5-candle momentum) |
| **Order Flow** | Detect buying/selling pressure from order book |
| **Volatility Filter** | Avoid dead markets, size down in high vol |
| **Quick TP/SL** | 0.8% take profit, 0.5% stop loss |
| **Trailing Stop** | 0.3% trailing after profit |
| **Breakeven** | Move SL to entry after 0.4% profit |
| **Time Exit** | Close after 5 minutes max |

## Project Structure

```
bybit-scalper/
├── config/
│   ├── .env           # Your credentials (DO NOT commit)
│   ├── .env.example   # Template
│   └── settings.json  # App metadata
├── src/
│   ├── __init__.py
│   ├── main.py        # Entry point + main loop
│   ├── bybit_client.py   # REST + WebSocket API
│   ├── strategy.py    # Scalping strategy engine
│   ├── risk.py        # Risk management
│   ├── notifier.py    # Telegram alerts
│   └── config.py      # Config loader
├── logs/
│   └── scalper.log
├── requirements.txt
└── README.md
```

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

```bash
cp config/.env.example config/.env
# Edit config/.env with your Bybit API keys
```

### 3. Get Bybit API Keys

1. Go to [Bybit API Management](https://www.bybit.com/app/user/api-management)
2. Create new API key
3. Enable **Spot Trading** permission
4. Add your server IP to whitelist
5. Copy key + secret to `.env`

### 4. Run (Dry Run First!)

```bash
# Dry run — no real orders
python -m src.main

# Live trading — REAL MONEY
python -m src.main --live
```

### 5. Customize

```bash
# Trade different pair
python -m src.main --symbol ETHUSDT

# Custom config path
python -m src.main --config /path/to/.env
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `BYBIT_API_KEY` | — | Your Bybit API key |
| `BYBIT_API_SECRET` | — | Your Bybit API secret |
| `SYMBOL` | BSBUSDT | Trading pair |
| `SPREAD_THRESHOLD` | 0.001 | Min spread to enter (0.1%) |
| `TAKE_PROFIT_PCT` | 0.008 | Take profit (0.8%) |
| `STOP_LOSS_PCT` | 0.005 | Stop loss (0.5%) |
| `MAX_POSITION_USDT` | 50 | Max per-trade size |
| `MAX_DAILY_LOSS_USDT` | 100 | Daily loss limit |
| `MAX_OPEN_POSITIONS` | 3 | Max concurrent trades |
| `TRAILING_STOP_PCT` | 0.003 | Trailing stop (0.3%) |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token (optional) |
| `TELEGRAM_CHAT_ID` | — | Telegram chat ID (optional) |

## Telegram Alerts

1. Create bot via [@BotFather](https://t.me/BotFather)
2. Get your chat ID via [@userinfobot](https://t.me/userinfobot)
3. Add to `.env`

You'll get notifications for:
- 🚀 Bot started
- 🟢🔴 Trade opened
- ✅❌ Trade closed (with PnL)
- 📊 Daily summary
- ⚠️ Alerts/errors

## Risk Management

- **Position sizing**: Volatility-adjusted (smaller in high vol)
- **Daily loss limit**: Auto-stop after max loss
- **Max drawdown**: 5% max drawdown from peak
- **Max hold time**: 5 minutes per scalp
- **Breakeven**: Auto-move SL after 0.4% profit
- **Post-only orders**: Maker fees only (0.1%)

## Safety Features

- ✅ **Dry run mode** — default, no real orders
- ✅ **Live confirmation** — must type "YES" for live mode
- ✅ **Daily auto-reset** — stats reset at midnight
- ✅ **Graceful shutdown** — Ctrl+C cancels all orders
- ✅ **Error handling** — continues on API errors

## Disclaimer

⚠️ **Trading crypto involves substantial risk.** This bot is for educational purposes. Always test in dry run mode first. Never trade more than you can afford to lose.

## License

MIT — Use at your own risk.
