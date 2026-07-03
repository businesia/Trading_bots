"""
core/logging.py
===============
Централизованная настройка loguru для всего проекта.
Использование: from core.logging import setup_logging, get_logger
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    pass

LOG_DIR = Path(__file__).parent.parent / "logs"


def setup_logging(
    level: str = "INFO",
    log_dir: Path = LOG_DIR,
    bot_name: str = "bot",
) -> None:
    """
    Настраивает loguru: stdout + файловый лог с ротацией.

    Вызывай один раз при старте приложения:
        setup_logging(level=settings.log_level, bot_name="crypto_futures")
    """
    # Удаляем дефолтный хендлер
    logger.remove()

    # ── Stdout (dev-friendly) ──────────────────────────────────────────────
    logger.add(
        sys.stdout,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # ── Файловый лог (ротация, сжатие) ────────────────────────────────────
    log_dir.mkdir(parents=True, exist_ok=True)

    # Основной лог — всё включая DEBUG
    logger.add(
        log_dir / f"{bot_name}.log",
        level="DEBUG",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} | {message}"
        ),
        rotation="00:00",        # новый файл каждые сутки
        retention="30 days",     # хранить 30 дней
        compression="gz",        # сжимать старые логи
        backtrace=True,
        diagnose=True,
        enqueue=True,            # async-safe запись
    )

    # Лог ошибок — отдельно для быстрого мониторинга
    logger.add(
        log_dir / f"{bot_name}_errors.log",
        level="ERROR",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} | {message}\n{exception}"
        ),
        rotation="1 week",
        retention="90 days",
        compression="gz",
        backtrace=True,
        diagnose=True,
        enqueue=True,
    )

    logger.info(
        f"Логирование настроено | уровень={level} | бот={bot_name} | "
        f"директория={log_dir}"
    )


def get_logger(name: str):
    """
    Возвращает логгер с привязанным контекстом.

    Использование:
        log = get_logger("order_manager")
        log.info("Ордер размещён", order_id="abc123", symbol="BTCUSDT")
    """
    return logger.bind(module=name)


# ── Контекстный менеджер для трейд-операций ───────────────────────────────

class TradeLogger:
    """
    Удобная обёртка для логирования торговых операций.

    Использование:
        with TradeLogger("BTCUSDT", "funding_rate") as tlog:
            tlog.signal("Funding rate выше порога", rate=0.0001)
            tlog.order("Открываем позицию", side="LONG", size=0.01)
            tlog.fill("Ордер исполнен", fill_price=45000)
    """

    def __init__(self, symbol: str, strategy: str):
        self._log = logger.bind(symbol=symbol, strategy=strategy)

    def __enter__(self) -> "TradeLogger":
        return self

    def __exit__(self, *args) -> None:
        pass

    def signal(self, msg: str, **kwargs) -> None:
        self._log.info(f"[SIGNAL] {msg}", **kwargs)

    def order(self, msg: str, **kwargs) -> None:
        self._log.info(f"[ORDER] {msg}", **kwargs)

    def fill(self, msg: str, **kwargs) -> None:
        self._log.success(f"[FILL] {msg}", **kwargs)

    def risk(self, msg: str, **kwargs) -> None:
        self._log.warning(f"[RISK] {msg}", **kwargs)

    def error(self, msg: str, **kwargs) -> None:
        self._log.error(f"[ERROR] {msg}", **kwargs)
