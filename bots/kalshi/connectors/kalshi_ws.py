"""
bots/kalshi/connectors/kalshi_ws.py
=====================================
Kalshi WebSocket коннектор — real-time обновления рынков.

WS endpoint: wss://trading-api.kalshi.com/trade-api/ws/v2
Auth: те же RSA-заголовки, что и REST (передаются при подключении)

Подписки (channels):
  - orderbook_delta  — дельты стакана
  - ticker           — last price, volume, open interest
  - trade            — публичные сделки (нужны для whale_follow)
  - fill             — собственные исполнения
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable, Coroutine

import websockets
from loguru import logger

from bots.kalshi.connectors.kalshi_rest import KalshiRestConnector


# Типы callback'ов
TickerCallback = Callable[[str, dict], Coroutine[Any, Any, None]]
TradeCallback = Callable[[str, dict], Coroutine[Any, Any, None]]
OrderbookCallback = Callable[[str, dict], Coroutine[Any, Any, None]]
FillCallback = Callable[[dict], Coroutine[Any, Any, None]]


class KalshiWebSocketConnector:
    """
    WebSocket клиент для Kalshi real-time данных.

    Поддерживает автоматическое переподключение при разрыве.
    Авторизацию делает через RSA-подписанные заголовки (тот же механизм что REST).

    Использование:
        ws = KalshiWebSocketConnector(rest_connector)
        await ws.subscribe_ticker(
            tickers=["KXBTCD-24NOV30-T50000"],
            callback=my_callback,
        )
        await ws.connect()  # блокирует, переподключается автоматически
    """

    PROD_WS_URL = "wss://trading-api.kalshi.com/trade-api/ws/v2"
    DEMO_WS_URL = "wss://demo-api.kalshi.co/trade-api/ws/v2"

    RECONNECT_DELAY = 5.0   # секунды до переподключения
    PING_INTERVAL = 20.0    # секунды между ping

    def __init__(self, rest: KalshiRestConnector) -> None:
        self._rest = rest
        self._ws_url = (
            self.PROD_WS_URL if rest._env == "prod" else self.DEMO_WS_URL
        )

        # Подписки: channel -> (tickers, callback)
        self._subscriptions: list[dict] = []

        # Callbacks по типу сообщений
        self._ticker_callbacks: list[tuple[set[str], TickerCallback]] = []
        self._trade_callbacks: list[tuple[set[str], TradeCallback]] = []
        self._orderbook_callbacks: list[tuple[set[str], OrderbookCallback]] = []
        self._fill_callbacks: list[FillCallback] = []

        self._ws = None
        self._running = False
        self._seq_counter = 0

    # ── Subscription API ──────────────────────────────────────────────────

    def subscribe_ticker(
        self,
        tickers: list[str],
        callback: TickerCallback,
    ) -> None:
        """Подписывается на обновления ticker (last price, volume, OI)."""
        self._ticker_callbacks.append((set(tickers), callback))
        self._subscriptions.append({
            "id": self._next_id(),
            "cmd": "subscribe",
            "params": {
                "channels": ["ticker"],
                "market_tickers": tickers,
            },
        })

    def subscribe_trades(
        self,
        tickers: list[str],
        callback: TradeCallback,
    ) -> None:
        """Подписывается на публичные сделки (нужно для whale_follow)."""
        self._trade_callbacks.append((set(tickers), callback))
        self._subscriptions.append({
            "id": self._next_id(),
            "cmd": "subscribe",
            "params": {
                "channels": ["trade"],
                "market_tickers": tickers,
            },
        })

    def subscribe_orderbook(
        self,
        tickers: list[str],
        callback: OrderbookCallback,
    ) -> None:
        """Подписывается на дельты стакана заявок."""
        self._orderbook_callbacks.append((set(tickers), callback))
        self._subscriptions.append({
            "id": self._next_id(),
            "cmd": "subscribe",
            "params": {
                "channels": ["orderbook_delta"],
                "market_tickers": tickers,
            },
        })

    def subscribe_fills(self, callback: FillCallback) -> None:
        """Подписывается на собственные исполнения."""
        self._fill_callbacks.append(callback)
        self._subscriptions.append({
            "id": self._next_id(),
            "cmd": "subscribe",
            "params": {
                "channels": ["fill"],
            },
        })

    # ── Connection ────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """
        Устанавливает WebSocket соединение и переподключается при разрыве.
        Блокирующий вызов — запускайте как asyncio.Task.
        """
        self._running = True
        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    f"[Kalshi WS] Ошибка соединения: {e}. "
                    f"Переподключение через {self.RECONNECT_DELAY}s..."
                )
                await asyncio.sleep(self.RECONNECT_DELAY)

    async def disconnect(self) -> None:
        """Останавливает WebSocket соединение."""
        self._running = False
        if self._ws:
            await self._ws.close()

    async def _connect_and_listen(self) -> None:
        """Подключается и обрабатывает сообщения до разрыва."""
        auth_headers = self._rest._auth_headers("GET", "/trade-api/ws/v2")

        logger.info(f"[Kalshi WS] Подключение к {self._ws_url}")
        async with websockets.connect(
            self._ws_url,
            additional_headers=auth_headers,
            ping_interval=self.PING_INTERVAL,
        ) as ws:
            self._ws = ws
            logger.info("[Kalshi WS] Подключён ✅")

            # Отправляем все накопленные подписки
            for sub in self._subscriptions:
                await ws.send(json.dumps(sub))
                logger.debug(f"[Kalshi WS] Подписка: {sub['params']}")

            # Обрабатываем входящие сообщения
            async for raw_msg in ws:
                if not self._running:
                    break
                await self._handle_message(raw_msg)

    async def _handle_message(self, raw: str) -> None:
        """Разбирает и маршрутизирует входящее сообщение."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning(f"[Kalshi WS] Невалидный JSON: {e} | raw={raw[:200]}")
            return

        msg_type = msg.get("type")
        channel = msg.get("msg", {}).get("channel") if "msg" in msg else None

        if msg_type == "subscribed":
            logger.debug(f"[Kalshi WS] Подписка подтверждена: {msg}")
            return

        if msg_type == "error":
            logger.error(f"[Kalshi WS] Ошибка от сервера: {msg}")
            return

        if msg_type not in ("orderbook_snapshot", "orderbook_delta", "ticker", "trade", "fill"):
            return

        data = msg.get("msg", msg)
        ticker = data.get("market_ticker", "")

        # Маршрутизация по типу
        if msg_type == "ticker":
            for tickers, cb in self._ticker_callbacks:
                if not tickers or ticker in tickers:
                    await cb(ticker, data)

        elif msg_type == "trade":
            for tickers, cb in self._trade_callbacks:
                if not tickers or ticker in tickers:
                    await cb(ticker, data)

        elif msg_type in ("orderbook_snapshot", "orderbook_delta"):
            for tickers, cb in self._orderbook_callbacks:
                if not tickers or ticker in tickers:
                    await cb(ticker, data)

        elif msg_type == "fill":
            for cb in self._fill_callbacks:
                await cb(data)

    # ── Helpers ────────────────────────────────────────────────────────────

    def _next_id(self) -> int:
        self._seq_counter += 1
        return self._seq_counter
