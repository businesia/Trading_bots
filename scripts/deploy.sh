#!/usr/bin/env bash
# =============================================================
# scripts/deploy.sh — Ручной деплой на VPS
#
# Использование (с локального компьютера):
#   ./scripts/deploy.sh                  # деплой только crypto-bot
#   ./scripts/deploy.sh --all            # оба бота
#   ./scripts/deploy.sh --bot kalshi     # только kalshi-bot
#   ./scripts/deploy.sh --restart        # перезапуск без rebuild
#
# Требует:
#   - SSH доступ к VPS (ключ в ~/.ssh/config или явно через VPS_USER/VPS_HOST)
#   - rsync на локальной машине
#   - .env.vps файл (копия .env для продакшна, не в git!)
# =============================================================

set -euo pipefail

# ── Конфигурация ──────────────────────────────────────────────
VPS_HOST="${VPS_HOST:-}"
VPS_USER="${VPS_USER:-root}"
VPS_PORT="${VPS_PORT:-22}"
DEPLOY_PATH="${VPS_DEPLOY_PATH:-/opt/trading}"
BOT="crypto"   # по умолчанию только крипто
REBUILD=true

# ── Цвета ─────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}==>${NC} $*"; }
warn() { echo -e "${YELLOW}⚠️ ${NC} $*"; }
err()  { echo -e "${RED}❌${NC} $*" >&2; exit 1; }

# ── Парсинг аргументов ────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)       BOT="all"; shift ;;
    --bot)       BOT="$2"; shift 2 ;;
    --restart)   REBUILD=false; shift ;;
    --host)      VPS_HOST="$2"; shift 2 ;;
    --user)      VPS_USER="$2"; shift 2 ;;
    --path)      DEPLOY_PATH="$2"; shift 2 ;;
    -h|--help)
      echo "Использование: $0 [--all|--bot NAME] [--restart] [--host HOST]"
      exit 0 ;;
    *) err "Неизвестный аргумент: $1" ;;
  esac
done

[[ -z "$VPS_HOST" ]] && err "VPS_HOST не задан. Используй: --host IP или export VPS_HOST=..."

SSH_CMD="ssh -p $VPS_PORT $VPS_USER@$VPS_HOST"

# ── Шаг 1: Проверки ───────────────────────────────────────────
log "Деплой → $VPS_USER@$VPS_HOST:$DEPLOY_PATH (бот: $BOT)"

if [[ ! -f ".env" ]] && [[ ! -f ".env.vps" ]]; then
  warn ".env не найден — убедись что .env есть на сервере"
fi

# Не деплоим в пятницу перед выходными (по CLAUDE.md)
DAY_OF_WEEK=$(date +%u)
HOUR=$(date +%H)
if [[ "$DAY_OF_WEEK" == "5" && "$HOUR" -ge "15" ]]; then
  warn "⚠️  Пятница после 15:00 — деплой в выходные запрещён (CLAUDE.md)"
  read -r -p "Продолжить всё равно? [y/N] " confirm
  [[ "$confirm" =~ ^[Yy]$ ]] || { log "Деплой отменён"; exit 0; }
fi

# ── Шаг 2: rsync кода ─────────────────────────────────────────
log "Синхронизация кода..."
rsync -az --delete \
  --exclude='.git/' \
  --exclude='.env' \
  --exclude='keys/' \
  --exclude='*.db' \
  --exclude='logs/' \
  --exclude='__pycache__/' \
  --exclude='.venv/' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  -e "ssh -p $VPS_PORT" \
  . "$VPS_USER@$VPS_HOST:$DEPLOY_PATH/"

# Копируем .env.vps → .env на сервере (если есть)
if [[ -f ".env.vps" ]]; then
  log "Копируем .env.vps → сервер..."
  scp -P "$VPS_PORT" .env.vps "$VPS_USER@$VPS_HOST:$DEPLOY_PATH/.env"
fi

# ── Шаг 3: Деплой на сервере ──────────────────────────────────
log "Запускаем деплой на сервере..."

$SSH_CMD bash << EOF
  set -e
  cd $DEPLOY_PATH

  echo "--- Статус до деплоя ---"
  docker compose ps 2>/dev/null || true

EOF

if [[ "$REBUILD" == "true" ]]; then
  log "Rebuild образов..."
  if [[ "$BOT" == "all" ]]; then
    $SSH_CMD "cd $DEPLOY_PATH && docker compose build --no-cache"
  elif [[ "$BOT" == "kalshi" ]]; then
    $SSH_CMD "cd $DEPLOY_PATH && docker compose build --no-cache kalshi-bot"
  else
    $SSH_CMD "cd $DEPLOY_PATH && docker compose build --no-cache crypto-bot"
  fi
fi

# Rolling restart (по одному боту)
restart_bot() {
  local service="$1"
  log "Перезапуск $service..."
  $SSH_CMD "cd $DEPLOY_PATH && docker compose up -d --no-deps $service"
  sleep 10
  # Проверяем health
  local health
  health=$($SSH_CMD "docker inspect --format='{{.State.Health.Status}}' \$(docker compose -f $DEPLOY_PATH/docker-compose.yml ps -q $service) 2>/dev/null || echo 'no-health'")
  if [[ "$health" == "healthy" || "$health" == "no-health" ]]; then
    log "$service ✅"
  else
    err "$service не healthy после деплоя: $health"
  fi
}

if [[ "$BOT" == "all" ]]; then
  restart_bot "crypto-bot"
  restart_bot "kalshi-bot"
elif [[ "$BOT" == "kalshi" ]]; then
  restart_bot "kalshi-bot"
else
  restart_bot "crypto-bot"
fi

# ── Шаг 4: Финальный статус ───────────────────────────────────
log "--- Статус после деплоя ---"
$SSH_CMD "cd $DEPLOY_PATH && docker compose ps"

log "Деплой завершён ✅"
echo ""
echo "Логи: ssh $VPS_USER@$VPS_HOST 'docker compose -f $DEPLOY_PATH/docker-compose.yml logs -f'"
