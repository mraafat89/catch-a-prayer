#!/bin/bash
# Daily prayer time pipeline
# Runs at 2am to refresh prayer schedules for all mosques
# Add to crontab: 0 2 * * * /path/to/daily_pipeline.sh >> /var/log/cap_pipeline.log 2>&1

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="${SERVER_DIR}/logs"
DATE=$(date +%Y-%m-%d)

mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/pipeline_${DATE}.log"

echo "========================================" | tee -a "$LOG_FILE"
echo "Pipeline run: $(date)" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"

cd "$SERVER_DIR"

# Step 1: Reset stale pending jobs (jobs pending for >24h, re-queue)
echo "[Step 1] Resetting stale jobs..." | tee -a "$LOG_FILE"
python3 -c "
import asyncpg, asyncio, os, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

async def main():
    url = os.getenv('DATABASE_URL').replace('postgresql+asyncpg://', 'postgresql://')
    conn = await asyncpg.connect(url)

    # Re-queue mosques whose schedule is older than 6 days
    result = await conn.execute('''
        UPDATE scraping_jobs
        SET status = 'pending', last_attempted_at = NULL, error_message = NULL
        WHERE mosque_id IN (
            SELECT DISTINCT mosque_id FROM prayer_schedules
            WHERE scraped_at < NOW() - INTERVAL '6 days'
        )
        AND status = 'success'
    ''')
    print(f'Re-queued stale schedules: {result}')

    # Re-queue failed jobs older than 24h for retry
    result2 = await conn.execute('''
        UPDATE scraping_jobs
        SET status = 'pending', attempt_count = 0
        WHERE status = 'failed'
        AND last_attempted_at < NOW() - INTERVAL '24 hours'
    ''')
    print(f'Reset failed jobs for retry: {result2}')

    await conn.close()

asyncio.run(main())
" 2>&1 | tee -a "$LOG_FILE"

# Step 2: Run scraping worker for all pending jobs
echo "[Step 2] Running scraping worker..." | tee -a "$LOG_FILE"
python3 -m pipeline.scraping_worker 2>&1 | tee -a "$LOG_FILE"

# Step 3: Summary
echo "[Step 3] Pipeline summary:" | tee -a "$LOG_FILE"
python3 -c "
import asyncpg, asyncio, os, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

async def main():
    url = os.getenv('DATABASE_URL').replace('postgresql+asyncpg://', 'postgresql://')
    conn = await asyncpg.connect(url)
    total = await conn.fetchval('SELECT COUNT(*) FROM mosques')
    with_schedule = await conn.fetchval('SELECT COUNT(DISTINCT mosque_id) FROM prayer_schedules WHERE date = CURRENT_DATE')
    fresh = await conn.fetchval(\"SELECT COUNT(*) FROM prayer_schedules WHERE scraped_at > NOW() - INTERVAL '24 hours'\")
    pending = await conn.fetchval(\"SELECT COUNT(*) FROM scraping_jobs WHERE status='pending'\")
    failed = await conn.fetchval(\"SELECT COUNT(*) FROM scraping_jobs WHERE status='failed'\")
    print(f'Mosques: {total}')
    print(f'With schedule today: {with_schedule}')
    print(f'Freshly scraped (24h): {fresh}')
    print(f'Still pending: {pending}')
    print(f'Failed: {failed}')
    await conn.close()

asyncio.run(main())
" 2>&1 | tee -a "$LOG_FILE"

echo "Pipeline complete: $(date)" | tee -a "$LOG_FILE"
