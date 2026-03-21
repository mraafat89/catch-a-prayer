"""
Daily Alerts & Smart Notifications → WhatsApp
================================================
Sends daily digest + checks thresholds for anomalies.
Runs every hour for alerts, once at 9 AM ET for daily digest.

Usage:
    python -m pipeline.daily_alerts               # smart alerts only (hourly)
    python -m pipeline.daily_alerts --digest       # full daily digest
    python -m pipeline.daily_alerts --test         # send test message
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://cap:cap@db:5432/catchaprayer")
PHONE = os.environ.get("WHATSAPP_NUMBER", "14342499037@s.whatsapp.net")
ADMIN_KEY = os.environ.get("ADMIN_API_KEY", "37c0f1c589cbc6119be7d599974a9f58")
DASHBOARD_URL = f"https://catchaprayer.com/api/admin/dashboard?key={ADMIN_KEY}"

# Where we persist state between runs (last known values for comparison)
STATE_FILE = "/tmp/cap_alert_state.json"


def send_whatsapp(message: str) -> bool:
    """Send a WhatsApp message via OpenClaw CLI, or print to stdout if not available."""
    try:
        result = subprocess.run(
            ["openclaw", "message", "send",
             "--channel", "whatsapp",
             "--target", PHONE,
             "--message", message],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            log.info("WhatsApp message sent")
            return True
        log.error("OpenClaw failed: %s", result.stderr)
        return False
    except FileNotFoundError:
        # Running inside Docker — print message for bash wrapper to pick up
        print("__WHATSAPP_MSG_START__")
        print(message)
        print("__WHATSAPP_MSG_END__")
        return True
    except Exception as e:
        log.error("Failed to send: %s", e)
        return False


def load_state() -> dict:
    """Load previous alert state."""
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict):
    """Persist alert state."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


async def query_metrics(engine) -> dict:
    """Gather all metrics from DB."""
    metrics = {}
    today = date.today()

    async with engine.begin() as conn:
        # --- Mosque counts ---
        r = await conn.execute(text("""
            SELECT count(*) as total,
                count(*) filter (where website is not null) as has_website,
                count(*) filter (where phone is not null and phone != '') as has_phone
            FROM mosques WHERE is_active
        """))
        row = r.mappings().first()
        metrics["mosques_total"] = row["total"]
        metrics["mosques_website"] = row["has_website"]
        metrics["mosques_phone"] = row["has_phone"]

        # --- Prayer data quality ---
        r = await conn.execute(text("""
            SELECT count(*) as total,
                count(*) filter (where fajr_adhan_source != 'calculated') as real_data
            FROM prayer_schedules WHERE date = :today
        """), {"today": today})
        row = r.mappings().first()
        metrics["schedules_total"] = row["total"]
        metrics["real_data"] = row["real_data"]
        metrics["real_pct"] = round(row["real_data"] * 100 / max(row["total"], 1), 1)

        # --- Jumuah ---
        r = await conn.execute(text("SELECT count(distinct mosque_id) as cnt FROM jumuah_sessions"))
        metrics["jumuah_mosques"] = r.scalar()

        # --- Requests last 24h ---
        r = await conn.execute(text("""
            SELECT count(*) as total,
                count(distinct session_id) filter (where session_id is not null) as unique_users,
                count(*) filter (where response_code >= 500) as errors_5xx,
                round(avg(latency_ms)::numeric, 1) as avg_latency,
                round(percentile_cont(0.95) within group (order by latency_ms)::numeric, 1) as p95_latency,
                count(*) filter (where endpoint like '%%nearby%%') as searches,
                count(*) filter (where endpoint like '%%travel%%') as routes
            FROM request_logs WHERE created_at > now() - interval '24 hours'
        """))
        row = r.mappings().first()
        metrics["requests_24h"] = row["total"]
        metrics["unique_users_24h"] = row["unique_users"] or 0
        metrics["errors_5xx_24h"] = row["errors_5xx"]
        metrics["avg_latency_24h"] = float(row["avg_latency"] or 0)
        metrics["p95_latency_24h"] = float(row["p95_latency"] or 0)
        metrics["searches_24h"] = row["searches"]
        metrics["routes_24h"] = row["routes"]

        # --- Requests last hour (for hourly alerting) ---
        r = await conn.execute(text("""
            SELECT count(*) as total,
                count(*) filter (where response_code >= 500) as errors
            FROM request_logs WHERE created_at > now() - interval '1 hour'
        """))
        row = r.mappings().first()
        metrics["requests_1h"] = row["total"]
        metrics["errors_1h"] = row["errors"]

        # --- Geographic spread: unique states with search activity ---
        r = await conn.execute(text("""
            SELECT DISTINCT m.state
            FROM request_logs rl
            JOIN mosques m ON m.lat BETWEEN rl.lat - 0.2 AND rl.lat + 0.2
                          AND m.lng BETWEEN rl.lng - 0.2 AND rl.lng + 0.2
            WHERE rl.created_at > now() - interval '7 days'
              AND rl.lat IS NOT NULL AND m.state IS NOT NULL AND m.is_active
            LIMIT 50
        """))
        metrics["active_states"] = sorted([row["state"] for row in r.mappings()])

        # --- Canada activity ---
        r = await conn.execute(text("""
            SELECT count(*) as cnt FROM request_logs
            WHERE created_at > now() - interval '7 days'
              AND lat IS NOT NULL AND lat > 41.5 AND lat < 83
              AND lng > -141 AND lng < -52
        """))
        metrics["canada_searches_7d"] = r.scalar() or 0

        # --- New mosques added this week ---
        r = await conn.execute(text("""
            SELECT count(*) as cnt FROM mosques
            WHERE created_at > now() - interval '7 days' AND is_active
        """))
        metrics["new_mosques_7d"] = r.scalar() or 0

        # --- Scraper health ---
        r = await conn.execute(text("""
            SELECT count(*) filter (where status = 'success' and scraped_at > now() - interval '24 hours') as ok_24h,
                   count(*) filter (where status = 'failed' and scraped_at > now() - interval '24 hours') as fail_24h
            FROM scraping_jobs
        """))
        row = r.mappings().first()
        metrics["scraper_ok_24h"] = row["ok_24h"]
        metrics["scraper_fail_24h"] = row["fail_24h"]

        # --- DB size ---
        r = await conn.execute(text("""
            SELECT pg_size_pretty(pg_database_size('catchaprayer')) as size
        """))
        metrics["db_size"] = r.scalar()

    return metrics


def check_alerts(metrics: dict, prev: dict) -> list[str]:
    """
    Check metrics against thresholds. Returns list of alert messages.
    Each alert is a single line with an emoji prefix.
    """
    alerts = []

    # ── Bad things ──────────────────────────────────────────────
    # 5xx errors in the last hour
    if metrics["errors_1h"] > 5:
        alerts.append(f"{metrics['errors_1h']} server errors in the last hour!")

    # 5xx error rate > 5% in last 24h
    if metrics["requests_24h"] > 20:
        err_rate = metrics["errors_5xx_24h"] * 100 / metrics["requests_24h"]
        if err_rate > 5:
            alerts.append(f"Error rate {err_rate:.1f}% in last 24h ({metrics['errors_5xx_24h']} of {metrics['requests_24h']})")

    # P95 latency above 2 seconds
    if metrics["p95_latency_24h"] > 2000:
        alerts.append(f"P95 latency is {metrics['p95_latency_24h']:.0f}ms — responses are slow!")

    # No requests at all in 24h (API might be down)
    if metrics["requests_24h"] == 0 and prev.get("requests_24h", 0) > 0:
        alerts.append("Zero API requests in the last 24h — is the server down?")

    # Real data percentage dropped significantly
    prev_pct = prev.get("real_pct", 0)
    if prev_pct > 0 and metrics["real_pct"] < prev_pct - 5:
        alerts.append(f"Real data dropped from {prev_pct}% to {metrics['real_pct']}%")

    # Scraper failures > 50% of runs
    scraper_total = metrics["scraper_ok_24h"] + metrics["scraper_fail_24h"]
    if scraper_total > 5 and metrics["scraper_fail_24h"] > scraper_total * 0.5:
        alerts.append(f"Scraper failing: {metrics['scraper_fail_24h']}/{scraper_total} failed in 24h")

    # ── Good things ─────────────────────────────────────────────
    # Traffic milestone crossed
    for milestone in [100, 500, 1000, 5000, 10000, 50000]:
        if metrics["requests_24h"] >= milestone and prev.get("requests_24h", 0) < milestone:
            alerts.append(f"Hit {milestone:,} requests in a day!")
            break

    # Unique users milestone
    for milestone in [10, 50, 100, 500, 1000]:
        if metrics["unique_users_24h"] >= milestone and prev.get("unique_users_24h", 0) < milestone:
            alerts.append(f"{milestone} unique users in a day!")
            break

    # New state appeared in searches
    prev_states = set(prev.get("active_states", []))
    new_states = set(metrics["active_states"]) - prev_states
    if new_states and prev_states:  # only alert if we had state data before
        alerts.append(f"New activity from: {', '.join(sorted(new_states))}")

    # Canada activity starting
    if metrics["canada_searches_7d"] > 0 and prev.get("canada_searches_7d", 0) == 0:
        alerts.append(f"First Canadian searches detected! ({metrics['canada_searches_7d']} in 7 days)")
    elif metrics["canada_searches_7d"] >= 10 and prev.get("canada_searches_7d", 0) < 10:
        alerts.append(f"Canada is picking up: {metrics['canada_searches_7d']} searches this week")

    # Route planning usage growing
    if metrics["routes_24h"] >= 10 and prev.get("routes_24h", 0) < 10:
        alerts.append(f"Route planning taking off: {metrics['routes_24h']} routes planned today")

    # Real data improvement
    if metrics["real_pct"] >= prev_pct + 5 and prev_pct > 0:
        alerts.append(f"Real data improved: {prev_pct}% → {metrics['real_pct']}%!")

    # Mosque count growth
    if metrics["new_mosques_7d"] > 10:
        alerts.append(f"{metrics['new_mosques_7d']} new mosques added this week")

    return alerts


def format_daily_digest(metrics: dict) -> str:
    """Format the daily digest message."""
    today_str = date.today().strftime("%b %d, %Y")
    real_pct = metrics["real_pct"]

    # Status emoji based on health
    if metrics["errors_5xx_24h"] > 10 or metrics["p95_latency_24h"] > 3000:
        health = "🔴"
    elif metrics["errors_5xx_24h"] > 0 or metrics["p95_latency_24h"] > 1000:
        health = "🟡"
    else:
        health = "🟢"

    states_str = ", ".join(metrics["active_states"][:10]) if metrics["active_states"] else "None yet"
    if len(metrics["active_states"]) > 10:
        states_str += f" +{len(metrics['active_states']) - 10} more"

    msg = f"""Catch a Prayer — Daily Report
{today_str}

{health} System Health
• Requests (24h): {metrics['requests_24h']:,}
• Unique users: {metrics['unique_users_24h']}
• Errors: {metrics['errors_5xx_24h']} | Latency: {metrics['avg_latency_24h']:.0f}ms avg, {metrics['p95_latency_24h']:.0f}ms p95

Coverage
• Mosques: {metrics['mosques_total']:,} ({metrics['mosques_website']:,} websites, {metrics['mosques_phone']:,} phones)
• Jumuah data: {metrics['jumuah_mosques']} mosques

Prayer Data Quality
• Real: {metrics['real_data']:,} ({real_pct}%) | Calc: {metrics['schedules_total'] - metrics['real_data']:,}

User Activity
• Searches: {metrics['searches_24h']} | Routes: {metrics['routes_24h']}
• Active states: {states_str}
• Canada: {metrics['canada_searches_7d']} searches (7d)

Scraper (24h): {metrics['scraper_ok_24h']} ok, {metrics['scraper_fail_24h']} failed
DB size: {metrics['db_size']}

{DASHBOARD_URL}"""

    return msg


async def run(mode: str):
    """Main entry point."""
    engine = create_async_engine(DATABASE_URL)

    try:
        metrics = await query_metrics(engine)
        prev = load_state()

        if mode == "test":
            send_whatsapp(f"Test alert from Catch a Prayer\nTimestamp: {datetime.utcnow().isoformat()[:19]} UTC\n\n{DASHBOARD_URL}")
            return

        if mode == "digest":
            # Full daily digest
            msg = format_daily_digest(metrics)

            # Also check for alerts and append if any
            alerts = check_alerts(metrics, prev)
            if alerts:
                msg += "\n\nAlerts:\n" + "\n".join(alerts)

            send_whatsapp(msg)
            log.info("Daily digest sent")

        elif mode == "alerts":
            # Hourly smart alerts — only send if there's something noteworthy
            alerts = check_alerts(metrics, prev)
            if alerts:
                msg = f"Cap Alert — {datetime.utcnow().strftime('%b %d %H:%M')} UTC\n\n"
                msg += "\n".join(alerts)
                msg += f"\n\n{DASHBOARD_URL}"
                send_whatsapp(msg)
                log.info("Sent %d alerts", len(alerts))
            else:
                log.info("No alerts to send — all metrics normal")

        # Save current state for next comparison
        save_state(metrics)

    finally:
        await engine.dispose()


if __name__ == "__main__":
    import asyncio

    parser = argparse.ArgumentParser(description="Daily alerts & notifications")
    parser.add_argument("--digest", action="store_true", help="Send full daily digest")
    parser.add_argument("--test", action="store_true", help="Send test message")
    args = parser.parse_args()

    if args.test:
        mode = "test"
    elif args.digest:
        mode = "digest"
    else:
        mode = "alerts"

    asyncio.run(run(mode))
