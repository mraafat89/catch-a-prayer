#!/bin/bash
# ─── Daily Digest → WhatsApp ─────────────────────────────────────────────────
# Runs at 8 AM ET via cron. Sends a summary of yesterday's metrics.

set -euo pipefail

PHONE="14342499037@s.whatsapp.net"

# Gather metrics from the database
MOSQUE_COUNT=$(docker exec cap-db psql -U cap -d catchaprayer -t -c "SELECT count(*) FROM mosques WHERE is_active = true;" 2>/dev/null | tr -d ' ')
SCHEDULE_COUNT=$(docker exec cap-db psql -U cap -d catchaprayer -t -c "SELECT count(*) FROM prayer_schedules WHERE date = CURRENT_DATE;" 2>/dev/null | tr -d ' ')
SPOT_COUNT=$(docker exec cap-db psql -U cap -d catchaprayer -t -c "SELECT count(*) FROM prayer_spots;" 2>/dev/null | tr -d ' ')

# Server stats
UPTIME=$(uptime -p)
DISK_PCT=$(df / | tail -1 | awk '{print $5}')
MEM_USED=$(free -h | awk '/^Mem:/ {print $3}')
MEM_TOTAL=$(free -h | awk '/^Mem:/ {print $2}')

# Backup status
LATEST_BACKUP=$(ls -t /opt/cap/backups/daily/*.dump 2>/dev/null | head -1)
if [ -n "$LATEST_BACKUP" ]; then
  BACKUP_AGE=$(( ($(date +%s) - $(stat -c %Y "$LATEST_BACKUP")) / 3600 ))
  BACKUP_SIZE=$(du -h "$LATEST_BACKUP" | cut -f1)
  BACKUP_STATUS="✅ ${BACKUP_SIZE}, ${BACKUP_AGE}h ago"
else
  BACKUP_STATUS="⚠️ No backups found"
fi

# API container health
API_STATUS=$(docker inspect cap-api --format='{{.State.Health.Status}}' 2>/dev/null || echo "unknown")

MSG="📊 Catch a Prayer — Daily Digest

🕌 Data:
• ${MOSQUE_COUNT} active mosques
• ${SCHEDULE_COUNT} schedules for today
• ${SPOT_COUNT} prayer spots

💻 Server:
• API: ${API_STATUS}
• ${UPTIME}
• Memory: ${MEM_USED} / ${MEM_TOTAL}
• Disk: ${DISK_PCT}

💾 Backup: ${BACKUP_STATUS}

🌐 https://catchaprayer.com"

openclaw message send --channel whatsapp --target "$PHONE" --message "$MSG" 2>/dev/null
echo "[$(date)] Daily digest sent"
