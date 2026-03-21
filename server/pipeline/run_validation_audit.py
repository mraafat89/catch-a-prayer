"""Run validation against all prayer schedules in DB and log issues."""
import os
from datetime import date
from sqlalchemy import create_engine, text
from pipeline.validation import validate_prayer_schedule, validate_jumuah

pg_pass = os.environ.get("POSTGRES_PASSWORD", "cap")
engine = create_engine(f"postgresql+psycopg2://cap:{pg_pass}@db:5432/catchaprayer")
today = date.today()

stats = {
    "total": 0, "valid": 0, "issues": 0, "fatal": 0,
    "by_issue": {}, "by_field": {}, "by_source": {},
}

with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT ps.mosque_id::text, ps.fajr_adhan, ps.fajr_iqama, ps.sunrise,
            ps.dhuhr_adhan, ps.dhuhr_iqama, ps.asr_adhan, ps.asr_iqama,
            ps.maghrib_adhan, ps.maghrib_iqama, ps.isha_adhan, ps.isha_iqama,
            ps.fajr_adhan_source, m.lat
        FROM prayer_schedules ps
        JOIN mosques m ON m.id = ps.mosque_id
        WHERE ps.date = :today
    """), {"today": today}).fetchall()

    issue_count = 0
    for r in rows:
        stats["total"] += 1
        source = r[12] or "unknown"
        mosque_lat = float(r[13]) if r[13] else None
        scraped = {
            "fajr_adhan": r[1], "fajr_iqama": r[2], "sunrise": r[3],
            "dhuhr_adhan": r[4], "dhuhr_iqama": r[5],
            "asr_adhan": r[6], "asr_iqama": r[7],
            "maghrib_adhan": r[8], "maghrib_iqama": r[9],
            "isha_adhan": r[10], "isha_iqama": r[11],
        }
        vr = validate_prayer_schedule(scraped, lat=mosque_lat)
        if not vr.issues:
            stats["valid"] += 1
        else:
            stats["issues"] += 1
            if not vr.valid:
                stats["fatal"] += 1
            for issue in vr.issues:
                desc = issue["issue"]
                field = issue["field"]
                stats["by_issue"][desc] = stats["by_issue"].get(desc, 0) + 1
                stats["by_field"][field] = stats["by_field"].get(field, 0) + 1
                stats["by_source"][source] = stats["by_source"].get(source, 0) + 1

            # Log to DB
            for issue in vr.issues:
                try:
                    conn.execute(text("""
                        INSERT INTO scraping_validation_log
                            (mosque_id, scrape_date, field_name, scraped_value,
                             expected_range, issue_description, action_taken)
                        VALUES (CAST(:mid AS uuid), :dt, :field, :val,
                                :expected, :issue, :action)
                    """), {
                        "mid": r[0], "dt": today,
                        "field": issue.get("field", ""),
                        "val": issue.get("value"),
                        "expected": issue.get("expected", ""),
                        "issue": issue.get("issue", ""),
                        "action": issue.get("action", ""),
                    })
                    issue_count += 1
                except Exception:
                    pass
    conn.commit()

print(f"\n=== VALIDATION REPORT ({today}) ===")
print(f"Total schedules: {stats['total']}")
print(f"Clean (no issues): {stats['valid']} ({stats['valid'] * 100 // max(stats['total'], 1)}%)")
print(f"With issues: {stats['issues']} ({stats['issues'] * 100 // max(stats['total'], 1)}%)")
print(f"Fatal (would reject): {stats['fatal']}")
print(f"Issues logged to DB: {issue_count}")

print(f"\n--- Top issues ---")
for issue, cnt in sorted(stats["by_issue"].items(), key=lambda x: -x[1])[:15]:
    print(f"  {cnt:4d}  {issue}")

print(f"\n--- By field ---")
for field, cnt in sorted(stats["by_field"].items(), key=lambda x: -x[1])[:15]:
    print(f"  {cnt:4d}  {field}")

print(f"\n--- By source ---")
for source, cnt in sorted(stats["by_source"].items(), key=lambda x: -x[1]):
    print(f"  {cnt:4d}  {source}")
