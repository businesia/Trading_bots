# CLAUDE.md — Trading Bots Monorepo

Этот файл описывает проект для Claude. Читай его перед любой работой с кодом.

---

## Что это за проект

**Монорепо с двумя алготрейдинговыми ботами:**

### Бот 1 — Kalshi Bot
Серверный бот для **Kalshi** (prediction market биржа, CFTC, США). Торгует бинарными контрактами на события: экономика, крипто, политика, погода. Основан на форке [Krypt Trader](https://github.com/scripflipped/Krypt-Trader) (MIT) — взяли Python-ядро, выбросили Electron, переписали в headless-сервис.

### Бот 2 — Crypto Futures Bot
Серверный бот для крипто-фьючерсов (Binance/Bybit). Стратегии: Funding Rate Arbitrage, Trend Following (EMA + ADX), Grid Bot. Гипотеза A (Funding Rate) уже протестирована симулятором `backtest/funding_rate_simulator.py`.

**Оба бота:** работают 24/7 на VPS, управляются через Telegram, используют единое ядро (риск, ордера, хранилище, логи).

---

## Текущая фаза

> Смотри `ROADMAP.md` для актуального статуса.

Начинаем с **Фазы 0**: создание единого ядра (`core/`) как фундамента для обоих ботов.

---

## Структура репозитория

```
TRADING/
├── CLAUDE.md                  ← этот файл
├── ROADMAP.md                 ← дорожная карта
├── INCIDENTS.md               ← лог инцидентов (создать при первом)
│
├── core/                      ← ОБЩЕЕ ЯДРО (оба бота используют)
│   ├── __init__.py
│   ├── engine/
│   │   ├── order_manager.py       ← размещение, отмена, трекинг ордеров
│   │   ├── position_tracker.py    ← P&L, сверка с биржей
│   │   ├── risk_manager.py        ← дневные лимиты, circuit breaker
│   │   └── execution_engine.py    ← очередь ордеров, retry, дедупликация
│   ├── storage/
│   │   ├── database.py            ← SQLite (dev) / PostgreSQL (prod)
│   │   └── models.py              ← SQLAlchemy модели (Trade, Position, Signal)
│   ├── telegram/
│   │   └── bot.py                 ← /status /kill /pause /report + алёрты
│   ├── api/
│   │   └── routes.py              ← FastAPI: /health /status /positions
│   ├── config.py                  ← pydantic-settings, читает .env
│   └── logging.py                 ← loguru настройка
│
├── bots/
│   ├── kalshi/                ← БОТ 1: Kalshi Prediction Markets
│   │   ├── main.py                ← точка входа
│   │   ├── connectors/
│   │   │   ├── kalshi_rest.py     ← REST API (httpx + RSA auth)
│   │   │   └── kalshi_ws.py       ← WebSocket real-time
│   │   └── strategies/
│   │       ├── base.py            ← BaseStrategy
│   │       ├── momentum.py        ← из Krypt Trader
│   │       ├── whale_follow.py    ← из Krypt Trader
│   │       └── crypto_corr.py     ← крипто-корреляция
│   │
│   └── crypto_futures/        ← БОТ 2: Crypto Futures
│       ├── main.py                ← точка входа
│       ├── connectors/
│       │   ├── binance.py         ← Binance Futures REST + WS
│       │   ├── bybit.py           ← Bybit (резервная биржа)
│       │   └── coinglass.py       ← funding rates, OI данные
│       └── strategies/
│           ├── base.py            ← BaseStrategy
│           ├── funding_rate.py    ← Гипотеза A (симулятор → реализация)
│           ├── trend_following.py ← EMA-кроссовер + ADX фильтр
│           └── grid_bot.py        ← Grid в боковике (ADX < 20)
│
├── backtest/                  ← БЭКТЕСТ ФРЕЙМВОРК
│   ├── funding_rate_simulator.py  ← ✅ ГОТОВО: тест Гипотезы A
│   ├── run_backtest.py            ← единая точка запуска
│   └── reports/                   ← equity curves, метрики
│
├── tests/                     ← pytest
│   ├── core/
│   │   ├── test_order_manager.py
│   │   └── test_risk_manager.py
│   ├── bots/
│   │   ├── test_kalshi_strategies.py
│   │   └── test_funding_rate.py
│   └── conftest.py
│
├── .env.example               ← шаблон переменных
├── config/
│   ├── kalshi.yaml            ← параметры стратегий Kalshi
│   └── crypto.yaml            ← параметры крипто-стратегий
├── Dockerfile.kalshi
├── Dockerfile.crypto
└── docker-compose.yml         ← поднимает оба бота
```

---

## Технологии

| Компонент | Стек |
|-----------|------|
| Язык | Python 3.11+ |
| Async | asyncio + httpx / aiohttp |
| Kalshi API | REST (httpx) + WebSocket (websockets) |
| Binance API | python-binance / ccxt |
| БД | SQLite (dev) → PostgreSQL (prod) |
| ORM | SQLAlchemy 2.x (async) |
| Конфиг | pydantic-settings v2 + `.env` + YAML |
| Логи | loguru |
| Тесты | pytest + pytest-asyncio |
| Telegram | python-telegram-bot v20+ |
| Веб API | FastAPI + uvicorn |
| Деплой | Docker + GitHub Actions |
| Бэктест | pandas + numpy (симулятор уже есть) |

---

## Ключевые принципы

### 1. Безопасность прежде всего
- Paper-trading включён по умолчанию. Реальные ордера — только `LIVE_TRADING=true` И `DRY_RUN=false` (оба флага явно).
- `RiskManager` блокирует торговлю при достижении дневного лимита. Нельзя обходить.
- Kill-switch (`/kill` в Telegram) — немедленная остановка всех позиций обоих ботов.
- API ключи: только Trade + Order права. **Никогда Withdraw.**
- Не более 30% капитала на одной бирже (риск FTX-коллапса).

### 2. Надёжность
- Все ордера пишутся в БД до отправки на биржу и после получения ответа.
- При рестарте — сверка с реальным состоянием счёта через API.
- Circuit breaker: −5% portfolio за день → оба бота стоп.
- Retry с экспоненциальным backoff (кроме ордеров — там идемпотентность важнее).

### 3. Наблюдаемость
- Каждое действие (сигнал, ордер, резолюция, funding) логируется с контекстом.
- OODA Loop: еженедельный review метрик по каждому боту отдельно.
- Никогда не глотаем исключения молча.

### 4. Конфиг — не в коде
- API ключи только в `.env` (в `.gitignore`).
- Параметры стратегий в `config/kalshi.yaml` и `config/crypto.yaml`.
- Стоп-пороги, размеры позиций, плечо — всё через конфиг, без деплоя кода.

---

## Переменные окружения (.env)

```bash
# === KALSHI BOT ===
KALSHI_API_KEY=...
KALSHI_PRIVATE_KEY_PATH=./keys/kalshi_private.pem
KALSHI_ENV=demo                      # demo | prod

# === CRYPTO FUTURES BOT ===
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
BINANCE_TESTNET=true                 # true = testnet
BYBIT_API_KEY=...
BYBIT_API_SECRET=...

# === РЕЖИМ ТОРГОВЛИ (оба бота) ===
LIVE_TRADING=false                   # false = paper trading
DRY_RUN=true                         # true = логируем, не отправляем

# === TELEGRAM ===
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_CHAT_ID=...

# === БАЗА ДАННЫХ ===
DATABASE_URL=sqlite+aiosqlite:///./trading.db

# === МОНИТОРИНГ ===
LOG_LEVEL=INFO
```

---

## Kalshi API — детали

- **Auth:** RSA-256 подпись каждого запроса
- **Prod:** `https://trading-api.kalshi.com/trade-api/v2`
- **Demo:** `https://demo-api.kalshi.co/trade-api/v2`
- **WS:** `wss://trading-api.kalshi.com/trade-api/ws/v2`
- Документация: https://trading-api.kalshi.com/trade-api/v2/docs

## Binance Futures API — детали

- **Testnet:** `https://testnet.binancefuture.com`
- **Prod:** `https://fapi.binance.com`
- Funding Rate endpoint: `/fapi/v1/fundingRate` (бесплатно, без ключей)
- Rate limits: 2400 weight/min, 10 ордеров/sec

---

## Как добавить новую стратегию

1. Создай файл `bots/<bot>/strategies/my_strategy.py`
2. Унаследуй от `BaseStrategy` из `bots/<bot>/strategies/base.py`
3. Реализуй `generate_signal(market_data) -> Signal | None`
4. Зарегистрируй в `config/<bot>.yaml` → `strategies:`
5. Запусти бэктест: `python backtest/run_backtest.py --bot crypto --strategy my_strategy --days 90`
6. Sharpe > 1.0 и PnL > 0 после комиссий на out-of-sample данных — обязательно

---

## Что НЕ делать

- Не хранить API ключи в коде или коммитах
- Не обходить `RiskManager` — все ордера через `ExecutionEngine`
- Не добавлять стратегии без бэктеста с реальными данными
- Не переключать `LIVE_TRADING=true` без 30 дней paper-trading
- Не делать синхронные HTTP-запросы в asyncio (только `async def`)
- Не запускать оба бота live одновременно с первого дня — сначала Funding Rate Bot один
- Не деплоить изменения в пятницу перед выходными
- Не менять несколько параметров стратегии одновременно (OODA принцип)
- Не хранить состояние только в памяти — всё важное в БД

---

## Связанные файлы

- `ROADMAP.md` — дорожная карта с чекпоинтами
- `INCIDENTS.md` — лог инцидентов (создать при первом)
- `backtest/funding_rate_simulator.py` — ✅ готовый симулятор Гипотезы A
- `backtest/reports/` — результаты бэктестов
- `.env.example` — шаблон переменных

---

## Контекст для Claude

- **Всегда** проверяй что новый код идёт через `RiskManager` и `ExecutionEngine`
- При добавлении зависимостей — в `requirements.txt` с пиненой версией
- Код async-first: I/O функции — `async def`
- Тесты обязательны для любого компонента движка
- Изменения схемы БД — только через Alembic миграции
- Логи: `from loguru import logger`, не `print()` и не стандартный `logging`
- Ошибки API — логируй с полным телом ответа
- Funding Rate симулятор уже написан и работает — при разработке `funding_rate.py` стратегии используй его логику как основу
- Оба бота разделяют `core/` — изменения в ядре затрагивают обоих, тесты обязательны
