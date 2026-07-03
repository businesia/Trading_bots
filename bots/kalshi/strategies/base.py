"""
bots/kalshi/strategies/base.py
================================
Базовый класс стратегии для Kalshi бота.

Kalshi-специфика:
  - Контракты бинарные: YES / NO
  - Цена в центах (1-99), выплата $1 при правильном исходе
  - Ликвидность ниже чем на крипто-биржах
  - Рынки имеют дату экспирации
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from core.engine.execution_engine import ExecutionEngine


class KalshiSide(str, Enum):
    YES = "yes"
    NO = "no"


class KalshiAction(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class KalshiSignal:
    """Сигнал для покупки/продажи Kalshi контракта."""

    # Что торгуем
    ticker: str                       # тикер рынка (напр. KXBTCD-24NOV30-T50000)
    side: KalshiSide                  # YES или NO
    action: KalshiAction              # buy или sell
    count: int                        # количество контрактов

    # Ценообразование
    yes_price: int                    # цена YES в центах (1-99)

    # Мета
    strategy: str                     # имя стратегии
    confidence: float = 0.5          # уверенность [0, 1]
    notes: str = ""

    # Рассчитывается автоматически
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def no_price(self) -> int:
        """Цена NO всегда дополняет YES до 100."""
        return 100 - self.yes_price

    @property
    def cost_cents(self) -> int:
        """Стоимость позиции в центах."""
        price = self.yes_price if self.side == KalshiSide.YES else self.no_price
        return self.count * price

    @property
    def cost_usd(self) -> float:
        """Стоимость позиции в долларах."""
        return self.cost_cents / 100


@dataclass
class KalshiCloseSignal:
    """Сигнал на закрытие позиции (продажа открытой позиции)."""

    ticker: str
    side: KalshiSide          # сторона открытой позиции (продаём ту же сторону)
    count: int
    strategy: str
    reason: str
    current_yes_price: int    # текущая цена для расчёта PnL


# ── Базовый класс стратегии ───────────────────────────────────────────────

class BaseKalshiStrategy(ABC):
    """
    Базовый класс для всех Kalshi стратегий.

    Каждая стратегия:
    1. Принимает market_data (из WebSocket или REST поллинга)
    2. Анализирует данные
    3. Возвращает KalshiSignal | KalshiCloseSignal | None

    Стратегии не взаимодействуют с биржей напрямую —
    только через ExecutionEngine (через KalshiOrderManager).
    """

    def __init__(
        self,
        name: str,
        config: dict,
    ) -> None:
        self._name = name
        self._config = config
        self._active = True
        self._signal_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_active(self) -> bool:
        return self._active

    def pause(self) -> None:
        """Приостанавливает стратегию (без остановки бота)."""
        self._active = False
        logger.info(f"[{self._name}] Стратегия приостановлена")

    def resume(self) -> None:
        """Возобновляет стратегию."""
        self._active = True
        logger.info(f"[{self._name}] Стратегия возобновлена")

    @abstractmethod
    async def generate_signal(
        self, market_data: dict
    ) -> KalshiSignal | KalshiCloseSignal | None:
        """
        Анализирует market_data и возвращает сигнал или None.

        market_data структура зависит от типа данных:
        - ticker update: {"ticker": "...", "yes_price": 45, "volume": 1234, ...}
        - trade: {"ticker": "...", "count": 50, "yes_price": 45, "taker_side": "yes"}
        - orderbook: {"ticker": "...", "yes": [[price, size], ...], "no": [...]}
        """
        ...

    async def on_start(self) -> None:
        """Вызывается при запуске стратегии. Переопределяй при необходимости."""
        logger.info(f"[{self._name}] Стратегия запущена")

    async def on_stop(self) -> None:
        """Вызывается при остановке стратегии."""
        logger.info(f"[{self._name}] Стратегия остановлена | сигналов={self._signal_count}")

    def _log_signal(self, signal: KalshiSignal) -> None:
        """Логирует сигнал."""
        self._signal_count += 1
        logger.info(
            f"[{self._name}] Сигнал #{self._signal_count}: "
            f"{signal.ticker} {signal.action.value} {signal.side.value} "
            f"×{signal.count} @ {signal.yes_price}¢ | "
            f"conf={signal.confidence:.2f} | {signal.notes}"
        )
