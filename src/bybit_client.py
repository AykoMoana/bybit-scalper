"""
Bybit API Client
================
REST + WebSocket wrapper for Bybit V5 API.
Handles authentication, request signing, rate limiting.
"""

import hashlib
import hmac
import json
import time
import logging
from typing import Any, Optional
from urllib.parse import urlencode

import requests
import websocket

logger = logging.getLogger(__name__)


class BybitAuth:
    """HMAC-SHA256 request signing for Bybit V5 API."""

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret

    def sign_request(self, timestamp: str, params: str = "") -> str:
        """Generate HMAC-SHA256 signature."""
        pre_sign = f"{timestamp}{self.api_key}5000{params}"
        return hmac.new(
            self.api_secret.encode(), pre_sign.encode(), hashlib.sha256
        ).hexdigest()

    def get_headers(self, params: str = "") -> dict:
        """Get authenticated headers."""
        ts = str(int(time.time() * 1000))
        return {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-SIGN": self.sign_request(ts, params),
            "X-BAPI-SIGN-TYPE": "2",
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": "5000",
            "Content-Type": "application/json",
        }


class BybitRestClient:
    """Bybit V5 REST API client."""

    BASE_URL = "https://api.bybit.com"

    def __init__(self, api_key: str, api_secret: str):
        self.auth = BybitAuth(api_key, api_secret)
        self.session = requests.Session()
        self._rate_limit_remaining = 120
        self._last_request_time = 0

    def _request(
        self, method: str, endpoint: str, params: dict = None, signed: bool = False
    ) -> dict:
        """Make API request with rate limiting."""
        # Rate limit: max 120 req/min
        elapsed = time.time() - self._last_request_time
        if elapsed < 0.5:
            time.sleep(0.5 - elapsed)

        url = f"{self.BASE_URL}{endpoint}"
        params = params or {}

        if signed:
            body = json.dumps(params) if method == "POST" else urlencode(params)
            headers = self.auth.get_headers(body)
        else:
            headers = {"Content-Type": "application/json"}

        try:
            if method == "GET":
                resp = self.session.get(url, params=params, headers=headers, timeout=10)
            elif method == "POST":
                resp = self.session.post(url, json=params, headers=headers, timeout=10)
            else:
                raise ValueError(f"Unsupported method: {method}")

            self._last_request_time = time.time()
            data = resp.json()

            if data.get("retCode") != 0:
                logger.error(f"API error: {data.get('retMsg')} (code={data.get('retCode')})")
                return {"success": False, "error": data.get("retMsg"), "code": data.get("retCode")}

            return {"success": True, "data": data.get("result", {})}

        except requests.RequestException as e:
            logger.error(f"Request failed: {e}")
            return {"success": False, "error": str(e)}

    # ── Market Data ──────────────────────────────────────────

    def get_tickers(self, symbol: str, category: str = "spot") -> dict:
        """Get current ticker (price, volume, etc)."""
        return self._request("GET", "/v5/market/tickers", {
            "category": category,
            "symbol": symbol,
        })

    def get_orderbook(self, symbol: str, category: str = "spot", limit: int = 25) -> dict:
        """Get order book depth."""
        return self._request("GET", "/v5/market/orderbook", {
            "category": category,
            "symbol": symbol,
            "limit": limit,
        })

    def get_klines(
        self, symbol: str, interval: str = "1", category: str = "spot", limit: int = 20
    ) -> dict:
        """Get candlestick data."""
        return self._request("GET", "/v5/market/kline", {
            "category": category,
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        })

    def get_instruments(self, symbol: str, category: str = "spot") -> dict:
        """Get instrument info (min qty, tick size, etc)."""
        return self._request("GET", "/v5/market/instruments-info", {
            "category": category,
            "symbol": symbol,
        })

    # ── Account ──────────────────────────────────────────────

    def get_wallet_balance(self, account_type: str = "SPOT") -> dict:
        """Get wallet balance."""
        return self._request("GET", "/v5/account/wallet-balance", {
            "accountType": account_type,
        }, signed=True)

    # ── Trading ──────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        order_type: str = "Limit",
        price: float = None,
        category: str = "spot",
        time_in_force: str = "GTC",
        post_only: bool = True,
    ) -> dict:
        """Place a new order."""
        params = {
            "category": category,
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "qty": str(qty),
            "timeInForce": time_in_force,
        }
        if price:
            params["price"] = str(price)
        if post_only and order_type == "Limit":
            params["isLeverage"] = "0"

        logger.info(f"Placing {side} order: {qty} {symbol} @ {price} ({order_type})")
        return self._request("POST", "/v5/order/create", params, signed=True)

    def cancel_order(
        self, symbol: str, order_id: str, category: str = "spot"
    ) -> dict:
        """Cancel an order."""
        return self._request("POST", "/v5/order/cancel", {
            "category": category,
            "symbol": symbol,
            "orderId": order_id,
        }, signed=True)

    def cancel_all_orders(self, symbol: str, category: str = "spot") -> dict:
        """Cancel all open orders for a symbol."""
        return self._request("POST", "/v5/order/cancel-all", {
            "category": category,
            "symbol": symbol,
        }, signed=True)

    def get_open_orders(self, symbol: str, category: str = "spot") -> dict:
        """Get all open orders."""
        return self._request("GET", "/v5/order/realtime", {
            "category": category,
            "symbol": symbol,
        }, signed=True)

    def get_order_history(
        self, symbol: str, category: str = "spot", limit: int = 20
    ) -> dict:
        """Get order history."""
        return self._request("GET", "/v5/order/history", {
            "category": category,
            "symbol": symbol,
            "limit": limit,
        }, signed=True)

    def get_trade_history(
        self, symbol: str, category: str = "spot", limit: int = 20
    ) -> dict:
        """Get trade execution history."""
        return self._request("GET", "/v5/execution/list", {
            "category": category,
            "symbol": symbol,
            "limit": limit,
        }, signed=True)


class BybitWebSocket:
    """Bybit V5 WebSocket client for real-time data."""

    WS_URL = "wss://stream.bybit.com/v5/public/spot"

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.ws: Optional[websocket.WebSocketApp] = None
        self._callbacks = {}
        self._running = False

    def on(self, event: str, callback):
        """Register event callback."""
        self._callbacks[event] = callback

    def _on_message(self, ws, message):
        """Handle incoming message."""
        try:
            data = json.loads(message)
            topic = data.get("topic", "")

            if "orderbook" in topic:
                if "orderbook" in self._callbacks:
                    self._callbacks["orderbook"](data.get("data", {}))
            elif "trade" in topic:
                if "trade" in self._callbacks:
                    self._callbacks["trade"](data.get("data", []))
            elif "tickers" in topic:
                if "tickers" in self._callbacks:
                    self._callbacks["tickers"](data.get("data", {}))
            elif "kline" in topic:
                if "kline" in self._callbacks:
                    self._callbacks["kline"](data.get("data", []))

        except json.JSONDecodeError:
            pass

    def _on_error(self, ws, error):
        logger.error(f"WebSocket error: {error}")
        if "error" in self._callbacks:
            self._callbacks["error"](error)

    def _on_close(self, ws, close_status, close_msg):
        logger.warning(f"WebSocket closed: {close_status} - {close_msg}")
        self._running = False
        if "close" in self._callbacks:
            self._callbacks["close"](close_status, close_msg)

    def _on_open(self, ws):
        logger.info("WebSocket connected")
        # Subscribe to channels
        subscribe_msg = {
            "op": "subscribe",
            "args": [
                f"orderbook.1.{self.symbol}",
                f"publicTrade.{self.symbol}",
                f"tickers.{self.symbol}",
            ],
        }
        ws.send(json.dumps(subscribe_msg))

    def connect(self):
        """Start WebSocket connection."""
        self.ws = websocket.WebSocketApp(
            self.WS_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._running = True
        self.ws.run_forever(ping_interval=20, ping_timeout=10)

    def disconnect(self):
        """Close WebSocket connection."""
        if self.ws:
            self.ws.close()
        self._running = False

    @property
    def is_connected(self) -> bool:
        return self._running
