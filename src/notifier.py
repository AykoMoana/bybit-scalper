"""
Telegram Notification Module
=============================
Send trade alerts and status updates via Telegram.
"""

import json
import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Send notifications to Telegram chat."""

    BASE_URL = "https://api.telegram.org/bot{token}"

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = self.BASE_URL.format(token=bot_token)
        self._enabled = bool(bot_token and chat_id)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def send(self, message: str, parse_mode: str = "Markdown") -> bool:
        """Send a message to Telegram."""
        if not self._enabled:
            return False

        try:
            resp = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            data = resp.json()
            if not data.get("ok"):
                logger.error(f"Telegram send failed: {data}")
                return False
            return True
        except requests.RequestException as e:
            logger.error(f"Telegram request failed: {e}")
            return False

    def send_trade_open(self, side: str, symbol: str, price: float, qty: float, tp: float, sl: float):
        """Notify trade opened."""
        emoji = "🟢" if side == "BUY" else "🔴"
        msg = (
            f"{emoji} *SCALP {side} OPENED*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 Pair: `{symbol}`\n"
            f"💰 Entry: `${price:.4f}`\n"
            f"📦 Qty: `{qty:.2f}`\n"
            f"🎯 TP: `${tp:.4f}`\n"
            f"🛑 SL: `${sl:.4f}`\n"
            f"⏰ {time.strftime('%H:%M:%S')}"
        )
        return self.send(msg)

    def send_trade_close(
        self, side: str, symbol: str, entry: float, exit_price: float,
        pnl: float, pnl_pct: float, reason: str
    ):
        """Notify trade closed."""
        emoji = "✅" if pnl > 0 else "❌"
        sign = "+" if pnl > 0 else ""
        msg = (
            f"{emoji} *SCALP {side} CLOSED*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 Pair: `{symbol}`\n"
            f"💰 Entry: `${entry:.4f}` → Exit: `${exit_price:.4f}`\n"
            f"📈 PnL: `{sign}${pnl:.4f}` ({sign}{pnl_pct:.2%})\n"
            f"📝 Reason: {reason}\n"
            f"⏰ {time.strftime('%H:%M:%S')}"
        )
        return self.send(msg)

    def send_daily_summary(self, stats: dict):
        """Send daily trading summary."""
        msg = (
            f"📊 *DAILY SUMMARY*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📅 Date: {stats.get('date', 'N/A')}\n"
            f"🔄 Trades: {stats.get('total_trades', 0)}\n"
            f"🏆 Win Rate: {stats.get('win_rate', 'N/A')}\n"
            f"💰 Gross PnL: {stats.get('gross_pnl', 'N/A')}\n"
            f"💸 Fees: {stats.get('total_fees', 'N/A')}\n"
            f"📈 Net PnL: {stats.get('net_pnl', 'N/A')}\n"
            f"📂 Open Pos: {stats.get('open_positions', 0)}"
        )
        return self.send(msg)

    def send_alert(self, title: str, message: str):
        """Send alert notification."""
        msg = f"⚠️ *{title}*\n{message}"
        return self.send(msg)

    def send_startup(self, symbol: str, config: dict):
        """Notify bot started."""
        msg = (
            f"🚀 *SCALPER BOT STARTED*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 Pair: `{symbol}`\n"
            f"🎯 TP: {config.get('take_profit', 'N/A')}\n"
            f"🛑 SL: {config.get('stop_loss', 'N/A')}\n"
            f"📦 Max Pos: ${config.get('max_position', 'N/A')}\n"
            f"💰 Daily Loss Limit: ${config.get('daily_loss_limit', 'N/A')}\n"
            f"⏰ {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return self.send(msg)

    def send_stop(self, reason: str = ""):
        """Notify bot stopped."""
        msg = f"🛑 *SCALPER BOT STOPPED*\nReason: {reason}\n⏰ {time.strftime('%H:%M:%S')}"
        return self.send(msg)
