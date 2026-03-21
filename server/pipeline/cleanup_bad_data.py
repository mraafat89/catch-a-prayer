"""
Clean up existing bad prayer data in DB.
Nulls out fields that fail validation so daily_calculated can replace them.
Run after validation audit to fix historical issues.

Usage: python -m pipeline.cleanup_bad_data
       python -m pipeline.cleanup_bad_data --dry-run
"""
import argparse
import os
from datetime import date
from sqlalchemy import create_engine, text
from pipeline.validation import validate_prayer_schedule

pg_pass = os.environ.get("POSTGRES_PASSWORD", "cap")
engine = create_engine(f"postgresql+psycopg2://cap:{pg_pass}@db:5432/catchaprayer")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    today = date.today()
    nulled_fields = 0
    deleted_rows = 0
    total_checked = 0

    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT ps.id::text, ps.mosque_id::text,
                ps.fajr_adhan, ps.fajr_iqama, ps.sunrise,
                ps.dhuhr_adhan, ps.dhuhr_iqama,
                ps.asr_adhan, ps.asr_iqama,
                ps.maghrib_adhan, ps.maghrib_iqama,
                ps.isha_adhan, ps.isha_iqama,
                ps.fajr_adhan_source
            FROM prayer_schedules ps
            WHERE ps.date = :today
        """), {"today": today}).fetchall()

        for r in rows:
            total_checked += 1
            row_id = r[0]
            source = r[13] or "unknown"
            scraped = {
                "fajr_adhan": r[2], "fajr_iqama": r[3], "sunrise": r[4],
                "dhuhr_adhan": r[5], "dhuhr_iqama": r[6],
                "asr_adhan": r[7], "asr_iqama": r[8],
                "maghrib_adhan": r[9], "maghrib_iqama": r[10],
                "isha_adhan": r[11], "isha_iqama": r[12],
            }

            vr = validate_prayer_schedule(scraped)

            if not vr.issues:
                continue

            if not vr.valid:
                # Fatal: delete the row so daily_calculated regenerates it
                if not args.dry_run:
                    conn.execute(text(
                        "DELETE FROM prayer_schedules WHERE id = CAST(:id AS uuid)"
                    ), {"id": row_id})
                deleted_rows += 1
                continue

            # Non-fatal: null out specific bad fields
            updates = []
            for issue in vr.issues:
                field = issue["field"]
                action = issue["action"]
                if action == "nulled" and field in scraped:
                    updates.append(f"{field} = NULL")
                    nulled_fields += 1
                # Also null corresponding source column
                if action == "nulled":
                    for suffix in ["_source", "_confidence"]:
                        src_field = field + suffix
                        if src_field.replace("_source", "").replace("_confidence", "") in scraped:
                            updates.append(f"{field}{suffix} = NULL")

            if updates and not args.dry_run:
                update_sql = ", ".join(set(updates))
                conn.execute(text(
                    f"UPDATE prayer_schedules SET {update_sql} WHERE id = CAST(:id AS uuid)"
                ), {"id": row_id})

    print(f"\nCLEANUP {'(DRY RUN) ' if args.dry_run else ''}COMPLETE")
    print(f"  Checked: {total_checked}")
    print(f"  Deleted (fatal): {deleted_rows}")
    print(f"  Fields nulled: {nulled_fields}")
    print(f"  Clean rows: {total_checked - deleted_rows - (nulled_fields > 0 and 1 or 0)}")

    if deleted_rows > 0 and not args.dry_run:
        print(f"\nRun daily_calculated to regenerate {deleted_rows} deleted rows:")
        print(f"  python -m pipeline.daily_calculated")


if __name__ == "__main__":
    main()
