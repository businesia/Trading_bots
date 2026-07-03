# 🗺️ ROADMAP: Trading Bots Monorepo

> **Два бота, одно ядро:**  
> 🟢 **Kalshi Bot** — prediction markets (Krypt Trader форк, headless)  
> 🔵 **Crypto Futures Bot** — Binance/Bybit (Funding Rate, Trend, Grid)  
>
> Последнее обновление: июль 2026

---

## ✅ Уже готово

| Артефакт | Статус | Описание |
|----------|--------|----------|
| `backtest/funding_rate_simulator.py` | ✅ Готово | Симулятор Гипотезы A: delta-neutral Funding Rate Arb |
| `CRYPTO-FUTURES-BOT-PLAN-v2.md` | ✅ Готово | Risk Register R1-R12, OODA, OST, Assumption Testing |
| `CLAUDE.md` | ✅ Готово | Описание проекта и инструкции для Claude |
| `ROADMAP.md` | ✅ Готово | Этот файл |

---

## Фаза 0 — Основание (core/)
**Цель:** единое ядро, которое используют оба бота

### Задачи
- [ ] Создать структуру папок монорепо (core/, bots/kalshi/, bots/crypto_futures/, backtest/, tests/)
- [ ] `core/config.py` — pydantic-settings v2: читает `.env` и YAML
- [ ] `core/logging.py` — loguru: ротация, форматы для dev/prod
- [ ] `core/storage/models.py` — SQLAlchemy модели: Trade, Position, Signal, Event
- [ ] `core/storage/database.py` — async engine, SQLite dev / PostgreSQL prod
- [ ] `core/engine/risk_manager.py` — дневной лимит, circuit breaker, max exposure
- [ ] `core/engine/order_manager.py` — размещение, отмена, трекинг статуса
- [ ] `core/engine/position_tracker.py` — P&L, сверка с биржей при рестарте
- [ ] `core/engine/execution_engine.py` — очередь ордеров, retry, дедупликация
- [ ] `core/telegram/bot.py` — /status /kill /pause /resume /report
- [ ] `core/api/routes.py` — FastAPI: /health /status /positions
- [ ] `requirements.txt` — все зависимости с пиненными версиями
- [ ] `docker-compose.yml` — оба бота как отдельные сервисы
- [ ] Тесты: `tests/core/test_risk_manager.py`, `test_order_manager.py`

### ✅ Критерии готовности
- `python -m pytest tests/core/` — все зелёные
- `RiskManager` блокирует торговлю при достижении лимита (тест)
- Paper-trading включён по умолчанию (тест что при `DRY_RUN=true` ордера не идут)

---

## Фаза 1 — Crypto Futures Bot 🔵
**Цель:** первый рабочий бот на базе уже проверенной стратегии

> Почему сначала Crypto Futures? Симулятор Funding Rate уже готов → наименьший риск.

### 1.1 Коннектор Binance
- [ ] `bots/crypto_futures/connectors/binance.py` — REST: balance, orderbook, place/cancel order
- [ ] Binance WebSocket: real-time funding rate, цены, orderbook updates
- [ ] Testnet режим (переключается через `.env`)
- [ ] Rate limiter: не превышать 2400 weight/min

### 1.2 Стратегия: Funding Rate Arbitrage
- [ ] `bots/crypto_futures/strategies/funding_rate.py` — перенести логику из симулятора
- [ ] Параметры из симулятора: `stop_threshold=0.00002`, `stop_consec=3`, `reentry_threshold=0.00005`
- [ ] Интеграция с `ExecutionEngine` (не прямые ордера — через ядро)
- [ ] Мониторинг funding rate в реальном времени (Binance WebSocket)
- [ ] Автостоп при funding < 0.002%/8h (R2 из Risk Register)

### 1.3 Запуск
- [ ] `bots/crypto_futures/main.py` — asyncio event loop, запуск всех компонентов
- [ ] `Dockerfile.crypto` — образ для продакшн
- [ ] 2 недели paper-trading на Binance Testnet

### ✅ Критерии готовности
- Бот 14 дней работает без ручного вмешательства (paper mode)
- P&L в paper mode соответствует прогнозу симулятора ±20%
- Telegram команды работают: /status показывает funding rate и P&L
- При funding < порога — автоматический выход из позиции

---

## Фаза 2 — Kalshi Bot 🟢
**Цель:** headless серверный бот из Krypt Trader

### 2.1 Аудит Krypt Trader
- [ ] Клонировать `scripflipped/Krypt-Trader`, запустить локально
- [ ] Изучить `python/` — стратегии, Kalshi connector, бэктест
- [ ] Таблица: модуль → оставить / переписать / выбросить
- [ ] Получить Kalshi API ключи (demo аккаунт)

### 2.2 Kalshi коннектор
- [ ] `bots/kalshi/connectors/kalshi_rest.py` — RSA-256 auth, все нужные endpoint
- [ ] `bots/kalshi/connectors/kalshi_ws.py` — real-time market data
- [ ] Сверка портфеля с API при рестарте

### 2.3 Стратегии
- [ ] `bots/kalshi/strategies/base.py` — BaseStrategy, Signal dataclass
- [ ] `bots/kalshi/strategies/momentum.py` — из Krypt Trader
- [ ] `bots/kalshi/strategies/whale_follow.py` — из Krypt Trader
- [ ] Бэктест каждой стратегии: `python backtest/run_backtest.py --bot kalshi --strategy momentum --days 90`
- [ ] Только стратегии с Sharpe > 1.0 идут в прод

### 2.4 Запуск
- [ ] `bots/kalshi/main.py`
- [ ] `Dockerfile.kalshi`
- [ ] 2 недели paper-trading на Kalshi Demo

### ✅ Критерии готовности
- 14 дней работы в demo режиме без ручного вмешательства
- Хотя бы одна стратегия с Sharpe > 1.0 на бэктесте
- /status показывает маркеты, позиции, P&L

---

## Фаза 3 — Деплой и мониторинг
**Цель:** оба бота работают 24/7 в облаке

### Задачи
- [ ] Выбрать VPS (Hetzner CX11: €3.29/мес — 1 vCPU, 2GB RAM — хватит для начала)
- [ ] CI/CD: GitHub Actions → автодеплой при push в `main`
- [ ] Docker restart policy: `always` (автоподъём при падении)
- [ ] Telegram алёрты на всё: падение бота, circuit breaker, fill, новый сигнал
- [ ] Ежедневный бэкап SQLite → Backblaze B2 ($0.006/GB)
- [ ] Uptime Robot (бесплатно): мониторинг /health endpoint каждые 5 мин
- [ ] IP whitelist для API ключей (только IP сервера)

### ✅ Критерии готовности
- Оба бота работают > 7 дней без ручного вмешательства
- При падении поднимаются автоматически за < 60 сек
- API ключи нигде в репо, только на сервере в переменных окружения

---

## Фаза 4 — Боевой запуск (Live Trading)

### Crypto Futures Bot
- [ ] A/B: paper vs live параллельно, минимальный капитал $500, 2 недели
- [ ] Стартовые лимиты: max $50 в одной позиции, max 2x leverage
- [ ] Еженедельный review (OODA: Monday 30 мин)
- [ ] Withdraw прибыли каждую неделю если > 20% депозита
- [ ] Только после 30 дней paper → переход на live

### Kalshi Bot
- [ ] То же, но отдельно от Crypto бота
- [ ] Стартовый капитал: min $100 (минимум Kalshi)

### ✅ Критерии готовности
- 30 дней paper-trading с положительным P&L у каждого бота
- Все риски R1-R12 из Risk Register закрыты
- Процедура graceful shutdown документирована

---

## Фаза 5 — Расширение стратегий
**Только после стабильной работы Фазы 4**

### Crypto Futures
- [ ] `trend_following.py` — EMA-кроссовер + ADX > 25 фильтр
- [ ] `grid_bot.py` — активен только при ADX < 20
- [ ] Regime detector: определяет режим рынка → выбирает активную стратегию
- [ ] Мультиактивный Funding Rate: ETH, SOL, BNB в дополнение к BTC

### Kalshi
- [ ] `crypto_corr.py` — корреляция с BTC/ETH для крипто-маркетов
- [ ] ML-сигналы на основе whale tracker данных

---

## Текущий статус

| Бот | Фаза | Статус | Прогресс |
|-----|------|--------|----------|
| 🔵 Crypto Futures | 0 — Ядро | ✅ Готово | 100% |
| 🔵 Crypto Futures | 1 — Бот | ✅ Готово | 100% |
| 🟢 Kalshi | 0 — Ядро | ✅ Готово (общее ядро) | 100% |
| 🟢 Kalshi | 2 — Бот | ✅ Готово | 100% |
| 🟡 Оба | 3 — Деплой | 🔲 Не начата | 0% |
| 🟡 Оба | 4 — Live | 🔲 Не начата | 0% |

### Что написано (Фазы 0–2)

**core/** — общее ядро обоих ботов:
- `core/config.py` — pydantic-settings v2, `.env` + YAML конфиги
- `core/logging.py` — loguru с ротацией и trade logger
- `core/storage/models.py` — Trade, Position, Signal, RiskEvent (SQLAlchemy 2.x)
- `core/storage/database.py` — async SQLite/PostgreSQL engine
- `core/engine/risk_manager.py` — дневной лимит, circuit breaker, kill-switch
- `core/engine/order_manager.py` — размещение, paper trading, дедупликация
- `core/engine/position_tracker.py` — P&L, сверка с биржей при рестарте
- `core/engine/execution_engine.py` — очередь + retry с exponential backoff
- `core/telegram/bot.py` — /status /kill /pause /resume /report
- `core/api/routes.py` — FastAPI /health /status /positions /risk
- `tests/core/test_risk_manager.py` — 10 тестов
- `tests/core/test_order_manager.py` — 7 тестов

**bots/crypto_futures/** — Binance Funding Rate Bot:
- `connectors/binance.py` — REST + WebSocket (mark price stream)
- `strategies/base.py` — BaseStrategy, Signal, CloseSignal
- `strategies/funding_rate.py` — Гипотеза A (порт симулятора)
- `main.py` — полный asyncio event loop
- `Dockerfile.crypto`, `docker-compose.yml`
- `tests/bots/test_funding_rate.py` — 14 тестов

**bots/kalshi/** — Kalshi Prediction Markets Bot:
- `connectors/kalshi_rest.py` — RSA-256 auth, orders, markets, fills
- `connectors/kalshi_ws.py` — ticker, trades, orderbook, fill WS
- `strategies/base.py` — BaseKalshiStrategy, KalshiSignal dataclasses
- `strategies/momentum.py` — порт из Krypt Trader
- `strategies/whale_follow.py` — порт из Krypt Trader
- `main.py` — KalshiBot с polling + WS
- `tests/bots/test_kalshi_strategies.py` — 18 тестов

**backtest/**:
- `funding_rate_simulator.py` — ✅ готов (результаты в reports/)
- `run_backtest.py` — единая точка запуска бэктестов

---

## Приоритет разработки

```
НЕДЕЛЯ 1-2:  Фаза 0 — Ядро (core/)
НЕДЕЛЯ 3-4:  Фаза 1.1-1.2 — Binance коннектор + Funding Rate стратегия
НЕДЕЛЯ 5-6:  Фаза 1.3 — Crypto bot запуск, paper trading начало
НЕДЕЛЯ 7-8:  Фаза 2.1-2.2 — Аудит Krypt Trader, Kalshi коннектор
НЕДЕЛЯ 9-10: Фаза 2.3-2.4 — Kalshi стратегии, запуск
НЕДЕЛЯ 11:   Фаза 3 — Деплой на VPS
НЕДЕЛЯ 12+:  Paper trading оба бота → Фаза 4 Live
```

---

> ⚠️ Торговля несёт реальный финансовый риск.  
> Стратегии — гипотезы, не гарантии. Всегда проверять бэктестом до live.  
> Не держать более 30% капитала на одной бирже.  
> API ключи: только Trade права, никогда Withdraw.
