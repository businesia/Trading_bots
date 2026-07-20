#!/usr/bin/env bash
# =============================================================
# scripts/setup_vdsina_test.sh — Настройка VDSina для ТЕСТА
#
# Запускается ОДИН РАЗ от root на VDSina VPS.
# Оптимизирован для 1 GB RAM + 10 GB диск.
# Запускает ТОЛЬКО crypto-bot (kalshi-bot отключён).
# =============================================================

set -euo pipefail

DEPLOY_PATH="/opt/trading"

log()  { echo -e "\033[0;32m==>\033[0m $*"; }
warn() { echo -e "\033[1;33m⚠️ \033[0m $*"; }
err()  { echo -e "\033[0;31m❌\033[0m $*" >&2; exit 1; }

log "=== VDSina Test Setup (1 GB RAM) ==="

# ── 1. SWAP (КРИТИЧНО для 1 GB RAM) ───────────────────────────
if ! swapon --show | grep -q "/swapfile"; then
  log "Создаём 2 GB swap..."
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  log "Swap активирован: $(free -h | grep Swap)"
else
  log "Swap уже есть: $(free -h | grep Swap)"
fi

# ── 2. ОСТАНОВКА 3X-UI (освобождает RAM + порты) ──────────────
if systemctl is-active --quiet x-ui 2>/dev/null; then
  log "Останавливаем 3X-UI..."
  systemctl stop x-ui
  systemctl disable x-ui
  log "3X-UI остановлен и отключён от автозапуска"
else
  log "3X-UI уже неактивен"
fi

# ── 3. ОЧИСТКА DOCKER ─────────────────────────────────────────
log "Очистка Docker..."
docker system prune -a -f --volumes 2>/dev/null || true

# ── 4. УСТАНОВКА DOCKER (если нет) ────────────────────────────
if ! command -v docker &>/dev/null; then
  log "Установка Docker..."
  curl -fsSL https://get.docker.com | bash
  systemctl enable docker
  systemctl start docker
else
  log "Docker: $(docker --version)"
fi

# ── 5. DOCKER COMPOSE PLUGIN ──────────────────────────────────
if ! docker compose version &>/dev/null; then
  log "Установка Docker Compose..."
  mkdir -p /usr/local/lib/docker/cli-plugins
  curl -SL "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi
log "Docker Compose: $(docker compose version)"

# ── 6. B2 CLI ─────────────────────────────────────────────────
if ! command -v b2 &>/dev/null; then
  log "Установка Backblaze b2 CLI..."
  pip3 install --break-system-packages b2 2>/dev/null || pip3 install b2
fi

# ── 7. ДИРЕКТОРИИ ─────────────────────────────────────────────
log "Создание директорий..."
mkdir -p "$DEPLOY_PATH"/{logs,keys,config,data}
chmod 700 "$DEPLOY_PATH/keys"

# ── 8. FIREWALL (только нужные порты) ─────────────────────────
log "Настройка UFW..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 8080/tcp    # crypto-bot FastAPI
# 8081 НЕ открываем — kalshi-bot не запускаем
ufw --force enable
ufw status

# ── 9. SYSTEMD LIMITS (защита от OOM) ─────────────────────────
log "Настройка лимитов памяти для Docker..."
mkdir -p /etc/systemd/system/docker.service.d
cat > /etc/systemd/system/docker.service.d/override.conf << 'EOF'
[Service]
# Ограничиваем Docker daemon
MemoryLimit=800M
MemorySwapMax=1G
EOF
systemctl daemon-reload
systemctl restart docker

# ── 10. CRON ДЛЯ БЭКАПА ───────────────────────────────────────
log "Настройка cron для бэкапа (03:00 UTC)..."
CRON_LINE="0 3 * * * $DEPLOY_PATH/scripts/backup.sh >> $DEPLOY_PATH/logs/backup.log 2>&1"
(crontab -l 2>/dev/null | grep -v "backup.sh"; echo "$CRON_LINE") | crontab -

# ── 11. DOCKER-COMPOSE ОВЕРРАЙД ДЛЯ ТЕСТА ─────────────────────
log "Создание docker-compose.override.yml (только crypto-bot, лимиты памяти)..."
cat > "$DEPLOY_PATH/docker-compose.override.yml" << 'EOF'
version: "3.9"

services:
  crypto-bot:
    deploy:
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 256M
    environment:
      - DATABASE_URL=sqlite+aiosqlite:////app/data/crypto.db
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

  # kalshi-bot полностью отключён для теста
  kalshi-bot:
    deploy:
      replicas: 0
EOF

# ── 12. ФИНАЛ ─────────────────────────────────────────────────
log ""
log "=== VDSina готов к ТЕСТОВОМУ деплою ✅ ==="
log ""
log "Память: $(free -h | grep Mem)"
log "Swap:   $(free -h | grep Swap)"
log "Диск:   $(df -h / | tail -1 | awk '{print $4 " свободно из " $2}')"
log ""
log "Следующие шаги:"
log "  1. Склонируй репо: cd /opt/trading && git clone https://github.com/ТВОЙ_ЮЗЕР/ТВОЙ_РЕПО.git ."
log "  2. Создай .env: cp .env.example .env && nano .env"
log "  3. Заполни .env (LIVE_TRADING=false, DRY_RUN=true, BINANCE_TESTNET=true)"
log "  4. Запуск: docker compose up -d --build"
log "  5. Проверка: curl http://87.199.199.153:8080/health"
log "  6. Telegram: /status"
log ""
warn "⚠️  ТЕСТОВЫЙ РЕЖИМ: только crypto-bot, лимит 512 MB RAM"
warn "⚠️  kalshi-bot отключён (replicas: 0)"
warn "⚠️  Для продакшна — мигрируй на Hetzner CX11 (2 GB RAM)"