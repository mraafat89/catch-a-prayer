#!/usr/bin/env bash
# monitor_scraping.sh — Live view of the scraping loop.
#
# Usage (run in a separate terminal while run_scraping_loop.sh is running):
#   ./monitor_scraping.sh          # tail the live log
#   ./monitor_scraping.sh metrics  # print current DB metrics once and exit
#   ./monitor_scraping.sh watch    # watch metrics refresh every 30s (no log)

set -euo pipefail
cd "$(dirname "$0")"

PYTHON=python3
LOG_FILE="logs/scraping.log"

print_metrics_now() {
    $PYTHON - <<'PYEOF'
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sqlalchemy import create_engine, text
from app.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url.replace("+asyncpg", ""), echo=False)

with engine.connect() as conn:
    total      = conn.execute(text("SELECT COUNT(*) FROM mosques WHERE is_active=true")).scalar()
    with_sites = conn.execute(text("SELECT COUNT(*) FROM mosques WHERE website IS NOT NULL AND website != '' AND is_active=true")).scalar()

    statuses = dict(conn.execute(text("SELECT status, COUNT(*) FROM scraping_jobs GROUP BY status")).fetchall())
    success  = statuses.get('success', 0)
    pending  = statuses.get('pending', 0)
    total_jobs = success + pending
    pct_done = 100 * success / total_jobs if total_jobs else 0

    tiers = dict(conn.execute(text(
        "SELECT tier_reached, COUNT(*) FROM scraping_jobs WHERE status='success' GROUP BY tier_reached ORDER BY tier_reached"
    )).fetchall())

    sources = dict(conn.execute(text(
        "SELECT fajr_iqama_source, COUNT(DISTINCT mosque_id) FROM prayer_schedules GROUP BY fajr_iqama_source ORDER BY COUNT(DISTINCT mosque_id) DESC"
    )).fetchall())

    real_iqama  = sources.get('mosque_website_html', 0) + sources.get('mosque_website_js', 0)
    custom_ext  = sources.get('mosque_website_html', 0)  # Tier 2c results also appear as html
    total_sched = sum(sources.values())
    pct_real    = 100 * real_iqama / total_sched if total_sched else 0

    # Count custom extractor hits (Tier 2c logged source = mosque_website_html but tier=2)
    tier2c_hits = conn.execute(text(
        "SELECT COUNT(*) FROM scraping_jobs WHERE tier_reached=2 AND status='success'"
    )).scalar()

    # Adaptive extractor stats
    import os, json
    analyzed_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline", "adaptive_analyzed.json")
    analyzed_count = 0
    if os.path.exists(analyzed_file):
        with open(analyzed_file) as f:
            analyzed_count = len(json.load(f))

    extractors_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline", "custom_extractors.py")
    extractor_count = 0
    if os.path.exists(extractors_file):
        with open(extractors_file) as f:
            extractor_count = f.read().count("CUSTOM_EXTRACTORS.append(")

    from datetime import datetime
    print(f"\n{'='*50}")
    print(f"  SCRAPING STATUS  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")
    print(f"  Mosques:   {total} total  ({with_sites} with websites)")
    print(f"  Progress:  {success}/{total_jobs} done  ({pct_done:.1f}%)   {pending} pending")
    print()
    print(f"  Tier breakdown:")
    tier_labels = {1: 'IslamicFinder/Aladhan', 2: 'HTML / custom extractor', 3: 'JS render', 4: 'Vision/PDF', 5: 'calculated'}
    for t, cnt in sorted(tiers.items()):
        print(f"    Tier {t}  {tier_labels.get(t, f'tier{t}'):<28} {cnt:>5}")
    print()
    print(f"  Iqama sources  ({total_sched} mosques with schedules):")
    for src, cnt in sources.items():
        marker = " ✓" if src in ('mosque_website_html', 'mosque_website_js') else ""
        print(f"    {src:<32} {cnt:>5}{marker}")
    print(f"  → Real data: {real_iqama} mosques  ({pct_real:.1f}%)")
    print()
    print(f"  Adaptive extractor:")
    print(f"    Custom extractors generated:  {extractor_count}")
    print(f"    Domains analyzed:             {analyzed_count}")
    print(f"{'='*50}\n")
PYEOF
}

MODE=${1:-metrics}

case "$MODE" in
    metrics|"")
        # Default: print current metrics once and exit
        print_metrics_now
        ;;
    watch)
        # Auto-refresh metrics every 30s
        while true; do
            clear
            print_metrics_now
            sleep 30
        done
        ;;
    tail)
        # Tail the live scraping log
        echo "Tailing $LOG_FILE  (Ctrl-C to stop)"
        echo "Tip: run './monitor_scraping.sh watch' in another terminal for live metrics."
        if [ ! -f "$LOG_FILE" ]; then
            echo "Log file not found yet — waiting for run_scraping_loop.sh to start..."
            until [ -f "$LOG_FILE" ]; do sleep 1; done
        fi
        tail -f "$LOG_FILE"
        ;;
    *)
        echo "Usage: $0 [metrics|watch|tail]"
        echo "  metrics  — print current DB metrics once (default)"
        echo "  watch    — refresh metrics every 30s"
        echo "  tail     — follow the live scraping log"
        ;;
esac
