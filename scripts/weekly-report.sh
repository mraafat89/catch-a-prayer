#!/bin/bash
# ─── Weekly Report → WhatsApp ────────────────────────────────────────────────
# Sends comprehensive data quality report via WhatsApp.
# Runs Monday 9 AM ET (2 PM UTC) via cron.

set -euo pipefail

PHONE="14342499037@s.whatsapp.net"

# Query stats from DB
STATS=$(docker compose -f /opt/cap/docker-compose.prod.yml exec -T db psql -U cap -d catchaprayer -t -c "
SELECT json_build_object(
    'total_mosques', (SELECT count(*) FROM mosques WHERE is_active),
    'has_website', (SELECT count(*) FROM mosques WHERE is_active AND website IS NOT NULL),
    'has_phone', (SELECT count(*) FROM mosques WHERE is_active AND phone IS NOT NULL AND phone != ''),
    'real_data', (SELECT count(*) FROM prayer_schedules WHERE date = CURRENT_DATE AND fajr_adhan_source != 'calculated'),
    'calculated', (SELECT count(*) FROM prayer_schedules WHERE date = CURRENT_DATE AND fajr_adhan_source = 'calculated'),
    'jumuah', (SELECT count(DISTINCT mosque_id) FROM jumuah_sessions),
    'total_schedules', (SELECT count(*) FROM prayer_schedules WHERE date = CURRENT_DATE)
);
" 2>/dev/null | tr -d ' ')

# Parse JSON
TOTAL=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin)['total_mosques'])")
WEBSITE=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin)['has_website'])")
PHONE_COUNT=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin)['has_phone'])")
REAL=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin)['real_data'])")
CALC=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin)['calculated'])")
JUMUAH=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin)['jumuah'])")
SCHED=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin)['total_schedules'])")

# Calculate percentage
if [ "$SCHED" -gt 0 ]; then
    PCT=$((REAL * 100 / SCHED))
else
    PCT=0
fi

# Server stats
UPTIME=$(uptime -p)
DISK=$(df / | tail -1 | awk '{print $5}')
MEM=$(free -h | awk '/^Mem:/ {print $3 "/" $2}')

MSG="📊 Catch a Prayer — Weekly Report

🕌 Mosques: ${TOTAL}
🌐 With website: ${WEBSITE}
📞 With phone: ${PHONE_COUNT}
🕋 With jumuah: ${JUMUAH}

📋 Today's Prayer Data:
• Real (scraped): ${REAL} (${PCT}%)
• Calculated: ${CALC}
• Total: ${SCHED}

💻 Server:
• ${UPTIME}
• Memory: ${MEM}, Disk: ${DISK}

📈 Dashboard: https://catchaprayer.com/api/admin/dashboard"

openclaw message send --channel whatsapp --target "$PHONE" --message "$MSG" 2>/dev/null && echo "[$(date)] Weekly report sent" || echo "[$(date)] Failed to send"
