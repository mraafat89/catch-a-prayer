#!/bin/bash
# ─── Send Dashboard Screenshot to WhatsApp ───────────────────────────────────
# Takes a screenshot of the admin dashboard and sends it via OpenClaw.
# Requires: Playwright (installed on server), OpenClaw with WhatsApp linked.
#
# Usage: bash scripts/send-dashboard-screenshot.sh

set -euo pipefail

PHONE="14342499037@s.whatsapp.net"
ADMIN_KEY=$(grep ADMIN_API_KEY /opt/cap/server/.env.prod | cut -d= -f2)
DASHBOARD_URL="http://localhost/api/admin/dashboard?key=${ADMIN_KEY}"
SCREENSHOT_PATH="/tmp/cap_dashboard_$(date +%Y%m%d_%H%M).png"

echo "[$(date)] Taking dashboard screenshot..."

# Use Docker container's Playwright to screenshot the dashboard
docker compose -f /opt/cap/docker-compose.prod.yml exec -T api python3 -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1000, 'height': 1400})
    page.goto('http://localhost:8000/api/admin/dashboard?key=${ADMIN_KEY}', wait_until='networkidle', timeout=15000)
    page.wait_for_timeout(3000)
    page.screenshot(path='/tmp/dashboard.png', full_page=True)
    browser.close()
    print('Screenshot saved')
"

# Copy screenshot out of container
docker cp cap-api:/tmp/dashboard.png "${SCREENSHOT_PATH}"

if [ ! -f "$SCREENSHOT_PATH" ]; then
    echo "[$(date)] Screenshot failed"
    exit 1
fi

echo "[$(date)] Sending to WhatsApp..."

# Send via OpenClaw
openclaw message send \
    --channel whatsapp \
    --target "$PHONE" \
    --message "📊 Catch a Prayer — Dashboard Report $(date '+%b %d, %Y')" \
    --media "$SCREENSHOT_PATH" \
    2>/dev/null && echo "[$(date)] Sent!" || echo "[$(date)] Send failed"

# Cleanup
rm -f "$SCREENSHOT_PATH"
