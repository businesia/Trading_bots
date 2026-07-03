"""
bots/kalshi/connectors/kalshi_rest.py
======================================
Kalshi REST API коннектор.

Auth: RSA-256 подпись каждого запроса (PKCS#8 private key)
Prod:  https://trading-api.kalshi.com/trade-api/v2
Demo:  https://demo-api.kalshi.co/trade-api/v2

Документация: https://trading-api.kalshi.com/trade-api/v2/docs
"""

from __future__ import annotations

import base64
import hashlib
import time
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from loguru import logger


class KalshiAPIError(Exception):
    """Ошибка Kalshi API с полным телом ответа."""
    def __init__(self, status_code: int, body: str, url: str) -> None:
        self.status_code = status_code
        self.body = body
        self.url = url
        super().__init__(f"Kalshi API {status_code} @ {url}: {body}")


class KalshiRestConnector:
    """
    Kalshi REST API клиент с RSA-подписью запросов.

    Использование:
        async with KalshiRestConnector(api_key, key_path, env="demo") as conn:
            markets = await conn.get_markets(category="crypto")
    """

    PROD_URL = "https://trading-api.kalshi.com/trade-api/v2"
    DEMO_URL = "https://demo-api.kalshi.co/trade-api/v2"

    # Минимальный интервал между запросами (rate limit: ~100 req/10s)
    _REQUEST_DELAY_MS = 110  # 110ms ≈ 9 req/s с запасом

    def __init__(
        self,
        api_key: str,
        private_key_path: str | Path,
        env: str = "demo",
    ) -> None:
        self._api_key = api_key
        self._private_key_path = Path(private_key_path)
        self._base_url = self.PROD_URL if env == "prod" else self.DEMO_URL
        self._env = env

        # Загружается при входе в контекстный менеджер
        self._private_key = None
        self._client: httpx.AsyncClient | None = None
        self._last_request_ts: float = 0.0

    async def __aenter__(self) -> "KalshiRestConnector":
        self._load_private_key()
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers={"Content-Type": "application/json"},
        )
        logger.info(f"[Kalshi REST] Подключён ({self._env}) → {self._base_url}")
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()
            logger.info("[Kalshi REST] Соединение закрыто")

    # ── Авторизация ────────────────────────────────────────────────────────

    def _load_private_key(self) -> None:
        """Загружает RSA приватный ключ из PEM файла."""
        if not self._private_key_path.exists():
            raise FileNotFoundError(
                f"Kalshi private key не найден: {self._private_key_path}"
            )
        with open(self._private_key_path, "rb") as f:
            self._private_key = serialization.load_pem_private_key(f.read(), password=None)
        logger.debug(f"[Kalshi REST] Приватный ключ загружен из {self._private_key_path}")

    def _sign_request(self, method: str, path: str, timestamp_ms: int) -> str:
        """
        Создаёт RSA-256 подпись для запроса.

        Формат подписи (по документации Kalshi):
            message = timestamp_ms + method.upper() + path
        """
        message = f"{timestamp_ms}{method.upper()}{path}"
        signature_bytes = self._private_key.sign(
            message.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return base64.b64encode(signature_bytes).decode("utf-8")

    def _auth_headers(self, method: str, path: str) -> dict[str, str]:
        """Возвращает заголовки авторизации для запроса."""
        timestamp_ms = int(time.time() * 1000)
        signature = self._sign_request(method, path, timestamp_ms)
        return {
            "KALSHI-ACCESS-KEY": self._api_key,
            "KALSHI-ACCESS-TIMESTAMP": str(timestamp_ms),
            "KALSHI-ACCESS-SIGNATURE": signature,
        }

    # ── Rate limiting ──────────────────────────────────────────────────────

    async def _rate_limit(self) -> None:
        """Соблюдает минимальный интервал между запросами."""
        import asyncio
        now = time.monotonic()
        elapsed_ms = (now - self._last_request_ts) * 1000
        if elapsed_ms < self._REQUEST_DELAY_MS:
            await asyncio.sleep((self._REQUEST_DELAY_MS - elapsed_ms) / 1000)
        self._last_request_ts = time.monotonic()

    # ── HTTP методы ────────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict | None = None) -> dict:
        await self._rate_limit()
        headers = self._auth_headers("GET", path)
        resp = await self._client.get(path, params=params, headers=headers)
        return self._handle_response(resp)

    async def _post(self, path: str, body: dict | None = None) -> dict:
        await self._rate_limit()
        headers = self._auth_headers("POST", path)
        resp = await self._client.post(path, json=body or {}, headers=headers)
        return self._handle_response(resp)

    async def _delete(self, path: str) -> dict:
        await self._rate_limit()
        headers = self._auth_headers("DELETE", path)
        resp = await self._client.delete(path, headers=headers)
        return self._handle_response(resp)

    def _handle_response(self, resp: httpx.Response) -> dict:
        """Обрабатывает ответ API, логирует ошибки с полным телом."""
        if resp.status_code >= 400:
            logger.error(
                f"[Kalshi REST] Ошибка {resp.status_code} | "
                f"URL: {resp.url} | Body: {resp.text}"
            )
            raise KalshiAPIError(resp.status_code, resp.text, str(resp.url))
        return resp.json()

    # ── Account ────────────────────────────────────────────────────────────

    async def get_balance(self) -> dict:
        """Возвращает баланс аккаунта."""
        data = await self._get("/portfolio/balance")
        logger.debug(f"[Kalshi REST] Balance: {data}")
        return data

    async def get_positions(self) -> list[dict]:
        """Возвращает открытые позиции."""
        data = await self._get("/portfolio/positions")
        return data.get("market_positions", [])

    async def get_fills(self, limit: int = 100) -> list[dict]:
        """Возвращает историю исполнений."""
        data = await self._get("/portfolio/fills", params={"limit": limit})
        return data.get("fills", [])

    # ── Markets ────────────────────────────────────────────────────────────

    async def get_markets(
        self,
        status: str = "open",
        category: str | None = None,
        series_ticker: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict:
        """
        Возвращает список рынков.

        Args:
            status: open | closed | settled
            category: crypto | economics | politics | weather | sports | ...
            series_ticker: тикер серии (напр. KXBTC)
            limit: до 200
            cursor: для пагинации
        """
        params: dict[str, Any] = {"status": status, "limit": limit}
        if category:
            params["category"] = category
        if series_ticker:
            params["series_ticker"] = series_ticker
        if cursor:
            params["cursor"] = cursor

        return await self._get("/markets", params=params)

    async def get_market(self, ticker: str) -> dict:
        """Возвращает данные конкретного рынка."""
        return await self._get(f"/markets/{ticker}")

    async def get_market_orderbook(self, ticker: str, depth: int = 10) -> dict:
        """Возвращает стакан заявок рынка."""
        return await self._get(
            f"/markets/{ticker}/orderbook",
            params={"depth": depth},
        )

    async def get_market_history(
        self,
        ticker: str,
        start_ts: int | None = None,
        end_ts: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Возвращает историю цен рынка."""
        params: dict[str, Any] = {"limit": limit}
        if start_ts:
            params["min_ts"] = start_ts
        if end_ts:
            params["max_ts"] = end_ts
        data = await self._get(f"/markets/{ticker}/history", params=params)
        return data.get("history", [])

    async def get_trades(
        self,
        ticker: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> list[dict]:
        """Публичные сделки на рынке (для анализа whale activity)."""
        params: dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if cursor:
            params["cursor"] = cursor
        data = await self._get("/markets/trades", params=params)
        return data.get("trades", [])

    # ── Orders ────────────────────────────────────────────────────────────

    async def place_order(
        self,
        ticker: str,
        side: str,               # "yes" | "no"
        action: str,             # "buy" | "sell"
        count: int,              # количество контрактов
        order_type: str = "limit",
        yes_price: int | None = None,    # цена в центах (1-99)
        no_price: int | None = None,
        client_order_id: str | None = None,
    ) -> dict:
        """
        Размещает ордер на Kalshi.

        Kalshi использует yes/no цены в центах (1-99).
        yes_price + no_price = 100 (всегда).

        Args:
            ticker: тикер рынка (напр. KXBTCD-24NOV30-T50000)
            side: "yes" | "no"
            action: "buy" | "sell"
            count: количество контрактов
            yes_price: цена в центах (если side=yes, это лимит)
        """
        body: dict[str, Any] = {
            "ticker": ticker,
            "action": action,
            "side": side,
            "type": order_type,
            "count": count,
        }
        if yes_price is not None:
            body["yes_price"] = yes_price
        if no_price is not None:
            body["no_price"] = no_price
        if client_order_id:
            body["client_order_id"] = client_order_id

        logger.info(
            f"[Kalshi REST] Размещаем ордер: {ticker} {action} {side} "
            f"×{count} @ {yes_price or no_price}¢"
        )
        return await self._post("/portfolio/orders", body=body)

    async def cancel_order(self, order_id: str) -> dict:
        """Отменяет ордер по ID."""
        logger.info(f"[Kalshi REST] Отмена ордера {order_id}")
        return await self._delete(f"/portfolio/orders/{order_id}")

    async def get_orders(
        self,
        ticker: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Возвращает ордера аккаунта."""
        params: dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if status:
            params["status"] = status
        data = await self._get("/portfolio/orders", params=params)
        return data.get("orders", [])

    async def get_order(self, order_id: str) -> dict:
        """Возвращает статус конкретного ордера."""
        return await self._get(f"/portfolio/orders/{order_id}")

    # ── Series & Events ────────────────────────────────────────────────────

    async def get_series(self, series_ticker: str) -> dict:
        """Возвращает данные серии."""
        return await self._get(f"/series/{series_ticker}")

    async def get_events(
        self,
        category: str | None = None,
        status: str = "open",
        limit: int = 100,
    ) -> list[dict]:
        """Возвращает список событий."""
        params: dict[str, Any] = {"status": status, "limit": limit}
        if category:
            params["category"] = category
        data = await self._get("/events", params=params)
        return data.get("events", [])

    # ── Helpers ────────────────────────────────────────────────────────────

    async def get_open_markets_by_category(
        self,
        categories: list[str],
        min_liquidity: float = 1000.0,
        max_time_to_expiry_hours: float = 72.0,
    ) -> list[dict]:
        """
        Возвращает открытые рынки по категориям с фильтрацией.

        Удобный метод для стратегий — фильтрует по ликвидности и времени.
        """
        import asyncio
        from datetime import datetime, timezone

        all_markets: list[dict] = []

        for category in categories:
            data = await self.get_markets(status="open", category=category, limit=200)
            markets = data.get("markets", [])
            all_markets.extend(markets)

        # Фильтрация
        now = datetime.now(timezone.utc)
        filtered: list[dict] = []

        for m in all_markets:
            # Фильтр по ликвидности (volume + open interest как прокси)
            volume = float(m.get("volume", 0))
            open_interest = float(m.get("open_interest", 0))
            liquidity_proxy = volume + open_interest * 100  # грубая оценка

            if liquidity_proxy < min_liquidity:
                continue

            # Фильтр по времени до экспирации
            close_time_str = m.get("close_time") or m.get("expected_expiration_time")
            if close_time_str:
                try:
                    close_dt = datetime.fromisoformat(
                        close_time_str.replace("Z", "+00:00")
                    )
                    hours_left = (close_dt - now).total_seconds() / 3600
                    if hours_left > max_time_to_expiry_hours or hours_left < 0.5:
                        continue
                except ValueError:
                    pass

            filtered.append(m)

        logger.info(
            f"[Kalshi REST] Найдено {len(filtered)}/{len(all_markets)} "
            f"рынков по категориям {categories}"
        )
        return filtered
