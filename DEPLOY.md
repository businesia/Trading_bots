# Деплой Trading Bots на VPS

Пошаговая инструкция запуска обоих ботов на продакшн-сервере.

---

## Требования

- VPS: Ubuntu 22.04, минимум 1 vCPU / 2GB RAM (Hetzner CX11 — €3.29/мес)
- Локальная машина: Git, SSH клиент, rsync
- Аккаунты: Binance (Futures) / Kalshi, Telegram Bot, Backblaze B2

---

## Шаг 1: Подготовка VPS

```bash
# Подключаемся к VPS
ssh root@YOUR_VPS_IP

# Запускаем скрипт первоначальной настройки
curl -s https://raw.githubusercontent.com/YOUR/REPO/main/scripts/setup_vps.sh | bash
```

Скрипт установит: Docker, Docker Compose, b2 CLI, UFW firewall, fail2ban, cron для бэкапов.

---

## Шаг 2: API ключи

### Binance
1. Войди на [binance.com](https://binance.com) → API Management
2. Создай ключ с правами: **Futures Trading** (Read + Futures)
3. **Никогда не включай Withdraw**
4. Добавь IP whitelist: `YOUR_VPS_IP`

### Kalshi
1. Войди на [kalshi.com](https://kalshi.com) → Settings → API
2. Создай ключ, скачай приватный PEM файл
3. Скопируй PEM на VPS: `scp kalshi_private.pem root@VPS:/opt/trading/keys/`

### Telegram
1. Напиши [@BotFather](https://t.me/BotFather) → `/newbot`
2. Скопируй токен
3. Узнай свой chat_id: [@userinfobot](https://t.me/userinfobot)

### Backblaze B2
1. Зарегистрируйся на [backblaze.com](https://backblaze.com/b2/cloud-storage.html)
2. Создай bucket: `trading-backups`
3. App Keys → Create → сохрани Key ID и Application Key

---

## Шаг 3: Конфигурация `.env`

Скопируй `.env.example` → `.env` и заполни:

```bash
cp .env.example .env
nano .env
```

**Критически важные переменные:**

```bash
# Binance (testnet сначала!)
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
BINANCE_TESTNET=true          # ← true пока не 30 дней paper trading

# Kalshi
KALSHI_API_KEY=your_key
KALSHI_PRIVATE_KEY_PATH=/app/keys/kalshi_private.pem
KALSHI_ENV=demo               # ← demo пока не paper trading завершён

# Режим торговли (оба должны быть явными)
LIVE_TRADING=false            # ← false = paper trading
DRY_RUN=true                  # ← true = не отправляем ордера

# Telegram
TELEGRAM_BOT_TOKEN=123:ABC...
TELEGRAM_ALLOWED_CHAT_ID=12345678

# Backblaze (для бэкапов)
B2_APPLICATION_KEY_ID=...
B2_APPLICATION_KEY=...
B2_BUCKET_NAME=trading-backups
```

Копируем `.env` на VPS:

```bash
scp .env root@YOUR_VPS_IP:/opt/trading/.env
scp keys/kalshi_private.pem root@YOUR_VPS_IP:/opt/trading/keys/
```

---

## Шаг 4: Первый деплой

```bash
# Деплоим только crypto-bot (Kalshi — позже)
export VPS_HOST=YOUR_VPS_IP
./scripts/deploy.sh

# Проверяем
curl http://YOUR_VPS_IP:8080/health
```

Ожидаемый ответ:
```json
{"status": "ok", "bots": ["crypto_futures"], "uptime_seconds": 42}
```

---

## Шаг 5: GitHub Actions (автодеплой)

1. В GitHub репозитории → Settings → Secrets and variables → Actions
2. Добавь secrets:

| Secret | Значение |
|--------|----------|
| `VPS_HOST` | IP VPS |
| `VPS_USER` | `root` |
| `VPS_SSH_KEY` | содержимое `~/.ssh/id_rsa` (приватный ключ) |
| `VPS_DEPLOY_PATH` | `/opt/trading` |

3. После этого каждый `git push main` → автоматический деплой.

---

## Команды управления

```bash
# Подключиться к VPS
ssh root@VPS_IP

# Статус ботов
cd /opt/trading && docker compose ps

# Логи в реальном времени
docker compose logs -f crypto-bot
docker compose logs -f kalshi-bot

# Перезапуск бота
docker compose restart crypto-bot

# Полная остановка
docker compose down

# Ручной бэкап
./scripts/backup.sh
```

---

## Telegram команды

После запуска бота напиши в Telegram:

| Команда | Действие |
|---------|----------|
| `/status` | Текущие позиции, P&L, funding rate |
| `/pause` | Приостановить торговлю (позиции сохраняются) |
| `/resume` | Возобновить торговлю |
| `/kill confirm` | **Emergency stop** — немедленно закрыть все позиции |
| `/report` | Дневной отчёт: сделки, P&L, события |

---

## Мониторинг

### Uptime Robot (бесплатно)
1. Зарегистрируйся на [uptimerobot.com](https://uptimerobot.com)
2. Add Monitor → HTTP(s)
3. URL: `http://YOUR_VPS_IP:8080/health`
4. Интервал: 5 минут
5. Уведомления: email + Telegram

### Логи
```bash
# Последние 100 строк
docker compose logs --tail=100 crypto-bot

# Только ошибки
docker compose logs crypto-bot 2>&1 | grep -E "ERROR|CRITICAL|WARNING"

# Лог файлы (если настроен volume)
ls /var/lib/docker/volumes/trading_crypto_logs/_data/
```

---

## Переход на Live Trading

**Только после 30 дней успешного paper trading:**

1. Переведи Binance на mainnet:
   ```
   BINANCE_TESTNET=false
   ```

2. Установи реальные (не testnet) API ключи Binance

3. Включи реальную торговлю (ОБА флага явно):
   ```
   LIVE_TRADING=true
   DRY_RUN=false
   ```

4. Kalshi: переключи на `KALSHI_ENV=prod`

5. Деплой → наблюдай первые 24 часа вручную

---

## Rollback

Если что-то пошло не так:

```bash
# На VPS: откат к предыдущей версии
cd /opt/trading
git log --oneline -5           # смотрим хэши
git checkout PREVIOUS_HASH .   # откатываем файлы
docker compose up -d --build crypto-bot

# Или из GitHub Actions: Re-run предыдущего workflow
```

---

## Стоимость инфраструктуры

| Сервис | Стоимость |
|--------|-----------|
| Hetzner CX11 VPS | ~€3.29/мес |
| Backblaze B2 | ~$0.006/GB/мес |
| Uptime Robot | Бесплатно |
| GitHub Actions | Бесплатно (2000 мин/мес) |
| **Итого** | **~€4/мес** |

---

> ⚠️ **Важно:** Храни `.env` и `keys/` только на VPS и локально.  
> Никогда не коммить их в git. Проверяй `.gitignore` перед каждым `git add`.
