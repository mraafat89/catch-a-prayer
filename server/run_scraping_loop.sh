#!/usr/bin/env bash
# run_scraping_loop.sh — Run scraping_worker in a loop with progress metrics printed after each iteration.
# Adaptive extractor runs every ADAPTIVE_EVERY iterations to generate new extractors from failed sites.
#
# Usage:
#   ./run_scraping_loop.sh [BATCH_SIZE]
#
# Monitor in another terminal:
#   tail -f logs/scraping.log
set -euo pipefail

cd "$(dirname "$0")"

BATCH=${1:-25}
PYTHON=python3
ADAPTIVE_EVERY=3   # run adaptive extractor once every N iterations

# Log directory
mkdir -p logs
LOG_FILE="logs/scraping.log"
# Tee all output to log file (append mode)
exec > >(tee -a "$LOG_FILE") 2>&1

print_metrics() {
    local iteration=$1
    echo ""
    echo "=========================================="
    echo "  SCRAPING METRICS — after iteration $iteration"
    echo "  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "=========================================="
    $PYTHON - <<'PYEOF'
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sqlalchemy import create_engine, text
from app.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url.replace("+asyncpg", ""), echo=False)

with engine.connect() as conn:
    total = conn.execute(text("SELECT COUNT(*) FROM mosques WHERE is_active=true")).scalar()
    with_sites = conn.execute(text("SELECT COUNT(*) FROM mosques WHERE website IS NOT NULL AND website != '' AND is_active=true")).scalar()

    statuses = dict(conn.execute(text("SELECT status, COUNT(*) FROM scraping_jobs GROUP BY status")).fetchall())
    success = statuses.get('success', 0)
    pending = statuses.get('pending', 0)
    total_jobs = success + pending

    tiers = dict(conn.execute(text(
        "SELECT tier_reached, COUNT(*) FROM scraping_jobs WHERE status='success' GROUP BY tier_reached ORDER BY tier_reached"
    )).fetchall())

    sources = dict(conn.execute(text(
        "SELECT fajr_iqama_source, COUNT(DISTINCT mosque_id) FROM prayer_schedules GROUP BY fajr_iqama_source ORDER BY COUNT(DISTINCT mosque_id) DESC"
    )).fetchall())

    real_iqama = sources.get('mosque_website_html', 0) + sources.get('mosque_website_js', 0)
    total_sched = sum(sources.values())
    pct_real = 100 * real_iqama / total_sched if total_sched else 0
    pct_done = 100 * success / total_jobs if total_jobs else 0

    print(f"  Mosques total:        {total} ({with_sites} with websites)")
    print(f"  Jobs:                 {success} success / {pending} pending  ({pct_done:.1f}% done)")
    print()
    print(f"  Iqama source breakdown ({total_sched} mosques with schedules):")
    for src, cnt in sources.items():
        marker = " ✓" if src in ('mosque_website_html', 'mosque_website_js') else ""
        print(f"    {src:<28} {cnt:>5}{marker}")
    print(f"  → Real data from website: {real_iqama} ({pct_real:.1f}%)")
    print()
    print(f"  Tier breakdown (successes):")
    tier_labels = {2: 'static HTML', 3: 'JS render', 4: 'vision/PDF', 5: 'calculated'}
    for t, cnt in sorted(tiers.items()):
        label = tier_labels.get(t, f'tier{t}')
        print(f"    Tier {t} ({label:<14}) {cnt:>5}")
PYEOF
    echo ""
}

iteration=0
print_metrics 0

while true; do
    iteration=$((iteration + 1))
    echo ""
    echo "--- Starting iteration $iteration (batch=$BATCH) ---"

    $PYTHON -m pipeline.scraping_worker --batch "$BATCH" || true

    print_metrics "$iteration"

    # Run adaptive extractor every ADAPTIVE_EVERY iterations
    if [ $((iteration % ADAPTIVE_EVERY)) -eq 0 ]; then
        echo ""
        echo "--- Running adaptive extractor (iteration $iteration) ---"
        $PYTHON -m pipeline.adaptive_extractor || true
        echo "--- Adaptive extractor done ---"
    fi

    # Check if any pending jobs remain
    PENDING=$($PYTHON - <<'PYEOF'
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sqlalchemy import create_engine, text
from app.config import get_settings
settings = get_settings()
engine = create_engine(settings.database_url.replace("+asyncpg", ""), echo=False)
with engine.connect() as conn:
    print(conn.execute(text("SELECT COUNT(*) FROM scraping_jobs WHERE status='pending'")).scalar())
PYEOF
    )

    echo "  Pending jobs remaining: $PENDING"
    if [ "$PENDING" -eq 0 ]; then
        echo "  All jobs complete! Exiting."
        break
    fi

    echo "  Sleeping 120s before next iteration..."
    sleep 120
done
