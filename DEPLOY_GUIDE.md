# 🚀 DEPLOY GUIDE — Trading Bots на VPS (Вариант А)

> **Цель:** Развернуть обоих ботов на VPS с автодеплоем через GitHub Actions.
> **Ты делаешь:** настройку VPS и секретов.
> **Я делаю:** код, скрипты, workflow — уже готово.

---

## 📋 ЧЕКЛИСТ ПЕРЕД НАЧАЛОМ

- [ ] **VPS создан** (Hetzner CX11 €3.29/мес — 1 vCPU, 2GB RAM, 40GB SSD)
- [ ] **SSH ключ** добавлен на VPS (`ssh-copy-id root@VPS_IP`)
- [ ] **Домен/поддомен** (опционально, для SSL позже)
- [ ] **Binance API** созданы (Testnet: Read + Futures Trade, **БЕЗ Withdraw**)
- [ ] **Kalshi Demo** аккаунт создан, API ключи получены
- [ ] **Telegram Bot** создан через @BotFather, токен получен
- [ ] **Chat ID** получен через @userinfobot
- [ ] **Backblaze B2** бакет создан, Application Key получен (для бэкапов)

---

## 🔧 ШАГ 1: НАСТРОЙКА VPS (один раз)

### 1.1 Подключись к VPS
```bash
ssh root@ТВОЙ_VPS_IP
```

### 1.2 Запусти автоматическую настройку
```bash
curl -s https://raw.githubusercontent.com/ТВОЙ_ЮЗЕР/ТВОЙ_РЕПО/main/scripts/setup_vps.sh | bash
```

**Что делает скрипт:**
- Устанавливает Docker + Docker Compose plugin
- Настраивает UFW firewall (порты 22, 8080, 8081)
- Включает fail2ban
- Создаёт `/opt/trading/{logs,keys,config}` с правами 700 для keys
- Добавляет cron для бэкапа (03:00 UTC ежедневно)

### 1.3 Проверь
```bash
docker compose version
ufw status
# Должно показать: 22, 8080, 8081 ALLOW
```

---

## 🔐 ШАГ 2: GITHUB ACTIONS SECRETS

Зайди в GitHub: **Settings → Secrets and variables → Actions → New repository secret**

### Обязательные для деплоя:
| Secret | Значение | Пример |
|--------|----------|--------|
| `VPS_HOST` | IP твоего VPS | `123.45.67.89` |
| `VPS_USER` | SSH пользователь | `root` |
| `VPS_SSH_KEY` | **Весь приватный ключ** (cat ~/.ssh/id_ed25519) | `-----BEGIN OPENSSH PRIVATE KEY-----\n...` |
| `VPS_PORT` | SSH порт | `22` |
| `VPS_DEPLOY_PATH` | Путь на сервере | `/opt/trading` |

### Продакшн переменные (попадают в .env на сервере):
| Secret | Значение |
|--------|----------|
| `KALSHI_API_KEY` | Твой Kalshi API Key |
| `KALSHI_PRIVATE_KEY` | **Содержимое keys/kalshi_private.pem в одну строку** (замени `\n` на `\\n`) |
| `KALSHI_ENV` | `demo` |
| `BINANCE_API_KEY` | Binance API Key |
| `BINANCE_API_SECRET` | Binance API Secret |
| `BINANCE_TESTNET` | `true` |
| `BYBIT_API_KEY` | (опционально) |
| `BYBIT_API_SECRET` | (опционально) |
| `BYBIT_TESTNET` | `true` |
| `LIVE_TRADING` | `false` |
| `DRY_RUN` | `true` |
| `TELEGRAM_BOT_TOKEN` | Токен от @BotFather |
| `TELEGRAM_ALLOWED_CHAT_ID` | Твой chat_id (число) |
| `DATABASE_URL` | `sqlite+aiosqlite:////app/data/trading.db` |
| `LOG_LEVEL` | `INFO` |

### Backblaze B2 (для бэкапов):
| Secret | Значение |
|--------|----------|
| `B2_APPLICATION_KEY_ID` | applicationKeyId из B2 |
| `B2_APPLICATION_KEY` | applicationKey из B2 |
| `B2_BUCKET_NAME` | Имя бакета (например: `trading-backups`) |

> ⚠️ **Важно:** `KALSHI_PRIVATE_KEY` — это **многострочный PEM ключ**. В GitHub Secrets вставь его как есть (с переносами строк). GitHub Actions корректно передаст его в `.env`.

---

## 📁 ШАГ 3: ПЕРВЫЙ ДЕПЛОЙ (РУЧНОЙ, ОДИН РАЗ)

### 3.1 Склонируй репозиторий на VPS
```bash
# На VPS:
cd /opt/trading
git clone https://github.com/ТВОЙ_ЮЗЕР/ТВОЙ_РЕПО.git .
```

### 3.2 Создай .env на сервере
```bash
# На VPS:
cd /opt/trading
cp .env.example .env
# Отредактируй .env — вставь ВСЕ значения (или используй скрипт ниже)
nano .env
chmod 600 .env
```

**Или автоматически через скрипт (если все секреты в GitHub):**
```bash
# На локальной машине (один раз):
./scripts/deploy.sh --host ТВОЙ_VPS_IP --first-deploy
```

### 3.3 Скопируй Kalshi RSA ключ
```bash
# На локальной машине:
scp keys/kalshi_private.pem root@ТВОЙ_VPS_IP:/opt/trading/keys/
```

### 3.4 Запусти ботов
```bash
# На VPS:
cd /opt/trading
docker compose up -d --build
```

### 3.5 Проверь здоровье
```bash
curl http://ТВОЙ_VPS_IP:8080/health   # Crypto bot
curl http://ТВОЙ_VPS_IP:8081/health   # Kalshi bot

# Должно вернуть: {"status":"healthy","bot":"crypto_futures",...}
```

### 3.6 Проверь логи
```bash
docker compose logs -f crypto-bot
docker compose logs -f kalshi-bot
```

### 3.7 Протестируй Telegram
Напиши боту `/status` — должен ответить с P&L, позициями, статусом риск-менеджера.

---

## 🔄 ШАГ 4: АВТОДЕПЛОЙ (после первого успешного запуска)

Теперь **любой `git push origin main`** запустит:
1. ✅ Тесты (pytest)
2. 🐳 Сборку Docker образов (crypto + kalshi) в GHCR
3. 🚀 Деплой на VPS через SSH (`docker compose pull && up -d`)

**Проверить:** GitHub → Actions → Deploy to VPS

---

## 🛡️ ШАГ 5: IP WHITELIST (БЕЗОПАСНОСТЬ)

Добавь IP твоего VPS в белые списки бирж:

| Биржа | Где настроить | Какие права |
|-------|---------------|-------------|
| **Binance** | API Management → IP Access Restrictions | Read + Futures Trade (**НЕ Withdraw!**) |
| **Bybit** | API → IP Whitelist | Read + Trade |
| **Kalshi** | Dashboard → API Keys → Allowed IPs | Trade Only |

---

## 📊 ШАГ 6: МОНИТОРИНГ

### Uptime Robot (бесплатно)
1. Зарегистрируйся на uptimerobot.com
2. Add Monitor → HTTP(s)
3. URL: `http://ТВОЙ_VPS_IP:8080/health` (и `:8081/health`)
4. Interval: 5 минут
5. Alert: Telegram / Email

### Telegram алёрты (уже встроены)
Бот пришлёт:
- 🚨 Circuit breaker сработал
- 🚨 Kill-switch активирован
- ✅ Позиция открыта/закрыта
- 📊 Ежедневный отчёт (00:00 UTC)

---

## 💾 ШАГ 7: БЭКАПЫ (автоматически)

Cron на VPS запускает `/opt/trading/scripts/backup.sh` ежедневно в 03:00 UTC.

**Проверь вручную:**
```bash
# На VPS:
/opt/trading/scripts/backup.sh
# Должно загрузить .db.gz в Backblaze B2 бакет
```

**Восстановление:**
```bash
# Скачай нужный бэкап из B2:
b2 download-file-by-name trading-backups daily/crypto_20260720_030000.db.gz
gunzip crypto_20260720_030000.db.gz
# Останови ботов, замени /opt/trading/data/crypto.db, запусти ботов
```

---

## 📅 ШАГ 8: PAPER TRADING (2 НЕДЕЛИ)

| День | Действие |
|------|----------|
| 1-3 | Наблюдай за `/status`, проверь что funding rate мониторится |
| 4-7 | Сравни P&L с симулятором (`backtest/funding_rate_simulator.py`) |
| 8-14 | Если P&L в пределах ±20% от бэктеста → готов к Фазе 4 |

**Критерий перехода в Live:**
- [ ] 14 дней без ручного вмешательства
- [ ] P&L paper ≈ симулятор ±20%
- [ ] Telegram команды работают
- [ ] При funding < порога — автовыход срабатывает

---

## 🚀 ФАЗА 4: LIVE TRADING (после 2 недель paper)

```bash
# На VPS — отредактируй .env:
LIVE_TRADING=true
DRY_RUN=false
BINANCE_TESTNET=false  # ТОЛЬКО ПОСЛЕ УСПЕШНОГО PAPER!

# Перезапуск:
docker compose up -d --force-recreate
```

**Стартовые лимиты (первые 30 дней):**
- Max позиция: $50
- Max плечо: 2x
- Еженедельный вывод прибыли если > 20% депозита
- Только Crypto Futures Bot (Kalshi — отдельно позже)

---

## 🆘 ТРАБЛШУТИНГ

| Проблема | Решение |
|----------|---------|
| `docker compose up` падает | `docker compose logs -f` — смотри ошибку |
| Health check failing | Проверь порт 8080/8081 внутри контейнера: `docker exec -it crypto_bot curl localhost:8080/health` |
| Telegram не отвечает | Проверь `TELEGRAM_BOT_TOKEN` и `TELEGRAM_ALLOWED_CHAT_ID` в .env на сервере |
| Binance API error | Проверь IP whitelist, тестнет/мейннет режим, права API ключа |
| Kalshi RSA auth failed | Проверь путь к ключу `KALSHI_PRIVATE_KEY_PATH=/app/keys/kalshi_private.pem` и права 600 |
| Бэкап не загружается в B2 | Проверь `B2_APPLICATION_KEY_ID`, `B2_APPLICATION_KEY`, `B2_BUCKET_NAME` в .env |

---

## 📞 ПОЛЕЗНЫЕ КОМАНДЫ

```bash
# Статус контейнеров
docker compose ps

# Логи в реальном времени
docker compose logs -f crypto-bot
docker compose logs -f kalshi-bot

# Рестарт одного бота
docker compose restart crypto-bot

# Полный рестарт
docker compose down && docker compose up -d

# Обновление образов (ручной деплой)
docker compose pull && docker compose up -d

# Войти в контейнер
docker exec -it crypto_bot bash

# Посмотреть .env внутри контейнера
docker exec crypto_bot cat /app/.env

# Бэкап сейчас
/opt/trading/scripts/backup.sh

# Очистка старых Docker образов
docker image prune -f
```

---

## ✅ ГОТОВО!

После выполнения всех шагов у тебя будет:
- 🟢 **Crypto Futures Bot** на `:8080` — Funding Rate Arbitrage
- 🟢 **Kalshi Bot** на `:8081` — Momentum + Whale Follow
- 🔄 **Автодеплой** при push в main
- 📱 **Telegram контроль** (/status, /kill, /pause, /resume, /report)
- 💾 **Ежедневные бэкапы** в Backblaze B2
- 📊 **Мониторинг** через Uptime Robot
- 🛡️ **Безопасность**: IP whitelist, paper trading по умолчанию, kill-switch

---

## 🎯 СЛЕДУЮЩИЕ ШАГИ (после 2 недель paper)

1. Анализ P&L vs бэктест
2. Перевод Crypto бота в Live ($500 старт)
3. Настройка PostgreSQL вместо SQLite
4. Kalshi Bot в Demo → Live
5. Добавление стратегий: Trend Following, Grid Bot

**Удачи! 🚀** Любые вопросы — пиши.