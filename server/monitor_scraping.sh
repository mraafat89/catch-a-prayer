#!/usr/bin/env bash
# monitor_scraping.sh — Show current scraping metrics.
#
# Usage:
#   ./monitor_scraping.sh          — print metrics once (default)
#   ./monitor_scraping.sh watch    — auto-refresh every 30s
#   ./monitor_scraping.sh tail     — tail the live scraping log

set -euo pipefail
cd "$(dirname "$0")"

PYTHON=python3
LOG_FILE="logs/scraping.log"

print_metrics_now() {
    $PYTHON - <<'PYEOF'
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sqlalchemy import create_engine, text
from app.config import get_settings
from datetime import datetime

engine = create_engine(get_settings().database_url.replace("+asyncpg",""), echo=False)

with engine.connect() as c:
    total      = c.execute(text("SELECT COUNT(*) FROM mosques WHERE is_active=true")).scalar()
    with_web   = c.execute(text("SELECT COUNT(*) FROM mosques WHERE website IS NOT NULL AND website!='' AND is_active=true")).scalar()
    no_web     = total - with_web

    # ── Scraping jobs progress ──
    done       = c.execute(text("SELECT COUNT(*) FROM scraping_jobs WHERE status='success'")).scalar()
    pending    = c.execute(text("SELECT COUNT(*) FROM scraping_jobs WHERE status='pending'")).scalar()
    total_jobs = done + pending

    # ── Tier breakdown (success jobs) ──
    tiers = dict(c.execute(text(
        "SELECT tier_reached, COUNT(*) FROM scraping_jobs WHERE status='success' GROUP BY 1 ORDER BY 1"
    )).fetchall())

    # ── Real data: mosques with website that reached tier 2/3/4 ──
    real_scraped = c.execute(text("""
        SELECT COUNT(*) FROM mosques m JOIN scraping_jobs j ON j.mosque_id=m.id
        WHERE m.website IS NOT NULL AND m.website!='' AND m.is_active=true
          AND j.tier_reached IN (2,3,4) AND j.status='success'
    """)).scalar()

    # ── Stuck: website + tier 5 ──
    stuck = c.execute(text("""
        SELECT COUNT(*) FROM mosques m JOIN scraping_jobs j ON j.mosque_id=m.id
        WHERE m.website IS NOT NULL AND m.website!='' AND m.is_active=true
          AND j.tier_reached=5
    """)).scalar()

    # ── Adaptive extractor stats ──
    base = os.path.dirname(os.path.abspath(__file__))
    analyzed_file   = os.path.join(base, "pipeline", "adaptive_analyzed.json")
    extractors_file = os.path.join(base, "pipeline", "custom_extractors.py")

    analyzed_count = 0
    cooldown_count = 0
    if os.path.exists(analyzed_file):
        with open(analyzed_file) as f:
            data = json.load(f)
        analyzed_count = len(data) if isinstance(data, dict) else len(data)
        cooldown_count = analyzed_count  # all entries are cooldown entries

    extractor_count = 0
    if os.path.exists(extractors_file):
        with open(extractors_file) as f:
            extractor_count = f.read().count("CUSTOM_EXTRACTORS.append(")

    pct_done   = 100 * done / total_jobs if total_jobs else 0
    pct_real   = 100 * real_scraped / with_web if with_web else 0
    pct_stuck  = 100 * stuck / with_web if with_web else 0
    remaining  = with_web - real_scraped

    print(f"\n{'='*54}")
    print(f"  SCRAPING METRICS  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*54}")
    print()

    # Primary metric — the number we're optimizing for
    bar_filled = int(pct_real / 2)
    bar = '█' * bar_filled + '░' * (50 - bar_filled)
    print(f"  🎯 REAL SCRAPE RATE (% of mosques with website)")
    print(f"     {bar}")
    print(f"     {real_scraped} / {with_web} mosques  =  {pct_real:.1f}%")
    print(f"     Target: 100% — {remaining} still to recover")
    print()

    print(f"  Mosque breakdown:")
    print(f"    Total mosques:           {total}")
    print(f"    With website:            {with_web}  ← scraping target")
    print(f"    No website (floor):      {no_web}  (can't scrape without URL)")
    print()

    print(f"  Jobs progress:  {done}/{total_jobs}  ({pct_done:.1f}% done, {pending} pending)")
    print()

    print(f"  Tier breakdown  (website mosques):")
    tier_labels = {1:'IslamicFinder/Aladhan', 2:'HTML / custom extractor',
                   3:'JS render', 4:'Vision/PDF', 5:'calculated (stuck)'}
    for t, cnt in sorted(tiers.items()):
        marker = " ✓" if t in (2,3,4) else " ✗"
        pct = 100*cnt/with_web if with_web else 0
        print(f"    Tier {t}  {tier_labels.get(t,''):<28} {cnt:>5}  ({pct:.1f}%){marker}")
    print()

    print(f"  Adaptive extractor:")
    print(f"    Custom extractors generated:  {extractor_count}")
    print(f"    Domains on cooldown:          {cooldown_count}")
    print(f"    Mosques still stuck (T5+web): {stuck}  ({pct_stuck:.1f}% of websites)")
    print()

    # ── Mosque info coverage ──
    denom  = c.execute(text("SELECT COUNT(*) FROM mosques WHERE denomination IS NOT NULL AND is_active=true")).scalar()
    women  = c.execute(text("SELECT COUNT(*) FROM mosques WHERE has_womens_section IS NOT NULL AND is_active=true")).scalar()
    wheel  = c.execute(text("SELECT COUNT(*) FROM mosques WHERE wheelchair_accessible IS NOT NULL AND is_active=true")).scalar()
    langs  = c.execute(text("SELECT COUNT(*) FROM mosques WHERE languages_spoken IS NOT NULL AND array_length(languages_spoken,1)>0 AND is_active=true")).scalar()
    juma   = c.execute(text("SELECT COUNT(DISTINCT mosque_id) FROM jumuah_sessions")).scalar()
    print(f"  Mosque info coverage  (of {total} active mosques):")
    for label, val in [("denomination", denom), ("has_womens_section", women),
                       ("wheelchair", wheel), ("languages", langs), ("jumuah_sessions", juma)]:
        pct = 100 * val / total if total else 0
        print(f"    {label:<22} {val:>5}  ({pct:.1f}%)")
    print(f"{'='*54}\n")
PYEOF
}

MODE=${1:-metrics}

case "$MODE" in
    metrics|"")
        print_metrics_now
        ;;
    watch)
        while true; do
            clear
            print_metrics_now
            sleep 30
        done
        ;;
    tail)
        echo "Tailing $LOG_FILE  (Ctrl-C to stop)"
        echo "Run './monitor_scraping.sh watch' for live metrics."
        if [ ! -f "$LOG_FILE" ]; then
            echo "Waiting for log file..."
            until [ -f "$LOG_FILE" ]; do sleep 1; done
        fi
        tail -f "$LOG_FILE"
        ;;
    *)
        echo "Usage: $0 [metrics|watch|tail]"
        ;;
esac
