"""
tests/bots/test_funding_rate.py
=================================
Тесты для FundingRateStrategy.

Тестируем логику входа/выхода изолированно, без биржи.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from bots.crypto_futures.strategies.funding_rate import FundingRateStrategy, SymbolState
from bots.crypto_futures.strategies.base import Signal, CloseSignal
from core.storage.models import OrderSide, SignalType


# ── Фикстуры ──────────────────────────────────────────────────────────────

@pytest.fixture
def strategy_config():
    return {
        "enabled": True,
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "stop_threshold": 0.00002,
        "stop_consec": 3,
        "reentry_threshold": 0.00005,
        "reentry_consec": 3,
        "capital_per_symbol_pct": 20,
    }


@pytest.fixture
def mock_engine():
    return AsyncMock()


@pytest.fixture
def mock_tracker():
    tracker = AsyncMock()
    tracker.get_open_positions.return_value = []
    return tracker


@pytest.fixture
def strategy(strategy_config, mock_engine, mock_tracker):
    s = FundingRateStrategy(
        config=strategy_config,
        engine=mock_engine,
        position_tracker=mock_tracker,
    )
    s.update_capital(10_000.0)
    return s


# ── Тесты инициализации ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_on_start_restores_empty_positions(strategy, mock_tracker):
    """При старте без позиций стейты остаются чистыми."""
    mock_tracker.get_open_positions.return_value = []
    await strategy.on_start()

    for state in strategy._states.values():
        assert not state.in_position
        assert state.position_id is None


@pytest.mark.asyncio
async def test_on_start_restores_existing_position(strategy, mock_tracker):
    """При рестарте восстанавливаем позиции из БД."""
    from unittest.mock import MagicMock
    pos = MagicMock()
    pos.symbol = "BTCUSDT"
    pos.strategy = SignalType.FUNDING_RATE
    pos.id = 42
    pos.entry_price = 45000.0
    mock_tracker.get_open_positions.return_value = [pos]

    await strategy.on_start()

    state = strategy._states["BTCUSDT"]
    assert state.in_position is True
    assert state.position_id == 42
    assert state.entry_price == 45000.0


# ── Тесты логики входа ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_signal_below_reentry_threshold(strategy):
    """Rate ниже порога → нет сигнала."""
    market_data = {"symbol": "BTCUSDT", "rate": 0.00003, "mark_price": 45000.0}
    result = await strategy.generate_signal(market_data)
    assert result is None


@pytest.mark.asyncio
async def test_entry_signal_after_consec_good_periods(strategy):
    """После N хороших периодов → сигнал на вход."""
    market_data = {"symbol": "BTCUSDT", "rate": 0.0001, "mark_price": 45000.0}

    # Первые два хороших периода — ещё нет сигнала
    result1 = await strategy.generate_signal(market_data)
    result2 = await strategy.generate_signal(market_data)
    assert result1 is None
    assert result2 is None

    # Третий период — сигнал!
    result3 = await strategy.generate_signal(market_data)
    assert isinstance(result3, Signal)
    assert result3.symbol == "BTCUSDT"
    assert result3.direction == OrderSide.LONG
    assert result3.strategy == SignalType.FUNDING_RATE
    assert result3.suggested_quantity > 0


@pytest.mark.asyncio
async def test_consec_counter_resets_on_bad_rate(strategy):
    """Один плохой период сбрасывает счётчик хороших периодов."""
    good = {"symbol": "BTCUSDT", "rate": 0.0001, "mark_price": 45000.0}
    bad = {"symbol": "BTCUSDT", "rate": 0.00001, "mark_price": 45000.0}

    await strategy.generate_signal(good)  # consec_good = 1
    await strategy.generate_signal(good)  # consec_good = 2
    await strategy.generate_signal(bad)   # consec_good = 0 (сброс)
    result = await strategy.generate_signal(good)  # consec_good = 1 — нет сигнала

    assert result is None

    state = strategy._states["BTCUSDT"]
    assert state.consec_good == 1


@pytest.mark.asyncio
async def test_no_entry_when_already_in_position(strategy):
    """Когда уже в позиции — не входим снова."""
    state = strategy._states["BTCUSDT"]
    state.in_position = True
    state.position_id = 1

    market_data = {"symbol": "BTCUSDT", "rate": 0.0001, "mark_price": 45000.0}
    # Это должно попасть в _check_exit, не _check_entry
    result = await strategy.generate_signal(market_data)
    # Нет выхода (хороший rate) — нет сигнала
    assert result is None


# ── Тесты логики выхода ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exit_signal_after_consec_bad_periods(strategy):
    """После N плохих периодов → сигнал на выход."""
    # Входим в позицию
    state = strategy._states["BTCUSDT"]
    state.in_position = True
    state.position_id = 99

    bad = {"symbol": "BTCUSDT", "rate": 0.00001, "mark_price": 45000.0}

    result1 = await strategy.generate_signal(bad)
    result2 = await strategy.generate_signal(bad)
    assert result1 is None
    assert result2 is None

    result3 = await strategy.generate_signal(bad)
    assert isinstance(result3, CloseSignal)
    assert result3.symbol == "BTCUSDT"
    assert result3.position_id == 99


@pytest.mark.asyncio
async def test_no_exit_on_good_rate_in_position(strategy):
    """В позиции при хорошем rate — нет выхода."""
    state = strategy._states["BTCUSDT"]
    state.in_position = True
    state.position_id = 55

    good = {"symbol": "BTCUSDT", "rate": 0.0001, "mark_price": 45000.0}
    result = await strategy.generate_signal(good)
    assert result is None


@pytest.mark.asyncio
async def test_bad_counter_resets_on_good_rate(strategy):
    """Хороший rate сбрасывает счётчик плохих периодов."""
    state = strategy._states["BTCUSDT"]
    state.in_position = True
    state.position_id = 11

    bad = {"symbol": "BTCUSDT", "rate": 0.00001, "mark_price": 45000.0}
    good = {"symbol": "BTCUSDT", "rate": 0.0001, "mark_price": 45000.0}

    await strategy.generate_signal(bad)  # consec_bad = 1
    await strategy.generate_signal(bad)  # consec_bad = 2
    await strategy.generate_signal(good) # consec_bad = 0 (сброс)

    assert state.consec_bad == 0


# ── Тесты расчёта ─────────────────────────────────────────────────────────

def test_calculate_confidence_minimum_for_low_rate(strategy):
    """Rate на уровне порога → уверенность = 0.5."""
    conf = strategy._calculate_confidence(strategy._reentry_threshold)
    assert conf == 0.5


def test_calculate_confidence_grows_with_rate(strategy):
    """Высокий rate → уверенность выше 0.5."""
    low_conf = strategy._calculate_confidence(strategy._reentry_threshold)
    high_conf = strategy._calculate_confidence(strategy._reentry_threshold * 5)
    assert high_conf > low_conf


def test_calculate_confidence_capped_at_one(strategy):
    """Уверенность не превышает 1.0."""
    conf = strategy._calculate_confidence(1.0)  # огромный rate
    assert conf <= 1.0


def test_position_size_proportional_to_capital(strategy):
    """Размер позиции пропорционален капиталу."""
    qty1 = strategy._calculate_quantity(price=45000.0)
    strategy.update_capital(20_000.0)
    qty2 = strategy._calculate_quantity(price=45000.0)
    assert qty2 == pytest.approx(qty1 * 2, rel=0.01)


# ── Тесты управления состоянием ───────────────────────────────────────────

def test_on_position_opened_updates_state(strategy):
    """on_position_opened корректно обновляет стейт."""
    strategy.on_position_opened("BTCUSDT", position_id=7, entry_price=48000.0)
    state = strategy._states["BTCUSDT"]
    assert state.in_position is True
    assert state.position_id == 7
    assert state.entry_price == 48000.0
    assert state.n_entries == 1


def test_on_position_closed_resets_state(strategy):
    """on_position_closed сбрасывает стейт."""
    strategy.on_position_opened("BTCUSDT", position_id=7, entry_price=48000.0)
    strategy.on_position_closed("BTCUSDT")
    state = strategy._states["BTCUSDT"]
    assert state.in_position is False
    assert state.position_id is None
    assert state.n_exits == 1


@pytest.mark.asyncio
async def test_unknown_symbol_returns_none(strategy):
    """Неизвестный символ → None."""
    result = await strategy.generate_signal({
        "symbol": "SOLUSDT", "rate": 0.001, "mark_price": 100.0
    })
    assert result is None


def test_get_status_structure(strategy):
    """get_status возвращает правильную структуру."""
    status = strategy.get_status()
    assert "strategy" in status
    assert "symbols" in status
    assert "BTCUSDT" in status["symbols"]
    assert "ETHUSDT" in status["symbols"]
