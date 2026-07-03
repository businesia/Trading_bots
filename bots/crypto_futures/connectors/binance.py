"""
bots/crypto_futures/connectors/binance.py
==========================================
Async коннектор к Binance Futures (REST + WebSocket).
Поддерживает testnet и mainnet через настройки.

REST: баланс, ордера, цены, funding rate
WebSocket: real-time funding rate, цены mark price
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from urllib.parse import urlencode

import httpx
from loguru import logger

from core.engine.order_manager import ExchangeConnector
from core.engine.position_tracker import PositionDataProvider


class BinanceFuturesConnector(ExchangeConnector, PositionDataProvider):
    """
    Коннектор к Binance USD-M Futures.

    Использование:
        connector = BinanceFuturesConnector(
            api_key="...",
            api_secret="...",
            testnet=True,
        )
        async with connector:
            balance = await connector.get_balance()
            rate = await connector.get_funding_rate("BTCUSDT")
    """

    MAINNET_URL = "https://fapi.binance.com"
    TESTNET_URL = "https://testnet.binancefuture.com"
    WS_MAINNET   = "wss://fstream.binance.com/ws"
    WS_TESTNET   = "wss://stream.binancefuture.com/ws"

    # Rate limit: 2400 weight/min → 40 weight/sec
    _RATE_LIMIT_DELAY = 0.05  # 50ms между запросами

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = True,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._testnet = testnet
        self._base_url = self.TESTNET_URL if testnet else self.MAINNET_URL
        self._ws_url = self.WS_TESTNET if testnet else self.WS_MAINNET

        self._client: httpx.AsyncClient | None = None
        self._last_request_time: float = 0.0

        mode = "TESTNET" if testnet else "MAINNET"
        logger.info(f"BinanceFuturesConnector инициализирован | режим={mode}")

    # ── Context manager ────────────────────────────────────────────────────

    async def __aenter__(self) -> "BinanceFuturesConnector":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "X-MBX-APIKEY": self._api_key,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(10.0),
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Публичные методы (без подписи) ────────────────────────────────────

    async def get_funding_rate(self, symbol: str) -> dict:
        """
        Текущий funding rate и время следующего начисления.

        Returns:
            {
                "symbol": "BTCUSDT",
                "rate": 0.0001,          # текущая ставка
                "rate_pct": 0.01,        # в процентах
                "apr": 10.95,            # аннуализированный %
                "next_funding_time": "14:00 UTC",
                "mark_price": 45000.0,
            }
        """
        data = await self._get("/fapi/v1/premiumIndex", {"symbol": symbol})
        rate = float(data.get("lastFundingRate", 0))
        next_ts = int(data.get("nextFundingTime", 0))
        mark_price = float(data.get("markPrice", 0))

        next_dt_str = ""
        if next_ts:
            import datetime
            dt = datetime.datetime.fromtimestamp(next_ts / 1000, tz=datetime.timezone.utc)
            next_dt_str = dt.strftime("%H:%M UTC")

        return {
            "symbol": symbol,
            "rate": rate,
            "rate_pct": rate * 100,
            "apr": rate * 3 * 365 * 100,  # 3 раза в день × 365 дней
            "next_funding_time": next_dt_str,
            "mark_price": mark_price,
        }

    async def get_funding_rate_history(
        self,
        symbol: str,
        limit: int = 100,
    ) -> list[dict]:
        """История funding rates (до 1000 записей на запрос)."""
        data = await self._get(
            "/fapi/v1/fundingRate",
            {"symbol": symbol, "limit": min(limit, 1000)},
        )
        return [
            {
                "time": d["fundingTime"],
                "rate": float(d["fundingRate"]),
                "rate_pct": float(d["fundingRate"]) * 100,
            }
            for d in data
        ]

    async def get_current_price(self, symbol: str) -> float:
        """Текущая mark price."""
        data = await self._get("/fapi/v1/premiumIndex", {"symbol": symbol})
        return float(data.get("markPrice", 0))

    async def get_orderbook(self, symbol: str, limit: int = 5) -> dict:
        """Стакан ордеров."""
        data = await self._get(
            "/fapi/v1/depth",
            {"symbol": symbol, "limit": limit},
        )
        return {
            "bids": [(float(p), float(q)) for p, q in data.get("bids", [])],
            "asks": [(float(p), float(q)) for p, q in data.get("asks", [])],
        }

    # ── Приватные методы (с подписью) ─────────────────────────────────────

    async def get_balance(self) -> dict[str, float]:
        """
        Баланс аккаунта по всем активам.

        Returns:
            {"USDT": 10000.0, "BTC": 0.0, ...}
        """
        data = await self._signed_get("/fapi/v2/account")
        assets = data.get("assets", [])
        return {
            a["asset"]: float(a["walletBalance"])
            for a in assets
            if float(a["walletBalance"]) > 0
        }

    async def get_account_positions(self) -> list[dict]:
        """
        Все открытые позиции (для сверки с PositionTracker).
        Имплементация протокола PositionDataProvider.
        """
        data = await self._signed_get("/fapi/v2/positionRisk")
        return [
            {
                "symbol": p["symbol"],
                "side": "LONG" if float(p["positionAmt"]) > 0 else "SHORT",
                "quantity": abs(float(p["positionAmt"])),
                "entry_price": float(p["entryPrice"]),
                "unrealized_pnl": float(p["unRealizedProfit"]),
                "leverage": float(p["leverage"]),
            }
            for p in data
            if float(p["positionAmt"]) != 0  # только реально открытые
        ]

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float | None = None,
        client_order_id: str | None = None,
    ) -> dict:
        """
        Размещает ордер.
        Имплементация протокола ExchangeConnector.
        """
        params: dict = {
            "symbol": symbol,
            "side": side.upper(),          # BUY / SELL
            "type": "MARKET" if price is None else "LIMIT",
            "quantity": str(quantity),
        }

        if price is not None:
            params["price"] = str(price)
            params["timeInForce"] = "GTC"

        if client_order_id:
            params["newClientOrderId"] = client_order_id[:36]  # Binance limit

        data = await self._signed_post("/fapi/v1/order", params)
        logger.info(
            f"[Binance] Ордер размещён | {symbol} {side} qty={quantity} "
            f"| orderId={data.get('orderId')}"
        )
        return data

    async def cancel_order(self, symbol: str, exchange_order_id: str) -> bool:
        """Отменяет ордер по exchange order id."""
        try:
            await self._signed_delete(
                "/fapi/v1/order",
                {"symbol": symbol, "orderId": exchange_order_id},
            )
            return True
        except Exception as e:
            logger.error(f"[Binance] Ошибка отмены ордера {exchange_order_id}: {e}")
            return False

    async def get_order_status(self, symbol: str, exchange_order_id: str) -> dict:
        """Статус конкретного ордера."""
        return await self._signed_get(
            "/fapi/v1/order",
            {"symbol": symbol, "orderId": exchange_order_id},
        )

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        """Устанавливает плечо для символа."""
        await self._signed_post(
            "/fapi/v1/leverage",
            {"symbol": symbol, "leverage": leverage},
        )
        logger.info(f"[Binance] Плечо {leverage}x установлено для {symbol}")

    async def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> None:
        """ISOLATED или CROSSED margin."""
        try:
            await self._signed_post(
                "/fapi/v1/marginType",
                {"symbol": symbol, "marginType": margin_type},
            )
        except Exception as e:
            # Ошибка "No need to change" — не критична
            if "no need" in str(e).lower():
                pass
            else:
                raise

    # ── WebSocket ─────────────────────────────────────────────────────────

    async def stream_mark_prices(
        self,
        symbols: list[str],
        callback,
    ) -> None:
        """
        Подписывается на mark price stream (обновления каждые 3 сек).

        Args:
            symbols: ["BTCUSDT", "ETHUSDT"]
            callback: async функция(symbol, mark_price, funding_rate)
        """
        import websockets

        streams = "/".join(f"{s.lower()}@markPrice@3s" for s in symbols)
        url = f"{self._ws_url}/{streams}" if len(symbols) == 1 else \
              f"{self._ws_url.replace('/ws', '/stream')}?streams={streams}"

        logger.info(f"[Binance WS] Подключаюсь к mark price stream: {symbols}")

        while True:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    logger.info("[Binance WS] Соединение установлено")
                    async for message in ws:
                        import json
                        data = json.loads(message)

                        # Одиночный стрим vs combined
                        if "data" in data:
                            data = data["data"]

                        if data.get("e") == "markPriceUpdate":
                            await callback(
                                data["s"],  # symbol
                                float(data["p"]),  # mark price
                                float(data.get("r", 0)),  # funding rate
                            )

            except Exception as e:
                logger.warning(f"[Binance WS] Разрыв соединения: {e}. Переподключение через 5с...")
                await asyncio.sleep(5)

    # ── HTTP хелперы ──────────────────────────────────────────────────────

    async def _get(self, endpoint: str, params: dict | None = None) -> dict | list:
        """Публичный GET запрос (без подписи)."""
        await self._rate_limit()
        try:
            response = await self._client.get(endpoint, params=params or {})
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"[Binance] HTTP {e.response.status_code} на {endpoint}: "
                f"{e.response.text}"
            )
            raise

    async def _signed_get(self, endpoint: str, params: dict | None = None) -> dict | list:
        """Приватный GET с HMAC подписью."""
        await self._rate_limit()
        signed_params = self._sign(params or {})
        try:
            response = await self._client.get(endpoint, params=signed_params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"[Binance] HTTP {e.response.status_code} на {endpoint}: "
                f"{e.response.text}"
            )
            raise

    async def _signed_post(self, endpoint: str, params: dict) -> dict:
        """Приватный POST с HMAC подписью."""
        await self._rate_limit()
        signed_params = self._sign(params)
        try:
            response = await self._client.post(endpoint, data=signed_params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"[Binance] HTTP {e.response.status_code} на {endpoint}: "
                f"{e.response.text}"
            )
            raise

    async def _signed_delete(self, endpoint: str, params: dict) -> dict:
        """Приватный DELETE с HMAC подписью."""
        await self._rate_limit()
        signed_params = self._sign(params)
        try:
            response = await self._client.request("DELETE", endpoint, params=signed_params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"[Binance] HTTP {e.response.status_code} на {endpoint}: "
                f"{e.response.text}"
            )
            raise

    def _sign(self, params: dict) -> dict:
        """Добавляет timestamp и HMAC-SHA256 подпись."""
        params["timestamp"] = int(time.time() * 1000)
        query_string = urlencode(params)
        signature = hmac.new(
            self._api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = signature
        return params

    async def _rate_limit(self) -> None:
        """Простой rate limiter: минимум 50ms между запросами."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self._RATE_LIMIT_DELAY:
            await asyncio.sleep(self._RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = time.monotonic()
