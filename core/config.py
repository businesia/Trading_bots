"""
core/config.py
==============
Централизованная конфигурация обоих ботов.
Читает .env через pydantic-settings, YAML через yaml.
Используй: from core.config import settings
"""

from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).parent.parent


# ── Enums ─────────────────────────────────────────────────────────────────

class KalshiEnv(str, Enum):
    DEMO = "demo"
    PROD = "prod"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


# ── Settings ──────────────────────────────────────────────────────────────

class Settings(BaseSettings):
    """
    Все настройки читаются из .env.
    Приоритет: переменные окружения > .env файл > default значения.
    """
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # === KALSHI ===
    kalshi_api_key: str = Field(default="", description="Kalshi API Key")
    kalshi_private_key_path: Path = Field(
        default=ROOT_DIR / "keys" / "kalshi_private.pem"
    )
    kalshi_env: KalshiEnv = Field(default=KalshiEnv.DEMO)

    @property
    def kalshi_base_url(self) -> str:
        if self.kalshi_env == KalshiEnv.PROD:
            return "https://trading-api.kalshi.com/trade-api/v2"
        return "https://demo-api.kalshi.co/trade-api/v2"

    @property
    def kalshi_ws_url(self) -> str:
        if self.kalshi_env == KalshiEnv.PROD:
            return "wss://trading-api.kalshi.com/trade-api/ws/v2"
        return "wss://demo-api.kalshi.co/trade-api/ws/v2"

    # === BINANCE ===
    binance_api_key: str = Field(default="")
    binance_api_secret: str = Field(default="")
    binance_testnet: bool = Field(default=True)

    @property
    def binance_base_url(self) -> str:
        if self.binance_testnet:
            return "https://testnet.binancefuture.com"
        return "https://fapi.binance.com"

    # === BYBIT ===
    bybit_api_key: str = Field(default="")
    bybit_api_secret: str = Field(default="")
    bybit_testnet: bool = Field(default=True)

    # === ТОРГОВЫЙ РЕЖИМ ===
    live_trading: bool = Field(
        default=False,
        description="false = paper trading (безопасный режим по умолчанию)"
    )
    dry_run: bool = Field(
        default=True,
        description="true = логируем ордера, не отправляем на биржу"
    )

    @property
    def is_paper_trading(self) -> bool:
        """True если хотя бы один из флагов выключен."""
        return not self.live_trading or self.dry_run

    # === TELEGRAM ===
    telegram_bot_token: str = Field(default="")
    telegram_allowed_chat_id: int = Field(default=0)

    # === БАЗА ДАННЫХ ===
    database_url: str = Field(
        default="sqlite+aiosqlite:///./trading.db"
    )

    # === МОНИТОРИНГ ===
    log_level: LogLevel = Field(default=LogLevel.INFO)

    @field_validator("live_trading", "dry_run", mode="before")
    @classmethod
    def parse_bool(cls, v: object) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes")
        return bool(v)

    def validate_live_trading(self) -> None:
        """
        Явная проверка перед реальной торговлей.
        Вызывай при старте бота.
        """
        if self.live_trading and self.dry_run:
            raise ValueError(
                "Конфликт: LIVE_TRADING=true но DRY_RUN=true. "
                "Для реальной торговли нужно оба флага: "
                "LIVE_TRADING=true и DRY_RUN=false"
            )
        if self.live_trading and not self.dry_run:
            if self.kalshi_env == KalshiEnv.DEMO:
                pass  # demo с live_trading = тест на реальные деньги demo счёта
            # Здесь можно добавить другие проверки перед prod


# ── YAML конфиги стратегий ────────────────────────────────────────────────

def load_bot_config(bot: str) -> dict:
    """
    Загружает config/kalshi.yaml или config/crypto.yaml.

    Использование:
        cfg = load_bot_config("crypto")
        threshold = cfg["strategies"]["funding_rate"]["stop_threshold"]
    """
    config_path = ROOT_DIR / "config" / f"{bot}.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Конфиг не найден: {config_path}")
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Singleton ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# Удобный алиас для импорта
settings = get_settings()
