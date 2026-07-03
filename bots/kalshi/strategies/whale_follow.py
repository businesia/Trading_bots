"""
bots/kalshi/strategies/whale_follow.py
=========================================
Whale Follow стратегия для Kalshi.

Логика (портировано из Krypt Trader):
  - Отслеживает крупные сделки в реальном времени (через WS trade channel)
  - "Кит" = сделка ≥ min_whale_size контрактов за один ордер
  - Если кит купил YES → мы тоже покупаем YES (follow the smart money)
  - Дополнительная фильтрация: смотрим на направление нескольких последних китов

Гипотеза:
  Крупные игроки на prediction markets часто имеют информационное преимущество
  (особенно на политических и экономических рынках). Следование их позициям
  может давать edge.

Риски:
  - Кит может быть маркет-мейкером (хеджирует)
  - Манипуляция: pump-and-dump на малоликвидных рынках
  → Защита: требуем несколько китов в одном направлении (consec_whales)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque

from loguru import logger

from bots.kalshi.strategies.base import (
    BaseKalshiStrategy,
    KalshiAction,
    KalshiCloseSignal,
    KalshiSignal,
    KalshiSide,
)


@dataclass
class WhaleEvent:
    """Одна крупная сделка (кит)."""
    ticker: str
    side: KalshiSide          # купил YES или NO
    count: int                # объём в контрактах
    yes_price: int            # цена в момент сделки (cents)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class MarketWhaleState:
    """Состояние whale-трекера по одному рынку."""
    ticker: str
    recent_whales: Deque[WhaleEvent] = field(
        default_factory=lambda: deque(maxlen=20)
    )
    # Открытая позиция
    in_position: bool = False
    position_side: KalshiSide | None = None
    position_count: int = 0
    entry_price: int = 0


class WhaleFollowStrategy(BaseKalshiStrategy):
    """
    Whale Follow стратегия.

    Алгоритм:
    1. Слушаем trade events через WebSocket
    2. Если сделка ≥ min_whale_size → записываем как "кит"
    3. Если последние consec_whales китов идут в одном направлении → сигнал
    4. Стоп-лосс по фиксированному % от цены входа
    """

    def __init__(self, config: dict) -> None:
        super().__init__(name="whale_follow", config=config)

        # Параметры
        self._min_whale_size = config.get("min_whale_size", 1000)
        self._consec_whales = config.get("consec_whales", 2)      # минимум китов в одну сторону
        self._max_follow_count = config.get("max_follow_count", 10)  # наш размер
        self._profit_target_pct = config.get("profit_target_pct", 10)
        self._stop_loss_pct = config.get("stop_loss_pct", 5)
        self._whale_window_minutes = config.get("whale_window_minutes", 30)  # окно наблюдения
        self._min_yes_price = config.get("min_yes_price", 15)
        self._max_yes_price = config.get("max_yes_price", 85)

        # Состояние по рынкам
        self._states: dict[str, MarketWhaleState] = {}

    async def on_start(self) -> None:
        logger.info(
            f"[WhaleFollow] Запущена | "
            f"min_size={self._min_whale_size} контрактов | "
            f"consec={self._consec_whales} | "
            f"stop={self._stop_loss_pct}% profit={self._profit_target_pct}%"
        )

    async def generate_signal(
        self, market_data: dict
    ) -> KalshiSignal | KalshiCloseSignal | None:
        """
        Обрабатывает trade event и возвращает сигнал.

        Ожидаемые поля market_data (из WS trade channel):
        {
            "ticker": "KXBTCD-24NOV30-T50000",
            "yes_price": 45,          # цена YES в момент сделки
            "count": 500,             # объём сделки в контрактах
            "taker_side": "yes",      # кто взял ликвидность (yes/no)
            "created_time": "2024-..."
        }
        """
        if not self.is_active:
            return None

        ticker = market_data.get("ticker")
        count = market_data.get("count", 0)
        yes_price = market_data.get("yes_price")
        taker_side = market_data.get("taker_side")

        if not all([ticker, yes_price, taker_side]):
            return None

        # Инициализируем состояние
        if ticker not in self._states:
            self._states[ticker] = MarketWhaleState(ticker=ticker)

        state = self._states[ticker]

        # Фильтр: цена в разумном диапазоне
        if not (self._min_yes_price <= yes_price <= self._max_yes_price):
            return None

        # Проверяем: это кит?
        if count >= self._min_whale_size:
            side = KalshiSide.YES if taker_side == "yes" else KalshiSide.NO
            whale = WhaleEvent(
                ticker=ticker,
                side=side,
                count=count,
                yes_price=yes_price,
            )
            state.recent_whales.append(whale)
            logger.info(
                f"[WhaleFollow] 🐋 КИТА замечен: {ticker} | "
                f"{side.value} ×{count} @ {yes_price}¢"
            )

        # Если в позиции — проверяем выход
        if state.in_position:
            return self._check_exit(state, yes_price)

        # Не в позиции — проверяем вход
        return self._check_entry(state, yes_price)

    def _check_entry(
        self,
        state: MarketWhaleState,
        yes_price: int,
    ) -> KalshiSignal | None:
        """Проверяет условие входа после накопления whale signals."""
        if len(state.recent_whales) < self._consec_whales:
            return None

        # Берём только свежих китов (в пределах окна наблюдения)
        now = datetime.now(timezone.utc)
        fresh_whales = [
            w for w in state.recent_whales
            if (now - w.timestamp).total_seconds() < self._whale_window_minutes * 60
        ]

        if len(fresh_whales) < self._consec_whales:
            return None

        # Последние N китов — все в одном направлении?
        recent_n = fresh_whales[-self._consec_whales:]
        sides = [w.side for w in recent_n]

        if len(set(sides)) != 1:
            return None  # разные стороны — неопределённость

        whale_side = sides[0]

        # Взвешиваем по объёму
        total_whale_volume = sum(w.count for w in recent_n)
        avg_whale_size = total_whale_volume / len(recent_n)
        confidence = min(0.5 + (avg_whale_size / self._min_whale_size - 1) * 0.1, 0.95)

        logger.info(
            f"[WhaleFollow] 📈 СИГНАЛ ВХОДА {state.ticker} | "
            f"следуем китам: {whale_side.value} | "
            f"китов={len(recent_n)} | объём={total_whale_volume} | "
            f"conf={confidence:.2f}"
        )

        signal = KalshiSignal(
            ticker=state.ticker,
            side=whale_side,
            action=KalshiAction.BUY,
            count=self._max_follow_count,
            yes_price=yes_price,
            strategy=self._name,
            confidence=confidence,
            notes=(
                f"Китов: {len(recent_n)} | "
                f"суммарный объём: {total_whale_volume} контрактов | "
                f"средний кит: {avg_whale_size:.0f}"
            ),
        )
        self._log_signal(signal)

        # Запоминаем позицию
        state.in_position = True
        state.position_side = whale_side
        state.position_count = self._max_follow_count
        state.entry_price = (
            yes_price if whale_side == KalshiSide.YES else (100 - yes_price)
        )
        state.recent_whales.clear()  # сбрасываем после входа

        return signal

    def _check_exit(
        self,
        state: MarketWhaleState,
        yes_price: int,
    ) -> KalshiCloseSignal | None:
        """Проверяет условие выхода."""
        if not state.position_side or state.entry_price == 0:
            return None

        current_price = (
            yes_price if state.position_side == KalshiSide.YES else (100 - yes_price)
        )
        pnl_pct = (current_price - state.entry_price) / state.entry_price * 100

        reason = None
        if pnl_pct >= self._profit_target_pct:
            reason = f"Take profit: +{pnl_pct:.1f}%"
        elif pnl_pct <= -self._stop_loss_pct:
            reason = f"Stop loss: {pnl_pct:.1f}%"

        # Также выходим если киты начали идти в противоположную сторону
        if not reason and len(state.recent_whales) >= self._consec_whales:
            recent_sides = [w.side for w in list(state.recent_whales)[-self._consec_whales:]]
            opposite = KalshiSide.NO if state.position_side == KalshiSide.YES else KalshiSide.YES
            if all(s == opposite for s in recent_sides):
                reason = f"Киты развернулись: {len(recent_sides)} в {opposite.value}"

        if reason:
            logger.info(
                f"[WhaleFollow] ВЫХОД {state.ticker} | {reason} | "
                f"entry={state.entry_price}¢ current={current_price}¢ "
                f"pnl={pnl_pct:.1f}%"
            )
            signal = KalshiCloseSignal(
                ticker=state.ticker,
                side=state.position_side,
                count=state.position_count,
                strategy=self._name,
                reason=reason,
                current_yes_price=yes_price,
            )
            state.in_position = False
            state.position_side = None
            state.position_count = 0
            state.entry_price = 0
            return signal

        return None

    def get_status(self) -> dict:
        """Текущее состояние для Telegram /status."""
        open_positions = {
            ticker: {
                "side": s.position_side.value if s.position_side else None,
                "count": s.position_count,
                "entry": s.entry_price,
                "whale_queue": len(s.recent_whales),
            }
            for ticker, s in self._states.items()
            if s.in_position
        }
        return {
            "strategy": "whale_follow",
            "active": self._active,
            "tracked_markets": len(self._states),
            "open_positions": len(open_positions),
            "positions": open_positions,
            "total_signals": self._signal_count,
        }
