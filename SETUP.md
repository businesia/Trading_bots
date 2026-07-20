# 🚀 SETUP — Запуск paper trading за 30 минут

Этот гайд проведёт тебя от нуля до работающих ботов в paper mode.  
**Paper mode = никаких реальных денег, всё безопасно.**

---

## Что нам нужно

| Шаг | Сервис | Время | Стоимость |
|-----|--------|-------|-----------|
| 1 | Telegram Bot | 3 мин | Бесплатно |
| 2 | Binance Testnet | 5 мин | Бесплатно |
| 3 | Kalshi Demo | 5 мин | Бесплатно |
| 4 | Docker Desktop | 5 мин | Бесплатно |
| 5 | Создать `.env` | 5 мин | — |
| 6 | Первый запуск | 5 мин | — |

---

## Шаг 1 — Telegram Bot 📱

Telegram бот нужен чтобы управлять ботами с телефона: смотреть статус, останавливать, получать алёрты.

### 1.1 Создать бота

1. Открой Telegram, найди **@BotFather**
2. Напиши: `/newbot`
3. Придумай имя: `Trading Monitor Bot` (любое)
4. Придумай username: `my_trading_monitor_bot` (должен оканчиваться на `_bot`)
5. BotFather пришлёт токен вида: `7412345678:AAHkjhd_kjhKJHkjhKJH-kjhkjh`

> ⚠️ **Сохрани токен** — это `TELEGRAM_BOT_TOKEN` в `.env`

### 1.2 Узнать свой Chat ID

1. Найди в Telegram: **@userinfobot**
2. Напиши: `/start`
3. Бот ответит твоим ID, например: `Id: 123456789`

> ⚠️ **Сохрани ID** — это `TELEGRAM_ALLOWED_CHAT_ID` в `.env`

### 1.3 Проверка

После того как бот запустится — напиши ему `/start` и он должен ответить.

---

## Шаг 2 — Binance Testnet 🔵

Testnet = полноценный Binance Futures, но с виртуальными деньгами. Идеально для paper trading.

### 2.1 Регистрация на Testnet

1. Перейди на: **https://testnet.binancefuture.com**
2. Нажми **Register** (можно войти через существующий Binance аккаунт или создать новый)
3. Подтверди email

> 💡 Testnet — отдельный аккаунт, не связан с основным Binance

### 2.2 Создать API ключи

1. Войди на https://testnet.binancefuture.com
2. Нажми на аватар → **API Management** (или User Center → API)
3. Нажми **Create**
4. Label: `trading-bot` (любое)
5. Скопируй **API Key** и **Secret Key**

> ⚠️ Secret Key показывается **один раз** — сохрани сразу!

### 2.3 Пополнить тестовый баланс

На testnet баланс пополняется автоматически. Если нет:
1. Перейди в **Wallet** → **Futures**
2. Нажми **Transfer** — переведи USDT из Spot в Futures

---

## Шаг 3 — Kalshi Demo 🟢

Kalshi — это CFTC-регулируемая биржа предсказаний в США. Demo аккаунт бесплатный.

### 3.1 Регистрация

1. Перейди на: **https://kalshi.com**
2. Создай аккаунт (email + верификация)
3. **Не нужно** вносить деньги для Demo

### 3.2 Получить Demo API ключи

1. Войди на https://kalshi.com → **Settings** → **API**
2. Нажми **Create API Key**
3. Скачай приватный RSA ключ (`.pem` файл)
4. Сохрани `KALSHI_API_KEY` (публичный key ID)

### 3.3 Разместить PEM файл

```powershell
# В папке проекта создай папку keys/
mkdir keys

# Скопируй туда скачанный .pem файл
# Переименуй в: kalshi_private.pem
```

> ⚠️ `keys/` папка в `.gitignore` — ключ никогда не попадёт в git

> 💡 Если Kalshi пока не нужен — закомментируй Kalshi секцию в `docker-compose.yml`  
> и запускай только Crypto бот: `docker compose up crypto-bot`

---

## Шаг 4 — Docker Desktop 🐳

Docker запускает оба бота в изолированных контейнерах.

### 4.1 Установка

1. Перейди на: **https://www.docker.com/products/docker-desktop**
2. Скачай **Docker Desktop for Windows**
3. Запусти установщик, перезагрузи компьютер если попросит
4. Запусти **Docker Desktop** из меню Пуск

### 4.2 Проверка

Открой PowerShell и выполни:
```powershell
docker --version
docker compose version
```

Должен увидеть что-то вроде:
```
Docker version 25.0.3, build 4debf41
Docker Compose version v2.24.5-desktop.1
```

---

## Шаг 5 — Создать .env файл ⚙️

**Вариант А — Автоматически** (рекомендуется):

```powershell
cd "D:\В ЗАМАРОЗКЕ\ИИ Claude Code\ПРОЕКТЫ В РАБОТЕ\TRADING\TRADING"
.\scripts\setup_env.ps1
```

Скрипт сам спросит все значения и создаст `.env`.

---

**Вариант Б — Вручную**:

```powershell
cd "D:\В ЗАМАРОЗКЕ\ИИ Claude Code\ПРОЕКТЫ В РАБОТЕ\TRADING\TRADING"
Copy-Item .env.example .env
notepad .env
```

Заполни эти поля:

```bash
# Telegram (Шаг 1)
TELEGRAM_BOT_TOKEN=7412345678:AAHkjhd_kjhKJHkjhKJH-kjhkjh
TELEGRAM_ALLOWED_CHAT_ID=123456789

# Binance Testnet (Шаг 2)
BINANCE_API_KEY=ваш_api_key
BINANCE_API_SECRET=ваш_secret_key
BINANCE_TESTNET=true          # ← ВАЖНО: true = testnet

# Kalshi Demo (Шаг 3, или пропусти)
KALSHI_API_KEY=ваш_kalshi_key
KALSHI_PRIVATE_KEY_PATH=./keys/kalshi_private.pem
KALSHI_ENV=demo               # ← ВАЖНО: demo = не реальный

# Режим торговли (НЕ менять пока не 30 дней paper trading!)
LIVE_TRADING=false
DRY_RUN=true
```

---

## Шаг 6 — Первый запуск 🎯

### 6.1 Запустить только Crypto бота (рекомендуется для начала)

```powershell
cd "D:\В ЗАМАРОЗКЕ\ИИ Claude Code\ПРОЕКТЫ В РАБОТЕ\TRADING\TRADING"

# Собрать образ и запустить
docker compose up crypto-bot --build

# Или в фоне:
docker compose up crypto-bot --build -d
```

### 6.2 Проверить что бот работает

```powershell
# Статус контейнера
docker compose ps

# Логи в реальном времени
docker compose logs -f crypto-bot

# Здоровье через API
curl http://localhost:8080/health
```

Ожидаемый ответ:
```json
{"status": "ok", "bots": ["crypto_futures"], "uptime_seconds": 42}
```

### 6.3 Telegram команды

Напиши своему боту:

| Команда | Что покажет |
|---------|-------------|
| `/status` | Текущий funding rate, позиции, P&L |
| `/report` | Сводка за день |
| `/pause` | Остановить генерацию сигналов |
| `/resume` | Возобновить |
| `/kill confirm` | ⚠️ Аварийная остановка |

### 6.4 Запустить оба бота

```powershell
# Kalshi бот запускается через profile
docker compose --profile kalshi up --build -d
```

---

## Что проверить в первые 24 часа

- [ ] Логи без `ERROR` и `CRITICAL` записей
- [ ] `/status` в Telegram отвечает
- [ ] В `trading.db` появляются записи (сигналы, даже если DRY_RUN=true)
- [ ] Funding rate обновляется каждые 8 часов
- [ ] Memory и CPU в Docker Desktop в норме (< 200MB / < 5% CPU)

```powershell
# Посмотреть БД
docker compose exec crypto-bot sqlite3 trading.db "SELECT * FROM signals LIMIT 10;"

# Использование ресурсов
docker stats
```

---

## Возможные проблемы

### "Cannot connect to Docker daemon"
→ Запусти Docker Desktop из меню Пуск и подожди 30 секунд

### "API key invalid" от Binance
→ Проверь что в `.env` нет пробелов вокруг `=`  
→ Убедись что используешь testnet ключи с https://testnet.binancefuture.com

### Бот не отвечает в Telegram
→ Проверь `TELEGRAM_BOT_TOKEN` и `TELEGRAM_ALLOWED_CHAT_ID`  
→ Напиши боту `/start` первым

### "Permission denied" для kalshi_private.pem
→ Файл должен быть в `keys/kalshi_private.pem` относительно папки проекта

### Порт 8080 занят
→ Измени в `docker-compose.yml`: `"8080:8000"` → `"8090:8000"`

---

## Что дальше (после запуска)

1. **Наблюдай 7 дней** — смотри логи, Telegram статусы, убедись что нет ошибок
2. **Смотри на сигналы** — даже в DRY_RUN=true бот генерирует сигналы и пишет в БД
3. **После 30 дней** → сравни paper P&L с симулятором → если расходятся > 20% → ищи баг
4. **Никогда** не меняй `LIVE_TRADING=true` без 30 дней позитивного paper trading

---

> 💡 **Автоматический мастер настройки:** `.\scripts\setup_env.ps1`  
> 💡 **Дашборд управления:** `.\scripts\start_manager.ps1`  
> 💡 **Создать снапшот перед запуском:** `.\scripts\snapshot.ps1 -Version "v0.3.1" -Note "готов к paper trading"`
