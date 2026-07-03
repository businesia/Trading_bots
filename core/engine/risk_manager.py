"""
core/engine/risk_manager.py
============================
Риск-менеджер: центральный страж всех торговых решений.
Ни один ордер не проходит без его одобрения.

Проверяет:
- Дневной лимит убытка (circuit breaker)
- Максимальный размер позиции
- Максимальную суммарную экспозицию
- Kill-switch (принудительная остановка)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import select

from core.storage.database import get_session
from core.storage.models import BotType, RiskEvent

if TYPE_CHECKING:
    pass


# ── Dataclasses ───────────────────────────────────────────────────────────

@dataclass
class RiskConfig:
    """Параметры риска для одного бота. Загружаются из YAML."""
    daily_loss_limit_pct: float = 5.0       # % от дневного начального капитала
    max_position_size_pct: float = 10.0     # % капитала в одной позиции
    max_total_exposure_pct: float = 50.0    # % капитала во всех позициях
    max_leverage: float = 2.0


@dataclass
class RiskCheckResult:
    allowed: bool
    reason: str = ""

    @classmethod
    def ok(cls) -> "RiskCheckResult":
        return cls(allowed=True, reason="")

    @classmethod
    def deny(cls, reason: str) -> "RiskCheckResult":
        return cls(allowed=False, reason=reason)


@dataclass
class DailyStats:
    date: date = field(default_factory=lambda: date.today())
    starting_capital: float = 0.0
    realized_pnl: float = 0.0
    open_pnl: float = 0.0

    @property
    def total_pnl(self) -> float:
        return self.realized_pnl + self.open_pnl

    @property
    def total_pnl_pct(self) -> float:
        if self.starting_capital == 0:
            return 0.0
        return (self.total_pnl / self.starting_capital) * 100


# ── RiskManager ───────────────────────────────────────────────────────────

class RiskManager:
    """
    Единая точка контроля риска для бота.

    Использование:
        risk = RiskManager(bot=BotType.CRYPTO_FUTURES, config=risk_cfg, capital=10_000)
        await risk.initialize()

        result = await risk.check_new_order(symbol="BTCUSDT", size_usd=500)
        if not result.allowed:
            logger.warning(f"Ордер отклонён: {result.reason}")
    """

    def __init__(
        self,
        bot: BotType,
        config: RiskConfig,
        capital: float,
    ) -> None:
        self.bot = bot
        self.config = config
        self._capital = capital

        self._kill_switch: bool = False
        self._trading_paused: bool = False
        self._circuit_breaker_triggered: bool = False

        self._daily_stats = DailyStats(starting_capital=capital)
        self._open_exposure_usd: float = 0.0  # сумма всех открытых позиций

        self._lock = asyncio.Lock()

        logger.info(
            f"RiskManager инициализирован | бот={bot.value} | "
            f"капитал=${capital:,.0f} | "
            f"daily_limit={config.daily_loss_limit_pct}% | "
            f"max_position={config.max_position_size_pct}%"
        )

    async def initialize(self) -> None:
        """Загружает состояние из БД при рестарте."""
        self._reset_daily_stats_if_new_day()
        logger.info(f"[{self.bot.value}] RiskManager готов к работе")

    # ── Основные проверки ──────────────────────────────────────────────────

    async def check_new_order(
        self,
        symbol: str,
        size_usd: float,
        leverage: float = 1.0,
    ) -> RiskCheckResult:
        """
        Проверяет разрешён ли новый ордер.
        Вызывай ПЕРЕД каждым ордером в ExecutionEngine.

        Args:
            symbol: торговая пара
            size_usd: размер позиции в USD (без учёта плеча)
            leverage: плечо (для расчёта реального риска)
        """
        async with self._lock:
            self._reset_daily_stats_if_new_day()

            # 1. Kill-switch
            if self._kill_switch:
                return RiskCheckResult.deny("Kill-switch активирован — торговля остановлена")

            # 2. Пауза
            if self._trading_paused:
                return RiskCheckResult.deny("Торговля на паузе (/resume для возобновления)")

            # 3. Circuit breaker (дневной лимит убытка)
            if self._circuit_breaker_triggered:
                return RiskCheckResult.deny(
                    f"Circuit breaker: дневной убыток превысил "
                    f"{self.config.daily_loss_limit_pct}%"
                )

            # 4. Проверка текущего дневного убытка
            if self._daily_stats.total_pnl_pct <= -self.config.daily_loss_limit_pct:
                await self._trigger_circuit_breaker()
                return RiskCheckResult.deny(
                    f"Circuit breaker: P&L={self._daily_stats.total_pnl_pct:.2f}% "
                    f"превысил лимит -{self.config.daily_loss_limit_pct}%"
                )

            # 5. Максимальный размер одной позиции
            max_position_usd = self._capital * (self.config.max_position_size_pct / 100)
            effective_size = size_usd * leverage
            if effective_size > max_position_usd:
                return RiskCheckResult.deny(
                    f"Позиция ${effective_size:,.0f} превышает лимит "
                    f"${max_position_usd:,.0f} ({self.config.max_position_size_pct}% капитала)"
                )

            # 6. Максимальная суммарная экспозиция
            max_exposure_usd = self._capital * (self.config.max_total_exposure_pct / 100)
            if self._open_exposure_usd + effective_size > max_exposure_usd:
                return RiskCheckResult.deny(
                    f"Суммарная экспозиция ${self._open_exposure_usd + effective_size:,.0f} "
                    f"превысит лимит ${max_exposure_usd:,.0f} "
                    f"({self.config.max_total_exposure_pct}% капитала)"
                )

            # 7. Плечо
            if leverage > self.config.max_leverage:
                return RiskCheckResult.deny(
                    f"Плечо {leverage}x превышает максимум {self.config.max_leverage}x"
                )

            return RiskCheckResult.ok()

    async def register_order_placed(self, size_usd: float, leverage: float = 1.0) -> None:
        """Вызывай после успешного размещения ордера."""
        async with self._lock:
            self._open_exposure_usd += size_usd * leverage
            logger.debug(
                f"[{self.bot.value}] Экспозиция +${size_usd * leverage:,.0f} "
                f"| итого: ${self._open_exposure_usd:,.0f}"
            )

    async def register_position_closed(
        self,
        size_usd: float,
        realized_pnl: float,
        leverage: float = 1.0,
    ) -> None:
        """Вызывай после закрытия позиции."""
        async with self._lock:
            self._open_exposure_usd = max(0.0, self._open_exposure_usd - size_usd * leverage)
            self._daily_stats.realized_pnl += realized_pnl
            self._capital += realized_pnl

            logger.info(
                f"[{self.bot.value}] Позиция закрыта | "
                f"PnL=${realized_pnl:+.2f} | "
                f"Дневной PnL={self._daily_stats.total_pnl_pct:+.2f}%"
            )

            # Проверяем circuit breaker после закрытия
            if self._daily_stats.total_pnl_pct <= -self.config.daily_loss_limit_pct:
                await self._trigger_circuit_breaker()

    async def update_open_pnl(self, open_pnl: float) -> None:
        """Обновляет текущий нереализованный P&L (вызывай периодически)."""
        async with self._lock:
            self._daily_stats.open_pnl = open_pnl

    # ── Kill-switch и паузы ────────────────────────────────────────────────

    async def activate_kill_switch(self, reason: str = "Ручная остановка") -> None:
        """Немедленная остановка всей торговли. Требует рестарта для отмены."""
        async with self._lock:
            self._kill_switch = True
            logger.critical(f"[{self.bot.value}] 🚨 KILL-SWITCH: {reason}")
            await self._log_risk_event("kill_switch", reason)

    async def pause_trading(self, reason: str = "Пауза") -> None:
        """Временная пауза. Возобновляется через /resume."""
        async with self._lock:
            self._trading_paused = True
            logger.warning(f"[{self.bot.value}] ⏸️ Торговля на паузе: {reason}")
            await self._log_risk_event("pause", reason)

    async def resume_trading(self) -> None:
        """Снимает паузу. Kill-switch не снимает."""
        async with self._lock:
            if self._kill_switch:
                logger.error("Kill-switch активен — нельзя возобновить без рестарта")
                return
            self._trading_paused = False
            logger.info(f"[{self.bot.value}] ▶️ Торговля возобновлена")

    # ── Состояние ─────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Возвращает текущее состояние риск-менеджера."""
        return {
            "bot": self.bot.value,
            "kill_switch": self._kill_switch,
            "paused": self._trading_paused,
            "circuit_breaker": self._circuit_breaker_triggered,
            "capital": round(self._capital, 2),
            "open_exposure_usd": round(self._open_exposure_usd, 2),
            "daily_pnl": round(self._daily_stats.total_pnl, 2),
            "daily_pnl_pct": round(self._daily_stats.total_pnl_pct, 2),
            "daily_loss_limit_pct": self.config.daily_loss_limit_pct,
            "trading_allowed": (
                not self._kill_switch
                and not self._trading_paused
                and not self._circuit_breaker_triggered
            ),
        }

    @property
    def is_trading_allowed(self) -> bool:
        return (
            not self._kill_switch
            and not self._trading_paused
            and not self._circuit_breaker_triggered
        )

    # ── Внутренние методы ──────────────────────────────────────────────────

    async def _trigger_circuit_breaker(self) -> None:
        """Активирует circuit breaker и логирует событие."""
        if not self._circuit_breaker_triggered:
            self._circuit_breaker_triggered = True
            msg = (
                f"Circuit breaker! Дневной убыток: "
                f"{self._daily_stats.total_pnl_pct:.2f}% "
                f"(лимит: -{self.config.daily_loss_limit_pct}%)"
            )
            logger.critical(f"[{self.bot.value}] 🔴 {msg}")
            await self._log_risk_event(
                "circuit_breaker",
                msg,
                value=self._daily_stats.total_pnl_pct,
                threshold=-self.config.daily_loss_limit_pct,
            )

    def _reset_daily_stats_if_new_day(self) -> None:
        """Сбрасывает дневную статистику и circuit breaker в начале нового дня."""
        today = date.today()
        if self._daily_stats.date != today:
            logger.info(f"[{self.bot.value}] Новый торговый день — сброс дневной статистики")
            self._daily_stats = DailyStats(
                date=today,
                starting_capital=self._capital,
            )
            self._circuit_breaker_triggered = False  # сброс circuit breaker на новый день

    async def _log_risk_event(
        self,
        event_type: str,
        description: str,
        value: float | None = None,
        threshold: float | None = None,
    ) -> None:
        """Пишет событие риска в БД."""
        try:
            async with get_session() as session:
                event = RiskEvent(
                    bot=self.bot,
                    event_type=event_type,
                    description=description,
                    value=value,
                    threshold=threshold,
                )
                session.add(event)
        except Exception as e:
            logger.error(f"Не удалось записать RiskEvent: {e}")
