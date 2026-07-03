"""
core/storage/database.py
========================
Async SQLAlchemy движок + сессионная фабрика.
Работает с SQLite (dev) и PostgreSQL (prod) без изменения кода.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from loguru import logger
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.storage.models import Base

# Глобальные объекты (инициализируются через init_db)
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db(database_url: str, echo: bool = False) -> None:
    """
    Создаёт движок и все таблицы (если не существуют).
    Вызывать один раз при старте приложения.

    Args:
        database_url: строка подключения (sqlite или postgresql)
        echo: логировать SQL запросы (только для отладки)
    """
    global _engine, _session_factory

    # SQLite требует connect_args для asyncio
    connect_args: dict = {}
    if "sqlite" in database_url:
        connect_args["check_same_thread"] = False

    _engine = create_async_engine(
        database_url,
        echo=echo,
        connect_args=connect_args,
        # Connection pool для PostgreSQL
        pool_pre_ping=True,       # проверяет соединение перед использованием
        pool_recycle=3600,        # переподключение каждый час
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,   # объекты остаются доступны после commit
        autoflush=False,
    )

    # Создаём таблицы (эквивалент CREATE TABLE IF NOT EXISTS)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info(f"БД инициализирована: {_mask_url(database_url)}")


async def close_db() -> None:
    """Закрывает все соединения. Вызывать при shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        logger.info("БД соединение закрыто")


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Контекстный менеджер для одной транзакции.

    Использование:
        async with get_session() as session:
            session.add(trade)
            await session.commit()

    При исключении — автоматический rollback.
    """
    if _session_factory is None:
        raise RuntimeError("БД не инициализирована. Вызови await init_db() при старте.")

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_engine() -> AsyncEngine:
    """Возвращает движок (для миграций Alembic)."""
    if _engine is None:
        raise RuntimeError("БД не инициализирована.")
    return _engine


# ── Вспомогательные функции ────────────────────────────────────────────────

def _mask_url(url: str) -> str:
    """Скрывает пароль в URL для безопасного логирования."""
    if "@" in url:
        parts = url.split("@")
        creds = parts[0].split("://")
        if len(creds) > 1:
            user_pass = creds[1].split(":")
            if len(user_pass) > 1:
                masked = f"{creds[0]}://{user_pass[0]}:***@{parts[1]}"
                return masked
    return url
