"""
bots/crypto_futures/strategies/funding_rate.py
===============================================
Стратегия: Funding Rate Arbitrage (Гипотеза A)

Delta-neutral позиция: Long Spot + Short Perpetual
Собираем funding rate каждые 8 часов без зависимости от направления цены.

Логика портирована из backtest/funding_rate_simulator.py
(симулятор уже подтвердил жизнеспособность стратегии).

Параметры (из config/crypto.yaml):
  stop_threshold: 0.00002      # 0.002%/8h — выходим ниже
  stop_consec: 3               # N подряд плохих периодов → выход
  reentry_threshold: 0.00005   # 0.005%/8h — входим выше
  reentry_consec: 3            # N подряд хороших периодов → вход
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from loguru import logger

from bots.crypto_futures.strategies.base import BaseStrategy, CloseSignal, Signal
from core.engine.execution_engine import OrderRequest
from core.storage.models import OrderSide, SignalType

if TYPE_CHECKING:
    from core.engine.execution_engine import ExecutionEngine
    from core.engine.position_tracker import PositionTracker


# ── State машина ──────────────────────────────────────────────────────────

@dataclass
class SymbolState:
    """Состояние стратегии по одному символу."""
    symbol: str
    in_position: bool = False
    position_id: int | None = None
    entry_price: float = 0.0

    # Счётчики последовательных периодов
    consec_bad: int = 0        # подряд плохих (funding < threshold) — для выхода
    consec_good: int = 0       # подряд хороших (funding > reentry) — для входа

    # История последних funding rates (для логов и диагностики)
    rate_history: deque = field(default_factory=lambda: deque(maxlen=10))

    # Статистика за сессию
    total_collected: float = 0.0   # суммарный funding собрал
    n_entries: int = 0
    n_exits: int = 0


# ── Стратегия ─────────────────────────────────────────────────────────────

class FundingRateStrategy(BaseStrategy):
    """
    Funding Rate Arbitrage стратегия.

    Работает так:
    1. Следит за funding rate каждые 8 часов (или при WebSocket обновлении)
    2. Если rate выше reentry_threshold N раз подряд — открываем позицию
    3. Если rate ниже stop_threshold N раз подряд — закрываем позицию
    4. В позиции: каждые 8 часов собираем funding (rate × capital)

    Важно: сам по себе funding Binance начисляет автоматически при удержании
    позиции. Нам не нужно ничего делать — только не закрывать раньше времени.
    """

    FUNDING_INTERVAL_HOURS = 8  # Binance начисляет каждые 8 часов

    def __init__(
        self,
        config: dict,
        engine: "ExecutionEngine",
        position_tracker: "PositionTracker",
    ) -> None:
        super().__init__(
            name="funding_rate",
            config=config,
            engine=engine,
        )
        self._tracker = position_tracker

        # Параметры из конфига (с дефолтами из симулятора)
        self._stop_threshold = config.get("stop_threshold", 0.00002)
        self._stop_consec = config.get("stop_consec", 3)
        self._reentry_threshold = config.get("reentry_threshold", 0.00005)
        self._reentry_consec = config.get("reentry_consec", 3)
        self._symbols: list[str] = config.get("symbols", ["BTCUSDT"])
        self._capital_per_symbol_pct = config.get("capital_per_symbol_pct", 20)

        # Состояние по каждому символу
        self._states: dict[str, SymbolState] = {
            s: SymbolState(symbol=s) for s in self._symbols
        }

        # Доступный капитал (обновляется из RiskManager)
        self._available_capital: float = 0.0

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def on_start(self) -> None:
        logger.info(
            f"[FundingRate] Стратегия запущена | символы={self._symbols} | "
            f"stop={self._stop_threshold*100:.4f}%/8h | "
            f"reentry={self._reentry_threshold*100:.4f}%/8h"
        )
        # Синхронизируем позиции при рестарте
        open_positions = await self._tracker.get_open_positions()
        for pos in open_positions:
            if pos.symbol in self._states and pos.strategy == SignalType.FUNDING_RATE:
                self._states[pos.symbol].in_position = True
                self._states[pos.symbol].position_id = pos.id
                self._states[pos.symbol].entry_price = pos.entry_price
                logger.info(
                    f"[FundingRate] Восстановлена позиция {pos.symbol} "
                    f"@ ${pos.entry_price:,.2f}"
                )

    async def on_stop(self) -> None:
        logger.info("[FundingRate] Стратегия остановлена")
        self._log_session_summary()

    # ── Главный цикл ──────────────────────────────────────────────────────

    async def generate_signal(self, market_data: dict) -> Signal | CloseSignal | None:
        """
        Принимает обновление market data и возвращает сигнал если нужно.

        market_data структура:
        {
            "symbol": "BTCUSDT",
            "rate": 0.0001,          # funding rate (decimal)
            "mark_price": 45000.0,
        }
        """
        symbol = market_data.get("symbol")
        rate = market_data.get("rate", 0.0)
        mark_price = market_data.get("mark_price", 0.0)

        if symbol not in self._states:
            return None

        state = self._states[symbol]
        state.rate_history.append(rate)

        # Логируем текущий rate
        logger.debug(
            f"[FundingRate] {symbol} rate={rate*100:.4f}%/8h "
            f"APR={rate*3*365*100:.2f}% | in_pos={state.in_position}"
        )

        if state.in_position:
            return await self._check_exit(state, rate, mark_price)
        else:
            return await self._check_entry(state, rate, mark_price)

    async def on_price_update(self, symbol: str, price: float, funding_rate: float) -> None:
        """Обработчик WebSocket обновлений."""
        if not self.is_active:
            return
        await self.generate_signal({
            "symbol": symbol,
            "rate": funding_rate,
            "mark_price": price,
        })

    # ── Логика входа ──────────────────────────────────────────────────────

    async def _check_entry(
        self,
        state: SymbolState,
        rate: float,
        mark_price: float,
    ) -> Signal | None:
        """Проверяет условие входа в позицию."""
        if rate >= self._reentry_threshold:
            state.consec_good += 1
            state.consec_bad = 0

            logger.debug(
                f"[FundingRate] {state.symbol} хороший период "
                f"{state.consec_good}/{self._reentry_consec}"
            )

            if state.consec_good >= self._reentry_consec:
                # Условие выполнено → генерируем сигнал на вход
                quantity = self._calculate_quantity(mark_price)
                state.consec_good = 0

                logger.info(
                    f"[FundingRate] 📈 СИГНАЛ ВХОДА {state.symbol} | "
                    f"rate={rate*100:.4f}%/8h | "
                    f"qty={quantity:.6f} | price=${mark_price:,.2f}"
                )

                return Signal(
                    symbol=state.symbol,
                    direction=OrderSide.LONG,
                    strategy=SignalType.FUNDING_RATE,
                    confidence=self._calculate_confidence(rate),
                    suggested_quantity=quantity,
                    suggested_price=mark_price,
                    notes=(
                        f"Funding rate {rate*100:.4f}%/8h | "
                        f"APR={rate*3*365*100:.2f}% | "
                        f"{state.consec_good} хороших периодов подряд"
                    ),
                )
        else:
            state.consec_good = 0

        return None

    # ── Логика выхода ─────────────────────────────────────────────────────

    async def _check_exit(
        self,
        state: SymbolState,
        rate: float,
        mark_price: float,
    ) -> CloseSignal | None:
        """Проверяет условие выхода из позиции (стоп по funding rate)."""
        if rate < self._stop_threshold:
            state.consec_bad += 1
            state.consec_good = 0

            logger.warning(
                f"[FundingRate] ⚠️ {state.symbol} плохой период "
                f"{state.consec_bad}/{self._stop_consec} | "
                f"rate={rate*100:.4f}%/8h"
            )

            if state.consec_bad >= self._stop_consec:
                state.consec_bad = 0

                logger.info(
                    f"[FundingRate] 📉 СИГНАЛ ВЫХОДА {state.symbol} | "
                    f"rate={rate*100:.4f}%/8h — ниже порога {self._stop_threshold*100:.4f}%/8h"
                )

                if state.position_id is not None:
                    return CloseSignal(
                        position_id=state.position_id,
                        symbol=state.symbol,
                        side=OrderSide.SELL,
                        quantity=self._get_open_quantity(state),
                        strategy=SignalType.FUNDING_RATE,
                        reason=f"Funding rate {rate*100:.4f}%/8h < порога",
                        current_price=mark_price,
                    )
        else:
            state.consec_bad = 0
            # Накапливаем статистику collected funding
            state.total_collected += rate * self._available_capital * \
                                     (self._capital_per_symbol_pct / 100)

        return None

    # ── Обновление состояния ──────────────────────────────────────────────

    def on_position_opened(self, symbol: str, position_id: int, entry_price: float) -> None:
        """Вызывается после успешного открытия позиции."""
        if symbol in self._states:
            state = self._states[symbol]
            state.in_position = True
            state.position_id = position_id
            state.entry_price = entry_price
            state.n_entries += 1

    def on_position_closed(self, symbol: str) -> None:
        """Вызывается после закрытия позиции."""
        if symbol in self._states:
            state = self._states[symbol]
            state.in_position = False
            state.position_id = None
            state.entry_price = 0.0
            state.n_exits += 1

    def update_capital(self, capital: float) -> None:
        """Обновляет доступный капитал (вызывать периодически из main)."""
        self._available_capital = capital

    # ── Вспомогательные методы ────────────────────────────────────────────

    def _calculate_quantity(self, price: float) -> float:
        """Рассчитывает размер позиции исходя из % капитала на символ."""
        if price <= 0 or self._available_capital <= 0:
            return 0.001  # минимум
        position_usd = self._available_capital * (self._capital_per_symbol_pct / 100)
        quantity = position_usd / price
        # Округляем до 3 знаков (для BTC достаточно)
        return round(quantity, 3)

    def _calculate_confidence(self, rate: float) -> float:
        """
        Уверенность = насколько rate выше reentry_threshold.
        Нормализуем в диапазон [0.5, 1.0].
        """
        if rate <= self._reentry_threshold:
            return 0.5
        # Чем выше ставка относительно порога — тем выше уверенность
        ratio = rate / self._reentry_threshold
        return min(0.5 + (ratio - 1) * 0.1, 1.0)

    def _get_open_quantity(self, state: SymbolState) -> float:
        """Размер текущей открытой позиции (берём из стейта или считаем)."""
        if self._available_capital <= 0:
            return 0.001
        position_usd = self._available_capital * (self._capital_per_symbol_pct / 100)
        return round(position_usd / max(state.entry_price, 1), 3)

    def _log_session_summary(self) -> None:
        """Логирует итоги сессии при остановке."""
        for symbol, state in self._states.items():
            logger.info(
                f"[FundingRate] Итоги {symbol}: "
                f"входов={state.n_entries} выходов={state.n_exits} "
                f"собрано_funding=${state.total_collected:.2f}"
            )

    def get_status(self) -> dict:
        """Текущее состояние для Telegram /status."""
        return {
            "strategy": "funding_rate",
            "symbols": {
                symbol: {
                    "in_position": state.in_position,
                    "entry_price": state.entry_price,
                    "consec_bad": state.consec_bad,
                    "consec_good": state.consec_good,
                    "last_rate": state.rate_history[-1] if state.rate_history else 0,
                    "total_collected": round(state.total_collected, 4),
                }
                for symbol, state in self._states.items()
            },
        }
