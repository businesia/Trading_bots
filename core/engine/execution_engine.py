"""
core/engine/execution_engine.py
================================
Центральный оркестратор выполнения ордеров.

Все ордера проходят через него:
1. RiskManager проверяет → разрешает или блокирует
2. OrderManager размещает ордер
3. PositionTracker обновляет позицию

Также обрабатывает retry с экспоненциальным backoff.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from loguru import logger

from core.engine.order_manager import OrderManager
from core.engine.position_tracker import PositionTracker
from core.engine.risk_manager import RiskManager
from core.storage.models import BotType, OrderSide, SignalType, Trade

if TYPE_CHECKING:
    pass


# ── Dataclasses ───────────────────────────────────────────────────────────

@dataclass
class OrderRequest:
    """Запрос на размещение ордера от стратегии."""
    symbol: str
    side: OrderSide
    quantity: float
    strategy: SignalType
    price: float | None = None             # None = market order
    size_usd: float = 0.0                  # для проверки риска
    leverage: float = 1.0
    stop_loss: float | None = None
    take_profit: float | None = None
    notes: str | None = None


@dataclass
class ExecutionResult:
    success: bool
    trade: Trade | None = None
    reason: str = ""

    @classmethod
    def ok(cls, trade: Trade) -> "ExecutionResult":
        return cls(success=True, trade=trade)

    @classmethod
    def blocked(cls, reason: str) -> "ExecutionResult":
        return cls(success=False, reason=reason)

    @classmethod
    def failed(cls, reason: str) -> "ExecutionResult":
        return cls(success=False, reason=f"Ошибка исполнения: {reason}")


# ── ExecutionEngine ───────────────────────────────────────────────────────

class ExecutionEngine:
    """
    Единая точка входа для всех ордеров.
    Стратегии вызывают только этот класс, никогда напрямую OrderManager.

    Использование:
        engine = ExecutionEngine(risk_manager, order_manager, position_tracker)

        result = await engine.execute(OrderRequest(
            symbol="BTCUSDT",
            side=OrderSide.LONG,
            quantity=0.001,
            strategy=SignalType.FUNDING_RATE,
            size_usd=45.0,
        ))

        if result.success:
            logger.info(f"Исполнено: trade_id={result.trade.id}")
        else:
            logger.warning(f"Отклонено: {result.reason}")
    """

    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 1.0  # секунды

    def __init__(
        self,
        risk_manager: RiskManager,
        order_manager: OrderManager,
        position_tracker: PositionTracker,
    ) -> None:
        self._risk = risk_manager
        self._orders = order_manager
        self._positions = position_tracker
        self._pending_queue: asyncio.Queue[OrderRequest] = asyncio.Queue()
        self._is_running = False
        self._dedup_cache: set[str] = set()  # предотвращаем дублирование

    async def execute(self, request: OrderRequest) -> ExecutionResult:
        """
        Основной метод: проверяет риск → размещает ордер → обновляет позицию.

        Синхронный: ждёт результата исполнения.
        Для фоновой обработки используй queue_order().
        """
        # Дедупликация
        dedup_key = f"{request.symbol}_{request.side.value}_{request.quantity}"
        if dedup_key in self._dedup_cache:
            return ExecutionResult.blocked(f"Дубликат ордера: {dedup_key}")

        # Проверка риска
        risk_result = await self._risk.check_new_order(
            symbol=request.symbol,
            size_usd=request.size_usd or (request.quantity * (request.price or 0)),
            leverage=request.leverage,
        )

        if not risk_result.allowed:
            logger.warning(
                f"[{self._risk.bot.value}] Ордер заблокирован | "
                f"{request.symbol} {request.side.value}: {risk_result.reason}"
            )
            return ExecutionResult.blocked(risk_result.reason)

        # Исполнение с retry
        self._dedup_cache.add(dedup_key)
        try:
            trade = await self._execute_with_retry(request)
        except Exception as e:
            return ExecutionResult.failed(str(e))
        finally:
            self._dedup_cache.discard(dedup_key)

        # Обновляем статистику риска
        await self._risk.register_order_placed(
            size_usd=request.size_usd,
            leverage=request.leverage,
        )

        # Открываем позицию в трекере
        if request.price:
            await self._positions.open_position(
                symbol=request.symbol,
                side=request.side,
                strategy=request.strategy,
                quantity=request.quantity,
                entry_price=trade.fill_price or request.price,
                stop_loss=request.stop_loss,
                take_profit=request.take_profit,
                leverage=request.leverage,
                is_paper=self._orders._is_paper,
            )

        return ExecutionResult.ok(trade)

    async def close_position(
        self,
        position_id: int,
        symbol: str,
        side: OrderSide,      # противоположная сторона для закрытия
        quantity: float,
        strategy: SignalType,
        price: float | None = None,
        current_price: float = 0.0,
    ) -> ExecutionResult:
        """Закрывает существующую позицию."""
        request = OrderRequest(
            symbol=symbol,
            side=side,
            quantity=quantity,
            strategy=strategy,
            price=price,
            size_usd=quantity * current_price,
        )

        # При закрытии позиции риск-менеджер не блокирует
        try:
            trade = await self._execute_with_retry(request)
        except Exception as e:
            return ExecutionResult.failed(str(e))

        # Закрываем позицию в трекере
        close_price = trade.fill_price or price or current_price
        position = await self._positions.close_position(position_id, exit_price=close_price)

        # Обновляем риск-менеджер
        await self._risk.register_position_closed(
            size_usd=quantity * close_price,
            realized_pnl=position.realized_pnl,
        )

        return ExecutionResult.ok(trade)

    # ── Фоновая очередь ────────────────────────────────────────────────────

    async def queue_order(self, request: OrderRequest) -> None:
        """Добавляет ордер в фоновую очередь (fire-and-forget)."""
        await self._pending_queue.put(request)

    async def start_queue_processor(self) -> None:
        """Запускает фоновую обработку очереди. Вызывать как asyncio задачу."""
        self._is_running = True
        logger.info(f"[{self._risk.bot.value}] ExecutionEngine: очередь ордеров запущена")

        while self._is_running:
            try:
                request = await asyncio.wait_for(
                    self._pending_queue.get(),
                    timeout=1.0,
                )
                result = await self.execute(request)
                if not result.success:
                    logger.warning(f"Ордер из очереди отклонён: {result.reason}")
                self._pending_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Ошибка в очереди ордеров: {e}", exc_info=True)

    async def stop(self) -> None:
        """Останавливает фоновую обработку."""
        self._is_running = False
        logger.info(f"[{self._risk.bot.value}] ExecutionEngine остановлен")

    # ── Retry логика ───────────────────────────────────────────────────────

    async def _execute_with_retry(self, request: OrderRequest) -> Trade:
        """
        Исполняет ордер с экспоненциальным backoff при временных ошибках.

        НЕ делает retry при:
        - REJECTED (биржа отклонила — повтор бессмысленен)
        - Ошибках риск-менеджера
        """
        last_error: Exception | None = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                trade = await self._orders.place_order(
                    symbol=request.symbol,
                    side=request.side,
                    quantity=request.quantity,
                    strategy=request.strategy,
                    price=request.price,
                    stop_loss=request.stop_loss,
                    take_profit=request.take_profit,
                    notes=request.notes,
                )
                return trade

            except Exception as e:
                last_error = e
                # Не делаем retry при явных отказах биржи
                if "rejected" in str(e).lower() or "insufficient" in str(e).lower():
                    logger.error(f"Биржа отклонила ордер (no retry): {e}")
                    raise

                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        f"Попытка {attempt}/{self.MAX_RETRIES} не удалась, "
                        f"retry через {delay}с: {e}"
                    )
                    await asyncio.sleep(delay)

        raise RuntimeError(
            f"Все {self.MAX_RETRIES} попытки исполнения ордера провалились. "
            f"Последняя ошибка: {last_error}"
        )
