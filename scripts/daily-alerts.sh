#!/bin/bash
# ─── Daily Alerts & Smart Notifications ──────────────────────────────────────
# Runs the Python alert engine inside Docker, sends WhatsApp from host.
#
# Usage:
#   bash scripts/daily-alerts.sh --digest   # full daily report (9 AM ET)
#   bash scripts/daily-alerts.sh            # hourly smart alerts
#   bash scripts/daily-alerts.sh --test     # test message

set -euo pipefail

PHONE="14342499037@s.whatsapp.net"
COMPOSE="/opt/cap/docker-compose.prod.yml"
MODE="${1:-}"

# Load env vars for DB password
export $(grep -v '^#' /opt/cap/server/.env.prod | xargs) 2>/dev/null || true

# Run Python script inside the API container
OUTPUT=$(docker compose -f "$COMPOSE" exec -T api python -m pipeline.daily_alerts $MODE 2>&1) || true

# Extract message from Python output (between markers)
MSG=$(echo "$OUTPUT" | sed -n '/^__WHATSAPP_MSG_START__$/,/^__WHATSAPP_MSG_END__$/{ /^__WHATSAPP_MSG_/d; p; }')

if [ -z "$MSG" ]; then
    # No message to send (either no alerts triggered, or openclaw was available in container)
    echo "[$(date)] No message to send. Output: $OUTPUT"
    exit 0
fi

# Send via OpenClaw on the host
openclaw message send \
    --channel whatsapp \
    --target "$PHONE" \
    --message "$MSG" \
    2>/dev/null && echo "[$(date)] Alert sent" || echo "[$(date)] Failed to send"
