"""
tests/core/test_risk_manager.py
================================
Тесты для RiskManager — самый критичный компонент.
Запуск: pytest tests/core/test_risk_manager.py -v
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from core.engine.risk_manager import RiskConfig, RiskManager
from core.storage.database import init_db
from core.storage.models import BotType


# ── Фикстуры ──────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    """Временная in-memory SQLite для тестов."""
    await init_db("sqlite+aiosqlite:///:memory:")
    yield


@pytest_asyncio.fixture
async def risk_manager(db):
    """RiskManager с тестовой конфигурацией."""
    config = RiskConfig(
        daily_loss_limit_pct=5.0,
        max_position_size_pct=10.0,
        max_total_exposure_pct=50.0,
        max_leverage=2.0,
    )
    rm = RiskManager(
        bot=BotType.CRYPTO_FUTURES,
        config=config,
        capital=10_000.0,
    )
    await rm.initialize()
    return rm


# ── Тесты: базовые разрешения ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_normal_order_allowed(risk_manager):
    """Обычный ордер в пределах лимитов — должен пройти."""
    result = await risk_manager.check_new_order(
        symbol="BTCUSDT",
        size_usd=500.0,  # 5% от 10k — в пределах 10%
        leverage=1.0,
    )
    assert result.allowed is True
    assert result.reason == ""


@pytest.mark.asyncio
async def test_order_exceeds_position_limit(risk_manager):
    """Ордер больше max_position_size_pct — должен быть отклонён."""
    result = await risk_manager.check_new_order(
        symbol="BTCUSDT",
        size_usd=1_500.0,  # 15% от 10k > лимит 10%
        leverage=1.0,
    )
    assert result.allowed is False
    assert "лимит" in result.reason.lower()


@pytest.mark.asyncio
async def test_leverage_exceeds_limit(risk_manager):
    """Плечо выше лимита — отклонить."""
    result = await risk_manager.check_new_order(
        symbol="BTCUSDT",
        size_usd=100.0,
        leverage=5.0,  # > max_leverage=2.0
    )
    assert result.allowed is False
    assert "плечо" in result.reason.lower()


@pytest.mark.asyncio
async def test_exposure_limit(risk_manager):
    """Суммарная экспозиция не должна превышать max_total_exposure_pct."""
    # Добавляем уже открытые позиции
    await risk_manager.register_order_placed(size_usd=4_000.0)  # 40% открыто

    # Новый ордер на 1500 → итого 55% > лимита 50%
    result = await risk_manager.check_new_order(
        symbol="ETHUSDT",
        size_usd=1_500.0,
        leverage=1.0,
    )
    assert result.allowed is False
    assert "позиц" in result.reason.lower()


# ── Тесты: Kill-switch и паузы ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_kill_switch_blocks_all_orders(risk_manager):
    """После kill-switch все ордера должны быть заблокированы."""
    await risk_manager.activate_kill_switch(reason="Тест")

    result = await risk_manager.check_new_order(
        symbol="BTCUSDT",
        size_usd=100.0,
        leverage=1.0,
    )
    assert result.allowed is False
    assert "kill" in result.reason.lower()


@pytest.mark.asyncio
async def test_pause_blocks_orders(risk_manager):
    """Пауза блокирует новые ордера."""
    await risk_manager.pause_trading(reason="Тест паузы")

    result = await risk_manager.check_new_order(
        symbol="BTCUSDT",
        size_usd=100.0,
    )
    assert result.allowed is False

    # После resume — разблокируются
    await risk_manager.resume_trading()
    result = await risk_manager.check_new_order(
        symbol="BTCUSDT",
        size_usd=100.0,
    )
    assert result.allowed is True


@pytest.mark.asyncio
async def test_kill_switch_cannot_be_resumed(risk_manager):
    """Kill-switch нельзя снять через resume."""
    await risk_manager.activate_kill_switch()
    await risk_manager.resume_trading()  # должно быть проигнорировано

    result = await risk_manager.check_new_order(
        symbol="BTCUSDT",
        size_usd=100.0,
    )
    assert result.allowed is False  # kill-switch всё ещё активен


# ── Тесты: Circuit breaker ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_circuit_breaker_triggers_at_loss_limit(risk_manager):
    """Circuit breaker срабатывает при дневном убытке >= лимита."""
    # Симулируем убыток -5% = -500$ (лимит 5%)
    await risk_manager.register_position_closed(
        size_usd=1000.0,
        realized_pnl=-500.0,  # -5% от 10k
    )

    result = await risk_manager.check_new_order(
        symbol="BTCUSDT",
        size_usd=100.0,
    )
    assert result.allowed is False
    assert "circuit" in result.reason.lower()


@pytest.mark.asyncio
async def test_circuit_breaker_resets_next_day(risk_manager):
    """Circuit breaker сбрасывается на новый торговый день."""
    from datetime import date
    from unittest.mock import patch

    # Активируем circuit breaker
    await risk_manager.register_position_closed(
        size_usd=1000.0,
        realized_pnl=-500.0,
    )
    assert risk_manager._circuit_breaker_triggered is True

    # Симулируем переход на следующий день
    from datetime import timedelta
    tomorrow = date.today() + timedelta(days=1)
    with patch("core.engine.risk_manager.date") as mock_date:
        mock_date.today.return_value = tomorrow
        risk_manager._reset_daily_stats_if_new_day()

    assert risk_manager._circuit_breaker_triggered is False


# ── Тесты: Состояние ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_status_structure(risk_manager):
    """get_status() возвращает все нужные поля."""
    status = risk_manager.get_status()

    required_keys = {
        "bot", "kill_switch", "paused", "circuit_breaker",
        "capital", "daily_pnl", "daily_pnl_pct", "trading_allowed"
    }
    assert required_keys.issubset(status.keys())
    assert status["trading_allowed"] is True
    assert status["capital"] == 10_000.0


@pytest.mark.asyncio
async def test_pnl_tracking(risk_manager):
    """P&L корректно обновляется после закрытия позиции."""
    initial_capital = risk_manager._capital

    await risk_manager.register_position_closed(
        size_usd=1000.0,
        realized_pnl=100.0,  # прибыль
    )

    assert risk_manager._capital == initial_capital + 100.0
    assert risk_manager._daily_stats.realized_pnl == 100.0
