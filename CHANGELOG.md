# CHANGELOG — Trading Bots Monorepo

Журнал всех изменений проекта. Обновляется после каждой сессии с Claude.

Формат версий: `MAJOR.MINOR.PATCH`
- MAJOR — крупная фаза (0→1→2...)
- MINOR — новый компонент внутри фазы
- PATCH — правки и улучшения

---

## [v0.3.0] — 2026-07-04 — Фаза 3: Деплой и мониторинг

### Добавлено
- `.github/workflows/deploy.yml` — CI/CD pipeline: lint → pytest → docker build → деплой на VPS
- `scripts/setup_vps.sh` — первоначальная настройка VPS (Docker, UFW, fail2ban, cron)
- `scripts/deploy.sh` — ручной деплой с локальной машины через rsync + SSH
- `scripts/backup.sh` — ежедневный SQLite бэкап в Backblaze B2 с авторотацией 30 дней
- `DEPLOY.md` — пошаговая инструкция деплоя: VPS → API ключи → запуск → мониторинг → live
- `INCIDENTS.md` — шаблон журнала инцидентов
- `CHANGELOG.md` — этот файл

### Защита
- `deploy.sh` блокирует деплой в пятницу после 15:00 (правило из CLAUDE.md)
- CI/CD деплоит только при зелёных тестах
- Rolling restart: один бот перезапускается, второй продолжает работать

---

## [v0.2.0] — 2026-07-04 — Фаза 2: Kalshi Bot

### Добавлено
- `bots/kalshi/connectors/kalshi_rest.py` — REST API с RSA-256 авторизацией
- `bots/kalshi/connectors/kalshi_ws.py` — WebSocket (ticker, trades, orderbook, fills)
- `bots/kalshi/strategies/base.py` — BaseKalshiStrategy, KalshiSignal, KalshiCloseSignal
- `bots/kalshi/strategies/momentum.py` — Momentum стратегия (порт из Krypt Trader)
- `bots/kalshi/strategies/whale_follow.py` — Whale Follow стратегия (порт из Krypt Trader)
- `bots/kalshi/main.py` — KalshiBot: коннекторы + стратегии + Telegram + lifecycle
- `tests/bots/test_kalshi_strategies.py` — 18 тестов (Momentum + WhaleFollow)
- `backtest/run_backtest.py` — единая точка запуска бэктестов через CLI

---

## [v0.1.0] — 2026-07-04 — Фаза 1: Crypto Futures Bot

### Добавлено
- `bots/crypto_futures/connectors/binance.py` — Binance Futures REST + WebSocket
- `bots/crypto_futures/strategies/base.py` — BaseStrategy, Signal, CloseSignal
- `bots/crypto_futures/strategies/funding_rate.py` — Funding Rate Arbitrage (Гипотеза A)
- `bots/crypto_futures/main.py` — CryptoFuturesBot: полный asyncio event loop
- `Dockerfile.crypto` + `Dockerfile.kalshi` — Docker образы
- `docker-compose.yml` — оркестрация обоих сервисов
- `tests/bots/test_funding_rate.py` — 14 тестов стратегии

---

## [v0.0.1] — 2026-07-04 — Фаза 0: Общее ядро (core/)

### Добавлено
- `core/config.py` — pydantic-settings v2, `.env` + YAML конфиги
- `core/logging.py` — loguru: ротация, TradeLogger контекстный менеджер
- `core/storage/models.py` — SQLAlchemy: Trade, Position, Signal, RiskEvent
- `core/storage/database.py` — async SQLite/PostgreSQL engine
- `core/engine/risk_manager.py` — дневной лимит, circuit breaker (-5%), kill-switch
- `core/engine/order_manager.py` — размещение ордеров, paper trading, дедупликация
- `core/engine/position_tracker.py` — P&L, сверка с биржей при рестарте
- `core/engine/execution_engine.py` — очередь + retry (exponential backoff)
- `core/telegram/bot.py` — /status /kill /pause /resume /report
- `core/api/routes.py` — FastAPI /health /status /positions /risk
- `tests/core/test_risk_manager.py` — 10 тестов
- `tests/core/test_order_manager.py` — 7 тестов

### Конфигурация
- `requirements.txt` — все зависимости с пиненными версиями
- `.env.example` — шаблон переменных окружения
- `.gitignore` — исключены .env, keys/, *.db, logs/
- `config/kalshi.yaml` + `config/crypto.yaml` — параметры стратегий
- `pytest.ini` — asyncio_mode=auto

---

## Шаблон для следующей записи

```
## [vX.X.X] — YYYY-MM-DD — Название

### Добавлено
- ...

### Изменено
- ...

### Исправлено
- ...

### Удалено
- ...
```
