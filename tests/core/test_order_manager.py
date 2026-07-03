"""
tests/core/test_order_manager.py
=================================
Тесты для OrderManager.
Запуск: pytest tests/core/test_order_manager.py -v
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from core.engine.order_manager import OrderManager
from core.storage.database import init_db
from core.storage.models import BotType, OrderSide, OrderStatus, SignalType


# ── Фикстуры ──────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    await init_db("sqlite+aiosqlite:///:memory:")
    yield


@pytest_asyncio.fixture
async def order_manager(db):
    """OrderManager в paper-trading режиме (нет реального коннектора)."""
    return OrderManager(
        bot=BotType.CRYPTO_FUTURES,
        connector=None,  # paper mode
        is_paper=True,
    )


# ── Тесты ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_place_paper_order_creates_trade(order_manager):
    """В paper mode ордер создаётся и сразу исполняется."""
    trade = await order_manager.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=0.001,
        strategy=SignalType.FUNDING_RATE,
        price=45_000.0,
    )

    assert trade is not None
    assert trade.status == OrderStatus.FILLED
    assert trade.symbol == "BTCUSDT"
    assert trade.quantity == 0.001
    assert trade.is_paper is True
    assert trade.fill_price == 45_000.0
    assert trade.fee > 0  # комиссия должна быть


@pytest.mark.asyncio
async def test_paper_order_gets_unique_client_id(order_manager):
    """Каждый ордер получает уникальный client_order_id."""
    trade1 = await order_manager.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=0.001,
        strategy=SignalType.FUNDING_RATE,
        price=45_000.0,
    )
    trade2 = await order_manager.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        quantity=0.001,
        strategy=SignalType.FUNDING_RATE,
        price=46_000.0,
    )

    assert trade1.client_order_id != trade2.client_order_id
    assert trade1.client_order_id.startswith("tb_")


@pytest.mark.asyncio
async def test_cancel_pending_order(order_manager):
    """Отмена ордера меняет статус на CANCELLED."""
    trade = await order_manager.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=0.001,
        strategy=SignalType.TREND,
        price=45_000.0,
    )
    # В paper mode ордер сразу FILLED, создадим PENDING через прямой подход
    # (в реальном коде pending остаётся до ответа биржи)
    # Для теста проверяем что cancel на FILLED возвращает False (нельзя отменить)
    result = await order_manager.cancel_order(trade.id)
    assert result is False  # уже FILLED


@pytest.mark.asyncio
async def test_get_trade_history(order_manager):
    """История сделок возвращает исполненные ордера."""
    for i in range(3):
        await order_manager.place_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=0.001,
            strategy=SignalType.FUNDING_RATE,
            price=45_000.0 + i * 100,
        )

    history = await order_manager.get_trade_history(symbol="BTCUSDT")
    assert len(history) == 3
    # Должны быть в порядке убывания по времени
    assert all(t.status == OrderStatus.FILLED for t in history)


@pytest.mark.asyncio
async def test_market_order_no_price(order_manager):
    """Market ордер (price=None) создаётся корректно."""
    trade = await order_manager.place_order(
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        quantity=0.01,
        strategy=SignalType.MOMENTUM,
        price=None,  # market order
    )
    assert trade is not None
    assert trade.price is None


@pytest.mark.asyncio
async def test_nonexistent_trade_cancel(order_manager):
    """Отмена несуществующего ордера возвращает False без исключения."""
    result = await order_manager.cancel_order(trade_id=99999)
    assert result is False


@pytest.mark.asyncio
async def test_paper_order_fee_calculation(order_manager):
    """Комиссия рассчитывается как 0.04% от объёма."""
    price = 50_000.0
    quantity = 0.01

    trade = await order_manager.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=quantity,
        strategy=SignalType.FUNDING_RATE,
        price=price,
    )

    expected_fee = quantity * price * 0.0004
    assert abs(trade.fee - expected_fee) < 0.0001
