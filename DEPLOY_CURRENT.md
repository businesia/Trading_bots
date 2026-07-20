# 🚀 ИНСТРУКЦИЯ ПО ЗАПУСКУ И РАЗВЁРТЫВАНИЮ (Текущая конфигурация)

> **Версия:** v1.0.0 (от 21 июля 2026)
> **Среда:** VDSina VPS (1 vCPU, 1 GB RAM, 10 GB SSD) + Bybit Testnet
> **Статус:** ✅ РАБОЧАЯ ВЕРСИЯ

---

## 📋 КРАТКАЯ СВОДКА ТЕКУЩЕЙ КОНФИГУРАЦИИ

| Параметр | Значение |
|----------|----------|
| **Биржа** | Bybit (Testnet) |
| **Сервер** | VDSina (87.199.199.153, Amsterdam, 1 GB RAM) |
| **ОС на сервере** | Ubuntu 24.04 LTS |
| **Режим торговли** | Paper Trading (виртуальные ордера) |
| **Стратегия** | Funding Rate Arbitrage (BTCUSDT, ETHUSDT) |
| **Капитал (демо)** | $10,000 |
| **Деплой** | Docker Compose |
| **Бот в Telegram** | `@BOT_TREDING_AI` |

---

## 🛠 ПОДГОТОВКА (если разворачиваешь с нуля)

### 1. Что нужно иметь:
1. **GitHub репозиторий** с кодом (или ZIP архив)
2. **VPS сервер** с Ubuntu 24.04 (минимум 1 GB RAM)
3. **Bybit Testnet API ключи** (https://testnet.bybit.com)
4. **Telegram Bot Token** (от @BotFather)
5. **Твой Chat ID** (от @userinfobot)

### 2. Создание Telegram бота:
1. Напиши @BotFather в Telegram
2. Отправь `/newbot`
3. Придумай имя (например `Trading Bot AI`)
4. Придумай username (например `BOT_TREDING_AI`)
5. **Сохрани токен** (вида `123456789:ABCdef...`)

### 3. Создание Bybit API ключей (Testnet):
1. Зайди на https://testnet.bybit.com
2. Зарегистрируйся / войди
3. Перейди в **API Management**
4. Нажми **Create API Key**
5. **Permissions:** ✅ Read + ✅ Futures Trade (НЕ Withdraw!)
6. Скопируй `API Key` и `API Secret`

---

## 🌐 НАСТРОЙКА СЕРВЕРА (VDSina)

### Шаг 1. Подключись к серверу
```bash
ssh root@87.199.199.153
# Введи пароль от сервера (из панели VDSina)
```

### Шаг 2. Запусти авто-настройку
Скопируй скрипт `scripts/setup_vdsina_test.sh` на сервер и запусти, ИЛИ выполни локально:
```bash
curl -s https://raw.githubusercontent.com/businesia/Trading_bots/main/scripts/setup_vdsina_test.sh | bash
```

**Что он делает (2-3 минуты):**
- Устанавливает Docker + Docker Compose
- Создаёт 2 GB swap (критично для 1 GB RAM!)
- Настраивает UFW firewall (порты 22, 8080)
- Останавливает 3X-UI (если есть)
- Настраивает cron для бэкапов (03:00 UTC)

### Шаг 3. Клонируй репозиторий
```bash
cd /opt/trading
git clone https://github.com/businesia/Trading_bots.git .
```

### Шаг 4. Настрой переменные окружения (.env)
```bash
cp .env.vdsina.test .env
nano .env
```

**Заполни эти строки:**
```env
BYBIT_API_KEY=твой_bybit_api_key
BYBIT_API_SECRET=твой_bybit_api_secret
BYBIT_TESTNET=true
LIVE_TRADING=false
DRY_RUN=true
TELEGRAM_BOT_TOKEN=твой_telegram_bot_token
TELEGRAM_ALLOWED_CHAT_ID=твой_chat_id_число
```
*(Сохрани: Ctrl+O → Enter → Ctrl+X)*

```bash
chmod 600 .env
```

---

## 🐳 ЗАПУСК БОТА

### Шаг 5. Запусти Docker контейнеры
```bash
docker compose up -d --build
```
*(Сборка займёт 3-5 минут в первый раз)*

### Шаг 6. Проверь, что бот работает
```bash
docker compose ps
# Статус должен быть "Up"

curl http://localhost:8080/health
# Должно вернуть: {"status":"healthy",...}
```

### Шаг 7. Проверь Telegram
1. Найди своего бота в Telegram (по username)
2. Напиши `/start` или `/status`
3. Бот должен ответить со сводкой P&L и позиций

---

## 📊 МОНИТОРИНГ И УПРАВЛЕНИЕ

### Команды Telegram:
| Команда | Что делает |
|---------|------------|
| `/status` | Текущий P&L, позиции, капитал |
| `/report` | Дневной отчёт |
| `/pause` | Поставить торговлю на паузу |
| `/resume` | Возобновить торговлю |
| `/kill` | 🚨 Экстренная остановка |
| `/help` | Список команд |

### Команды сервера (через SSH):
```bash
# Посмотреть статус контейнеров
docker compose ps

# Посмотреть логи (в реальном времени)
docker compose logs -f crypto-bot

# Перезапустить бота
docker compose restart crypto-bot

# Остановить бота
docker compose down

# Обновить код и перезапустить
cd /opt/trading && git pull && docker compose up -d --build
```

---

## 🔄 ОБНОВЛЕНИЕ КОДА (DEPLOY)

Если ты изменил код и запушил на GitHub:
```bash
# На сервере:
cd /opt/trading
git pull
docker compose up -d --build
```

---

## 🆘 РЕШЕНИЕ ПРОБЛЕМ

### Бот падает (Restarting в `docker compose ps`):
```bash
# Посмотри ошибку:
docker compose logs crypto-bot --tail 50
```

### Бот не отвечает в Telegram:
1. Проверь `TELEGRAM_BOT_TOKEN` в `.env`
2. Проверь `TELEGRAM_ALLOWED_CHAT_ID` (должно быть число)
3. Перезапусти: `docker compose restart crypto-bot`

### Ошибка базы данных (unable to open database file):
```bash
docker compose down
docker volume rm trading_crypto_data
docker compose up -d --build
```

### Нехватка памяти (OOM Killed):
```bash
# Проверь swap:
free -h
# Если Swap = 0, создай:
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
```

---

## 🚀 ПЕРЕХОД НА LIVE TRADING (ПОСЛЕ 2 НЕДЕЛЬ PAPER)

1. В `.env` поменяй:
   ```env
   LIVE_TRADING=true
   DRY_RUN=false
   BYBIT_TESTNET=false  # ← ТОЛЬКО ПОСЛЕ УСПЕШНОГО ТЕСТА!
   ```
2. Перезапусти: `docker compose up -d --build`

**Стартовые лимиты (первые 30 дней):**
- Max позиция: $50
- Max плечо: 2x

---

## 📁 СТРУКТУРА ПРОЕКТА

```
Trading_bots/
├── bots/crypto_futures/      # Бот
│   ├── connectors/bybit.py   # Коннектор к Bybit (REST + WS)
│   ├── strategies/           # Стратегии
│   └── main.py               # Точка входа
├── core/                     # Общее ядро
│   ├── engine/               # Риск, ордера, позиции
│   ├── storage/              # База данных SQLite
│   ├── telegram/bot.py       # Telegram управление
│   └── api/routes.py         # FastAPI (health/status)
├── config/crypto.yaml        # Параметры стратегий
├── docker-compose.yml        # Конфигурация Docker
├── Dockerfile.crypto         # Образ Crypto бота
├── .env.vdsina.test          # Шаблон переменных окружения
└── scripts/
    ├── setup_vdsina_test.sh  # Настройка сервера
    └── backup.sh             # Бэкап БД
```
