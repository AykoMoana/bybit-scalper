"""
Main Bot Entry Point — MEXC Edition
======================================
Orchestrates the scalping bot:
  1. Load config
  2. Connect to MEXC (REST + WebSocket)
  3. Main loop: analyze → signal → trade → manage
  4. Cleanup on exit
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime

from .mexc_client import MEXCRestClient, MEXCWebSocket
from .strategy import ScalpingStrategy, MarketState, Signal
from .risk import RiskManager
from .notifier import TelegramNotifier
from .config import load_config

# ── Logging Setup ──────────────────────────────────────────

def setup_logging(log_level: str, log_file: str):
    """Configure logging."""
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(log_file)
    fh.setFormatter(formatter)

    ch = logging.StreamHandler()
    ch.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    root.addHandler(fh)
    root.addHandler(ch)


logger = logging.getLogger(__name__)


class ScalpingBot:
    """Main scalping bot for MEXC."""

    def __init__(self, config):
        self.config = config
        self.dry_run = config.dry_run
        self.running = False

        # Initialize components
        self.client = MEXCRestClient(config.mexc_api_key, config.mexc_api_secret)
        self.strategy = ScalpingStrategy(
            spread_threshold=config.spread_threshold,
            take_profit_pct=config.take_profit_pct,
            stop_loss_pct=config.stop_loss_pct,
            trailing_stop_pct=config.trailing_stop_pct,
        )
        self.risk = RiskManager(
            max_position_usdt=config.max_position_usdt,
            max_daily_loss_usdt=config.max_daily_loss_usdt,
            max_open_positions=config.max_open_positions,
        )
        self.notifier = TelegramNotifier(
            config.telegram_bot_token, config.telegram_chat_id
        )

        # Market state
        self.market = MarketState(symbol=config.symbol)
        self.positions = []

        # Get initial balance
        if not self.dry_run:
            balance = self.client.get_balance("USDT")
            if balance is not None:
                self.risk.initial_balance = balance
                logger.info(f"Initial balance: {balance} USDT")
            else:
                logger.warning("Could not fetch balance")

        # Get exchange info
        info = self.client.get_exchange_info(config.symbol)
        if info["success"]:
            logger.info(f"Exchange info: {json.dumps(info['data'], indent=2)[:500]}")

    def start(self):
        """Start the bot."""
        mode = "DRY RUN" if self.dry_run else "LIVE"
        logger.info(f"Starting MEXC scalping bot — {mode} mode")
        logger.info(f"Symbol: {self.config.symbol}")
        logger.info(f"TP: {self.config.take_profit_pct:.2%}, SL: {self.config.stop_loss_pct:.2%}")

        self.running = True

        self.notifier.send_startup(self.config.symbol, {
            "take_profit": f"{self.config.take_profit_pct:.2%}",
            "stop_loss": f"{self.config.stop_loss_pct:.2%}",
            "max_position": self.config.max_position_usdt,
            "daily_loss_limit": self.config.max_daily_loss_usdt,
        })

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        try:
            self._main_loop()
        except Exception as e:
            logger.error(f"Bot crashed: {e}", exc_info=True)
            self.notifier.send_alert("BOT CRASH", str(e))
        finally:
            self.stop()

    def stop(self):
        """Stop the bot gracefully."""
        logger.info("Stopping bot...")
        self.running = False

        if not self.dry_run:
            self.client.cancel_all_orders(self.config.symbol)

        stats = self.risk.get_stats_summary()
        self.notifier.send_daily_summary(stats)
        self.notifier.send_stop("Manual stop" if self.running else "Completed")

        logger.info(f"Final stats: {json.dumps(stats, indent=2)}")

    def _signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}")
        self.running = False

    def _main_loop(self):
        """Main trading loop."""
        loop_count = 0

        while self.running:
            try:
                loop_count += 1

                # 1. Fetch market data
                self._update_market_state()

                # 2. Manage existing positions
                self._manage_positions()

                # 3. Look for new entries
                if len(self.positions) < self.config.max_open_positions:
                    self._look_for_entry()

                # 4. Log status every 10 loops
                if loop_count % 10 == 0:
                    self._log_status()

                # 5. Check daily reset
                self._check_daily_reset()

                time.sleep(1)

            except Exception as e:
                logger.error(f"Loop error: {e}", exc_info=True)
                time.sleep(5)

    def _update_market_state(self):
        """Fetch and update market data from MEXC."""
        # Get ticker
        ticker = self.client.get_tickers(self.config.symbol)
        if ticker["success"]:
            data = ticker["data"]
            self.market.bid_price = float(data.get("bidPrice", 0))
            self.market.ask_price = float(data.get("askPrice", 0))
            self.market.last_price = float(data.get("lastPrice", 0))
            self.market.bid_volume = float(data.get("bidQty", 0))
            self.market.ask_volume = float(data.get("askQty", 0))

            if self.market.bid_price > 0 and self.market.ask_price > 0:
                self.market.mid_price = (self.market.bid_price + self.market.ask_price) / 2
                self.market.spread = self.market.ask_price - self.market.bid_price
                self.market.spread_pct = self.market.spread / self.market.mid_price

            self.market.price_history.append(self.market.last_price)
            if len(self.market.price_history) > 100:
                self.market.price_history = self.market.price_history[-100:]

            self.market.timestamp = time.time()

        # Get order book
        ob = self.client.get_orderbook(self.config.symbol, limit=10)
        if ob["success"]:
            data = ob["data"]
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            if bids:
                self.market.bid_price = float(bids[0][0])
                self.market.bid_volume = sum(float(b[1]) for b in bids)
            if asks:
                self.market.ask_price = float(asks[0][0])
                self.market.ask_volume = sum(float(a[1]) for a in asks)

    def _manage_positions(self):
        """Check and manage open positions."""
        for pos in self.positions[:]:
            should_exit, reason = pos.should_exit(self.market.last_price)
            if should_exit:
                self._close_position(pos, reason)

    def _look_for_entry(self):
        """Analyze market and look for entry signals."""
        can_trade, reason = self.risk.can_open_position()
        if not can_trade:
            logger.debug(f"Cannot trade: {reason}")
            return

        signal, meta = self.strategy.analyze(self.market)

        if signal == Signal.HOLD:
            return

        logger.info(f"Signal: {signal.value} | {meta}")

        # Calculate position size
        available = self.risk.initial_balance or self.config.max_position_usdt
        qty = self.risk.calculate_position_size(
            self.market.last_price,
            self.market.volatility,
            available,
        )

        if qty <= 0:
            logger.warning("Calculated qty is 0, skipping")
            return

        # Create position
        position = self.strategy.create_position(signal, self.market, qty)

        # Place order
        if self.dry_run:
            logger.info(
                f"[DRY RUN] Would {signal.value} {qty} {self.config.symbol} "
                f"@ {self.market.last_price:.4f}"
            )
            position.order_id = f"dryrun_{int(time.time())}"
        else:
            side = "BUY" if signal == Signal.BUY else "SELL"
            order = self.client.place_order(
                symbol=self.config.symbol,
                side=side,
                order_type=self.config.order_type,
                quantity=qty,
                price=self.market.last_price,
                time_in_force=self.config.time_in_force,
            )
            if order["success"]:
                position.order_id = str(order["data"].get("orderId", ""))
                logger.info(f"Order placed: {position.order_id}")
            else:
                logger.error(f"Order failed: {order.get('error')}")
                return

        self.positions.append(position)
        self.risk.on_position_opened()

        # Notify
        tp_price = position.entry_price * (1 + self.config.take_profit_pct) if signal == Signal.BUY else position.entry_price * (1 - self.config.take_profit_pct)
        sl_price = position.entry_price * (1 - self.config.stop_loss_pct) if signal == Signal.BUY else position.entry_price * (1 + self.config.stop_loss_pct)
        self.notifier.send_trade_open(
            signal.value, self.config.symbol, position.entry_price, qty, tp_price, sl_price
        )

    def _close_position(self, pos, reason: str):
        """Close a position."""
        exit_price = self.market.last_price
        pnl = pos.pnl_pct(exit_price) * pos.qty * pos.entry_price
        fee = self.risk.estimate_fee(pos.qty, exit_price)

        if not self.dry_run:
            side = "SELL" if pos.side == Signal.BUY else "BUY"
            result = self.client.place_order(
                symbol=self.config.symbol,
                side=side,
                order_type="MARKET",
                quantity=pos.qty,
            )
            if not result["success"]:
                logger.error(f"Failed to close position: {result.get('error')}")

        self.positions.remove(pos)
        self.risk.on_position_closed(pnl, fee, pos.side.value, pos.entry_price, exit_price)

        logger.info(
            f"Closed {pos.side.value} @ {exit_price:.4f} | "
            f"PnL: ${pnl:.4f} | Reason: {reason}"
        )

        self.notifier.send_trade_close(
            pos.side.value, self.config.symbol,
            pos.entry_price, exit_price,
            pnl, pos.pnl_pct(exit_price), reason
        )

    def _log_status(self):
        """Log current status."""
        stats = self.risk.get_stats_summary()
        logger.info(
            f"Status: Price={self.market.last_price:.4f} "
            f"Spread={self.market.spread_pct:.4%} "
            f"Momentum={self.market.momentum:.4%} "
            f"Vol={self.market.volatility:.6f} "
            f"Pos={len(self.positions)} "
            f"DailyPnL={stats['net_pnl']}"
        )

    def _check_daily_reset(self):
        """Reset daily stats at midnight."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self.risk.daily_stats.date != today:
            if self.risk.daily_stats.total_trades > 0:
                self.notifier.send_daily_summary(self.risk.get_stats_summary())
            from .risk import DailyStats
            self.risk.daily_stats = DailyStats(date=today)
            logger.info("Daily stats reset")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="MEXC Scalping Bot — BSB/USDT")
    parser.add_argument("--live", action="store_true", help="Enable live trading (default: dry run)")
    parser.add_argument("--config", default="config/.env", help="Path to .env config file")
    parser.add_argument("--symbol", default=None, help="Override trading symbol")
    args = parser.parse_args()

    dry_run = not args.live
    config = load_config(args.config, dry_run=dry_run)

    if args.symbol:
        config.symbol = args.symbol

    errors = config.validate()
    if errors:
        for e in errors:
            print(f"❌ {e}")
        sys.exit(1)

    setup_logging(config.log_level, config.log_file)

    if not dry_run:
        print("⚠️  LIVE TRADING MODE — Real money at risk!")
        print(f"   Symbol: {config.symbol}")
        print(f"   Max position: ${config.max_position_usdt}")
        print(f"   Daily loss limit: ${config.max_daily_loss_usdt}")
        confirm = input("Type 'YES' to confirm: ")
        if confirm != "YES":
            print("Aborted.")
            sys.exit(0)

    bot = ScalpingBot(config)
    bot.start()


if __name__ == "__main__":
    main()
