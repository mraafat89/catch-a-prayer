#!/bin/bash
# ─── Database Restore Script ─────────────────────────────────────────────────
# Restore from a backup dump file.
# Usage:
#   ./scripts/restore.sh                     ← restore latest daily backup
#   ./scripts/restore.sh /path/to/file.dump  ← restore specific file

set -euo pipefail

BACKUP_DIR="/opt/cap/backups/daily"
COMPOSE_FILE="/opt/cap/docker-compose.prod.yml"

# Find the dump file
if [ -n "${1:-}" ]; then
  DUMP_FILE="$1"
else
  DUMP_FILE=$(ls -t "$BACKUP_DIR"/*.dump 2>/dev/null | head -1)
fi

if [ -z "$DUMP_FILE" ] || [ ! -f "$DUMP_FILE" ]; then
  echo "❌ No backup file found."
  echo "Usage: $0 [/path/to/backup.dump]"
  echo ""
  echo "Available backups:"
  ls -lh "$BACKUP_DIR"/*.dump 2>/dev/null || echo "  (none)"
  echo ""
  ls -lh /opt/cap/backups/weekly/*.dump 2>/dev/null || true
  exit 1
fi

DUMP_SIZE=$(du -h "$DUMP_FILE" | cut -f1)
DUMP_DATE=$(basename "$DUMP_FILE" | sed 's/cap_//;s/\.dump//')

echo "═══ Database Restore ═══"
echo ""
echo "  File: $DUMP_FILE"
echo "  Size: $DUMP_SIZE"
echo "  Date: $DUMP_DATE"
echo ""
read -p "⚠️  This will REPLACE the current database. Continue? [y/N] " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Cancelled."
  exit 0
fi

# Take a safety backup of current state first
echo "→ Taking safety backup of current DB..."
SAFETY_FILE="$BACKUP_DIR/cap_pre_restore_$(date +%Y%m%d_%H%M%S).dump"
docker compose -f "$COMPOSE_FILE" exec -T db \
  pg_dump -U cap -d catchaprayer --format=custom \
  > "$SAFETY_FILE"
echo "  Safety backup: $SAFETY_FILE ($(du -h "$SAFETY_FILE" | cut -f1))"

# Restore
echo "→ Restoring from $DUMP_FILE..."
docker compose -f "$COMPOSE_FILE" exec -T db \
  pg_restore -U cap -d catchaprayer --clean --if-exists --no-owner --no-privileges \
  < "$DUMP_FILE" 2>&1 | grep -c "ERROR" | xargs -I{} echo "  ({} expected cleanup errors)"

# Verify
MOSQUE_COUNT=$(docker compose -f "$COMPOSE_FILE" exec -T db \
  psql -U cap -d catchaprayer -t -c "SELECT count(*) FROM mosques;")
echo ""
echo "✅ Restore complete!"
echo "  Mosques in DB: $MOSQUE_COUNT"
echo "  Safety backup: $SAFETY_FILE (roll back with: $0 $SAFETY_FILE)"

# Restart API to clear any cached connections
echo "→ Restarting API..."
docker compose -f "$COMPOSE_FILE" restart api
echo "✅ Done."
