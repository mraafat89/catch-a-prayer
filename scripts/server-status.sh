#!/bin/bash
# ─── Server Status → WhatsApp ────────────────────────────────────────────────
# Query server/scraper/DB status and send to WhatsApp.
# Can be triggered manually or by cron.
#
# Usage:
#   bash scripts/server-status.sh scraper    # scraper progress
#   bash scripts/server-status.sh health     # system health
#   bash scripts/server-status.sh data       # data quality report
#   bash scripts/server-status.sh full       # everything

set -euo pipefail

PHONE="14342499037@s.whatsapp.net"
COMPOSE="/opt/cap/docker-compose.prod.yml"
CMD="${1:-full}"

DB="docker compose -f $COMPOSE exec -T db psql -U cap -d catchaprayer -t -c"

scraper_status() {
    # Running processes
    PROCS=$(docker top cap-api 2>/dev/null | grep -c python || echo 0)
    SCRAPER_RUNNING="no"
    [ "$PROCS" -gt 1 ] && SCRAPER_RUNNING="yes ($((PROCS-1)) workers)"

    # Scraper counts
    STATS=$($DB "
        SELECT json_build_object(
            'playwright', (SELECT count(*) FROM prayer_schedules WHERE date = CURRENT_DATE AND fajr_adhan_source = 'playwright_scrape'),
            'jina', (SELECT count(*) FROM prayer_schedules WHERE date = CURRENT_DATE AND fajr_adhan_source = 'jina_reader'),
            'total_real', (SELECT count(*) FROM prayer_schedules WHERE date = CURRENT_DATE AND fajr_adhan_source != 'calculated'),
            'total', (SELECT count(*) FROM prayer_schedules WHERE date = CURRENT_DATE),
            'alive_sites', (SELECT count(*) FROM scraping_jobs WHERE website_alive = true),
            'dead_sites', (SELECT count(*) FROM scraping_jobs WHERE website_alive = false),
            'validation_issues', (SELECT count(*) FROM scraping_validation_log WHERE scrape_date = CURRENT_DATE)
        );" 2>/dev/null | tr -d ' ')

    PW=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin)['playwright'])" 2>/dev/null || echo "?")
    JN=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin)['jina'])" 2>/dev/null || echo "?")
    REAL=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin)['total_real'])" 2>/dev/null || echo "?")
    TOTAL=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin)['total'])" 2>/dev/null || echo "?")
    ALIVE=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin)['alive_sites'])" 2>/dev/null || echo "?")
    VAL=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin)['validation_issues'])" 2>/dev/null || echo "?")

    PCT=0
    [ "$TOTAL" -gt 0 ] 2>/dev/null && PCT=$((REAL * 100 / TOTAL))

    echo "SCRAPER STATUS"
    echo ""
    echo "Running: $SCRAPER_RUNNING"
    echo "Real data: $REAL / $TOTAL ($PCT%)"
    echo "Playwright: $PW | Jina: $JN"
    echo "Alive sites: $ALIVE"
    echo "Validation issues: $VAL"
}

health_status() {
    API=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/health 2>/dev/null || echo "down")
    UPTIME=$(uptime -p 2>/dev/null || echo "?")
    DISK=$(df / | tail -1 | awk '{print $5}')
    MEM=$(free -h 2>/dev/null | awk '/^Mem:/ {print $3 "/" $2}' || echo "?")
    DB_SIZE=$($DB "SELECT pg_size_pretty(pg_database_size('catchaprayer'));" 2>/dev/null | tr -d ' ' || echo "?")
    CONTAINERS=$(docker ps --format '{{.Names}}:{{.Status}}' 2>/dev/null | tr '\n' ' ')

    echo "SYSTEM HEALTH"
    echo ""
    echo "API: $API"
    echo "Uptime: $UPTIME"
    echo "Memory: $MEM | Disk: $DISK"
    echo "DB size: $DB_SIZE"
    echo "Containers: $CONTAINERS"
}

data_status() {
    STATS=$($DB "
        SELECT json_build_object(
            'total_mosques', (SELECT count(*) FROM mosques WHERE is_active),
            'with_website', (SELECT count(*) FROM mosques WHERE is_active AND website IS NOT NULL),
            'with_phone', (SELECT count(*) FROM mosques WHERE is_active AND phone IS NOT NULL AND phone != ''),
            'real_data', (SELECT count(*) FROM prayer_schedules WHERE date = CURRENT_DATE AND fajr_adhan_source != 'calculated'),
            'calculated', (SELECT count(*) FROM prayer_schedules WHERE date = CURRENT_DATE AND fajr_adhan_source = 'calculated'),
            'jumuah', (SELECT count(DISTINCT mosque_id) FROM jumuah_sessions),
            'spots', (SELECT count(*) FROM prayer_spots),
            'suggestions', (SELECT count(*) FROM mosque_suggestions WHERE status = 'pending')
        );" 2>/dev/null | tr -d ' ')

    echo "DATA QUALITY"
    echo ""
    echo "$STATS" | python3 -c "
import sys, json
d = json.load(sys.stdin)
total = d['real_data'] + d['calculated']
pct = d['real_data'] * 100 // max(total, 1)
print(f\"Mosques: {d['total_mosques']:,}\")
print(f\"Real data: {d['real_data']:,} / {total:,} ({pct}%)\")
print(f\"Websites: {d['with_website']:,} | Phones: {d['with_phone']:,}\")
print(f\"Jumuah: {d['jumuah']} | Spots: {d['spots']}\")
print(f\"Pending suggestions: {d['suggestions']}\")
" 2>/dev/null || echo "(query failed)"
}

# Build message
MSG=""
case "$CMD" in
    scraper) MSG=$(scraper_status) ;;
    health)  MSG=$(health_status) ;;
    data)    MSG=$(data_status) ;;
    full)
        MSG="Catch a Prayer - Server Report"
        MSG="$MSG
$(echo '')
$(health_status)
$(echo '')
$(data_status)
$(echo '')
$(scraper_status)
$(echo '')
Dashboard: https://catchaprayer.com/api/admin/dashboard?key=$(grep ADMIN_API_KEY /opt/cap/server/.env.prod | cut -d= -f2)"
        ;;
    *) echo "Usage: $0 {scraper|health|data|full}"; exit 1 ;;
esac

# Send via OpenClaw
openclaw message send \
    --channel whatsapp \
    --target "$PHONE" \
    --message "$MSG" \
    2>/dev/null && echo "[$(date)] Status sent ($CMD)" || echo "[$(date)] Failed to send"
