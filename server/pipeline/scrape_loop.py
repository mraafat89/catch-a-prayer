"""
Autonomous Scraping Loop
==========================
Runs scraper batches in a loop, samples failures between batches,
logs progress, and keeps going until no more sites to scrape.

Usage:
    python -m pipeline.scrape_loop                    # default: 5 rounds of 200 sites
    python -m pipeline.scrape_loop --rounds 10        # 10 rounds
    python -m pipeline.scrape_loop --batch-size 100   # smaller batches
    python -m pipeline.scrape_loop --forever           # run until no sites left
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
from datetime import date

from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

pg_pass = os.environ.get("POSTGRES_PASSWORD", "cap")
pg_user = os.environ.get("POSTGRES_USER", "cap")
pg_db = os.environ.get("POSTGRES_DB", "catchaprayer")
if pg_pass and pg_pass != "cap":
    DB_URL = f"postgresql+psycopg2://{pg_user}:{pg_pass}@db:5432/{pg_db}"
else:
    _raw = os.environ.get("DATABASE_URL", "postgresql+asyncpg://cap:cap@db:5432/catchaprayer")
    DB_URL = _raw.replace("+asyncpg", "+psycopg2")


def get_stats(engine) -> dict:
    """Get current scraping stats."""
    with engine.connect() as conn:
        r = conn.execute(text("""
            SELECT
                (SELECT count(*) FROM prayer_schedules WHERE date = CURRENT_DATE AND fajr_adhan_source != 'calculated') as real_data,
                (SELECT count(*) FROM prayer_schedules WHERE date = CURRENT_DATE) as total,
                (SELECT count(*) FROM prayer_schedules WHERE date = CURRENT_DATE AND fajr_adhan_source = 'playwright_scrape') as playwright,
                (SELECT count(*) FROM prayer_schedules WHERE date = CURRENT_DATE AND fajr_adhan_source = 'jina_reader') as jina,
                (SELECT count(*) FROM mosques m
                    JOIN scraping_jobs sj ON sj.mosque_id = m.id AND sj.website_alive = true
                    WHERE m.is_active AND m.website IS NOT NULL
                    AND m.website NOT LIKE '%facebook%' AND m.website NOT LIKE '%instagram%'
                    AND m.website NOT LIKE '%youtube%' AND m.website NOT LIKE '%yelp%'
                    AND m.website NOT LIKE '%x.com%'
                    AND m.id NOT IN (SELECT mosque_id FROM prayer_schedules
                        WHERE date = CURRENT_DATE AND fajr_adhan_source NOT IN ('calculated'))
                ) as remaining,
                (SELECT count(*) FROM scraping_validation_log WHERE scrape_date = CURRENT_DATE) as validation_issues
        """)).mappings().first()
        return dict(r)


def sample_failures(engine, limit: int = 5) -> list[dict]:
    """Sample random alive websites that haven't been scraped successfully."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT m.name, m.website
            FROM mosques m
            JOIN scraping_jobs sj ON sj.mosque_id = m.id AND sj.website_alive = true
            WHERE m.is_active AND m.website IS NOT NULL
              AND m.website NOT LIKE '%facebook%' AND m.website NOT LIKE '%instagram%'
              AND m.website NOT LIKE '%youtube%' AND m.website NOT LIKE '%yelp%'
              AND m.website NOT LIKE '%x.com%'
              AND m.id NOT IN (SELECT mosque_id FROM prayer_schedules
                  WHERE date = CURRENT_DATE AND fajr_adhan_source NOT IN ('calculated'))
            ORDER BY random() LIMIT :lim
        """), {"lim": limit}).fetchall()
        return [{"name": r[0], "website": r[1]} for r in rows]


async def run_playwright_batch(batch_size: int, engine):
    """Run one Playwright scraper batch."""
    from pipeline.smart_bulk_scraper import scrape_with_playwright, _get_websites
    websites = _get_websites(engine, batch_size)
    if not websites:
        return {"attempted": 0, "success": 0, "no_data": 0, "error": 0}
    return await scrape_with_playwright(websites, engine, save=True)


async def run_jina_batch(batch_size: int, engine):
    """Run one Jina Reader scraper batch."""
    from pipeline.smart_bulk_scraper import scrape_with_jina, _get_websites
    websites = _get_websites(engine, batch_size)
    if not websites:
        return {"attempted": 0, "success": 0, "no_data": 0, "error": 0}
    return await scrape_with_jina(websites, engine, save=True)


def main():
    parser = argparse.ArgumentParser(description="Autonomous scraping loop")
    parser.add_argument("--rounds", type=int, default=5, help="Number of rounds (default 5)")
    parser.add_argument("--batch-size", type=int, default=200, help="Sites per batch (default 200)")
    parser.add_argument("--forever", action="store_true", help="Run until no sites left")
    parser.add_argument("--method", choices=["playwright", "jina", "both"], default="both")
    args = parser.parse_args()

    engine = create_engine(DB_URL)

    # Initial stats
    stats = get_stats(engine)
    log.info(f"=== SCRAPE LOOP START ===")
    log.info(f"Real data: {stats['real_data']}/{stats['total']} ({stats['real_data']*100//max(stats['total'],1)}%)")
    log.info(f"PW: {stats['playwright']} | Jina: {stats['jina']}")
    log.info(f"Remaining targets: {stats['remaining']}")
    log.info(f"Method: {args.method} | Batch: {args.batch_size} | Rounds: {'infinite' if args.forever else args.rounds}")

    round_num = 0
    no_progress_count = 0
    prev_real = stats['real_data']

    while True:
        round_num += 1
        if not args.forever and round_num > args.rounds:
            break

        stats = get_stats(engine)
        if stats['remaining'] == 0:
            log.info("No more sites to scrape!")
            break

        log.info(f"\n--- Round {round_num} ---")
        log.info(f"Remaining: {stats['remaining']} | Real: {stats['real_data']}")

        # Sample failures for logging
        failures = sample_failures(engine, 3)
        if failures:
            log.info(f"Sample unscrapped sites:")
            for f in failures:
                log.info(f"  {f['name']}: {f['website']}")

        # Run scraper batch
        start = time.time()
        try:
            if args.method in ("playwright", "both"):
                log.info(f"Running Playwright on {args.batch_size} sites...")
                pw_stats = asyncio.run(run_playwright_batch(args.batch_size, engine))
                log.info(f"Playwright: {pw_stats['success']}/{pw_stats['attempted']} success")

            if args.method in ("jina", "both"):
                jina_size = args.batch_size // 2  # Jina is rate-limited, do fewer
                log.info(f"Running Jina on {jina_size} sites...")
                jina_stats = asyncio.run(run_jina_batch(jina_size, engine))
                log.info(f"Jina: {jina_stats['success']}/{jina_stats['attempted']} success")
        except Exception as e:
            log.error(f"Batch failed: {e}")

        elapsed = time.time() - start

        # Check progress
        new_stats = get_stats(engine)
        gained = new_stats['real_data'] - prev_real
        log.info(f"Round {round_num} done in {elapsed:.0f}s | +{gained} new | Real: {new_stats['real_data']} ({new_stats['real_data']*100//max(new_stats['total'],1)}%)")
        log.info(f"Validation issues today: {new_stats['validation_issues']}")

        # Detect stall
        if gained == 0:
            no_progress_count += 1
            log.info(f"No progress ({no_progress_count} rounds)")
            if no_progress_count >= 3:
                log.info("3 rounds with no progress — stopping. Remaining sites likely unscrappable.")
                break
        else:
            no_progress_count = 0

        prev_real = new_stats['real_data']

    # Final stats
    final = get_stats(engine)
    total_gained = final['real_data'] - stats.get('real_data', 0)
    log.info(f"\n=== SCRAPE LOOP COMPLETE ===")
    log.info(f"Rounds: {round_num}")
    log.info(f"Real data: {final['real_data']}/{final['total']} ({final['real_data']*100//max(final['total'],1)}%)")
    log.info(f"PW: {final['playwright']} | Jina: {final['jina']}")
    log.info(f"Remaining: {final['remaining']}")
    log.info(f"Total gained this session: +{total_gained}")


# Helper to be imported by the loop
def _get_websites(engine, limit: int) -> list[dict]:
    """Get websites to scrape, prioritized by high-population states."""
    HIGH_PRIORITY = "('NY','CA','TX','IL','NJ','FL','MI','PA','MD','VA','GA','OH','DC','ON','QC','BC','AB')"
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT m.id::text, m.name, m.website
            FROM mosques m
            JOIN scraping_jobs sj ON sj.mosque_id = m.id AND sj.website_alive = true
            WHERE m.is_active AND m.website IS NOT NULL
              AND m.website NOT LIKE '%facebook%' AND m.website NOT LIKE '%instagram%'
              AND m.website NOT LIKE '%youtube%' AND m.website NOT LIKE '%yelp%'
              AND m.website NOT LIKE '%x.com%'
              AND m.id NOT IN (SELECT mosque_id FROM prayer_schedules
                  WHERE date = CURRENT_DATE AND fajr_adhan_source NOT IN ('calculated'))
            ORDER BY CASE WHEN m.state IN {HIGH_PRIORITY} THEN 0 ELSE 1 END, random()
            LIMIT :lim
        """), {"lim": limit}).fetchall()
        return [{"id": r[0], "name": r[1], "website": r[2]} for r in rows]


if __name__ == "__main__":
    main()
