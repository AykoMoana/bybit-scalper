"""
Risk Management Module
======================
Position sizing, daily loss limits, exposure control.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DailyStats:
    """Track daily trading statistics."""
    date: str = ""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl_usdt: float = 0.0
    total_fees_usdt: float = 0.0
    max_drawdown: float = 0.0
    peak_balance: float = 0.0
    trades: list = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades

    @property
    def net_pnl(self) -> float:
        return self.total_pnl_usdt - self.total_fees_usdt

    def record_trade(self, pnl: float, fee: float, side: str, entry: float, exit_price: float):
        """Record a completed trade."""
        self.total_trades += 1
        self.total_pnl_usdt += pnl
        self.total_fees_usdt += fee
        if pnl > 0:
            self.winning_trades += 1
        elif pnl < 0:
            self.losing_trades += 1
        self.trades.append({
            "time": time.strftime("%H:%M:%S"),
            "side": side,
            "entry": entry,
            "exit": exit_price,
            "pnl": round(pnl, 4),
            "fee": round(fee, 4),
        })


class RiskManager:
    """
    Risk management for scalping bot.

    Controls:
      - Max position size per trade
      - Max concurrent positions
      - Daily loss limit
      - Max drawdown
      - Position sizing based on volatility
    """

    # Bybit spot trading fees (maker/taker)
    MAKER_FEE = 0.001  # 0.1%
    TAKER_FEE = 0.001  # 0.1%

    def __init__(
        self,
        max_position_usdt: float = 50.0,
        max_daily_loss_usdt: float = 100.0,
        max_open_positions: int = 3,
        max_drawdown_pct: float = 0.05,
        initial_balance: float = 0.0,
    ):
        self.max_position_usdt = max_position_usdt
        self.max_daily_loss_usdt = max_daily_loss_usdt
        self.max_open_positions = max_open_positions
        self.max_drawdown_pct = max_drawdown_pct
        self.initial_balance = initial_balance
        self.daily_stats = DailyStats(date=time.strftime("%Y-%m-%d"))
        self._open_positions = 0

    def can_open_position(self) -> tuple[bool, str]:
        """Check if a new position can be opened."""
        # Max positions check
        if self._open_positions >= self.max_open_positions:
            return False, f"Max positions reached ({self._open_positions}/{self.max_open_positions})"

        # Daily loss limit check
        if self.daily_stats.net_pnl <= -self.max_daily_loss_usdt:
            return False, f"Daily loss limit hit: {self.daily_stats.net_pnl:.2f} USDT"

        # Drawdown check
        if self.initial_balance > 0:
            current_balance = self.initial_balance + self.daily_stats.net_pnl
            drawdown = (self.initial_balance - current_balance) / self.initial_balance
            if drawdown >= self.max_drawdown_pct:
                return False, f"Max drawdown hit: {drawdown:.2%}"

        return True, "OK"

    def calculate_position_size(
        self, price: float, volatility: float, available_balance: float
    ) -> float:
        """
        Calculate optimal position size.

        Uses volatility-based sizing: smaller positions in high volatility.
        """
        # Base size: max_position_usdt or available balance, whichever is smaller
        base_size = min(self.max_position_usdt, available_balance * 0.95)

        # Volatility adjustment: reduce size if volatile
        if volatility > 0.002:
            vol_factor = 0.5
        elif volatility > 0.001:
            vol_factor = 0.75
        else:
            vol_factor = 1.0

        position_usdt = base_size * vol_factor

        # Ensure we don't exceed available balance
        position_usdt = min(position_usdt, available_balance * 0.95)

        # Convert to quantity
        qty = position_usdt / price

        logger.info(
            f"Position sizing: ${position_usdt:.2f} USDT "
            f"({qty:.4f} units, vol_factor={vol_factor})"
        )
        return round(qty, 4)

    def on_position_opened(self):
        """Track new position."""
        self._open_positions += 1
        logger.info(f"Position opened. Open: {self._open_positions}/{self.max_open_positions}")

    def on_position_closed(self, pnl: float, fee: float, side: str, entry: float, exit_price: float):
        """Track closed position."""
        self._open_positions = max(0, self._open_positions - 1)
        self.daily_stats.record_trade(pnl, fee, side, entry, exit_price)
        logger.info(
            f"Position closed. PnL: ${pnl:.4f}, Fee: ${fee:.4f}, "
            f"Open: {self._open_positions}, Daily net: ${self.daily_stats.net_pnl:.4f}"
        )

    def get_fee(self, is_maker: bool = True) -> float:
        """Get trading fee rate."""
        return self.MAKER_FEE if is_maker else self.TAKER_FEE

    def estimate_fee(self, qty: float, price: float, is_maker: bool = True) -> float:
        """Estimate trading fee for an order."""
        return qty * price * self.get_fee(is_maker)

    def get_stats_summary(self) -> dict:
        """Get daily stats summary."""
        ds = self.daily_stats
        return {
            "date": ds.date,
            "total_trades": ds.total_trades,
            "win_rate": f"{ds.win_rate:.1%}",
            "gross_pnl": f"${ds.total_pnl_usdt:.4f}",
            "total_fees": f"${ds.total_fees_usdt:.4f}",
            "net_pnl": f"${ds.net_pnl:.4f}",
            "open_positions": self._open_positions,
        }
