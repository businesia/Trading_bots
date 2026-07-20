"""
bots/crypto_futures/connectors/bybit.py
========================================
Async коннектор к Bybit Futures (REST + WebSocket).
Поддерживает testnet и mainnet.

REST: баланс, ордера, цены, funding rate
WebSocket: real-time funding rate, mark price
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import httpx
from loguru import logger

from core.engine.order_manager import ExchangeConnector
from core.engine.position_tracker import PositionDataProvider

if TYPE_CHECKING:
    pass


class BybitFuturesConnector(ExchangeConnector, PositionDataProvider):
    """
    Коннектор к Bybit USDT Perpetual Futures.

    Использование:
        connector = BybitFuturesConnector(
            api_key="...",
            api_secret="...",
            testnet=True,
        )
        async with connector:
            balance = await connector.get_balance()
            rate = await connector.get_funding_rate("BTCUSDT")
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = True,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._testnet = testnet

        if testnet:
            self._base_url = "https://api-testnet.bybit.com"
            self._ws_url = "wss://stream-testnet.bybit.com/v5/public/linear"
        else:
            self._base_url = "https://api.bybit.com"
            self._ws_url = "wss://stream.bybit.com/v5/public/linear"

        self._client: httpx.AsyncClient | None = None
        self._ws = None
        self._ws_task = None
        self._price_callbacks: dict[str, list] = {}
        self._running = False

        logger.info(f"BybitFuturesConnector инициализирован | testnet={testnet}")

    # ── Context Manager ──────────────────────────────────────────────────

    async def __aenter__(self) -> "BybitFuturesConnector":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(max_connections=10),
        )
        # Проверка подключения
        await self._client.get("/v5/market/time")
        logger.success("Bybit REST подключён")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop_ws()
        if self._client:
            await self._client.aclose()
        logger.info("Bybit коннектор закрыт")

    # ── Подпись запросов ─────────────────────────────────────────────────

    def _sign(self, params: dict, timestamp: int) -> str:
        """Создаёт подпись для приватных запросов."""
        param_str = urlencode(sorted(params.items()))
        sign_str = f"{timestamp}{self._api_key}{param_str}"
        return hmac.new(
            self._api_secret.encode(),
            sign_str.encode(),
            hashlib.sha256,
        ).hexdigest()

    def _headers(self, params: dict) -> dict:
        timestamp = int(time.time() * 1000)
        return {
            "X-BAPI-API-KEY": self._api_key,
            "X-BAPI-TIMESTAMP": str(timestamp),
            "X-BAPI-SIGN": self._sign(params, timestamp),
            "X-BAPI-RECV-WINDOW": "5000",
            "Content-Type": "application/json",
        }

    # ── Публичные REST методы ────────────────────────────────────────────

    async def get_funding_rate(self, symbol: str) -> dict:
        """
        Получает текущий funding rate для символа.

        Returns:
            {
                "symbol": "BTCUSDT",
                "rate": 0.0001,           # decimal (0.01% = 0.0001)
                "rate_pct": 0.01,         # %
                "apr": 36.5,              # % годовых
                "next_funding_time": 1234567890000,  # ms
                "mark_price": 45000.0,
            }
        """
        # Bybit funding rate endpoint
        resp = await self._client.get(
            "/v5/market/funding/history",
            params={"category": "linear", "symbol": symbol, "limit": 1},
        )
        data = resp.json()
        if data["retCode"] != 0:
            raise RuntimeError(f"Bybit funding rate error: {data['retMsg']}")

        item = data["result"]["list"][0]
        rate = float(item["fundingRate"])
        next_funding = int(item["nextFundingTime"])

        # Mark price
        mark_resp = await self._client.get(
            "/v5/market/tickers",
            params={"category": "linear", "symbol": symbol},
        )
        mark_data = mark_resp.json()
        mark_price = float(mark_data["result"]["list"][0]["markPrice"])

        return {
            "symbol": symbol,
            "rate": rate,
            "rate_pct": rate * 100,
            "apr": rate * 3 * 365 * 100,
            "next_funding_time": next_funding,
            "mark_price": mark_price,
        }

    async def get_mark_price(self, symbol: str) -> float:
        """Текущая mark price."""
        resp = await self._client.get(
            "/v5/market/tickers",
            params={"category": "linear", "symbol": symbol},
        )
        data = resp.json()
        return float(data["result"]["list"][0]["markPrice"])

    # ── Приватные REST методы (требуют API ключи) ────────────────────────

    async def get_balance(self) -> dict[str, float]:
        """Баланс кошелька (USDT и др.)."""
        if not self._api_key or not self._api_secret:
            return {"USDT": 10_000.0}  # paper trading fallback

        params = {"accountType": "UNIFIED", "coin": "USDT"}
        headers = self._headers(params)
        resp = await self._client.get("/v5/account/wallet-balance", params=params, headers=headers)
        data = resp.json()
        if data["retCode"] != 0:
            raise RuntimeError(f"Bybit balance error: {data['retMsg']}")

        balances = {}
        for coin in data["result"]["list"][0]["coin"]:
            balances[coin["coin"]] = float(coin["walletBalance"])
        return balances

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float | None = None,
        client_order_id: str | None = None,
    ) -> dict:
        """Размещает ордер на Bybit."""
        if not self._api_key or not self._api_secret:
            # Paper trading simulation
            return {
                "orderId": f"paper_{client_order_id or int(time.time()*1000)}",
                "symbol": symbol,
                "side": side,
                "orderType": "Market" if price is None else "Limit",
                "qty": str(quantity),
                "price": str(price) if price else "",
                "status": "Filled",
                "avgPrice": str(price or 0),
                "executedQty": str(quantity),
                "cumQuote": str(quantity * (price or 0)),
                "timeInForce": "GTC",
            }

        params = {
            "category": "linear",
            "symbol": symbol,
            "side": side.capitalize(),  # Buy / Sell
            "orderType": "Market" if price is None else "Limit",
            "qty": str(quantity),
            "timeInForce": "GTC",
        }
        if price is not None:
            params["price"] = str(price)
        if client_order_id:
            params["orderLinkId"] = client_order_id

        headers = self._headers(params)
        resp = await self._client.post("/v5/order/create", json=params, headers=headers)
        data = resp.json()
        if data["retCode"] != 0:
            raise RuntimeError(f"Bybit place order error: {data['retMsg']}")

        return data["result"]

    async def cancel_order(
        self,
        symbol: str,
        exchange_order_id: str,
    ) -> bool:
        """Отменяет ордер."""
        if not self._api_key or not self._api_secret:
            return True  # paper trading

        params = {
            "category": "linear",
            "symbol": symbol,
            "orderId": exchange_order_id,
        }
        headers = self._headers(params)
        resp = await self._client.post("/v5/order/cancel", json=params, headers=headers)
        data = resp.json()
        return data["retCode"] == 0

    async def get_order_status(
        self,
        symbol: str,
        exchange_order_id: str,
    ) -> dict:
        """Статус ордера."""
        if not self._api_key or not self._api_secret:
            return {"status": "Filled", "avgPrice": "0", "executedQty": "0"}

        params = {"category": "linear", "symbol": symbol, "orderId": exchange_order_id}
        headers = self._headers(params)
        resp = await self._client.get("/v5/order/realtime", params=params, headers=headers)
        data = resp.json()
        if data["retCode"] != 0:
            raise RuntimeError(f"Bybit order status error: {data['retMsg']}")

        order = data["result"]["list"][0]
        return {
            "orderId": order["orderId"],
            "symbol": order["symbol"],
            "status": order["orderStatus"],
            "side": order["side"],
            "orderType": order["orderType"],
            "qty": order["qty"],
            "price": order["price"],
            "avgPrice": order["avgPrice"],
            "executedQty": order["cumExecQty"],
            "cumQuote": order["cumExecValue"],
            "timeInForce": order["timeInForce"],
        }

    async def get_positions(self) -> list[dict]:
        """Открытые позиции."""
        if not self._api_key or not self._api_secret:
            return []

        params = {"category": "linear", "settleCoin": "USDT"}
        headers = self._headers(params)
        resp = await self._client.get("/v5/position/list", params=params, headers=headers)
        data = resp.json()
        if data["retCode"] != 0:
            raise RuntimeError(f"Bybit positions error: {data['retMsg']}")

        positions = []
        for pos in data["result"]["list"]:
            if float(pos["size"]) > 0:
                positions.append({
                    "symbol": pos["symbol"],
                    "side": "LONG" if pos["side"] == "Buy" else "SHORT",
                    "size": float(pos["size"]),
                    "entryPrice": float(pos["avgPrice"]),
                    "markPrice": float(pos["markPrice"]),
                    "unrealisedPnl": float(pos["unrealisedPnl"]),
                    "leverage": float(pos["leverage"]),
                })
        return positions

    # ── WebSocket ────────────────────────────────────────────────────────

    async def start_ws(self, symbols: list[str], callback) -> None:
        """Запускает WebSocket для real-time mark price + funding rate."""
        import websockets

        self._running = True
        self._price_callbacks = {s: [] for s in symbols}
        for s in symbols:
            self._price_callbacks[s].append(callback)

        self._ws_task = asyncio.create_task(self._ws_loop(symbols))

    async def _ws_loop(self, symbols: list[str]) -> None:
        import websockets

        while self._running:
            try:
                async with websockets.connect(self._ws_url) as ws:
                    self._ws = ws
                    # Подписка на mark price + funding rate
                    for symbol in symbols:
                        await ws.send(json.dumps({
                            "op": "subscribe",
                            "args": [
                                f"tickers.{symbol}",
                            ],
                        }))

                    async for msg in ws:
                        if not self._running:
                            break
                        data = json.loads(msg)
                        if data.get("topic", "").startswith("tickers."):
                            await self._handle_ticker(data)
            except Exception as e:
                logger.warning(f"Bybit WS ошибка: {e}, переподключение через 5с...")
                await asyncio.sleep(5)

    async def _handle_ticker(self, data: dict) -> None:
        """Обрабатывает ticker обновление."""
        topic = data.get("topic", "")
        symbol = topic.replace("tickers.", "")
        if symbol not in self._price_callbacks:
            return

        ticker = data["data"]
        mark_price = float(ticker["markPrice"])
        funding_rate = float(ticker.get("fundingRate", 0))

        for callback in self._price_callbacks[symbol]:
            try:
                await callback(symbol, mark_price, funding_rate)
            except Exception as e:
                logger.error(f"WS callback error: {e}")

    async def stop_ws(self) -> None:
        """Останавливает WebSocket."""
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass

    # ── PositionDataProvider ─────────────────────────────────────────────

    async def get_account_positions(self) -> list[dict]:
        return await self.get_positions()

    async def get_current_price(self, symbol: str) -> float:
        return await self.get_mark_price(symbol)