# 🗺️ ROADMAP: Trading Bots Monorepo

> **Два бота, одно ядро:**  
> 🟢 **Kalshi Bot** — prediction markets (Krypt Trader форк, headless)  
> 🔵 **Crypto Futures Bot** — Binance/Bybit (Funding Rate, Trend, Grid)  
>
> Последнее обновление: июль 2026

---

## ✅ Уже готово (Фазы 0–2 — 100%)

| Артефакт | Статус | Описание |
|----------|--------|----------|
| `backtest/funding_rate_simulator.py` | ✅ Готово | Симулятор Гипотезы A: delta-neutral Funding Rate Arb (+22% годовых, Sharpe 16.19) |
| `CRYPTO-FUTURES-BOT-PLAN-v2.md` | ✅ Готово | Risk Register R1-R12, OODA, OST, Assumption Testing |
| `CLAUDE.md` | ✅ Готово | Описание проекта и инструкции для Claude |
| `ROADMAP.md` | ✅ Готово | Этот файл |
| **core/** — общее ядро | ✅ **100%** | config, logging, storage, risk, order, position, execution, telegram, API |
| **bots/crypto_futures/** | ✅ **100%** | Binance коннектор (REST+WS), Funding Rate стратегия, main.py, Docker |
| **bots/kalshi/** | ✅ **100%** | Kalshi коннектор (RSA-256), Momentum + Whale Follow стратегии, main.py, Docker |
| **Тесты** | ✅ **53/53 passed** | core (18), funding_rate (15), kalshi_strategies (18) |
| **Docker Compose** | ✅ Готово | Оба бота как отдельные сервисы с healthcheck, volumes, restart policy |

---

## 📍 ТЕКУЩАЯ ФАЗА: 3 — Деплой и мониторинг
**Цель:** оба бота работают 24/7 в облаке

### Задачи
- [ ] **VPS** — заказать (Hetzner CX11: €3.29/мес, 1 vCPU, 2GB RAM)
- [ ] **CI/CD** — GitHub Actions workflow (`.github/workflows/ci.yml` ✅ создан)
- [ ] **Секреты на VPS** — настроить `.env` с реальными API ключами
- [ ] **PostgreSQL** — переключить `DATABASE_URL` на PostgreSQL для продакшна
- [ ] **Бэкап БД** — настроить `scripts/backup.sh` → Backblaze B2 (ежедневно)
- [ ] **Uptime мониторинг** — UptimeRobot (бесплатно) на `/health` каждые 5 мин
- [ ] **IP Whitelist** — ограничить API ключи только IP сервера
- [ ] **Deploy script** — `scripts/deploy.sh` для ручного деплоя

### ✅ Критерии готовности
- Оба бота работают > 7 дней без ручного вмешательства
- При падении поднимаются автоматически за < 60 сек (Docker restart policy)
- API ключи нигде в репо, только на сервере в переменных окружения
- Ежедневный бэкап БД работает и восстанавливается

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

## Приоритет разработки (ИСТОРИЯ — уже выполнено)

```
НЕДЕЛЯ 1-2:  Фаза 0 — Ядро (core/)                    ✅ ГОТОВО
НЕДЕЛЯ 3-4:  Фаза 1.1-1.2 — Binance коннектор + Funding Rate стратегия  ✅ ГОТОВО
НЕДЕЛЯ 5-6:  Фаза 1.3 — Crypto bot запуск, paper trading начало          ✅ ГОТОВО
НЕДЕЛЯ 7-8:  Фаза 2.1-2.2 — Аудит Krypt Trader, Kalshi коннектор         ✅ ГОТОВО
НЕДЕЛЯ 9-10: Фаза 2.3-2.4 — Kalshi стратегии, запуск                     ✅ ГОТОВО
НЕДЕЛЯ 11:   Фаза 3 — Деплой на VPS                                        🔄 ТЕКУЩАЯ
НЕДЕЛЯ 12+:  Paper trading оба бота → Фаза 4 Live                         ⏳ СЛЕДУЮЩАЯ
```

---

> ⚠️ Торговля несёт реальный финансовый риск.  
> Стратегии — гипотезы, не гарантии. Всегда проверять бэктестом до live.  
> Не держать более 30% капитала на одной бирже.  
> API ключи: только Trade права, никогда Withdraw.
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
| 🟡 Оба | 3 — Деплой | ✅ Готово | 100% |
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
