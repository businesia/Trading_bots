"""
core/storage/models.py
======================
SQLAlchemy 2.x async модели для всех данных обоих ботов.
Используй: from core.storage.models import Trade, Position, Signal
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Base ──────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── Enums ─────────────────────────────────────────────────────────────────

class BotType(str, enum.Enum):
    KALSHI = "kalshi"
    CRYPTO_FUTURES = "crypto_futures"


class OrderSide(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"
    LONG = "long"    # псевдоним для фьючерсов
    SHORT = "short"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"        # создан, не отправлен
    SUBMITTED = "submitted"    # отправлен на биржу
    PARTIAL = "partial"        # частично исполнен
    FILLED = "filled"          # полностью исполнен
    CANCELLED = "cancelled"    # отменён
    REJECTED = "rejected"      # отклонён биржей
    FAILED = "failed"          # ошибка при отправке


class PositionStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class SignalType(str, enum.Enum):
    # Kalshi
    MOMENTUM = "momentum"
    WHALE_FOLLOW = "whale_follow"
    CRYPTO_CORR = "crypto_corr"
    # Crypto Futures
    FUNDING_RATE = "funding_rate"
    TREND = "trend"
    GRID = "grid"
    # General
    MANUAL = "manual"


# ── Trade ─────────────────────────────────────────────────────────────────

class Trade(Base):
    """
    Каждый исполненный ордер (fill) → одна запись.
    Все ордера пишутся ПЕРЕД отправкой (status=PENDING)
    и обновляются ПОСЛЕ получения ответа биржи.
    """
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot: Mapped[str] = mapped_column(SAEnum(BotType), nullable=False, index=True)

    # Идентификаторы
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    exchange_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Инструмент
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    side: Mapped[str] = mapped_column(SAEnum(OrderSide), nullable=False)
    strategy: Mapped[str] = mapped_column(SAEnum(SignalType), nullable=False)

    # Ценовые параметры
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)       # None = market order
    fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fill_quantity: Mapped[float] = mapped_column(Float, default=0.0)

    # Комиссии и P&L
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    fee_asset: Mapped[str] = mapped_column(String(16), default="USDT")
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)

    # Статус
    status: Mapped[str] = mapped_column(
        SAEnum(OrderStatus), default=OrderStatus.PENDING, nullable=False
    )
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True)  # paper или live

    # Временные метки
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    # Метаданные (JSON как текст)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_trades_bot_symbol", "bot", "symbol"),
        Index("ix_trades_created", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Trade id={self.id} {self.bot} {self.symbol} "
            f"{self.side} qty={self.quantity} status={self.status}>"
        )


# ── Position ──────────────────────────────────────────────────────────────

class Position(Base):
    """
    Открытая или закрытая позиция.
    Объединяет несколько трейдов (вход + частичные выходы + полный выход).
    """
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot: Mapped[str] = mapped_column(SAEnum(BotType), nullable=False, index=True)

    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    side: Mapped[str] = mapped_column(SAEnum(OrderSide), nullable=False)
    strategy: Mapped[str] = mapped_column(SAEnum(SignalType), nullable=False)

    # Размер и цены
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Риск
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    leverage: Mapped[float] = mapped_column(Float, default=1.0)

    # P&L
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    total_fees: Mapped[float] = mapped_column(Float, default=0.0)

    # Статус
    status: Mapped[str] = mapped_column(
        SAEnum(PositionStatus), default=PositionStatus.OPEN, nullable=False
    )
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True)

    # Временные метки
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_positions_bot_status", "bot", "status"),
    )

    @property
    def net_pnl(self) -> float:
        return self.realized_pnl - self.total_fees

    def __repr__(self) -> str:
        return (
            f"<Position id={self.id} {self.symbol} {self.side} "
            f"qty={self.quantity} pnl={self.realized_pnl:.2f} status={self.status}>"
        )


# ── Signal ────────────────────────────────────────────────────────────────

class Signal(Base):
    """
    Торговый сигнал — то что стратегия сгенерировала.
    Может и не привести к сделке (заблокирован RiskManager и т.д.).
    """
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot: Mapped[str] = mapped_column(SAEnum(BotType), nullable=False)
    strategy: Mapped[str] = mapped_column(SAEnum(SignalType), nullable=False)

    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(SAEnum(OrderSide), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0 – 1.0

    # Предложенные параметры
    suggested_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggested_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Что с ним случилось
    acted_on: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    trade_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Данные стратегии (raw context)
    raw_data: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_signals_bot_created", "bot", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Signal id={self.id} {self.strategy} {self.symbol} "
            f"{self.direction} conf={self.confidence:.2f} acted={self.acted_on}>"
        )


# ── RiskEvent ─────────────────────────────────────────────────────────────

class RiskEvent(Base):
    """
    Лог событий риск-менеджера: достижение лимитов, circuit breaker и т.д.
    """
    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot: Mapped[str] = mapped_column(SAEnum(BotType), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)  # "circuit_breaker", "daily_limit", etc.
    description: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)    # значение метрики
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True) # порог
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<RiskEvent {self.bot} {self.event_type} at {self.created_at}>"
