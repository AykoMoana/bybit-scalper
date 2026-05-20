"""
Configuration Loader
=====================
Load settings from .env file and CLI args.
"""

import os
import logging
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass
class Config:
    """Bot configuration."""

    # API
    bybit_api_key: str = ""
    bybit_api_secret: str = ""

    # Trading
    symbol: str = "BSBUSDT"
    category: str = "spot"
    leverage: int = 1

    # Strategy
    spread_threshold: float = 0.001
    take_profit_pct: float = 0.008
    stop_loss_pct: float = 0.005
    max_position_usdt: float = 50.0
    max_daily_loss_usdt: float = 100.0
    max_open_positions: int = 3

    # Order
    order_type: str = "Limit"
    post_only: bool = True
    time_in_force: str = "GTC"

    # Risk
    trailing_stop: bool = True
    trailing_stop_pct: float = 0.003
    break_even_after_pct: float = 0.004

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Logging
    log_level: str = "INFO"
    log_file: str = "logs/scalper.log"

    # Mode
    dry_run: bool = True  # Default to dry run for safety

    def validate(self) -> list[str]:
        """Validate config, return list of errors."""
        errors = []
        if not self.dry_run:
            if not self.bybit_api_key:
                errors.append("BYBIT_API_KEY required for live trading")
            if not self.bybit_api_secret:
                errors.append("BYBIT_API_SECRET required for live trading")
        if self.take_profit_pct <= 0:
            errors.append("TAKE_PROFIT_PCT must be positive")
        if self.stop_loss_pct <= 0:
            errors.append("STOP_LOSS_PCT must be positive")
        if self.max_position_usdt <= 0:
            errors.append("MAX_POSITION_USDT must be positive")
        return errors


def load_config(env_path: str = "config/.env", dry_run: bool = True) -> Config:
    """Load configuration from .env file."""
    # Load .env
    if os.path.exists(env_path):
        load_dotenv(env_path)
        logger.info(f"Loaded config from {env_path}")
    else:
        logger.warning(f"Config file not found: {env_path}, using defaults")

    config = Config(
        bybit_api_key=os.getenv("BYBIT_API_KEY", ""),
        bybit_api_secret=os.getenv("BYBIT_API_SECRET", ""),
        symbol=os.getenv("SYMBOL", "BSBUSDT"),
        category=os.getenv("CATEGORY", "spot"),
        leverage=int(os.getenv("LEVERAGE", "1")),
        spread_threshold=float(os.getenv("SPREAD_THRESHOLD", "0.001")),
        take_profit_pct=float(os.getenv("TAKE_PROFIT_PCT", "0.008")),
        stop_loss_pct=float(os.getenv("STOP_LOSS_PCT", "0.005")),
        max_position_usdt=float(os.getenv("MAX_POSITION_USDT", "50")),
        max_daily_loss_usdt=float(os.getenv("MAX_DAILY_LOSS_USDT", "100")),
        max_open_positions=int(os.getenv("MAX_OPEN_POSITIONS", "3")),
        order_type=os.getenv("ORDER_TYPE", "Limit"),
        post_only=os.getenv("POST_ONLY", "true").lower() == "true",
        time_in_force=os.getenv("TIME_IN_FORCE", "GTC"),
        trailing_stop=os.getenv("TRAILING_STOP", "true").lower() == "true",
        trailing_stop_pct=float(os.getenv("TRAILING_STOP_PCT", "0.003")),
        break_even_after_pct=float(os.getenv("BREAK_EVEN_AFTER_PCT", "0.004")),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        log_file=os.getenv("LOG_FILE", "logs/scalper.log"),
        dry_run=dry_run,
    )

    return config
