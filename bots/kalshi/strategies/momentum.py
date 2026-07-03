"""
bots/kalshi/strategies/momentum.py
=====================================
Momentum стратегия для Kalshi.

Логика (портировано из Krypt Trader):
  - Следит за трендом цены YES контракта
  - Если цена растёт N периодов подряд и momentum достаточен → BUY YES
  - Если цена падает N периодов подряд → SELL (или BUY NO)
  - Выход: достигли целевого profit или стоп-лосс

Дополнительные фильтры (anti-Krypt-Trader улучшения):
  - Минимальный объём (игнорируем неликвид)
  - Расстояние от mid (не покупаем на пике/дне)
  - Время до экспирации (не входим в последний час)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from loguru import logger

from bots.kalshi.strategies.base import (
    BaseKalshiStrategy,
    KalshiAction,
    KalshiCloseSignal,
    KalshiSignal,
    KalshiSide,
)


@dataclass
class MarketState:
    """Состояние стратегии по одному рынку."""
    ticker: str
    price_history: deque = field(default_factory=lambda: deque(maxlen=20))
    volume_history: deque = field(default_factory=lambda: deque(maxlen=10))

    # Открытая позиция (если есть)
    in_position: bool = False
    position_side: KalshiSide | None = None
    position_count: int = 0
    entry_price: int = 0         # cents

    # Счётчики тренда
    consec_up: int = 0
    consec_down: int = 0


class MomentumStrategy(BaseKalshiStrategy):
    """
    Momentum стратегия Kalshi.

    Алгоритм:
    1. Накапливаем историю цен (из ticker обновлений)
    2. Считаем momentum = (current - MA) / MA
    3. Если momentum > threshold и объём достаточный → сигнал BUY YES
    4. Стоп-лосс и тейк-профит в процентах от цены входа
    """

    def __init__(self, config: dict) -> None:
        super().__init__(name="momentum", config=config)

        # Параметры из конфига
        self._confidence_threshold = config.get("confidence_threshold", 0.65)
        self._min_volume = config.get("min_volume_24h", 500)
        self._consec_periods = config.get("consec_periods", 3)   # подряд периодов тренда
        self._profit_target_pct = config.get("profit_target_pct", 15)  # % прибыли
        self._stop_loss_pct = config.get("stop_loss_pct", 8)           # % стоп
        self._max_contracts = config.get("max_contracts", 20)
        self._min_yes_price = config.get("min_yes_price", 20)    # не покупаем дороже 80¢ YES
        self._max_yes_price = config.get("max_yes_price", 80)
        self._min_time_to_expiry_hours = config.get("min_time_to_expiry_hours", 2.0)

        # Состояние по рынкам
        self._states: dict[str, MarketState] = {}

    async def on_start(self) -> None:
        logger.info(
            f"[Momentum] Запущена | "
            f"conf_threshold={self._confidence_threshold} | "
            f"stop={self._stop_loss_pct}% profit={self._profit_target_pct}%"
        )

    async def generate_signal(
        self, market_data: dict
    ) -> KalshiSignal | KalshiCloseSignal | None:
        """
        Обрабатывает ticker обновление и возвращает сигнал.

        Ожидаемые поля market_data:
        {
            "ticker": "KXBTCD-24NOV30-T50000",
            "yes_price": 45,         # текущая цена YES в центах
            "volume": 1234,          # объём за 24h в контрактах
            "open_interest": 500,
            "close_time": "2024-11-30T20:00:00Z",  # время экспирации
        }
        """
        if not self.is_active:
            return None

        ticker = market_data.get("ticker")
        yes_price = market_data.get("yes_price")
        volume = market_data.get("volume", 0)

        if not ticker or yes_price is None:
            return None

        # Инициализируем состояние для нового рынка
        if ticker not in self._states:
            self._states[ticker] = MarketState(ticker=ticker)

        state = self._states[ticker]
        state.price_history.append(yes_price)
        state.volume_history.append(volume)

        # Нужно хотя бы consec_periods + 2 точек для анализа
        if len(state.price_history) < self._consec_periods + 2:
            return None

        # Проверяем открытую позицию (сначала — может нужен выход)
        if state.in_position:
            return self._check_exit(state, yes_price, market_data)
        else:
            return self._check_entry(state, yes_price, volume, market_data)

    def _check_entry(
        self,
        state: MarketState,
        yes_price: int,
        volume: int,
        market_data: dict,
    ) -> KalshiSignal | None:
        """Проверяет условие входа в позицию."""

        # Фильтр: слишком низкий объём
        avg_volume = sum(state.volume_history) / len(state.volume_history)
        if avg_volume < self._min_volume:
            return None

        # Фильтр: цена в запрещённом диапазоне (слишком близко к 0 или 100)
        if not (self._min_yes_price <= yes_price <= self._max_yes_price):
            return None

        # Фильтр: мало времени до экспирации
        close_time_str = market_data.get("close_time")
        if close_time_str and not self._has_enough_time(close_time_str):
            return None

        # Считаем тренд
        prices = list(state.price_history)
        recent = prices[-self._consec_periods:]

        # Все последние свечи растут?
        is_uptrend = all(recent[i] < recent[i+1] for i in range(len(recent)-1))
        # Все последние свечи падают?
        is_downtrend = all(recent[i] > recent[i+1] for i in range(len(recent)-1))

        if not is_uptrend and not is_downtrend:
            return None

        # Считаем momentum как отклонение от MA
        ma = sum(prices[-10:]) / min(len(prices), 10)
        momentum = (yes_price - ma) / ma if ma > 0 else 0
        abs_momentum = abs(momentum)

        # Уверенность пропорциональна momentum
        confidence = min(0.5 + abs_momentum * 5, 1.0)
        if confidence < self._confidence_threshold:
            return None

        # Определяем сторону сигнала
        if is_uptrend:
            side = KalshiSide.YES
            price = yes_price
        else:
            side = KalshiSide.NO
            price = 100 - yes_price

        # Количество контрактов (пропорционально уверенности)
        count = max(1, int(self._max_contracts * confidence))

        signal = KalshiSignal(
            ticker=state.ticker,
            side=side,
            action=KalshiAction.BUY,
            count=count,
            yes_price=yes_price,
            strategy=self._name,
            confidence=confidence,
            notes=(
                f"momentum={momentum:.3f} | ma={ma:.1f}¢ | "
                f"vol={volume} | trend={'↑' if is_uptrend else '↓'}"
            ),
        )
        self._log_signal(signal)

        # Обновляем состояние
        state.in_position = True
        state.position_side = side
        state.position_count = count
        state.entry_price = price

        return signal

    def _check_exit(
        self,
        state: MarketState,
        yes_price: int,
        market_data: dict,
    ) -> KalshiCloseSignal | None:
        """Проверяет условие выхода из позиции."""
        if state.position_side is None:
            return None

        # Текущая цена нашей стороны
        current_price = yes_price if state.position_side == KalshiSide.YES else (100 - yes_price)

        # Считаем PnL в процентах
        if state.entry_price > 0:
            pnl_pct = (current_price - state.entry_price) / state.entry_price * 100
        else:
            pnl_pct = 0

        reason = None

        if pnl_pct >= self._profit_target_pct:
            reason = f"Take profit: +{pnl_pct:.1f}%"
        elif pnl_pct <= -self._stop_loss_pct:
            reason = f"Stop loss: {pnl_pct:.1f}%"
        elif not self._has_enough_time(market_data.get("close_time", "")):
            reason = "Мало времени до экспирации"

        if reason:
            logger.info(
                f"[Momentum] ВЫХОД {state.ticker} | {reason} | "
                f"entry={state.entry_price}¢ current={current_price}¢"
            )
            signal = KalshiCloseSignal(
                ticker=state.ticker,
                side=state.position_side,
                count=state.position_count,
                strategy=self._name,
                reason=reason,
                current_yes_price=yes_price,
            )
            # Сбрасываем позицию
            state.in_position = False
            state.position_side = None
            state.position_count = 0
            state.entry_price = 0
            return signal

        return None

    def _has_enough_time(self, close_time_str: str) -> bool:
        """Проверяет, достаточно ли времени до экспирации."""
        if not close_time_str:
            return True
        try:
            close_dt = datetime.fromisoformat(
                close_time_str.replace("Z", "+00:00")
            )
            hours_left = (close_dt - datetime.now(timezone.utc)).total_seconds() / 3600
            return hours_left >= self._min_time_to_expiry_hours
        except ValueError:
            return True

    def get_status(self) -> dict:
        """Текущее состояние для Telegram /status."""
        positions = {
            ticker: {
                "in_position": s.in_position,
                "side": s.position_side.value if s.position_side else None,
                "count": s.position_count,
                "entry_price": s.entry_price,
                "last_price": s.price_history[-1] if s.price_history else None,
            }
            for ticker, s in self._states.items()
            if s.in_position
        }
        return {
            "strategy": "momentum",
            "active": self._active,
            "tracked_markets": len(self._states),
            "open_positions": len(positions),
            "positions": positions,
            "total_signals": self._signal_count,
        }
