#!/usr/bin/env bash
# =============================================================
# scripts/backup.sh — SQLite бэкап в Backblaze B2
#
# Запускается на VPS (через cron или systemd timer).
# Рекомендуемое расписание: ежедневно в 03:00 UTC
#
# Установка cron на VPS:
#   crontab -e
#   0 3 * * * /opt/trading/scripts/backup.sh >> /opt/trading/logs/backup.log 2>&1
#
# Требует:
#   - b2 CLI: pip install b2 (https://github.com/Backblaze/B2_Command_Line_Tool)
#   - Переменные (в .env или export):
#       B2_APPLICATION_KEY_ID=...
#       B2_APPLICATION_KEY=...
#       B2_BUCKET_NAME=trading-backups
#   - Docker volumes с именами crypto_data, kalshi_data
# =============================================================

set -euo pipefail

# ── Конфигурация ──────────────────────────────────────────────
DEPLOY_PATH="${VPS_DEPLOY_PATH:-/opt/trading}"
BACKUP_DIR="/tmp/trading_backups"
RETENTION_DAYS=30
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
B2_BUCKET="${B2_BUCKET_NAME:-trading-backups}"

# ── Логирование ───────────────────────────────────────────────
log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
err()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ $*" >&2; exit 1; }

log "=== Backup started ==="

# ── Загружаем .env (B2 ключи) ─────────────────────────────────
if [[ -f "$DEPLOY_PATH/.env" ]]; then
  # shellcheck disable=SC1091
  set -a; source "$DEPLOY_PATH/.env"; set +a
fi

[[ -z "${B2_APPLICATION_KEY_ID:-}" ]] && err "B2_APPLICATION_KEY_ID не задан"
[[ -z "${B2_APPLICATION_KEY:-}" ]]    && err "B2_APPLICATION_KEY не задан"

# ── Создаём временную директорию ──────────────────────────────
mkdir -p "$BACKUP_DIR"

backup_db() {
  local volume_name="$1"
  local db_filename="$2"
  local backup_name="${db_filename%.db}_${TIMESTAMP}.db.gz"

  log "Backup $volume_name/$db_filename..."

  # SQLite online backup через временный контейнер
  # Используем sqlite3 .backup чтобы не получить corrupted DB во время записи
  docker run --rm \
    -v "${volume_name}:/data:ro" \
    -v "${BACKUP_DIR}:/backup" \
    python:3.11-slim \
    bash -c "
      pip install -q aiosqlite 2>/dev/null
      sqlite3 /data/$db_filename \".backup /backup/${db_filename%.db}_safe.db\" 2>/dev/null || \
        cp /data/$db_filename /backup/${db_filename%.db}_safe.db
    " 2>/dev/null || {
      # Fallback: прямая копия если контейнер не запустился
      log "Warning: используем прямую копию (контейнер недоступен)"
      VOLUME_PATH=$(docker volume inspect "$volume_name" --format '{{.Mountpoint}}' 2>/dev/null || echo "")
      if [[ -n "$VOLUME_PATH" && -f "$VOLUME_PATH/$db_filename" ]]; then
        cp "$VOLUME_PATH/$db_filename" "$BACKUP_DIR/${db_filename%.db}_safe.db"
      else
        log "Warning: $db_filename не найден, пропускаем"
        return 0
      fi
    }

  # Сжимаем
  gzip -9 -c "$BACKUP_DIR/${db_filename%.db}_safe.db" > "$BACKUP_DIR/$backup_name"
  rm -f "$BACKUP_DIR/${db_filename%.db}_safe.db"

  local size_mb
  size_mb=$(du -sm "$BACKUP_DIR/$backup_name" | cut -f1)
  log "Создан: $backup_name (${size_mb}MB)"

  echo "$backup_name"
}

# ── Делаем бэкапы ─────────────────────────────────────────────
CRYPTO_BACKUP=$(backup_db "crypto_data" "crypto.db") || true
KALSHI_BACKUP=$(backup_db "kalshi_data" "kalshi.db") || true

# ── Загружаем в Backblaze B2 ──────────────────────────────────
log "Авторизация в Backblaze B2..."
b2 authorize-account "$B2_APPLICATION_KEY_ID" "$B2_APPLICATION_KEY" 2>/dev/null

upload_to_b2() {
  local filename="$1"
  local remote_path="daily/$filename"

  if [[ -f "$BACKUP_DIR/$filename" ]]; then
    log "Загружаем $filename → b2://$B2_BUCKET/$remote_path"
    b2 upload-file "$B2_BUCKET" "$BACKUP_DIR/$filename" "$remote_path"
    log "✅ Загружено: $filename"
  fi
}

[[ -n "${CRYPTO_BACKUP:-}" ]] && upload_to_b2 "$CRYPTO_BACKUP"
[[ -n "${KALSHI_BACKUP:-}" ]] && upload_to_b2 "$KALSHI_BACKUP"

# ── Чистим старые бэкапы (B2) ─────────────────────────────────
log "Удаляем бэкапы старше $RETENTION_DAYS дней из B2..."
CUTOFF_DATE=$(date -d "$RETENTION_DAYS days ago" +%Y%m%d 2>/dev/null || date -v-"${RETENTION_DAYS}d" +%Y%m%d)

b2 ls --long "$B2_BUCKET" "daily/" 2>/dev/null | \
  awk '{print $NF}' | \
  grep -E "_[0-9]{8}_[0-9]{6}\.db\.gz$" | \
  while read -r remote_file; do
    file_date=$(echo "$remote_file" | grep -oE "[0-9]{8}" | head -1)
    if [[ "$file_date" < "$CUTOFF_DATE" ]]; then
      log "Удаляем старый бэкап: $remote_file"
      b2 delete-file-version "$B2_BUCKET" "$remote_file" 2>/dev/null || true
    fi
  done

# ── Очищаем временные файлы ───────────────────────────────────
rm -rf "$BACKUP_DIR"

log "=== Backup completed successfully ==="
