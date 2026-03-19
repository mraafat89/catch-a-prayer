#!/bin/bash
# ─── Server Health Check → WhatsApp ──────────────────────────────────────────
# Runs every 30 min via cron. Only messages if something is wrong.

set -euo pipefail

PHONE="14342499037@s.whatsapp.net"
ISSUES=""

# Check API
if ! curl -sf http://localhost/health > /dev/null 2>&1; then
  ISSUES="${ISSUES}• API is DOWN\n"
fi

# Check DB
if ! docker exec cap-db pg_isready -U cap -d catchaprayer > /dev/null 2>&1; then
  ISSUES="${ISSUES}• Database is DOWN\n"
fi

# Check disk (alert if >85%)
DISK_PCT=$(df / | tail -1 | awk '{print $5}' | sed 's/%//')
if [ "$DISK_PCT" -gt 85 ]; then
  ISSUES="${ISSUES}• Disk usage at ${DISK_PCT}%\n"
fi

# Check memory (alert if <200MB free)
FREE_MB=$(free -m | awk '/^Mem:/ {print $7}')
if [ "$FREE_MB" -lt 200 ]; then
  ISSUES="${ISSUES}• Low memory: ${FREE_MB}MB available\n"
fi

# Only send if there are issues
if [ -n "$ISSUES" ]; then
  MSG="🚨 Catch a Prayer Alert\n\n${ISSUES}\nServer: 5.78.187.171\nTime: $(date -u '+%Y-%m-%d %H:%M UTC')"
  openclaw message send --channel whatsapp --target "$PHONE" --message "$(echo -e "$MSG")" 2>/dev/null
  echo "[$(date)] ALERT sent: $ISSUES"
else
  echo "[$(date)] All healthy"
fi
