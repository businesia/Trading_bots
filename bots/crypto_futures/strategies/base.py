"""
bots/crypto_futures/strategies/base.py
=======================================
Базовый класс для всех крипто-стратегий.
Каждая стратегия наследует BaseStrategy и реализует generate_signal().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from core.storage.models import OrderSide, SignalType

if TYPE_CHECKING:
    from core.engine.execution_engine import ExecutionEngine


# ── Signal ────────────────────────────────────────────────────────────────

@dataclass
class Signal:
    """
    Торговый сигнал от стратегии.
    ExecutionEngine решает: исполнять или нет (через RiskManager).
    """
    symbol: str
    direction: OrderSide          # BUY/SELL/LONG/SHORT
    strategy: SignalType
    confidence: float             # 0.0 – 1.0
    suggested_quantity: float
    suggested_price: float | None = None   # None = market order
    stop_loss: float | None = None
    take_profit: float | None = None
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __str__(self) -> str:
        return (
            f"Signal({self.strategy.value} {self.symbol} {self.direction.value} "
            f"qty={self.suggested_quantity} conf={self.confidence:.2f})"
        )


@dataclass
class CloseSignal:
    """Сигнал на закрытие существующей позиции."""
    position_id: int
    symbol: str
    side: OrderSide          # противоположная сторона для закрытия
    quantity: float
    strategy: SignalType
    reason: str = ""
    current_price: float = 0.0


# ── BaseStrategy ──────────────────────────────────────────────────────────

class BaseStrategy(ABC):
    """
    Абстрактный базовый класс для всех крипто-стратегий.

    Реализуй:
        generate_signal() → Signal | None
        on_price_update()  → опционально

    Шаблон добавления стратегии:
        1. Создай файл bots/crypto_futures/strategies/my_strategy.py
        2. class MyStrategy(BaseStrategy)
        3. Реализуй generate_signal()
        4. Добавь в config/crypto.yaml → strategies: my_strategy: enabled: true
        5. Зарегистрируй в main.py
    """

    def __init__(
        self,
        name: str,
        config: dict,
        engine: "ExecutionEngine",
    ) -> None:
        self.name = name
        self.config = config
        self._engine = engine
        self._is_active = True

    @abstractmethod
    async def generate_signal(self, market_data: dict) -> Signal | CloseSignal | None:
        """
        Анализирует рыночные данные и генерирует сигнал или None.

        Args:
            market_data: данные от коннектора (цена, funding rate, объём и т.д.)

        Returns:
            Signal — открыть позицию
            CloseSignal — закрыть позицию
            None — нет сигнала
        """
        ...

    async def on_start(self) -> None:
        """Вызывается при старте бота. Переопредели для инициализации."""
        pass

    async def on_stop(self) -> None:
        """Вызывается при остановке бота."""
        pass

    async def on_price_update(self, symbol: str, price: float, funding_rate: float) -> None:
        """
        Вызывается при каждом обновлении цены (из WebSocket).
        Переопредели для стратегий реагирующих на tick-данные.
        """
        pass

    def pause(self) -> None:
        self._is_active = False

    def resume(self) -> None:
        self._is_active = True

    @property
    def is_active(self) -> bool:
        return self._is_active
