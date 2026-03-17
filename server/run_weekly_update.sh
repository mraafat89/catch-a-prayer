#!/usr/bin/env bash
# run_weekly_update.sh — Production weekly update job.
# Requeues stale mosque data then runs the self-improving scraping loop.
#
# Cron schedule (add via `crontab -e` on your VPS):
#
#   # Prayer times refresh — every Tuesday at 2 AM
#   0 2 * * 2 /app/server/run_weekly_update.sh >> /app/server/logs/weekly_update.log 2>&1
#
#   # Monthly mosque discovery — 1st of every month at 3 AM
#   0 3 1 * * /app/server/run_weekly_update.sh --new-mosques >> /app/server/logs/monthly_seed.log 2>&1
#
set -euo pipefail
cd "$(dirname "$0")"

NEW_MOSQUES=${1:-""}
PYTHON=python3
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║      CATCH A PRAYER — WEEKLY UPDATE                 ║"
echo "║      $(date '+%Y-%m-%d %H:%M:%S')                    ║"
echo "╚══════════════════════════════════════════════════════╝"

# Step 1: Requeue stale data
echo ""
echo "── Step 1: Requeue stale prayer times and Jumuah info ─"
if [ "$NEW_MOSQUES" = "--new-mosques" ]; then
    $PYTHON -m pipeline.requeue_stale --days 30 --jumuah-days 7 --new-mosques
else
    $PYTHON -m pipeline.requeue_stale --days 30 --jumuah-days 7
fi

# Step 2: Run the self-improving scraping loop
echo ""
echo "── Step 2: Run scraping loop ───────────────────────────"
./run_scraping_loop.sh 50

echo ""
echo "══════════════════════════════════════════════════════"
echo "  Weekly update complete: $(date '+%Y-%m-%d %H:%M:%S')"
echo "══════════════════════════════════════════════════════"
