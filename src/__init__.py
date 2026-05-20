"""
Bybit Scalper - BSB/USDT Scalping Bot
======================================
High-frequency scalping strategy for Bybit Spot trading.

Strategy:
  1. Spread Capture: Enter when bid-ask spread > threshold
  2. Momentum Filter: Only trade in direction of short-term momentum
  3. Quick TP/SL: 0.8% TP, 0.5% SL
  4. Trailing Stop: Activate after 0.4% profit
  5. Breakeven: Move SL to entry after 0.4% profit

Author: Migi
License: MIT
"""

__version__ = "1.0.0"
