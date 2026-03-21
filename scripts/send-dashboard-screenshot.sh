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

# Use Python + Playwright to screenshot the dashboard
python3 << PYEOF
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1000, "height": 1400})
    page.goto("${DASHBOARD_URL}", wait_until="networkidle", timeout=15000)
    page.wait_for_timeout(3000)  # let heatmap render
    page.screenshot(path="${SCREENSHOT_PATH}", full_page=True)
    browser.close()
    print("Screenshot saved")
PYEOF

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
