"""
core/api/routes.py
==================
FastAPI роуты: health check, статус, позиции.
Минимальный REST API для внешнего мониторинга (Uptime Robot, Grafana, etc.)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

if TYPE_CHECKING:
    from core.engine.position_tracker import PositionTracker
    from core.engine.risk_manager import RiskManager

router = APIRouter()

# Простая API-key авторизация
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Глобальные ссылки (инициализируются при старте приложения)
_bots: dict[str, tuple["RiskManager", "PositionTracker"]] = {}
_api_key: str = ""
_start_time: datetime = datetime.now(timezone.utc)


def init_api(
    bots: dict[str, tuple["RiskManager", "PositionTracker"]],
    api_key: str = "",
) -> None:
    """Инициализирует API с данными ботов. Вызывать при старте FastAPI."""
    global _bots, _api_key
    _bots = bots
    _api_key = api_key


def _check_api_key(key: str | None = Security(_api_key_header)) -> str:
    """Проверяет API ключ (если задан)."""
    if _api_key and key != _api_key:
        raise HTTPException(status_code=401, detail="Неверный API ключ")
    return key or ""


# ── Роуты ─────────────────────────────────────────────────────────────────

@router.get("/health")
async def health_check():
    """
    Health check endpoint.
    Используется Uptime Robot, Docker healthcheck и т.д.
    Всегда отвечает 200 если сервис запущен.
    """
    return {
        "status": "ok",
        "uptime_seconds": (datetime.now(timezone.utc) - _start_time).total_seconds(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bots": list(_bots.keys()),
    }


@router.get("/status", dependencies=[Depends(_check_api_key)])
async def get_status():
    """Статус всех ботов: риск-менеджер + открытые позиции."""
    result = {}
    for bot_name, (risk, tracker) in _bots.items():
        risk_status = risk.get_status()
        pos_summary = await tracker.get_summary()
        result[bot_name] = {
            "risk": risk_status,
            "positions": pos_summary,
        }
    return result


@router.get("/positions", dependencies=[Depends(_check_api_key)])
async def get_positions(bot: str | None = None):
    """Список открытых позиций (всех ботов или конкретного)."""
    result = {}
    for bot_name, (_, tracker) in _bots.items():
        if bot and bot_name != bot:
            continue
        summary = await tracker.get_summary()
        result[bot_name] = summary["positions"]
    return result


@router.get("/risk", dependencies=[Depends(_check_api_key)])
async def get_risk():
    """Состояние риск-менеджеров."""
    return {name: risk.get_status() for name, (risk, _) in _bots.items()}
