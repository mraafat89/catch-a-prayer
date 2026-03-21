"""
Daily Calculated Prayer Times
==============================
Generates calculated prayer times (praytimes library) for ALL mosques
that don't have fresh scraped data for today.

This ensures every mosque in the app shows prayer times, even if the
scraper hasn't reached it yet. Calculated times are clearly labeled
as source="calculated" so the app can display appropriate badges.

Runs daily via cron at 1 AM local time.

Usage:
    python -m pipeline.daily_calculated              # generate for today
    python -m pipeline.daily_calculated --date 2026-03-21
    python -m pipeline.daily_calculated --dry-run     # count only, don't save
"""

import asyncio
import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta

import pytz
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings
from app.services.prayer_calc import calculate_prayer_times, estimate_iqama_times

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
settings = get_settings()


def get_db():
    db_url = os.environ.get("DATABASE_URL", settings.database_url)
    sync_url = db_url.replace("+asyncpg", "+psycopg2")
    if "psycopg2" not in sync_url:
        sync_url = sync_url.replace("postgresql://", "postgresql+psycopg2://")
    return create_engine(sync_url)


def run(args):
    engine = get_db()
    target_date = date.fromisoformat(args.date) if args.date else date.today()

    logger.info(f"Generating calculated prayer times for {target_date}")

    with engine.connect() as conn:
        # Find mosques that DON'T have a schedule for today
        # (or have only calculated data that's stale)
        rows = conn.execute(text("""
            SELECT m.id::text, m.name, m.lat, m.lng, m.timezone
            FROM mosques m
            WHERE m.is_active
              AND m.lat IS NOT NULL AND m.lng IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM prayer_schedules ps
                  WHERE ps.mosque_id = m.id
                    AND ps.date = :target_date
                    AND ps.fajr_adhan_source != 'calculated'
              )
            ORDER BY m.id
        """), {"target_date": target_date}).fetchall()

    logger.info(f"Found {len(rows)} mosques needing calculated times")

    if args.dry_run:
        logger.info("DRY RUN — not saving")
        return

    saved = 0
    errors = 0

    with engine.begin() as conn:
        for i, row in enumerate(rows):
            mid, name, lat, lng = row[0], row[1], float(row[2]), float(row[3])
            tz_str = row[4] or "UTC"

            try:
                # Calculate timezone offset
                try:
                    tz = pytz.timezone(tz_str)
                    offset = tz.utcoffset(datetime.combine(target_date, datetime.min.time())).total_seconds() / 3600
                except Exception:
                    offset = -5  # default EST

                calc = calculate_prayer_times(lat, lng, target_date, timezone_offset=offset)
                if not calc:
                    continue

                iqama = estimate_iqama_times(calc)
                schedule = {**calc, **iqama}

                # Upsert prayer schedule
                conn.execute(text("""
                    INSERT INTO prayer_schedules (
                        id, mosque_id, date,
                        fajr_adhan, fajr_iqama, fajr_adhan_source, fajr_iqama_source,
                        fajr_adhan_confidence, fajr_iqama_confidence,
                        sunrise, sunrise_source,
                        dhuhr_adhan, dhuhr_iqama, dhuhr_adhan_source, dhuhr_iqama_source,
                        dhuhr_adhan_confidence, dhuhr_iqama_confidence,
                        asr_adhan, asr_iqama, asr_adhan_source, asr_iqama_source,
                        asr_adhan_confidence, asr_iqama_confidence,
                        maghrib_adhan, maghrib_iqama, maghrib_adhan_source, maghrib_iqama_source,
                        maghrib_adhan_confidence, maghrib_iqama_confidence,
                        isha_adhan, isha_iqama, isha_adhan_source, isha_iqama_source,
                        isha_adhan_confidence, isha_iqama_confidence,
                        scraped_at, created_at, updated_at
                    ) VALUES (
                        gen_random_uuid(), :mid, :date,
                        :fajr_a, :fajr_i, 'calculated', 'calculated', 'low', 'low',
                        :sunrise, 'calculated',
                        :dhuhr_a, :dhuhr_i, 'calculated', 'calculated', 'low', 'low',
                        :asr_a, :asr_i, 'calculated', 'calculated', 'low', 'low',
                        :maghrib_a, :maghrib_i, 'calculated', 'calculated', 'low', 'low',
                        :isha_a, :isha_i, 'calculated', 'calculated', 'low', 'low',
                        now(), now(), now()
                    )
                    ON CONFLICT (mosque_id, date)
                    DO UPDATE SET
                        fajr_adhan = CASE WHEN prayer_schedules.fajr_adhan_source = 'calculated' THEN :fajr_a ELSE prayer_schedules.fajr_adhan END,
                        fajr_iqama = CASE WHEN prayer_schedules.fajr_iqama_source = 'calculated' THEN :fajr_i ELSE prayer_schedules.fajr_iqama END,
                        dhuhr_adhan = CASE WHEN prayer_schedules.dhuhr_adhan_source = 'calculated' THEN :dhuhr_a ELSE prayer_schedules.dhuhr_adhan END,
                        dhuhr_iqama = CASE WHEN prayer_schedules.dhuhr_iqama_source = 'calculated' THEN :dhuhr_i ELSE prayer_schedules.dhuhr_iqama END,
                        asr_adhan = CASE WHEN prayer_schedules.asr_adhan_source = 'calculated' THEN :asr_a ELSE prayer_schedules.asr_adhan END,
                        asr_iqama = CASE WHEN prayer_schedules.asr_iqama_source = 'calculated' THEN :asr_i ELSE prayer_schedules.asr_iqama END,
                        maghrib_adhan = CASE WHEN prayer_schedules.maghrib_adhan_source = 'calculated' THEN :maghrib_a ELSE prayer_schedules.maghrib_adhan END,
                        maghrib_iqama = CASE WHEN prayer_schedules.maghrib_iqama_source = 'calculated' THEN :maghrib_i ELSE prayer_schedules.maghrib_iqama END,
                        isha_adhan = CASE WHEN prayer_schedules.isha_adhan_source = 'calculated' THEN :isha_a ELSE prayer_schedules.isha_adhan END,
                        isha_iqama = CASE WHEN prayer_schedules.isha_iqama_source = 'calculated' THEN :isha_i ELSE prayer_schedules.isha_iqama END,
                        sunrise = COALESCE(prayer_schedules.sunrise, :sunrise),
                        updated_at = now()
                """), {
                    "mid": mid, "date": target_date,
                    "fajr_a": schedule.get("fajr_adhan"),
                    "fajr_i": schedule.get("fajr_iqama"),
                    "sunrise": schedule.get("sunrise"),
                    "dhuhr_a": schedule.get("dhuhr_adhan"),
                    "dhuhr_i": schedule.get("dhuhr_iqama"),
                    "asr_a": schedule.get("asr_adhan"),
                    "asr_i": schedule.get("asr_iqama"),
                    "maghrib_a": schedule.get("maghrib_adhan"),
                    "maghrib_i": schedule.get("maghrib_iqama"),
                    "isha_a": schedule.get("isha_adhan"),
                    "isha_i": schedule.get("isha_iqama"),
                })
                saved += 1

            except Exception as e:
                errors += 1
                if errors <= 5:
                    logger.warning(f"  Failed for {name}: {e}")

            if (i + 1) % 500 == 0:
                logger.info(f"  Progress: {i+1}/{len(rows)} ({saved} saved)")

    logger.info(f"\nDONE: {saved} schedules generated, {errors} errors")


def main():
    parser = argparse.ArgumentParser(description="Generate calculated prayer times")
    parser.add_argument("--date", type=str, help="Target date (YYYY-MM-DD), default today")
    parser.add_argument("--dry-run", action="store_true", help="Count only, don't save")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
