"""
Backtesting Module
===================
Test scalping strategy on historical data without needing API key.

Usage:
    python -m src.backtest --symbol BSBUSDT --interval 5m --days 3
"""

import argparse
import json
import logging
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import requests

from .strategy import ScalpingStrategy, MarketState, Signal
from .risk import RiskManager, DailyStats

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """Backtest configuration."""
    symbol: str = "BSBUSDT"
    interval: str = "5m"
    days: int = 3
    initial_balance: float = 1000.0
    max_position_usdt: float = 50.0
    max_daily_loss_usdt: float = 100.0
    max_open_positions: int = 3
    spread_threshold: float = 0.001
    take_profit_pct: float = 0.008
    stop_loss_pct: float = 0.005
    trailing_stop_pct: float = 0.003
    maker_fee: float = 0.001
    taker_fee: float = 0.001


@dataclass
class Trade:
    """Recorded trade."""
    entry_time: str
    exit_time: str
    side: str
    entry_price: float
    exit_price: float
    qty: float
    pnl: float
    pnl_pct: float
    fee: float
    reason: str
    hold_time_min: float


@dataclass
class BacktestResult:
    """Backtest results."""
    config: dict
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    start_balance: float = 0.0
    end_balance: float = 0.0
    start_time: str = ""
    end_time: str = ""

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def winning_trades(self) -> int:
        return sum(1 for t in self.trades if t.pnl > 0)

    @property
    def losing_trades(self) -> int:
        return sum(1 for t in self.trades if t.pnl <= 0)

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def total_fees(self) -> float:
        return sum(t.fee for t in self.trades)

    @property
    def net_pnl(self) -> float:
        return self.total_pnl - self.total_fees

    @property
    def net_pnl_pct(self) -> float:
        if self.start_balance == 0:
            return 0.0
        return self.net_pnl / self.start_balance

    @property
    def max_drawdown(self) -> float:
        if not self.equity_curve:
            return 0.0
        peak = self.equity_curve[0]
        max_dd = 0.0
        for eq in self.equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @property
    def avg_trade_pnl(self) -> float:
        if not self.trades:
            return 0.0
        return self.net_pnl / len(self.trades)

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in self.trades if t.pnl < 0))
        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    @property
    def avg_hold_time(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.hold_time_min for t in self.trades) / len(self.trades)

    @property
    def best_trade(self) -> Optional[Trade]:
        if not self.trades:
            return None
        return max(self.trades, key=lambda t: t.pnl)

    @property
    def worst_trade(self) -> Optional[Trade]:
        if not self.trades:
            return None
        return min(self.trades, key=lambda t: t.pnl)

    def summary(self) -> dict:
        return {
            "period": f"{self.start_time} → {self.end_time}",
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": f"{self.win_rate:.1%}",
            "start_balance": f"${self.start_balance:.2f}",
            "end_balance": f"${self.end_balance:.2f}",
            "gross_pnl": f"${self.total_pnl:.4f}",
            "total_fees": f"${self.total_fees:.4f}",
            "net_pnl": f"${self.net_pnl:.4f}",
            "net_pnl_pct": f"{self.net_pnl_pct:.2%}",
            "max_drawdown": f"{self.max_drawdown:.2%}",
            "profit_factor": f"{self.profit_factor:.2f}",
            "avg_trade_pnl": f"${self.avg_trade_pnl:.4f}",
            "avg_hold_time": f"{self.avg_hold_time:.1f} min",
            "best_trade": f"${self.best_trade.pnl:.4f}" if self.best_trade else "N/A",
            "worst_trade": f"${self.worst_trade.pnl:.4f}" if self.worst_trade else "N/A",
        }


class DataFetcher:
    """Fetch historical kline data from MEXC."""

    BASE_URL = "https://api.mexc.com/api/v3/klines"

    @staticmethod
    def fetch(symbol: str, interval: str = "5m", limit: int = 1000) -> list:
        """Fetch kline data."""
        all_candles = []
        end_time = int(time.time() * 1000)

        # MEXC max 1000 candles per request
        # Fetch in batches if needed
        while len(all_candles) < limit:
            params = {
                "symbol": symbol,
                "interval": interval,
                "limit": min(1000, limit - len(all_candles)),
                "endTime": end_time,
            }
            try:
                resp = requests.get(DataFetcher.BASE_URL, params=params, timeout=15)
                data = resp.json()
                if not data or not isinstance(data, list):
                    break
                all_candles = data + all_candles
                # Update end_time to before the oldest candle
                end_time = data[0][0] - 1
                if len(data) < 1000:
                    break
                time.sleep(0.1)  # Rate limit
            except Exception as e:
                logger.error(f"Fetch error: {e}")
                break

        return all_candles[:limit]

    @staticmethod
    def fetch_days(symbol: str, interval: str = "5m", days: int = 3) -> list:
        """Fetch approximately N days of data."""
        # Calculate how many candles we need
        interval_minutes = {
            "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
            "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720,
            "1d": 1440,
        }
        mins = interval_minutes.get(interval, 5)
        candles_needed = (days * 24 * 60) // mins
        candles_needed = min(candles_needed, 5000)  # Cap at 5000

        logger.info(f"Fetching ~{candles_needed} candles ({interval}, {days} days)")
        return DataFetcher.fetch(symbol, interval, candles_needed)


class Backtester:
    """Run backtest on historical data."""

    def __init__(self, config: BacktestConfig):
        self.config = config
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
            initial_balance=config.initial_balance,
        )
        self.result = BacktestResult(
            config={
                "symbol": config.symbol,
                "interval": config.interval,
                "days": config.days,
                "initial_balance": config.initial_balance,
                "spread_threshold": config.spread_threshold,
                "take_profit_pct": config.take_profit_pct,
                "stop_loss_pct": config.stop_loss_pct,
                "trailing_stop_pct": config.trailing_stop_pct,
            },
            start_balance=config.initial_balance,
        )

    def run(self, candles: list) -> BacktestResult:
        """Run backtest on candle data."""
        if not candles:
            logger.error("No candle data")
            return self.result

        logger.info(f"Starting backtest: {len(candles)} candles")
        self.result.start_time = str(datetime.fromtimestamp(candles[0][0] / 1000))
        self.result.end_time = str(datetime.fromtimestamp(candles[-1][0] / 1000))

        balance = self.config.initial_balance
        positions = []
        market = MarketState(symbol=self.config.symbol)

        for i, candle in enumerate(candles):
            # Update market state
            ts, open_p, high, low, close, volume = candle[0], float(candle[1]), float(candle[2]), float(candle[3]), float(candle[4]), float(candle[5])

            market.last_price = close
            market.mid_price = close
            # Simulate bid/ask with realistic spread (0.1-0.3% of price)
            spread_pct = random.uniform(0.001, 0.003)
            spread = close * spread_pct
            market.bid_price = close - spread / 2
            market.ask_price = close + spread / 2
            market.spread = spread
            market.spread_pct = spread_pct
            market.bid_volume = volume * random.uniform(0.3, 0.7)
            market.ask_volume = volume * random.uniform(0.3, 0.7)
            market.price_history.append(close)
            if len(market.price_history) > 100:
                market.price_history = market.price_history[-100:]
            market.timestamp = ts / 1000

            # Manage existing positions
            for pos in positions[:]:
                should_exit, reason = pos.should_exit(close)
                if should_exit:
                    # Close position
                    pnl_pct = pos.pnl_pct(close)
                    trade_value = pos.qty * pos.entry_price
                    pnl = pnl_pct * trade_value
                    fee = pos.qty * close * self.config.taker_fee

                    balance += pnl - fee

                    hold_time = (ts / 1000) - pos.entry_time
                    self.result.trades.append(Trade(
                        entry_time=str(datetime.fromtimestamp(pos.entry_time)),
                        exit_time=str(datetime.fromtimestamp(ts / 1000)),
                        side=pos.side.value,
                        entry_price=pos.entry_price,
                        exit_price=close,
                        qty=pos.qty,
                        pnl=round(pnl, 4),
                        pnl_pct=round(pnl_pct, 6),
                        fee=round(fee, 4),
                        reason=reason,
                        hold_time_min=round(hold_time / 60, 1),
                    ))
                    positions.remove(pos)

            # Look for new entries
            if len(positions) < self.config.max_open_positions:
                signal, meta = self.strategy.analyze(market)

                if signal != Signal.HOLD:
                    # Calculate position size
                    pos_value = min(self.config.max_position_usdt, balance * 0.95)
                    qty = pos_value / close
                    qty = round(qty, 4)

                    if qty > 0 and qty * close > 1:  # Min notional ~$1
                        position = self.strategy.create_position(signal, market, qty)
                        position.entry_time = ts / 1000
                        positions.append(position)

            # Record equity
            unrealized = sum(
                pos.pnl_pct(close) * pos.qty * pos.entry_price
                for pos in positions
            )
            self.result.equity_curve.append(balance + unrealized)

        # Close any remaining positions at last price
        last_price = float(candles[-1][4])
        last_ts = candles[-1][0]
        for pos in positions:
            pnl_pct = pos.pnl_pct(last_price)
            pnl = pnl_pct * pos.qty * pos.entry_price
            fee = pos.qty * last_price * self.config.taker_fee
            balance += pnl - fee
            hold_time = (last_ts / 1000) - pos.entry_time
            self.result.trades.append(Trade(
                entry_time=str(datetime.fromtimestamp(pos.entry_time)),
                exit_time=str(datetime.fromtimestamp(last_ts / 1000)),
                side=pos.side.value,
                entry_price=pos.entry_price,
                exit_price=last_price,
                qty=pos.qty,
                pnl=round(pnl, 4),
                pnl_pct=round(pnl_pct, 6),
                fee=round(fee, 4),
                reason="END_OF_DATA",
                hold_time_min=round(hold_time / 60, 1),
            ))

        self.result.end_balance = balance
        return self.result


def print_report(result: BacktestResult):
    """Print formatted backtest report."""
    s = result.summary()

    print("\n" + "=" * 60)
    print("📊 BACKTEST REPORT")
    print("=" * 60)
    print(f"Period:        {s['period']}")
    print(f"Interval:      {result.config['interval']}")
    print("-" * 60)
    print("TRADES")
    print("-" * 60)
    print(f"Total:         {s['total_trades']}")
    print(f"Winning:       {s['winning_trades']}")
    print(f"Losing:        {s['losing_trades']}")
    print(f"Win Rate:      {s['win_rate']}")
    print("-" * 60)
    print("PERFORMANCE")
    print("-" * 60)
    print(f"Start Balance: {s['start_balance']}")
    print(f"End Balance:   {s['end_balance']}")
    print(f"Gross PnL:     {s['gross_pnl']}")
    print(f"Total Fees:    {s['total_fees']}")
    print(f"Net PnL:       {s['net_pnl']} ({s['net_pnl_pct']})")
    print(f"Max Drawdown:  {s['max_drawdown']}")
    print(f"Profit Factor: {s['profit_factor']}")
    print(f"Avg Trade:     {s['avg_trade_pnl']}")
    print(f"Avg Hold:      {s['avg_hold_time']}")
    print(f"Best Trade:    {s['best_trade']}")
    print(f"Worst Trade:   {s['worst_trade']}")
    print("=" * 60)

    # Exit reason breakdown
    if result.trades:
        print("\nEXIT REASONS")
        print("-" * 60)
        reasons = {}
        for t in result.trades:
            reasons[t.reason] = reasons.get(t.reason, 0) + 1
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            pct = count / len(result.trades)
            print(f"  {reason:20s}: {count:4d} ({pct:.1%})")
        print("=" * 60)


def main():
    """CLI entry point for backtesting."""
    parser = argparse.ArgumentParser(description="MEXC Scalping Bot — Backtest")
    parser.add_argument("--symbol", default="BSBUSDT", help="Trading pair")
    parser.add_argument("--interval", default="5m", help="Candle interval (1m, 5m, 15m, 1h)")
    parser.add_argument("--days", type=int, default=3, help="Days of historical data")
    parser.add_argument("--balance", type=float, default=1000.0, help="Initial balance USDT")
    parser.add_argument("--max-pos", type=float, default=50.0, help="Max position size USDT")
    parser.add_argument("--tp", type=float, default=0.008, help="Take profit %")
    parser.add_argument("--sl", type=float, default=0.005, help="Stop loss %")
    parser.add_argument("--output", default=None, help="Save results to JSON file")
    args = parser.parse_args()

    config = BacktestConfig(
        symbol=args.symbol,
        interval=args.interval,
        days=args.days,
        initial_balance=args.balance,
        max_position_usdt=args.max_pos,
        take_profit_pct=args.tp,
        stop_loss_pct=args.sl,
    )

    # Fetch data
    print(f"📥 Fetching {args.days} days of {args.interval} data for {args.symbol}...")
    candles = DataFetcher.fetch_days(args.symbol, args.interval, args.days)
    if not candles:
        print("❌ No data fetched!")
        sys.exit(1)
    print(f"✅ Fetched {len(candles)} candles")

    # Run backtest
    print(f"🔄 Running backtest...")
    bt = Backtester(config)
    result = bt.run(candles)

    # Print report
    print_report(result)

    # Save to file
    if args.output:
        output = {
            "summary": result.summary(),
            "config": result.config,
            "trades": [
                {
                    "entry_time": t.entry_time,
                    "exit_time": t.exit_time,
                    "side": t.side,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "qty": t.qty,
                    "pnl": t.pnl,
                    "pnl_pct": t.pnl_pct,
                    "fee": t.fee,
                    "reason": t.reason,
                    "hold_time_min": t.hold_time_min,
                }
                for t in result.trades
            ],
        }
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\n💾 Results saved to {args.output}")


if __name__ == "__main__":
    main()
