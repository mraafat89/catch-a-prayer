#!/bin/bash
# ─── CAP Server Tools ────────────────────────────────────────────────────────
# Safe commands that can be triggered from WhatsApp via OpenClaw.
# Each command outputs a text response to stdout.
#
# Usage: bash scripts/cap-tools.sh <command>
#
# Commands:
#   status      - Quick health check
#   scraper     - Scraper progress
#   data        - Data quality report
#   errors      - Recent errors
#   restart-api - Restart the API container
#   restart-scraper - Kill and restart scrapers
#   rollback    - Show last 5 deploys (for manual rollback)
#   logs        - Last 20 API log lines
#   db          - Database stats
#   stop-scraper - Stop running scrapers

set -euo pipefail
COMPOSE="/opt/cap/docker-compose.prod.yml"
DB="docker compose -f $COMPOSE exec -T db psql -U cap -d catchaprayer -t -c"

cmd="${1:-help}"

case "$cmd" in

status)
    API=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/health 2>/dev/null || echo "DOWN")
    PROCS=$(docker top cap-api 2>/dev/null | grep -c python || echo 0)
    MEM=$(free -h 2>/dev/null | awk '/^Mem:/ {print $3"/"$2}')
    DISK=$(df / | tail -1 | awk '{print $5}')
    echo "API: $API | Procs: $PROCS | Mem: $MEM | Disk: $DISK"
    docker ps --format '{{.Names}}: {{.Status}}' 2>/dev/null
    ;;

scraper)
    PROCS=$(docker top cap-api 2>/dev/null | grep -c python || echo 0)
    RUNNING="no"
    [ "$PROCS" -gt 1 ] && RUNNING="yes ($((PROCS-1)) workers)"
    STATS=$($DB "
        SELECT 'PW:' || count(*) filter (where fajr_adhan_source='playwright_scrape')
            || ' JN:' || count(*) filter (where fajr_adhan_source='jina_reader')
            || ' Real:' || count(*) filter (where fajr_adhan_source!='calculated')
            || '/' || count(*)
        FROM prayer_schedules WHERE date=CURRENT_DATE;" 2>/dev/null | tr -d ' ')
    echo "Scraper running: $RUNNING"
    echo "$STATS"
    echo "Validation issues today: $($DB "SELECT count(*) FROM scraping_validation_log WHERE scrape_date=CURRENT_DATE;" 2>/dev/null | tr -d ' ')"
    ;;

data)
    $DB "
        SELECT fajr_adhan_source, count(*)
        FROM prayer_schedules WHERE date=CURRENT_DATE
        GROUP BY 1 ORDER BY 2 DESC;" 2>/dev/null
    ;;

errors)
    echo "=== Last 10 API errors ==="
    docker logs cap-api 2>&1 | grep -i 'error\|exception\|traceback' | tail -10
    echo ""
    echo "=== 5xx responses (24h) ==="
    $DB "SELECT count(*) FROM request_logs WHERE response_code >= 500 AND created_at > now()-interval '24h';" 2>/dev/null | tr -d ' '
    ;;

restart-api)
    docker compose -f $COMPOSE restart api 2>&1 | tail -3
    sleep 5
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/health 2>/dev/null)
    echo "API restarted. Health: $STATUS"
    ;;

restart-scraper)
    # Kill existing scraper processes, start fresh
    docker exec cap-api pkill -f 'smart_bulk_scraper' 2>/dev/null || true
    sleep 2
    docker exec -d cap-api python -m pipeline.smart_bulk_scraper --scrape --limit 200
    echo "Scraper restarted (200 sites)"
    ;;

stop-scraper)
    docker exec cap-api pkill -f 'smart_bulk_scraper' 2>/dev/null || true
    docker exec cap-api pkill -f 'chromium' 2>/dev/null || true
    echo "Scraper stopped"
    ;;

rollback)
    echo "=== Last 5 commits on server ==="
    cd /opt/cap && git log --oneline -5
    echo ""
    echo "To rollback: git checkout <hash> && docker compose up -d --build api"
    ;;

logs)
    docker logs cap-api 2>&1 | tail -20
    ;;

db)
    $DB "
        SELECT json_build_object(
            'mosques', (SELECT count(*) FROM mosques WHERE is_active),
            'schedules_today', (SELECT count(*) FROM prayer_schedules WHERE date=CURRENT_DATE),
            'real_data', (SELECT count(*) FROM prayer_schedules WHERE date=CURRENT_DATE AND fajr_adhan_source!='calculated'),
            'scraping_jobs', (SELECT count(*) FROM scraping_jobs),
            'alive_sites', (SELECT count(*) FROM scraping_jobs WHERE website_alive=true),
            'db_size', (SELECT pg_size_pretty(pg_database_size('catchaprayer')))
        );" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); [print(f'{k}: {v}') for k,v in d.items()]"
    ;;

help|*)
    echo "CAP Server Tools"
    echo ""
    echo "Safe commands:"
    echo "  status    - Quick health check"
    echo "  scraper   - Scraper progress"
    echo "  data      - Data sources breakdown"
    echo "  errors    - Recent errors"
    echo "  db        - Database stats"
    echo "  logs      - Last API logs"
    echo ""
    echo "Actions:"
    echo "  restart-api     - Restart API"
    echo "  restart-scraper - Restart scraper"
    echo "  stop-scraper    - Stop scraper"
    echo "  rollback        - Show recent commits"
    ;;
esac
