"""
Requeue Stale Mosques
=====================
Marks scraping jobs as pending for mosques whose prayer data is outdated.
Run before the scraping loop to trigger a refresh cycle.

Usage:
    python -m pipeline.requeue_stale                    # requeue mosques stale > 30 days
    python -m pipeline.requeue_stale --days 7           # requeue stale > 7 days
    python -m pipeline.requeue_stale --jumuah-only      # only re-run mosque info enricher targets
    python -m pipeline.requeue_stale --new-mosques      # re-seed OSM + web sources for new mosques
    python -m pipeline.requeue_stale --dry-run          # show counts without changing anything
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def requeue_stale_prayer_times(conn, days: int, dry_run: bool) -> int:
    """
    Mark scraping jobs as pending for mosques whose prayer schedule is older than `days`.
    This forces them through the full 5-tier scraping pipeline again.
    """
    result = conn.execute(text("""
        SELECT COUNT(*) FROM scraping_jobs j
        JOIN mosques m ON m.id = j.mosque_id
        WHERE j.status = 'success'
          AND m.is_active = true
          AND (
              j.scraped_at IS NULL
              OR j.scraped_at < NOW() - INTERVAL ':days days'
          )
    """.replace(":days days", f"{days} days")))
    count = result.scalar()
    logger.info(f"  Prayer times stale > {days} days: {count} mosques")

    if not dry_run and count > 0:
        conn.execute(text("""
            UPDATE scraping_jobs
            SET status = 'pending', tier_reached = NULL, error_message = NULL
            WHERE id IN (
                SELECT j.id FROM scraping_jobs j
                JOIN mosques m ON m.id = j.mosque_id
                WHERE j.status = 'success'
                  AND m.is_active = true
                  AND (
                      j.scraped_at IS NULL
                      OR j.scraped_at < NOW() - INTERVAL ':days days'
                  )
            )
        """.replace(":days days", f"{days} days")))
        logger.info(f"  ✓ Re-queued {count} jobs for re-scraping")
    return count


def requeue_stale_jumuah(conn, days: int, dry_run: bool) -> int:
    """
    Clear denomination_enriched_at for mosques not enriched recently,
    so the mosque_info_enricher re-processes them (picks up new Jumuah times).
    """
    result = conn.execute(text("""
        SELECT COUNT(*) FROM mosques
        WHERE is_active = true
          AND website IS NOT NULL AND website != ''
          AND (
              denomination_enriched_at IS NULL
              OR denomination_enriched_at < NOW() - INTERVAL ':days days'
          )
    """.replace(":days days", f"{days} days")))
    count = result.scalar()
    logger.info(f"  Mosques needing info re-enrichment (>{days} days): {count}")

    if not dry_run and count > 0:
        conn.execute(text("""
            UPDATE mosques
            SET denomination_enriched_at = NULL
            WHERE is_active = true
              AND website IS NOT NULL AND website != ''
              AND (
                  denomination_enriched_at IS NULL
                  OR denomination_enriched_at < NOW() - INTERVAL ':days days'
              )
        """.replace(":days days", f"{days} days")))
        logger.info(f"  ✓ Cleared enrichment timestamps for {count} mosques")
    return count


def seed_new_mosques(dry_run: bool) -> None:
    """
    Re-run OSM + web source seeding to pick up newly added mosques.
    Only adds new mosques — existing ones are untouched (upsert by name+coords).
    """
    if dry_run:
        logger.info("  [dry-run] Would re-run pipeline.seed_mosques and pipeline.seed_from_web_sources")
        return
    logger.info("  Re-seeding mosques from OSM and web sources...")
    os.system("python -m pipeline.seed_mosques")
    os.system("python -m pipeline.seed_from_web_sources")
    logger.info("  ✓ Seeding complete — new mosques (if any) added as pending scraping jobs")


def main():
    parser = argparse.ArgumentParser(description="Requeue stale mosque data for refresh")
    parser.add_argument("--days",         type=int,  default=30,    help="Requeue prayer times older than N days (default: 30)")
    parser.add_argument("--jumuah-days",  type=int,  default=7,     help="Requeue Jumuah info older than N days (default: 7)")
    parser.add_argument("--jumuah-only",  action="store_true",      help="Only requeue Jumuah/info enrichment, skip prayer times")
    parser.add_argument("--new-mosques",  action="store_true",      help="Also re-seed from OSM/web to discover new mosques")
    parser.add_argument("--dry-run",      action="store_true",      help="Show what would be requeued without changing anything")
    args = parser.parse_args()

    logger.info("=== Requeue Stale Mosque Data ===")
    if args.dry_run:
        logger.info("  [DRY RUN — no changes will be made]")

    settings = get_settings()
    engine = create_engine(settings.database_url.replace("+asyncpg", ""), echo=False)

    with engine.begin() as conn:
        if not args.jumuah_only:
            requeue_stale_prayer_times(conn, args.days, args.dry_run)
        requeue_stale_jumuah(conn, args.jumuah_days, args.dry_run)

    if args.new_mosques:
        seed_new_mosques(args.dry_run)

    logger.info("=== Done — run ./run_scraping_loop.sh to process requeued jobs ===")


if __name__ == "__main__":
    main()
