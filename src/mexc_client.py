"""
MEXC API Client
================
REST + WebSocket wrapper for MEXC V3 API.
Handles authentication, request signing, rate limiting.

API Docs: https://mexcdevelop.github.io/apidocs/spot_v3_en/
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Optional
from urllib.parse import urlencode

import requests
import websocket

logger = logging.getLogger(__name__)


class MEXCAuth:
    """HMAC-SHA256 request signing for MEXC API."""

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret

    def sign(self, query_string: str) -> str:
        """Generate HMAC-SHA256 signature."""
        return hmac.new(
            self.api_secret.encode(), query_string.encode(), hashlib.sha256
        ).hexdigest()

    def get_signature(self, params: dict) -> str:
        """Get signature from params dict."""
        query = urlencode(sorted(params.items()))
        return self.sign(query)


class MEXCRestClient:
    """MEXC V3 REST API client."""

    BASE_URL = "https://api.mexc.com"

    def __init__(self, api_key: str, api_secret: str):
        self.auth = MEXCAuth(api_key, api_secret)
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "X-MEXC-APIKEY": api_key,
            "Content-Type": "application/json",
        })
        self._last_request_time = 0

    def _request(
        self, method: str, endpoint: str, params: dict = None, signed: bool = False
    ) -> dict:
        """Make API request with rate limiting."""
        # Rate limit: max 20 req/s for most endpoints
        elapsed = time.time() - self._last_request_time
        if elapsed < 0.05:
            time.sleep(0.05 - elapsed)

        url = f"{self.BASE_URL}{endpoint}"
        params = params or {}

        if signed:
            # Add timestamp
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = 5000
            # Sign
            signature = self.auth.get_signature(params)
            params["signature"] = signature

        try:
            if method == "GET":
                resp = self.session.get(url, params=params, timeout=10)
            elif method == "POST":
                if signed:
                    resp = self.session.post(url, params=params, timeout=10)
                else:
                    resp = self.session.post(url, json=params, timeout=10)
            elif method == "DELETE":
                resp = self.session.delete(url, params=params, timeout=10)
            else:
                raise ValueError(f"Unsupported method: {method}")

            self._last_request_time = time.time()
            data = resp.json()

            # MEXC returns code 200 on success
            if isinstance(data, dict) and data.get("code", 200) != 200:
                msg = data.get("msg", "Unknown error")
                logger.error(f"MEXC API error: {msg} (code={data.get('code')})")
                return {"success": False, "error": msg, "code": data.get("code")}

            return {"success": True, "data": data}

        except requests.RequestException as e:
            logger.error(f"Request failed: {e}")
            return {"success": False, "error": str(e)}

    # ── Market Data (Public) ────────────────────────────────

    def get_tickers(self, symbol: str) -> dict:
        """Get 24hr ticker."""
        return self._request("GET", "/api/v3/ticker/24hr", {"symbol": symbol})

    def get_price(self, symbol: str) -> dict:
        """Get current price."""
        return self._request("GET", "/api/v3/ticker/price", {"symbol": symbol})

    def get_orderbook(self, symbol: str, limit: int = 20) -> dict:
        """Get order book depth."""
        return self._request("GET", "/api/v3/depth", {
            "symbol": symbol,
            "limit": limit,
        })

    def get_klines(
        self, symbol: str, interval: str = "1m", limit: int = 50
    ) -> dict:
        """Get candlestick data. Public endpoint — no auth needed."""
        try:
            elapsed = time.time() - self._last_request_time
            if elapsed < 0.05:
                time.sleep(0.05 - elapsed)

            resp = self.session.get(
                f"{self.BASE_URL}/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
                timeout=10,
            )
            self._last_request_time = time.time()
            data = resp.json()

            if isinstance(data, list):
                # Format: [[ts, open, high, low, close, volume, ...], ...]
                candles = []
                for c in data:
                    candles.append({
                        "timestamp": c[0],
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": float(c[5]),
                    })
                return {"success": True, "data": candles}

            return {"success": False, "error": str(data)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_recent_trades(self, symbol: str, limit: int = 50) -> dict:
        """Get recent trades."""
        return self._request("GET", "/api/v3/trades", {
            "symbol": symbol,
            "limit": limit,
        })

    def get_exchange_info(self, symbol: str = None) -> dict:
        """Get exchange info (filters, precision, etc)."""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/api/v3/exchangeInfo", params)

    # ── Account (Private) ──────────────────────────────────

    def get_account(self) -> dict:
        """Get account info + balances."""
        return self._request("GET", "/api/v3/account", {}, signed=True)

    def get_balance(self, asset: str = "USDT") -> Optional[float]:
        """Get available balance for an asset."""
        resp = self.get_account()
        if resp["success"]:
            balances = resp["data"].get("balances", [])
            for b in balances:
                if b["asset"] == asset:
                    return float(b["free"])
        return None

    # ── Trading (Private) ──────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,          # BUY or SELL
        order_type: str,    # LIMIT or MARKET
        quantity: float = None,
        quote_quantity: float = None,
        price: float = None,
        time_in_force: str = "GTC",
    ) -> dict:
        """Place a new order."""
        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type.upper(),
        }

        if order_type.upper() == "LIMIT":
            params["price"] = str(price)
            params["quantity"] = str(quantity)
            params["timeInForce"] = time_in_force
        elif order_type.upper() == "MARKET":
            if quantity:
                params["quantity"] = str(quantity)
            elif quote_quantity:
                params["quoteOrderQty"] = str(quote_quantity)

        logger.info(f"Placing {side} {order_type}: {quantity or quote_quantity} {symbol} @ {price}")
        return self._request("POST", "/api/v3/order", params, signed=True)

    def cancel_order(self, symbol: str, order_id: str) -> dict:
        """Cancel an order."""
        return self._request("DELETE", "/api/v3/order", {
            "symbol": symbol,
            "orderId": order_id,
        }, signed=True)

    def cancel_all_orders(self, symbol: str) -> dict:
        """Cancel all open orders for a symbol."""
        return self._request("DELETE", "/api/v3/openOrders", {
            "symbol": symbol,
        }, signed=True)

    def get_open_orders(self, symbol: str = None) -> dict:
        """Get all open orders."""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/api/v3/openOrders", params, signed=True)

    def get_order_status(self, symbol: str, order_id: str) -> dict:
        """Get order status."""
        return self._request("GET", "/api/v3/order", {
            "symbol": symbol,
            "orderId": order_id,
        }, signed=True)

    def get_all_orders(
        self, symbol: str, limit: int = 50
    ) -> dict:
        """Get all orders (filled, canceled, etc)."""
        return self._request("GET", "/api/v3/allOrders", {
            "symbol": symbol,
            "limit": limit,
        }, signed=True)

    def get_my_trades(self, symbol: str, limit: int = 50) -> dict:
        """Get trade history."""
        return self._request("GET", "/api/v3/myTrades", {
            "symbol": symbol,
            "limit": limit,
        }, signed=True)


class MEXCWebSocket:
    """MEXC WebSocket client for real-time data."""

    # MEXC WebSocket: wss://wbs.mexc.com/ws
    WS_URL = "wss://wbs.mexc.com/ws"

    def __init__(self, symbol: str):
        self.symbol = symbol.lower()
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

            # MEXC sends ping, respond with pong
            if "ping" in data:
                ws.send(json.dumps({"pong": data["ping"]}))
                return

            channel = data.get("c", "")  # channel
            stream_data = data.get("d", {})

            if "deals" in channel:  # trade data
                if "trade" in self._callbacks:
                    self._callbacks["trade"](stream_data)
            elif "depth" in channel:  # order book
                if "orderbook" in self._callbacks:
                    self._callbacks["orderbook"](stream_data)
            elif "ticker" in channel:
                if "tickers" in self._callbacks:
                    self._callbacks["tickers"](stream_data)

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
        logger.info("MEXC WebSocket connected")
        # Subscribe to channels
        subscribe_msg = {
            "method": "SUBSCRIPTION",
            "params": [
                f"spot@public.deals.v3.api@{self.symbol}",
                f"spot@public.depth.v3.api@{self.symbol}",
                f"spot@public.ticker.v3.api@{self.symbol}",
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
        self.ws.run_forever(ping_interval=30, ping_timeout=10)

    def disconnect(self):
        """Close WebSocket connection."""
        if self.ws:
            self.ws.close()
        self._running = False

    @property
    def is_connected(self) -> bool:
        return self._running
