"""
core/engine/position_tracker.py
================================
Трекер позиций: актуальный P&L, синхронизация с биржей.
При рестарте сверяет локальную БД с реальным счётом биржи.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from loguru import logger
from sqlalchemy import select

from core.storage.database import get_session
from core.storage.models import (
    BotType,
    OrderSide,
    Position,
    PositionStatus,
    SignalType,
    Trade,
    OrderStatus,
)


# ── Протокол для получения данных с биржи ─────────────────────────────────

class PositionDataProvider(Protocol):
    async def get_account_positions(self) -> list[dict]:
        """Возвращает все открытые позиции с биржи."""
        ...

    async def get_current_price(self, symbol: str) -> float:
        """Текущая цена актива."""
        ...


# ── PositionTracker ───────────────────────────────────────────────────────

class PositionTracker:
    """
    Отслеживает открытые позиции и P&L.

    Использование:
        tracker = PositionTracker(bot=BotType.CRYPTO_FUTURES, provider=binance)
        await tracker.reconcile_with_exchange()  # при старте

        pos = await tracker.open_position(trade=trade, entry_price=45000)
        await tracker.update_prices({"BTCUSDT": 46000})
        summary = await tracker.get_summary()
    """

    def __init__(
        self,
        bot: BotType,
        provider: PositionDataProvider | None = None,
    ) -> None:
        self.bot = bot
        self._provider = provider
        self._price_cache: dict[str, float] = {}

    # ── Открытие / закрытие позиций ────────────────────────────────────────

    async def open_position(
        self,
        symbol: str,
        side: OrderSide,
        strategy: SignalType,
        quantity: float,
        entry_price: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        leverage: float = 1.0,
        is_paper: bool = True,
    ) -> Position:
        """Создаёт запись об открытой позиции в БД."""
        position = Position(
            bot=self.bot,
            symbol=symbol,
            side=side,
            strategy=strategy,
            quantity=quantity,
            entry_price=entry_price,
            current_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            leverage=leverage,
            status=PositionStatus.OPEN,
            is_paper=is_paper,
        )

        async with get_session() as session:
            session.add(position)
            await session.flush()
            pos_id = position.id

        logger.info(
            f"[{self.bot.value}] Позиция открыта | id={pos_id} | "
            f"{symbol} {side.value} qty={quantity} @ ${entry_price:,.2f}"
        )
        return position

    async def close_position(
        self,
        position_id: int,
        exit_price: float,
    ) -> Position:
        """Закрывает позицию и фиксирует финальный P&L."""
        async with get_session() as session:
            position = await session.get(Position, position_id)
            if position is None:
                raise ValueError(f"Позиция id={position_id} не найдена")

            if position.status == PositionStatus.CLOSED:
                logger.warning(f"Позиция id={position_id} уже закрыта")
                return position

            position.exit_price = exit_price
            position.current_price = exit_price
            position.realized_pnl = self._calculate_pnl(position, exit_price)
            position.unrealized_pnl = 0.0
            position.status = PositionStatus.CLOSED
            position.closed_at = datetime.now(timezone.utc)
            session.add(position)

        logger.info(
            f"[{self.bot.value}] Позиция закрыта | id={position_id} | "
            f"exit=${exit_price:,.2f} | PnL=${position.realized_pnl:+.2f}"
        )
        return position

    # ── Обновление цен ────────────────────────────────────────────────────

    async def update_prices(self, prices: dict[str, float]) -> dict[str, float]:
        """
        Обновляет текущие цены и пересчитывает unrealized P&L.

        Args:
            prices: {"BTCUSDT": 46000.0, "ETHUSDT": 3200.0}

        Returns:
            {"BTCUSDT": <unrealized_pnl>, ...}
        """
        self._price_cache.update(prices)
        pnl_by_symbol: dict[str, float] = {}

        async with get_session() as session:
            stmt = select(Position).where(
                Position.bot == self.bot,
                Position.status == PositionStatus.OPEN,
            )
            result = await session.execute(stmt)
            open_positions = result.scalars().all()

            for pos in open_positions:
                if pos.symbol in prices:
                    current_price = prices[pos.symbol]
                    pos.current_price = current_price
                    pos.unrealized_pnl = self._calculate_pnl(pos, current_price)
                    session.add(pos)
                    pnl_by_symbol[pos.symbol] = (
                        pnl_by_symbol.get(pos.symbol, 0) + pos.unrealized_pnl
                    )

        return pnl_by_symbol

    # ── Синхронизация с биржей ────────────────────────────────────────────

    async def reconcile_with_exchange(self) -> None:
        """
        Сверяет локальную БД с реальным состоянием счёта на бирже.
        Вызывай при рестарте бота.

        Если на бирже есть позиции которых нет в БД — логирует предупреждение.
        Если в БД есть позиции которых нет на бирже — закрывает их.
        """
        if self._provider is None:
            logger.info(f"[{self.bot.value}] Нет провайдера данных — сверка пропущена")
            return

        logger.info(f"[{self.bot.value}] Начинаю сверку с биржей...")

        try:
            exchange_positions = await self._provider.get_account_positions()
            exchange_symbols = {p["symbol"] for p in exchange_positions}
        except Exception as e:
            logger.error(f"Ошибка при получении позиций с биржи: {e}")
            return

        async with get_session() as session:
            stmt = select(Position).where(
                Position.bot == self.bot,
                Position.status == PositionStatus.OPEN,
            )
            result = await session.execute(stmt)
            local_positions = result.scalars().all()

        local_symbols = {p.symbol for p in local_positions}

        # Позиции на бирже, которых нет в БД
        unknown = exchange_symbols - local_symbols
        if unknown:
            logger.warning(
                f"[{self.bot.value}] ⚠️ На бирже есть позиции не в БД: {unknown}. "
                f"Проверь вручную!"
            )

        # Позиции в БД, которых нет на бирже (были закрыты пока бот не работал)
        ghost = local_symbols - exchange_symbols
        if ghost:
            logger.warning(
                f"[{self.bot.value}] Позиции в БД без подтверждения на бирже: {ghost}. "
                f"Помечаю как закрытые."
            )
            for pos in local_positions:
                if pos.symbol in ghost:
                    # Закрываем по последней известной цене
                    price = self._price_cache.get(pos.symbol, pos.entry_price)
                    await self.close_position(pos.id, exit_price=price)

        logger.info(f"[{self.bot.value}] Сверка завершена | локальных={len(local_positions)}")

    # ── Отчёт ────────────────────────────────────────────────────────────

    async def get_open_positions(self) -> list[Position]:
        """Возвращает все открытые позиции из БД."""
        async with get_session() as session:
            stmt = select(Position).where(
                Position.bot == self.bot,
                Position.status == PositionStatus.OPEN,
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_summary(self) -> dict:
        """Сводка по позициям для Telegram /status."""
        positions = await self.get_open_positions()
        total_unrealized = sum(p.unrealized_pnl for p in positions)
        total_exposure = sum(p.quantity * (p.current_price or p.entry_price) for p in positions)

        return {
            "bot": self.bot.value,
            "open_positions": len(positions),
            "total_unrealized_pnl": round(total_unrealized, 2),
            "total_exposure_usd": round(total_exposure, 2),
            "positions": [
                {
                    "id": p.id,
                    "symbol": p.symbol,
                    "side": p.side.value,
                    "quantity": p.quantity,
                    "entry_price": p.entry_price,
                    "current_price": p.current_price,
                    "unrealized_pnl": round(p.unrealized_pnl, 2),
                    "strategy": p.strategy.value,
                }
                for p in positions
            ],
        }

    # ── Расчёты ───────────────────────────────────────────────────────────

    @staticmethod
    def _calculate_pnl(position: Position, current_price: float) -> float:
        """Рассчитывает unrealized/realized PnL с учётом стороны и плеча."""
        if position.side in (OrderSide.BUY, OrderSide.LONG):
            raw_pnl = (current_price - position.entry_price) * position.quantity
        else:
            raw_pnl = (position.entry_price - current_price) * position.quantity

        return raw_pnl * position.leverage
