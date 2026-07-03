"""
core/engine/order_manager.py
=============================
Управление ордерами: создание, отправка, трекинг, отмена.

Принцип: каждый ордер пишется в БД ДО отправки на биржу (status=PENDING)
и обновляется ПОСЛЕ получения ответа (SUBMITTED → FILLED/CANCELLED/REJECTED).
Это гарантирует восстановление состояния при рестарте.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from loguru import logger
from sqlalchemy import select

from core.storage.database import get_session
from core.storage.models import (
    BotType,
    OrderSide,
    OrderStatus,
    SignalType,
    Trade,
)


# ── Протокол биржевого коннектора ─────────────────────────────────────────

@runtime_checkable
class ExchangeConnector(Protocol):
    """
    Интерфейс коннектора к бирже.
    Каждый коннектор (Binance, Kalshi и т.д.) должен реализовать этот протокол.
    """

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float | None = None,
        client_order_id: str | None = None,
    ) -> dict:
        """Отправляет ордер на биржу. Возвращает raw ответ биржи."""
        ...

    async def cancel_order(
        self,
        symbol: str,
        exchange_order_id: str,
    ) -> bool:
        """Отменяет ордер. Возвращает True при успехе."""
        ...

    async def get_order_status(
        self,
        symbol: str,
        exchange_order_id: str,
    ) -> dict:
        """Запрашивает статус ордера."""
        ...


# ── OrderManager ──────────────────────────────────────────────────────────

class OrderManager:
    """
    Управляет жизненным циклом ордеров.

    Использование:
        om = OrderManager(bot=BotType.CRYPTO_FUTURES, connector=binance_connector, is_paper=True)

        trade = await om.place_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=0.001,
            strategy=SignalType.FUNDING_RATE,
        )
    """

    def __init__(
        self,
        bot: BotType,
        connector: ExchangeConnector | None,
        is_paper: bool = True,
    ) -> None:
        self.bot = bot
        self._connector = connector
        self._is_paper = is_paper

        if is_paper:
            logger.info(f"[{bot.value}] OrderManager в режиме PAPER TRADING")
        else:
            logger.warning(f"[{bot.value}] OrderManager в режиме LIVE TRADING — реальные ордера!")

    # ── Основные операции ──────────────────────────────────────────────────

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        strategy: SignalType,
        price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        notes: str | None = None,
    ) -> Trade:
        """
        Размещает ордер.

        1. Создаёт запись в БД со статусом PENDING
        2. Отправляет на биржу (или симулирует в paper mode)
        3. Обновляет запись в БД

        Args:
            symbol: торговая пара ("BTCUSDT", "BTC-NLYEAR-ABOVE-100K")
            side: направление (BUY/SELL/LONG/SHORT)
            quantity: количество в базовом активе
            strategy: какая стратегия сгенерировала ордер
            price: None = market order
            stop_loss, take_profit: опциональные уровни
            notes: свободный текст для отладки
        """
        client_order_id = self._generate_client_id()

        # ── Шаг 1: Пишем в БД (PENDING) ───────────────────────────────────
        trade = Trade(
            bot=self.bot,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            strategy=strategy,
            quantity=quantity,
            price=price,
            status=OrderStatus.PENDING,
            is_paper=self._is_paper,
            notes=notes,
        )

        async with get_session() as session:
            session.add(trade)
            await session.flush()  # получаем id до commit
            trade_id = trade.id

        logger.info(
            f"[{self.bot.value}] Ордер создан | id={trade_id} | "
            f"{symbol} {side.value} qty={quantity} | paper={self._is_paper}"
        )

        # ── Шаг 2: Отправляем или симулируем ──────────────────────────────
        if self._is_paper:
            updated_trade = await self._simulate_fill(trade)
        else:
            updated_trade = await self._submit_to_exchange(trade)

        return updated_trade

    async def cancel_order(self, trade_id: int) -> bool:
        """
        Отменяет ордер по внутреннему ID.
        Возвращает True при успехе.
        """
        async with get_session() as session:
            trade = await session.get(Trade, trade_id)
            if trade is None:
                logger.error(f"Ордер id={trade_id} не найден")
                return False

            if trade.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
                logger.warning(f"Ордер id={trade_id} уже {trade.status.value}")
                return False

            if not self._is_paper and self._connector and trade.exchange_order_id:
                try:
                    success = await self._connector.cancel_order(
                        symbol=trade.symbol,
                        exchange_order_id=trade.exchange_order_id,
                    )
                    if not success:
                        logger.error(f"Биржа отклонила отмену ордера id={trade_id}")
                        return False
                except Exception as e:
                    logger.error(f"Ошибка при отмене ордера id={trade_id}: {e}")
                    return False

            trade.status = OrderStatus.CANCELLED
            trade.updated_at = datetime.now(timezone.utc)
            session.add(trade)

        logger.info(f"[{self.bot.value}] Ордер отменён | id={trade_id}")
        return True

    async def get_open_orders(self, symbol: str | None = None) -> list[Trade]:
        """Возвращает все незакрытые ордера (PENDING или SUBMITTED)."""
        async with get_session() as session:
            stmt = select(Trade).where(
                Trade.bot == self.bot,
                Trade.status.in_([OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIAL]),
            )
            if symbol:
                stmt = stmt.where(Trade.symbol == symbol)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_trade_history(
        self,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[Trade]:
        """Последние N исполненных ордеров."""
        async with get_session() as session:
            stmt = (
                select(Trade)
                .where(
                    Trade.bot == self.bot,
                    Trade.status == OrderStatus.FILLED,
                )
                .order_by(Trade.filled_at.desc())
                .limit(limit)
            )
            if symbol:
                stmt = stmt.where(Trade.symbol == symbol)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # ── Внутренние методы ──────────────────────────────────────────────────

    async def _simulate_fill(self, trade: Trade) -> Trade:
        """
        Paper trading: симулируем мгновенное исполнение по указанной цене.
        Для market order — цена = None (реальную цену подставит стратегия).
        """
        now = datetime.now(timezone.utc)
        async with get_session() as session:
            trade = await session.get(Trade, trade.id)
            trade.status = OrderStatus.FILLED
            trade.fill_price = trade.price  # в paper mode принимаем заявленную цену
            trade.fill_quantity = trade.quantity
            trade.submitted_at = now
            trade.filled_at = now
            # Симулируем комиссию: 0.04% taker
            trade.fee = trade.quantity * (trade.price or 0) * 0.0004
            trade.fee_asset = "USDT"
            session.add(trade)

        logger.success(
            f"[{self.bot.value}] [PAPER] Ордер исполнен | "
            f"id={trade.id} | {trade.symbol} {trade.side.value} "
            f"@ {trade.fill_price} | fee=${trade.fee:.4f}"
        )
        return trade

    async def _submit_to_exchange(self, trade: Trade) -> Trade:
        """Реальная отправка ордера на биржу."""
        if self._connector is None:
            raise RuntimeError("Нет коннектора для live trading")

        now = datetime.now(timezone.utc)

        try:
            # Отправляем
            response = await self._connector.place_order(
                symbol=trade.symbol,
                side=trade.side.value,
                quantity=trade.quantity,
                price=trade.price,
                client_order_id=trade.client_order_id,
            )

            async with get_session() as session:
                trade = await session.get(Trade, trade.id)
                trade.exchange_order_id = str(response.get("orderId", ""))
                trade.submitted_at = now

                # Проверяем статус из ответа
                exchange_status = response.get("status", "").upper()
                if exchange_status == "FILLED":
                    trade.status = OrderStatus.FILLED
                    trade.fill_price = float(response.get("avgPrice") or response.get("price", 0))
                    trade.fill_quantity = float(response.get("executedQty", trade.quantity))
                    trade.filled_at = now
                    trade.fee = float(response.get("commission", 0))
                elif exchange_status in ("NEW", "PARTIALLY_FILLED"):
                    trade.status = OrderStatus.SUBMITTED
                else:
                    trade.status = OrderStatus.REJECTED
                    trade.notes = f"Биржа: {exchange_status} | raw: {response}"

                session.add(trade)

            logger.success(
                f"[{self.bot.value}] Ордер отправлен | "
                f"id={trade.id} exchange_id={trade.exchange_order_id} | "
                f"статус={trade.status.value}"
            )

        except Exception as e:
            # Фиксируем ошибку в БД
            async with get_session() as session:
                trade = await session.get(Trade, trade.id)
                trade.status = OrderStatus.FAILED
                trade.notes = f"Ошибка: {type(e).__name__}: {e}"
                session.add(trade)

            logger.error(
                f"[{self.bot.value}] Ошибка размещения ордера id={trade.id}: {e}",
                exc_info=True,
            )
            raise

        return trade

    @staticmethod
    def _generate_client_id() -> str:
        """Генерирует уникальный client_order_id."""
        return f"tb_{uuid.uuid4().hex[:16]}"
