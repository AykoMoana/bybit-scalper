"""
Scalping Strategy Engine
========================
Multi-signal scalping strategy combining:
  1. Spread Capture — enter when spread is favorable
  2. Momentum Filter — trade with short-term trend
  3. Order Flow Imbalance — detect buying/selling pressure
  4. Volatility Filter — avoid low-volatility periods
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class Signal(Enum):
    """Trade signal types."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class MarketState:
    """Current market state."""
    symbol: str
    bid_price: float = 0.0
    ask_price: float = 0.0
    last_price: float = 0.0
    mid_price: float = 0.0
    spread: float = 0.0
    spread_pct: float = 0.0
    bid_volume: float = 0.0
    ask_volume: float = 0.0
    price_history: list = field(default_factory=list)
    trade_history: list = field(default_factory=list)
    timestamp: float = 0.0

    @property
    def order_imbalance(self) -> float:
        """Order book imbalance: positive = more buying pressure."""
        total = self.bid_volume + self.ask_volume
        if total == 0:
            return 0.0
        return (self.bid_volume - self.ask_volume) / total

    @property
    def volatility(self) -> float:
        """Calculate recent volatility (standard deviation of returns)."""
        if len(self.price_history) < 5:
            return 0.0
        returns = []
        for i in range(1, len(self.price_history)):
            if self.price_history[i - 1] > 0:
                r = (self.price_history[i] - self.price_history[i - 1]) / self.price_history[i - 1]
                returns.append(r)
        if not returns:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        return variance ** 0.5

    @property
    def momentum(self) -> float:
        """Short-term momentum: positive = uptrend."""
        if len(self.price_history) < 5:
            return 0.0
        recent = self.price_history[-5:]
        if recent[0] == 0:
            return 0.0
        return (recent[-1] - recent[0]) / recent[0]

    @property
    def vwap(self) -> float:
        """Volume-weighted average price from trade history."""
        if not self.trade_history:
            return self.last_price
        total_value = sum(t["price"] * t["qty"] for t in self.trade_history[-50:])
        total_qty = sum(t["qty"] for t in self.trade_history[-50:])
        if total_qty == 0:
            return self.last_price
        return total_value / total_qty


@dataclass
class ScalpPosition:
    """Active scalp position."""
    entry_price: float
    side: Signal
    qty: float
    take_profit: float
    stop_loss: float
    trailing_stop: float
    entry_time: float
    order_id: str = ""
    highest_profit: float = 0.0
    breakeven_moved: bool = False

    @property
    def age_seconds(self) -> float:
        return time.time() - self.entry_time

    def pnl_pct(self, current_price: float) -> float:
        """Calculate PnL percentage."""
        if self.entry_price == 0:
            return 0.0
        if self.side == Signal.BUY:
            return (current_price - self.entry_price) / self.entry_price
        else:
            return (self.entry_price - current_price) / self.entry_price

    def should_exit(self, current_price: float) -> tuple[bool, str]:
        """Check if position should be closed."""
        pnl = self.pnl_pct(current_price)

        # Update highest profit
        if pnl > self.highest_profit:
            self.highest_profit = pnl

        # Stop loss hit
        if pnl <= -abs(self.stop_loss):
            return True, "STOP_LOSS"

        # Take profit hit
        if pnl >= self.take_profit:
            return True, "TAKE_PROFIT"

        # Trailing stop
        if pnl > 0:
            drawdown = self.highest_profit - pnl
            if drawdown >= self.trailing_stop:
                return True, "TRAILING_STOP"

        # Breakeven move
        if not self.breakeven_moved and pnl >= 0.004:
            self.breakeven_moved = True
            if self.side == Signal.BUY:
                self.stop_loss = self.entry_price * 1.0005  # Small buffer
            else:
                self.stop_loss = self.entry_price * 0.9995

        # Max hold time: 5 minutes
        if self.age_seconds > 300 and pnl > 0:
            return True, "TIME_EXIT_PROFIT"
        if self.age_seconds > 300 and pnl <= 0:
            return True, "TIME_EXIT_LOSS"

        return False, ""


class ScalpingStrategy:
    """
    Main scalping strategy.

    Entry conditions (all must be met):
      1. Spread > SPREAD_THRESHOLD (profitable spread)
      2. Momentum aligns with trade direction
      3. Order imbalance supports direction
      4. Volatility is sufficient (not dead market)

    Exit conditions (any triggers):
      1. Take profit hit
      2. Stop loss hit
      3. Trailing stop triggered
      4. Max hold time exceeded
    """

    def __init__(
        self,
        spread_threshold: float = 0.001,
        take_profit_pct: float = 0.008,
        stop_loss_pct: float = 0.005,
        trailing_stop_pct: float = 0.003,
        momentum_threshold: float = 0.0005,
        volatility_min: float = 0.0001,
    ):
        self.spread_threshold = spread_threshold
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.trailing_stop_pct = trailing_stop_pct
        self.momentum_threshold = momentum_threshold
        self.volatility_min = volatility_min

    def analyze(self, state: MarketState) -> tuple[Signal, dict]:
        """
        Analyze market state and return trade signal.

        Returns:
            (Signal, metadata_dict)
        """
        meta = {
            "spread_pct": state.spread_pct,
            "momentum": state.momentum,
            "volatility": state.volatility,
            "order_imbalance": state.order_imbalance,
            "vwap": state.vwap,
        }

        # Not enough data
        if len(state.price_history) < 5:
            return Signal.HOLD, {**meta, "reason": "insufficient_data"}

        # Volatility too low — dead market
        if state.volatility < self.volatility_min:
            return Signal.HOLD, {**meta, "reason": "low_volatility"}

        # Spread too thin
        if state.spread_pct < self.spread_threshold:
            return Signal.HOLD, {**meta, "reason": "spread_too_thin"}

        # Check BUY signal
        buy_score = 0
        if state.momentum > self.momentum_threshold:
            buy_score += 1
        if state.order_imbalance > 0.1:
            buy_score += 1
        if state.last_price < state.vwap:
            buy_score += 1  # Price below VWAP = discount

        # Check SELL signal
        sell_score = 0
        if state.momentum < -self.momentum_threshold:
            sell_score += 1
        if state.order_imbalance < -0.1:
            sell_score += 1
        if state.last_price > state.vwap:
            sell_score += 1  # Price above VWAP = premium

        if buy_score >= 2 and buy_score > sell_score:
            return Signal.BUY, {**meta, "reason": "buy_signal", "score": buy_score}
        elif sell_score >= 2 and sell_score > buy_score:
            return Signal.SELL, {**meta, "reason": "sell_signal", "score": sell_score}

        return Signal.HOLD, {**meta, "reason": "no_clear_signal"}

    def create_position(
        self, signal: Signal, state: MarketState, qty: float
    ) -> ScalpPosition:
        """Create a new scalp position from signal."""
        entry = state.last_price

        if signal == Signal.BUY:
            tp = entry * (1 + self.take_profit_pct)
            sl = entry * (1 - self.stop_loss_pct)
        else:
            tp = entry * (1 - self.take_profit_pct)
            sl = entry * (1 + self.stop_loss_pct)

        return ScalpPosition(
            entry_price=entry,
            side=signal,
            qty=qty,
            take_profit=self.take_profit_pct,
            stop_loss=self.stop_loss_pct,
            trailing_stop=self.trailing_stop_pct,
            entry_time=time.time(),
        )
