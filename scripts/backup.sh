#!/bin/bash
# ─── Database Backup Script ───────────────────────────────────────────────────
# Runs daily via cron. Keeps last 7 daily + 4 weekly backups.

set -euo pipefail

BACKUP_DIR="/opt/cap/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DAY_OF_WEEK=$(date +%u)  # 1=Monday, 7=Sunday

mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly"

# Dump database
echo "[$(date)] Starting backup..."
docker compose -f /opt/cap/docker-compose.prod.yml exec -T db \
  pg_dump -U cap -d catchaprayer --format=custom \
  > "$BACKUP_DIR/daily/cap_${TIMESTAMP}.dump"

DUMP_SIZE=$(du -h "$BACKUP_DIR/daily/cap_${TIMESTAMP}.dump" | cut -f1)
echo "[$(date)] Backup complete: cap_${TIMESTAMP}.dump (${DUMP_SIZE})"

# Weekly backup on Sundays
if [ "$DAY_OF_WEEK" -eq 7 ]; then
  cp "$BACKUP_DIR/daily/cap_${TIMESTAMP}.dump" "$BACKUP_DIR/weekly/"
  echo "[$(date)] Weekly backup saved"
fi

# Cleanup: keep last 7 daily, last 4 weekly
cd "$BACKUP_DIR/daily" && ls -t *.dump 2>/dev/null | tail -n +8 | xargs -r rm
cd "$BACKUP_DIR/weekly" && ls -t *.dump 2>/dev/null | tail -n +5 | xargs -r rm

echo "[$(date)] Cleanup done. Daily: $(ls $BACKUP_DIR/daily/*.dump 2>/dev/null | wc -l), Weekly: $(ls $BACKUP_DIR/weekly/*.dump 2>/dev/null | wc -l)"
