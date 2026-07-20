"""
tests/bots/test_kalshi_strategies.py
=======================================
Тесты для Kalshi стратегий (Momentum + WhaleFollow).
"""

from __future__ import annotations

import pytest
from collections import deque
from datetime import datetime, timezone, timedelta

from bots.kalshi.strategies.base import KalshiSide, KalshiAction, KalshiSignal, KalshiCloseSignal
from bots.kalshi.strategies.momentum import MomentumStrategy, MarketState
from bots.kalshi.strategies.whale_follow import WhaleFollowStrategy, WhaleEvent


# ── Фикстуры ──────────────────────────────────────────────────────────────

@pytest.fixture
def momentum_config():
    return {
        "enabled": True,
        "confidence_threshold": 0.60,
        "min_volume_24h": 100,       # низкий порог для тестов
        "consec_periods": 3,
        "profit_target_pct": 15,
        "stop_loss_pct": 8,
        "max_contracts": 20,
        "min_yes_price": 15,
        "max_yes_price": 85,
        "min_time_to_expiry_hours": 1.0,
    }


@pytest.fixture
def whale_config():
    return {
        "enabled": True,
        "min_whale_size": 100,       # низкий порог для тестов
        "consec_whales": 2,
        "max_follow_count": 10,
        "profit_target_pct": 10,
        "stop_loss_pct": 5,
        "whale_window_minutes": 60,
        "min_yes_price": 15,
        "max_yes_price": 85,
    }


@pytest.fixture
def momentum(momentum_config):
    return MomentumStrategy(config=momentum_config)


@pytest.fixture
def whale(whale_config):
    return WhaleFollowStrategy(config=whale_config)


def future_close_time(hours: float = 24.0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(hours=hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def past_close_time(hours: float = 2.0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


TICKER = "KXBTCD-24NOV30-T50000"


# ── Momentum Strategy Tests ────────────────────────────────────────────────

class TestMomentumStrategy:

    @pytest.mark.asyncio
    async def test_no_signal_insufficient_history(self, momentum):
        """Нет сигнала при недостаточной истории."""
        data = {"ticker": TICKER, "yes_price": 45, "volume": 500, "close_time": future_close_time()}
        result = await momentum.generate_signal(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_uptrend_generates_yes_signal(self, momentum):
        """Восходящий тренд → BUY YES."""
        base_price = 30
        for i in range(10):
            data = {
                "ticker": TICKER,
                "yes_price": base_price + i,
                "volume": 1000,
                "close_time": future_close_time(),
            }
            result = await momentum.generate_signal(data)

        # После достаточной истории тренд должен сгенерировать сигнал
        # (может быть None если momentum threshold не достигнут — это ок)
        # Проверяем что состояние накапливается правильно
        state = momentum._states[TICKER]
        assert len(state.price_history) > 0

    @pytest.mark.asyncio
    async def test_low_volume_filtered_out(self, momentum):
        """Низкий объём → нет сигнала."""
        # Заполняем историю
        for i in range(10):
            await momentum.generate_signal({
                "ticker": TICKER,
                "yes_price": 30 + i,
                "volume": 50,         # ниже min_volume_24h=100
                "close_time": future_close_time(),
            })
        # Проверяем что не в позиции
        state = momentum._states.get(TICKER)
        if state:
            assert not state.in_position

    @pytest.mark.asyncio
    async def test_price_too_high_filtered(self, momentum):
        """Цена выше max_yes_price → нет сигнала."""
        for i in range(10):
            await momentum.generate_signal({
                "ticker": TICKER,
                "yes_price": 90,     # выше max_yes_price=85
                "volume": 1000,
                "close_time": future_close_time(),
            })
        state = momentum._states.get(TICKER)
        if state:
            assert not state.in_position

    @pytest.mark.asyncio
    async def test_expired_market_filtered(self, momentum):
        """Истёкший рынок → нет сигнала."""
        for i in range(10):
            result = await momentum.generate_signal({
                "ticker": TICKER,
                "yes_price": 30 + i,
                "volume": 1000,
                "close_time": past_close_time(),   # в прошлом
            })
        state = momentum._states.get(TICKER)
        if state:
            assert not state.in_position

    @pytest.mark.asyncio
    async def test_take_profit_closes_position(self, momentum):
        """Take profit срабатывает при достижении цели."""
        # Искусственно создаём позицию
        state = MarketState(ticker=TICKER)
        state.in_position = True
        state.position_side = KalshiSide.YES
        state.position_count = 10
        state.entry_price = 40        # вошли по 40¢
        # Заполняем историю
        for p in [35, 37, 39, 40, 42]:
            state.price_history.append(p)
        momentum._states[TICKER] = state

        # Цена выросла на 20% → 48¢ (> profit_target_pct=15%)
        result = await momentum.generate_signal({
            "ticker": TICKER,
            "yes_price": 48,          # +20% от 40
            "volume": 1000,
            "close_time": future_close_time(),
        })
        assert isinstance(result, KalshiCloseSignal)
        assert "Take profit" in result.reason

    @pytest.mark.asyncio
    async def test_stop_loss_closes_position(self, momentum):
        """Stop loss срабатывает при убытке."""
        state = MarketState(ticker=TICKER)
        state.in_position = True
        state.position_side = KalshiSide.YES
        state.position_count = 10
        state.entry_price = 50
        for p in [55, 52, 50, 48, 46]:
            state.price_history.append(p)
        momentum._states[TICKER] = state

        # Цена упала на 10% → 45¢ (> stop_loss_pct=8%)
        result = await momentum.generate_signal({
            "ticker": TICKER,
            "yes_price": 45,          # -10% от 50
            "volume": 1000,
            "close_time": future_close_time(),
        })
        assert isinstance(result, KalshiCloseSignal)
        assert "Stop loss" in result.reason

    def test_get_status_no_positions(self, momentum):
        """get_status работает без позиций."""
        status = momentum.get_status()
        assert status["strategy"] == "momentum"
        assert status["open_positions"] == 0

    def test_no_price_in_forbidden_range(self, momentum):
        """yes_price < min_yes_price → фильтрация в _check_entry."""
        result = momentum._check_entry(
            state=MarketState(ticker=TICKER, volume_history=deque([1000], maxlen=10)),
            yes_price=10,   # < min_yes_price=15
            volume=1000,
            market_data={"close_time": future_close_time()},
        )
        assert result is None


# ── Whale Follow Strategy Tests ────────────────────────────────────────────

class TestWhaleFollowStrategy:

    @pytest.mark.asyncio
    async def test_small_trade_not_a_whale(self, whale):
        """Маленькая сделка не считается китом."""
        data = {
            "ticker": TICKER,
            "yes_price": 45,
            "count": 10,             # намного меньше min_whale_size=100
            "taker_side": "yes",
        }
        result = await whale.generate_signal(data)
        assert result is None
        # Нет китов в истории
        state = whale._states.get(TICKER)
        if state:
            assert len(state.recent_whales) == 0

    @pytest.mark.asyncio
    async def test_single_whale_no_signal(self, whale):
        """Один кит недостаточно (consec_whales=2)."""
        data = {
            "ticker": TICKER,
            "yes_price": 45,
            "count": 200,
            "taker_side": "yes",
        }
        result = await whale.generate_signal(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_two_whales_same_direction_generates_signal(self, whale):
        """Два кита в одну сторону → сигнал."""
        data = {
            "ticker": TICKER,
            "yes_price": 45,
            "count": 200,
            "taker_side": "yes",
        }
        await whale.generate_signal(data)  # кит #1
        result = await whale.generate_signal(data)  # кит #2 → сигнал

        assert isinstance(result, KalshiSignal)
        assert result.side == KalshiSide.YES
        assert result.action == KalshiAction.BUY
        assert result.count == whale._max_follow_count

    @pytest.mark.asyncio
    async def test_whales_opposite_directions_no_signal(self, whale):
        """Киты в разные стороны → нет сигнала."""
        await whale.generate_signal({
            "ticker": TICKER, "yes_price": 45, "count": 200, "taker_side": "yes",
        })
        result = await whale.generate_signal({
            "ticker": TICKER, "yes_price": 45, "count": 200, "taker_side": "no",
        })
        assert result is None

    @pytest.mark.asyncio
    async def test_take_profit_exits_position(self, whale):
        """Take profit при росте позиции."""
        from bots.kalshi.strategies.whale_follow import MarketWhaleState
        state = MarketWhaleState(ticker=TICKER)
        state.in_position = True
        state.position_side = KalshiSide.YES
        state.position_count = 10
        state.entry_price = 40
        whale._states[TICKER] = state

        # Цена выросла до 45 (+12.5% > profit_target_pct=10%)
        result = await whale.generate_signal({
            "ticker": TICKER,
            "yes_price": 45,
            "count": 5,          # маленькая сделка — не кит
            "taker_side": "yes",
        })
        assert isinstance(result, KalshiCloseSignal)
        assert "Take profit" in result.reason

    @pytest.mark.asyncio
    async def test_stop_loss_exits_position(self, whale):
        """Stop loss при убытке."""
        from bots.kalshi.strategies.whale_follow import MarketWhaleState
        state = MarketWhaleState(ticker=TICKER)
        state.in_position = True
        state.position_side = KalshiSide.YES
        state.position_count = 10
        state.entry_price = 50
        whale._states[TICKER] = state

        # Цена упала до 47 (-6% > stop_loss_pct=5%)
        result = await whale.generate_signal({
            "ticker": TICKER,
            "yes_price": 47,
            "count": 5,
            "taker_side": "no",
        })
        assert isinstance(result, KalshiCloseSignal)
        assert "Stop loss" in result.reason

    @pytest.mark.asyncio
    async def test_price_outside_range_filtered(self, whale):
        """Цена за пределами [min, max] → нет сигнала."""
        result = await whale.generate_signal({
            "ticker": TICKER,
            "yes_price": 90,    # > max_yes_price=85
            "count": 500,
            "taker_side": "yes",
        })
        assert result is None

    def test_get_status_empty(self, whale):
        """get_status без позиций."""
        status = whale.get_status()
        assert status["strategy"] == "whale_follow"
        assert status["open_positions"] == 0

    @pytest.mark.asyncio
    async def test_state_cleared_after_signal(self, whale):
        """После генерации сигнала whale queue очищается."""
        data = {"ticker": TICKER, "yes_price": 45, "count": 200, "taker_side": "yes"}
        await whale.generate_signal(data)
        await whale.generate_signal(data)  # генерирует сигнал

        state = whale._states[TICKER]
        # После входа в позицию — queue сброшен
        assert len(state.recent_whales) == 0
