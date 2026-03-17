#!/usr/bin/env bash
# run_scraping_loop.sh — Self-improving prayer-time scraping loop.
#
# Each iteration:
#   1. Scraping worker processes a batch of pending jobs (5 tiers)
#   2. Adaptive extractor tries every Tier-5-stuck domain:
#      a. 7 automated zero-token approaches
#      b. Claude Haiku HTML extractor (batches of 5) for sites that defeat automation
#      c. Auto-generated Python functions written to custom_extractors.py
#   3. If new extractors generated → stuck mosques are auto-requeued → loop continues
#   4. Mosque info enricher fills denomination / women's section / jumuah fields
#   5. Exit only when: pending=0 AND adaptive extractor produced no new extractors
#
# Usage:
#   ./run_scraping_loop.sh [BATCH_SIZE]        default: 50
#   ./run_scraping_loop.sh 25 --fresh          clears stale cooldowns at start
#
# Monitor in another terminal:
#   ./monitor_scraping.sh watch
#   ./monitor_scraping.sh tail
set -euo pipefail

cd "$(dirname "$0")"

BATCH=${1:-50}
FRESH=${2:-""}
PYTHON=python3
MAX_IDLE_ROUNDS=3   # consecutive rounds with 0 new extractors before giving up

# Log directory
mkdir -p logs
LOG_FILE="logs/scraping.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║      CATCH A PRAYER — SELF-IMPROVING SCRAPER         ║"
echo "║      $(date '+%Y-%m-%d %H:%M:%S')                    ║"
echo "╚══════════════════════════════════════════════════════╝"
echo "  Batch size:  $BATCH"
echo "  Max idle rounds before exit: $MAX_IDLE_ROUNDS"

# ── Optional: clear stale cooldowns at startup ──────────────────────────────
COOLDOWN_FILE="pipeline/adaptive_analyzed.json"
if [ "$FRESH" = "--fresh" ] && [ -f "$COOLDOWN_FILE" ]; then
    echo "  --fresh: clearing stale cooldown file → all domains will be retried"
    rm "$COOLDOWN_FILE"
elif [ -f "$COOLDOWN_FILE" ]; then
    COOLDOWN_AGE=$(python3 -c "
import os, json, sys
from datetime import datetime
data = json.load(open('$COOLDOWN_FILE'))
if not data: print(0); sys.exit()
oldest = min(data.values())
days = (datetime.utcnow() - datetime.strptime(oldest, '%Y-%m-%d')).days
print(days)
" 2>/dev/null || echo 0)
    if [ "$COOLDOWN_AGE" -gt 7 ]; then
        echo "  Cooldown file is ${COOLDOWN_AGE} days old — clearing to retry all domains"
        rm "$COOLDOWN_FILE"
    fi
fi

print_metrics() {
    local label=$1
    echo ""
    echo "══════════════════════════════════════════════════════"
    echo "  METRICS — $label"
    echo "  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "══════════════════════════════════════════════════════"
    $PYTHON - <<'PYEOF'
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sqlalchemy import create_engine, text
from app.config import get_settings

engine = create_engine(get_settings().database_url.replace("+asyncpg", ""), echo=False)
with engine.connect() as c:
    total      = c.execute(text("SELECT COUNT(*) FROM mosques WHERE is_active=true")).scalar()
    with_sites = c.execute(text("SELECT COUNT(*) FROM mosques WHERE website IS NOT NULL AND website != '' AND is_active=true")).scalar()
    pending    = c.execute(text("SELECT COUNT(*) FROM scraping_jobs WHERE status='pending'")).scalar()
    success    = c.execute(text("SELECT COUNT(*) FROM scraping_jobs WHERE status='success'")).scalar()

    tiers = dict(c.execute(text(
        "SELECT tier_reached, COUNT(*) FROM scraping_jobs WHERE status='success' GROUP BY tier_reached ORDER BY tier_reached"
    )).fetchall())

    real = c.execute(text("""
        SELECT COUNT(*) FROM mosques m JOIN scraping_jobs j ON j.mosque_id=m.id
        WHERE m.website IS NOT NULL AND m.website!='' AND m.is_active=true
          AND j.tier_reached IN (2,3,4) AND j.status='success'
    """)).scalar()
    stuck = c.execute(text("""
        SELECT COUNT(*) FROM mosques m JOIN scraping_jobs j ON j.mosque_id=m.id
        WHERE m.website IS NOT NULL AND m.website!='' AND m.is_active=true
          AND j.tier_reached=5
    """)).scalar()

    pct_real = 100 * real / with_sites if with_sites else 0
    bar = '█' * int(pct_real / 2) + '░' * (50 - int(pct_real / 2))
    print(f"  🎯 REAL SCRAPE RATE: [{bar}] {real}/{with_sites} = {pct_real:.1f}%")
    print(f"  Jobs: {success} done / {pending} pending   Stuck Tier-5 (with website): {stuck}")
    tier_labels = {2:'HTML', 3:'JS render', 4:'vision/PDF', 5:'calculated(stuck)'}
    for t, cnt in sorted(tiers.items()):
        mark = "✓" if t in (2,3,4) else "✗"
        print(f"    {mark} Tier {t} {tier_labels.get(t,''):<20} {cnt:>5}")
PYEOF
    echo ""
}

# ── count extractors helper ──────────────────────────────────────────────────
count_extractors() {
    $PYTHON -c "
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath('.')))
try:
    from pipeline.custom_extractors import CUSTOM_EXTRACTORS
    print(len(CUSTOM_EXTRACTORS))
except Exception:
    print(0)
" 2>/dev/null || echo 0
}

# ── pending count helper ─────────────────────────────────────────────────────
count_pending() {
    $PYTHON - <<'PYEOF'
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sqlalchemy import create_engine, text
from app.config import get_settings
engine = create_engine(get_settings().database_url.replace("+asyncpg", ""), echo=False)
with engine.connect() as c:
    print(c.execute(text("SELECT COUNT(*) FROM scraping_jobs WHERE status='pending'")).scalar())
PYEOF
}

# ── main loop ────────────────────────────────────────────────────────────────
iteration=0
idle_rounds=0
print_metrics "startup"

while true; do
    iteration=$((iteration + 1))
    echo ""
    echo "─── Iteration $iteration  (batch=$BATCH, idle_rounds=$idle_rounds/$MAX_IDLE_ROUNDS) ───"

    # Step 1: scrape pending jobs
    PENDING=$(count_pending)
    if [ "$PENDING" -gt 0 ]; then
        echo "  → Scraping $PENDING pending jobs (batch $BATCH)..."
        $PYTHON -m pipeline.scraping_worker --batch "$BATCH" || true
    else
        echo "  → No pending jobs to scrape"
    fi

    # Step 2: adaptive extractor (generates Python extractors for stuck sites)
    echo ""
    echo "  → Running adaptive extractor..."
    BEFORE=$(count_extractors)
    $PYTHON -m pipeline.adaptive_extractor || true
    AFTER=$(count_extractors)
    NEW_EXT=$((AFTER - BEFORE))
    echo "  → Adaptive extractor: $NEW_EXT new extractor(s) (total: $AFTER)"

    # Step 3: mosque info enricher (denomination, women's section, jumuah, etc.)
    echo ""
    echo "  → Running mosque info enricher..."
    $PYTHON -m pipeline.mosque_info_enricher --batch 50 || true

    # Step 4: print metrics
    print_metrics "iteration $iteration"

    # Step 5: convergence check
    PENDING=$(count_pending)
    if [ "$PENDING" -eq 0 ] && [ "$NEW_EXT" -eq 0 ]; then
        idle_rounds=$((idle_rounds + 1))
        echo "  → No pending jobs and no new extractors (idle round $idle_rounds/$MAX_IDLE_ROUNDS)"
        if [ "$idle_rounds" -ge "$MAX_IDLE_ROUNDS" ]; then
            echo ""
            echo "══════════════════════════════════════════════════════"
            echo "  Converged: $MAX_IDLE_ROUNDS consecutive rounds with no improvement."
            echo "  All extractable mosques have been processed."
            echo "  Re-run with --fresh to retry all cooldown-blocked domains."
            echo "══════════════════════════════════════════════════════"
            break
        fi
        echo "  → Sleeping 60s then trying adaptive extractor again (waiting for cooldown reset)..."
        sleep 60
    else
        idle_rounds=0  # reset on any progress
        if [ "$PENDING" -gt 0 ] || [ "$NEW_EXT" -gt 0 ]; then
            echo "  → Progress made — continuing immediately..."
            sleep 5
        fi
    fi
done

print_metrics "final"
