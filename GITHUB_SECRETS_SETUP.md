# ============================================================
# GITHUB ACTIONS SECRETS — Настройка для автодеплоя
# ============================================================
#
# Зайди в GitHub: Settings → Secrets and variables → Actions → New repository secret
# Добавь ВСЕ секреты ниже:
#
# ============================================================
# ОБЯЗАТЕЛЬНЫЕ (для деплоя на VPS)
# ============================================================
# VPS_HOST          - IP адрес твоего VPS (например: 123.45.67.89)
# VPS_USER          - пользователь SSH (обычно: root или ubuntu)
# VPS_SSH_KEY       - PRIVATE SSH ключ (cat ~/.ssh/id_ed25519) — ВСЁ СОДЕРЖИМОЕ включая BEGIN/END
# VPS_PORT          - SSH порт (обычно: 22)
# VPS_DEPLOY_PATH   - путь на сервере (обычно: /opt/trading)
#
# ============================================================
# ПРОДАКШН ПЕРЕМЕННЫЕ (попадают в .env на сервере)
# ============================================================
# KALSHI_API_KEY           - Kalshi API Key (demo или prod)
# KALSHI_PRIVATE_KEY       - СОДЕРЖИМОЕ keys/kalshi_private.pem (в одну строку, \n заменены на \\n)
# KALSHI_ENV               - demo | prod
# BINANCE_API_KEY          - Binance API Key (testnet или mainnet)
# BINANCE_API_SECRET       - Binance API Secret
# BINANCE_TESTNET          - true | false
# BYBIT_API_KEY            - Bybit API Key (опционально)
# BYBIT_API_SECRET         - Bybit API Secret (опционально)
# BYBIT_TESTNET            - true | false
# LIVE_TRADING             - false (paper) | true (live) — ОСТОРОЖНО!
# DRY_RUN                  - true (paper) | false (live) — ОСТОРОЖНО!
# TELEGRAM_BOT_TOKEN       - @BotFather токен
# TELEGRAM_ALLOWED_CHAT_ID - твой chat_id (число, получить у @userinfobot)
# DATABASE_URL             - sqlite+aiosqlite:////app/data/trading.db (или postgres)
# LOG_LEVEL                - INFO | DEBUG
#
# ============================================================
# BACKBLAZE B2 (для бэкапов)
# ============================================================
# B2_APPLICATION_KEY_ID    - applicationKeyId из B2
# B2_APPLICATION_KEY       - applicationKey из B2
# B2_BUCKET_NAME           - имя бакета (например: trading-backups)
#
# ============================================================
# DOCKER REGISTRY (GHCR — уже есть через GITHUB_TOKEN)
# ============================================================
# Не нужно настраивать — использует ${{ secrets.GITHUB_TOKEN }}
#
# ============================================================
# ПРОВЕРОЧНЫЙ СПИСОК ПЕРЕД ПЕРВЫМ ДЕПЛОЕМ
# ============================================================
# [ ] VPS создан (Hetzner CX11 / DigitalOcean / Timeweb)
# [ ] SSH ключ добавлен на VPS (ssh-copy-id или вручную в ~/.ssh/authorized_keys)
# [ ] UFW открыты порты: 22 (SSH), 8080 (crypto), 8081 (kalshi)
# [ ] Binance API ключи созданы с правами: Read + Futures Trade (НЕ Withdraw!)
# [ ] Binance Testnet включён (BINANCE_TESTNET=true)
# [ ] Kalshi Demo аккаунт создан, API ключи получены
# [ ] Telegram бот создан через @BotFather, токен получен
# [ ] Chat ID получен через @userinfobot
# [ ] Backblaze B2 бакет создан, Application Key создан
# [ ] Все секреты выше добавлены в GitHub Actions Secrets
# [ ] Репозиторий публичный или есть доступ к GHCR (для приватных — настрой пакеты)
#
# ============================================================
# ПЕРВЫЙ ДЕПЛОЙ (ручной, один раз)
# ============================================================
# 1. На VPS (от root):
#    curl -s https://raw.githubusercontent.com/YOUR/REPO/main/scripts/setup_vps.sh | bash
#
# 2. Скопируй .env на сервер:
#    scp .env root@YOUR_VPS_IP:/opt/trading/.env
#    scp keys/kalshi_private.pem root@YOUR_VPS_IP:/opt/trading/keys/
#
# 3. Запусти деплой:
#    ./scripts/deploy.sh --host YOUR_VPS_IP
#
# 4. Проверь:
#    curl http://YOUR_VPS_IP:8080/health
#    curl http://YOUR_VPS_IP:8081/health
#
# ============================================================
# ПОСЛЕ УСПЕШНОГО ПЕРВОГО ДЕПЛОЯ
# ============================================================
# Любой push в main → автодеплой через GitHub Actions
# Логи: GitHub → Actions → Deploy to VPS
# Ручной деплой: ./scripts/deploy.sh --host YOUR_VPS_IP
#
# ============================================================