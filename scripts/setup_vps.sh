#!/usr/bin/env bash
# =============================================================
# scripts/setup_vps.sh — Первоначальная настройка VPS
#
# Запускается ОДИН РАЗ от root на новом VPS.
# После — всё управление через deploy.sh и GitHub Actions.
#
# Использование:
#   ssh root@YOUR_VPS_IP
#   curl -s https://raw.githubusercontent.com/YOUR/REPO/main/scripts/setup_vps.sh | bash
# =============================================================

set -euo pipefail

DEPLOY_PATH="/opt/trading"
DOCKER_COMPOSE_VERSION="2.29.7"

log()  { echo -e "\033[0;32m==>\033[0m $*"; }
warn() { echo -e "\033[1;33m⚠️ \033[0m $*"; }

log "=== VPS Setup для Trading Bots ==="
log "OS: $(lsb_release -ds 2>/dev/null || uname -s)"

# ── 1. Обновление системы ─────────────────────────────────────
log "Обновление пакетов..."
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
  curl wget rsync git unzip \
  sqlite3 \
  htop ufw fail2ban

# ── 2. Docker ─────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  log "Установка Docker..."
  curl -fsSL https://get.docker.com | bash
  systemctl enable docker
  systemctl start docker
else
  log "Docker уже установлен: $(docker --version)"
fi

# ── 3. Docker Compose plugin ──────────────────────────────────
if ! docker compose version &>/dev/null; then
  log "Установка Docker Compose..."
  mkdir -p /usr/local/lib/docker/cli-plugins
  curl -SL "https://github.com/docker/compose/releases/download/v${DOCKER_COMPOSE_VERSION}/docker-compose-linux-x86_64" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi
log "Docker Compose: $(docker compose version)"

# ── 4. b2 CLI для бэкапов ─────────────────────────────────────
if ! command -v b2 &>/dev/null; then
  log "Установка Backblaze b2 CLI..."
  pip3 install --break-system-packages b2 2>/dev/null || \
    pip3 install b2
fi

# ── 5. Директории ─────────────────────────────────────────────
log "Создание директорий..."
mkdir -p "$DEPLOY_PATH"/{logs,keys,config}
chmod 700 "$DEPLOY_PATH/keys"    # только root читает ключи

# ── 6. Firewall ───────────────────────────────────────────────
log "Настройка UFW firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh                     # SSH (порт 22)
ufw allow 8080/tcp                # crypto-bot FastAPI
ufw allow 8081/tcp                # kalshi-bot FastAPI
ufw --force enable
ufw status

# ── 7. fail2ban ───────────────────────────────────────────────
log "Настройка fail2ban..."
systemctl enable fail2ban
systemctl start fail2ban

# ── 8. Systemd timer для бэкапов ─────────────────────────────
log "Настройка cron для бэкапа..."
CRON_LINE="0 3 * * * $DEPLOY_PATH/scripts/backup.sh >> $DEPLOY_PATH/logs/backup.log 2>&1"
(crontab -l 2>/dev/null | grep -v "backup.sh"; echo "$CRON_LINE") | crontab -
log "Cron добавлен: $CRON_LINE"

# ── 9. Финал ──────────────────────────────────────────────────
log ""
log "=== VPS готов к деплою ✅ ==="
log ""
log "Следующие шаги:"
log "  1. Скопируй .env на сервер: scp .env root@\$VPS:/opt/trading/.env"
log "  2. Скопируй RSA ключ Kalshi: scp keys/kalshi_private.pem root@\$VPS:/opt/trading/keys/"
log "  3. Задеплой: ./scripts/deploy.sh --host \$VPS_IP"
log "  4. Проверь здоровье: curl http://\$VPS_IP:8080/health"
log ""
warn "API ключи хранятся только в /opt/trading/.env — не в git!"
warn "IP whitelist в Binance/Kalshi: добавь IP этого сервера"
