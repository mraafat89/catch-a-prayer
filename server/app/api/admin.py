"""
Admin API — Stats & Monitoring
================================
Provides metrics about data quality, server health, and usage.
Protected by API key — only accessible to admins.
"""
from __future__ import annotations
import os
import secrets
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db

router = APIRouter(tags=["admin"])

# Admin API key — set via ADMIN_API_KEY env var, or use a generated default
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "cap_admin_2026_secure_key")


def verify_admin(key: str = Query(None, alias="key")):
    """Verify admin API key from query parameter."""
    if not key or not secrets.compare_digest(key, ADMIN_API_KEY):
        raise HTTPException(status_code=403, detail="Invalid admin key")
    return True


@router.get("/admin/stats", dependencies=[Depends(verify_admin)])
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Comprehensive stats for monitoring dashboard."""

    today = date.today()
    week_ago = today - timedelta(days=7)

    stats = {}

    # === Mosque counts ===
    r = await db.execute(text("""
        SELECT
            count(*) as total,
            count(*) filter (where website is not null and website != '') as has_website,
            count(*) filter (where phone is not null and phone != '') as has_phone,
            count(*) filter (where google_place_id is not null) as has_google_id,
            count(*) filter (where has_womens_section = true) as has_womens,
            count(*) filter (where wheelchair_accessible = true) as has_wheelchair,
            count(*) filter (where denomination is not null) as has_denomination
        FROM mosques WHERE is_active
    """))
    row = r.mappings().first()
    stats["mosques"] = dict(row) if row else {}

    # === Prayer data quality ===
    r = await db.execute(text("""
        SELECT
            count(*) as total_schedules,
            count(*) filter (where fajr_adhan_source not in ('calculated')) as real_data,
            count(*) filter (where fajr_adhan_source = 'calculated') as calculated,
            count(*) filter (where fajr_adhan_source = 'html_parse') as html_parse,
            count(*) filter (where fajr_adhan_source = 'mawaqit_api') as mawaqit,
            count(*) filter (where fajr_adhan_source = 'islamicfinder') as islamicfinder,
            count(*) filter (where fajr_adhan_source like 'mosque_website%') as old_scraper,
            count(*) filter (where fajr_adhan_source like 'claude%') as claude_ai,
            count(*) filter (where fajr_adhan_source = 'iframe_widget') as iframe_widget
        FROM prayer_schedules WHERE date = :today
    """), {"today": today})
    row = r.mappings().first()
    stats["prayer_data_today"] = dict(row) if row else {}

    # === Jumuah coverage ===
    r = await db.execute(text("""
        SELECT
            count(distinct mosque_id) as mosques_with_jumuah,
            count(*) as total_sessions
        FROM jumuah_sessions
    """))
    row = r.mappings().first()
    stats["jumuah"] = dict(row) if row else {}

    # === Special prayers ===
    r = await db.execute(text("""
        SELECT prayer_type, count(distinct mosque_id) as mosques
        FROM special_prayers
        GROUP BY prayer_type
    """))
    stats["special_prayers"] = {row["prayer_type"]: row["mosques"] for row in r.mappings()}

    # === Coverage by state (top 15) ===
    r = await db.execute(text("""
        SELECT state, count(*) as mosques,
            count(*) filter (where id in (
                select mosque_id from prayer_schedules
                where date = :today and fajr_adhan_source != 'calculated'
            )) as real_data
        FROM mosques WHERE is_active AND state IS NOT NULL
        GROUP BY state ORDER BY count(*) DESC LIMIT 15
    """), {"today": today})
    stats["coverage_by_state"] = [dict(row) for row in r.mappings()]

    # === Scraper stats ===
    r = await db.execute(text("""
        SELECT
            count(*) filter (where status = 'success') as success,
            count(*) filter (where status = 'failed') as failed,
            count(*) filter (where status = 'pending') as pending,
            count(*) filter (where website_alive = false) as dead_websites,
            count(*) filter (where scrape_method is not null) as has_method
        FROM scraping_jobs
    """))
    row = r.mappings().first()
    stats["scraper"] = dict(row) if row else {}

    # === Data freshness ===
    r = await db.execute(text("""
        SELECT
            count(distinct mosque_id) filter (where date = :today) as today,
            count(distinct mosque_id) filter (where date >= :week_ago) as this_week
        FROM prayer_schedules
        WHERE fajr_adhan_source != 'calculated'
    """), {"today": today, "week_ago": week_ago})
    row = r.mappings().first()
    stats["freshness"] = dict(row) if row else {}

    # === Data freshness ===
    r = await db.execute(text("""
        SELECT
            round(avg(CURRENT_DATE - ps.date), 1) as avg_age_days,
            max(ps.date)::text as newest,
            min(ps.date)::text as oldest
        FROM prayer_schedules ps
        WHERE ps.fajr_adhan_source != 'calculated'
    """))
    row = r.mappings().first()
    stats["data_freshness"] = dict(row) if row else {}

    # === Mosque locations for heatmap ===
    r = await db.execute(text("""
        SELECT lat, lng FROM mosques
        WHERE is_active AND lat IS NOT NULL AND lng IS NOT NULL
    """))
    stats["mosque_locations"] = [[float(row["lat"]), float(row["lng"])] for row in r.mappings()]

    # === Top searched areas (from request metrics) ===
    # Populated from in-memory request_metrics

    # === Community suggestions ===
    r = await db.execute(text("""
        SELECT
            count(*) as total,
            count(*) filter (where status = 'pending') as pending,
            count(*) filter (where status = 'approved') as approved
        FROM mosque_suggestions
    """))
    row = r.mappings().first()
    stats["suggestions"] = dict(row) if row else {}

    # === Scraper run history ===
    r = await db.execute(text("""
        SELECT
            max(scraped_at)::text as last_scrape,
            count(*) filter (where scraped_at > now() - interval '7 days') as scraped_this_week,
            count(*) filter (where scraped_at > now() - interval '24 hours') as scraped_today
        FROM scraping_jobs WHERE status = 'success'
    """))
    row = r.mappings().first()
    stats["scraper_history"] = dict(row) if row else {}

    # === Scraper method breakdown ===
    r = await db.execute(text("""
        SELECT scrape_method, count(*) as cnt
        FROM scraping_jobs WHERE status = 'success' AND scrape_method IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC
    """))
    stats["scraper_methods"] = {row["scrape_method"]: row["cnt"] for row in r.mappings()}

    # === Alive/dead websites ===
    r = await db.execute(text("""
        SELECT
            count(*) filter (where website_alive = true) as alive,
            count(*) filter (where website_alive = false) as dead
        FROM scraping_jobs
    """))
    row = r.mappings().first()
    stats["website_health"] = dict(row) if row else {}

    # === Validation issues (today) ===
    r = await db.execute(text("""
        SELECT count(*) as total_issues,
            count(distinct mosque_id) as mosques_with_issues
        FROM scraping_validation_log WHERE scrape_date = CURRENT_DATE
    """))
    row = r.mappings().first()
    stats["validation_today"] = dict(row) if row else {}

    # === Prayer spots ===
    r = await db.execute(text("""
        SELECT
            count(*) as total,
            count(*) filter (where created_at > now() - interval '7 days') as added_this_week,
            count(*) filter (where created_at > now() - interval '24 hours') as added_today
        FROM prayer_spots
    """))
    row = r.mappings().first()
    stats["prayer_spots"] = dict(row) if row else {}

    # === User activity (from request_logs) ===
    r = await db.execute(text("""
        SELECT
            count(distinct session_id) filter (where created_at > now() - interval '24 hours') as users_today,
            count(distinct session_id) filter (where created_at > now() - interval '7 days') as users_this_week,
            count(*) filter (where endpoint like '%nearby%' and created_at > now() - interval '24 hours') as searches_today,
            count(*) filter (where endpoint like '%travel%' and created_at > now() - interval '24 hours') as routes_today
        FROM request_logs WHERE session_id IS NOT NULL
    """))
    row = r.mappings().first()
    stats["user_activity"] = dict(row) if row else {}

    # === User search locations (from request_logs) ===
    r = await db.execute(text("""
        SELECT lat, lng, count(*) as searches
        FROM request_logs
        WHERE lat IS NOT NULL AND lng IS NOT NULL
          AND created_at > now() - interval '30 days'
        GROUP BY lat, lng
    """))
    stats["user_searches"] = [[float(row["lat"]), float(row["lng"]), int(row["searches"])]
                               for row in r.mappings()]

    # === Route planning origins/destinations ===
    r = await db.execute(text("""
        SELECT lat, lng, count(*) as routes
        FROM request_logs
        WHERE lat IS NOT NULL AND endpoint LIKE '%%travel%%'
          AND created_at > now() - interval '30 days'
        GROUP BY lat, lng
    """))
    stats["route_origins"] = [[float(row["lat"]), float(row["lng"]), int(row["routes"])]
                               for row in r.mappings()]

    # === Coverage gaps (user searched but few mosques nearby) ===
    r = await db.execute(text("""
        SELECT rl.lat, rl.lng, count(distinct rl.id) as searches,
            (SELECT count(*) FROM mosques m
             WHERE m.is_active AND m.lat BETWEEN rl.lat-0.1 AND rl.lat+0.1
             AND m.lng BETWEEN rl.lng-0.1 AND rl.lng+0.1) as nearby_mosques
        FROM request_logs rl
        WHERE rl.lat IS NOT NULL AND rl.lng IS NOT NULL
          AND rl.created_at > now() - interval '30 days'
        GROUP BY rl.lat, rl.lng
        HAVING (SELECT count(*) FROM mosques m
                WHERE m.is_active AND m.lat BETWEEN rl.lat-0.1 AND rl.lat+0.1
                AND m.lng BETWEEN rl.lng-0.1 AND rl.lng+0.1) < 3
    """))
    stats["coverage_gaps"] = [[float(row["lat"]), float(row["lng"]), int(row["searches"])]
                               for row in r.mappings()]

    # === Request volume by day (last 30 days) ===
    r = await db.execute(text("""
        SELECT date_trunc('day', created_at)::date::text as day, count(*) as requests
        FROM request_logs
        WHERE created_at > now() - interval '30 days'
        GROUP BY 1 ORDER BY 1
    """))
    stats["daily_requests"] = {row["day"]: row["requests"] for row in r.mappings()}

    # === Hourly request volume (last 48 hours) — for live chart ===
    r = await db.execute(text("""
        SELECT to_char(date_trunc('hour', created_at), 'MM/DD HH24:00') as hour,
               count(*) as requests,
               round(avg(latency_ms)::numeric, 1) as avg_latency,
               count(*) filter (where response_code >= 500) as errors
        FROM request_logs
        WHERE created_at > now() - interval '48 hours'
        GROUP BY 1 ORDER BY 1
    """))
    hourly = [dict(row) for row in r.mappings()]
    stats["hourly_requests"] = hourly

    # === Endpoint latency breakdown (last 24h) ===
    r = await db.execute(text("""
        SELECT endpoint,
               count(*) as hits,
               round(avg(latency_ms)::numeric, 1) as avg_ms,
               round(percentile_cont(0.95) within group (order by latency_ms)::numeric, 1) as p95_ms,
               max(latency_ms) as max_ms
        FROM request_logs
        WHERE created_at > now() - interval '24 hours'
        GROUP BY endpoint ORDER BY count(*) DESC LIMIT 10
    """))
    stats["endpoint_latency"] = [dict(row) for row in r.mappings()]

    # === Request metrics (in-memory, since last restart) ===
    try:
        from app.main import request_metrics as rm
        avg_latency = round(rm["latency_sum_ms"] / max(rm["latency_count"], 1), 1)
        stats["api_usage"] = {
            "total_requests": rm["total_requests"],
            "errors_5xx": rm["errors_5xx"],
            "avg_latency_ms": avg_latency,
            "unique_locations": len(rm["unique_locations"]),
            "routes_planned": rm["routes_planned"],
            "spots_submitted": rm["spots_submitted"],
            "top_endpoints": dict(sorted(rm["requests_by_endpoint"].items(),
                                         key=lambda x: -x[1])[:10]),
            "requests_by_hour": dict(sorted(rm["requests_by_hour"].items())[-24:]),
            "tracking_since": rm["started_at"],
        }
    except Exception:
        stats["api_usage"] = {"error": "metrics not available"}

    # === Trend: real data % by day (last 14 days) ===
    r = await db.execute(text("""
        SELECT date::text as day,
            count(*) as total,
            count(*) filter (where fajr_adhan_source != 'calculated') as real_data
        FROM prayer_schedules
        WHERE date >= CURRENT_DATE - 14
        GROUP BY date ORDER BY date
    """))
    stats["trend_real_data"] = [
        {"day": row["day"], "pct": round(row["real_data"] * 100 / max(row["total"], 1), 1)}
        for row in r.mappings()
    ]

    # === Trend: scraper activity by day (last 14 days) ===
    r = await db.execute(text("""
        SELECT date_trunc('day', scraped_at)::date::text as day,
            count(*) filter (where status = 'success') as success,
            count(*) filter (where status = 'failed') as failed
        FROM scraping_jobs
        WHERE scraped_at > now() - interval '14 days'
        GROUP BY 1 ORDER BY 1
    """))
    stats["trend_scraper"] = [dict(row) for row in r.mappings()]

    # === Trend: validation issues by day (last 14 days) ===
    r = await db.execute(text("""
        SELECT scrape_date::text as day, count(*) as issues
        FROM scraping_validation_log
        WHERE scrape_date >= CURRENT_DATE - 14
        GROUP BY 1 ORDER BY 1
    """))
    stats["trend_validation"] = [dict(row) for row in r.mappings()]

    # === Server info ===
    stats["server"] = {
        "timestamp": datetime.utcnow().isoformat(),
        "date": today.isoformat(),
    }

    return stats


# ---------------------------------------------------------------------------
# Admin Review Queue — accept/reject community suggestions
# ---------------------------------------------------------------------------

@router.get("/admin/suggestions", dependencies=[Depends(verify_admin)])
async def list_pending_suggestions(db: AsyncSession = Depends(get_db)):
    """List all pending community suggestions for admin review."""
    r = await db.execute(text("""
        SELECT s.id::text, s.mosque_id::text, m.name as mosque_name,
               s.field_name, s.suggested_value, s.current_value,
               s.upvote_count, s.downvote_count, s.submitted_by_session,
               s.created_at::text, s.expires_at::text
        FROM mosque_suggestions s
        JOIN mosques m ON m.id = s.mosque_id
        WHERE s.status = 'pending'
        ORDER BY s.created_at DESC
        LIMIT 100
    """))
    return [dict(row) for row in r.mappings()]


@router.post("/admin/suggestions/{suggestion_id}/accept", dependencies=[Depends(verify_admin)])
async def accept_suggestion(suggestion_id: str, db: AsyncSession = Depends(get_db)):
    """Admin force-accept a suggestion and apply the change."""
    r = await db.execute(text("""
        SELECT id, mosque_id::text, field_name, suggested_value, status
        FROM mosque_suggestions WHERE id = CAST(:id AS uuid)
    """), {"id": suggestion_id})
    row = r.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if row["status"] != "pending":
        raise HTTPException(status_code=410, detail=f"Suggestion already {row['status']}")

    # Apply the change
    from app.api.suggestions import _apply_suggestion
    await _apply_suggestion(db, row["mosque_id"], row["field_name"], row["suggested_value"])

    await db.execute(text("""
        UPDATE mosque_suggestions SET status = 'accepted', updated_at = NOW()
        WHERE id = CAST(:id AS uuid)
    """), {"id": suggestion_id})
    await db.commit()
    return {"status": "accepted", "id": suggestion_id}


@router.post("/admin/suggestions/{suggestion_id}/reject", dependencies=[Depends(verify_admin)])
async def reject_suggestion(suggestion_id: str, db: AsyncSession = Depends(get_db)):
    """Admin force-reject a suggestion."""
    r = await db.execute(text("""
        SELECT id, status FROM mosque_suggestions WHERE id = CAST(:id AS uuid)
    """), {"id": suggestion_id})
    row = r.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if row["status"] != "pending":
        raise HTTPException(status_code=410, detail=f"Suggestion already {row['status']}")

    await db.execute(text("""
        UPDATE mosque_suggestions SET status = 'rejected', updated_at = NOW()
        WHERE id = CAST(:id AS uuid)
    """), {"id": suggestion_id})
    await db.commit()
    return {"status": "rejected", "id": suggestion_id}


@router.get("/admin/dashboard", response_class=None, dependencies=[Depends(verify_admin)])
async def dashboard(db: AsyncSession = Depends(get_db)):
    """Simple HTML dashboard page."""
    from fastapi.responses import HTMLResponse

    stats = await get_stats(db)
    m = stats["mosques"]
    p = stats["prayer_data_today"]
    j = stats["jumuah"]
    f = stats["freshness"]

    real_pct = round(p.get("real_data", 0) * 100 / max(p.get("total_schedules", 1), 1), 1)

    # Coverage table rows
    coverage_rows = ""
    for s in stats["coverage_by_state"]:
        pct = round(s["real_data"] * 100 / max(s["mosques"], 1))
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        coverage_rows += f"<tr><td>{s['state']}</td><td>{s['mosques']}</td><td>{s['real_data']}</td><td>{pct}%</td><td style='font-family:monospace'>{bar}</td></tr>"

    # Pending suggestions for review queue
    pending_sug = await db.execute(text("""
        SELECT s.id::text, m.name as mosque_name,
               s.field_name, s.suggested_value, s.current_value,
               s.upvote_count, s.downvote_count, s.created_at::text
        FROM mosque_suggestions s
        JOIN mosques m ON m.id = s.mosque_id
        WHERE s.status = 'pending'
        ORDER BY s.created_at DESC LIMIT 20
    """))
    pending_suggestions = [dict(row) for row in pending_sug.mappings()]

    import json as _json
    locations_json = _json.dumps(stats.get("mosque_locations", []))
    scraper_h = stats.get("scraper_history", {})
    data_fresh = stats.get("data_freshness", {})
    suggestions = stats.get("suggestions", {})
    usage = stats.get("api_usage", {})

    # Requests by hour for chart
    hours_data = usage.get("requests_by_hour", {})
    hours_labels = _json.dumps(list(hours_data.keys())[-24:])
    hours_values = _json.dumps(list(hours_data.values())[-24:])

    # Hourly live data for Chart.js
    hourly = stats.get("hourly_requests", [])
    hourly_labels_json = _json.dumps([h["hour"] for h in hourly])
    hourly_reqs_json = _json.dumps([h["requests"] for h in hourly])
    hourly_latency_json = _json.dumps([float(h["avg_latency"] or 0) for h in hourly])
    hourly_errors_json = _json.dumps([h["errors"] for h in hourly])

    # Daily volume for bar chart
    daily_req = stats.get("daily_requests", {})
    daily_labels_json = _json.dumps(list(daily_req.keys()))
    daily_values_json = _json.dumps(list(daily_req.values()))

    # Trend data for charts
    trend_real = stats.get("trend_real_data", [])
    trend_real_labels = _json.dumps([t["day"][-5:] for t in trend_real])  # MM-DD
    trend_real_values = _json.dumps([t["pct"] for t in trend_real])

    trend_scraper = stats.get("trend_scraper", [])
    trend_scraper_labels = _json.dumps([t["day"][-5:] for t in trend_scraper])
    trend_scraper_success = _json.dumps([t["success"] for t in trend_scraper])
    trend_scraper_failed = _json.dumps([t["failed"] for t in trend_scraper])

    trend_val = stats.get("trend_validation", [])
    trend_val_labels = _json.dumps([t["day"][-5:] for t in trend_val])
    trend_val_values = _json.dumps([t["issues"] for t in trend_val])

    # Endpoint latency table
    ep_latency_rows = ""
    for ep in stats.get("endpoint_latency", []):
        color = "#dc2626" if float(ep.get("p95_ms", 0)) > 500 else "#666"
        ep_latency_rows += f"<tr><td><code>{ep['endpoint']}</code></td><td>{ep['hits']}</td><td>{ep['avg_ms']}ms</td><td style='color:{color}'>{ep['p95_ms']}ms</td><td>{ep['max_ms']}ms</td></tr>"

    # Top endpoints
    top_ep_rows = ""
    for ep, count in list(usage.get("top_endpoints", {}).items())[:8]:
        top_ep_rows += f"<tr><td><code>{ep}</code></td><td>{count}</td></tr>"

    # Review queue rows
    review_rows = ""
    for s in pending_suggestions:
        votes = f"+{s['upvote_count']}/-{s['downvote_count']}"
        created = s['created_at'][:16] if s['created_at'] else ''
        review_rows += f"""<tr>
<td>{s['mosque_name'][:30]}</td><td><code>{s['field_name']}</code></td>
<td>{s['current_value'] or '—'}</td><td><b>{s['suggested_value']}</b></td><td>{votes}</td><td>{created}</td>
<td><button onclick="reviewAction('{s['id']}','accept')" style="background:#16a34a;color:white;border:none;border-radius:4px;padding:3px 8px;cursor:pointer;font-size:11px;">✓</button>
<button onclick="reviewAction('{s['id']}','reject')" style="background:#dc2626;color:white;border:none;border-radius:4px;padding:3px 8px;cursor:pointer;font-size:11px;">✗</button></td></tr>"""

    ua = stats.get("user_activity", {})
    ps = stats.get("prayer_spots", {})
    wh = stats.get("website_health", {})
    vt = stats.get("validation_today", {})

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Catch a Prayer — Dashboard</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.heat/dist/leaflet-heat.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:600px;margin:0 auto;padding:12px;background:#f5f6f8;color:#1a1a1a;font-size:13px}}
h1{{color:#0d9488;font-size:20px;margin:0 0 2px}}
.sub{{color:#888;font-size:11px;margin-bottom:14px}}
.row{{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px;margin-bottom:14px}}
.c{{background:white;border-radius:10px;padding:10px;box-shadow:0 1px 2px rgba(0,0,0,.08);text-align:center}}
.c .n{{font-size:20px;font-weight:700;color:#0d9488}}
.c .l{{font-size:9px;color:#888;margin-top:2px}}
.c.w .n{{color:#d97706}}
.c.b .n{{color:#dc2626}}
.sect{{margin-top:16px}}
h2{{color:#2e3d44;font-size:14px;margin:0 0 8px;font-weight:600}}
.chart-box{{background:white;border-radius:10px;padding:10px;box-shadow:0 1px 2px rgba(0,0,0,.08);margin-bottom:8px}}
.tabs{{display:flex;gap:4px;margin-bottom:8px;flex-wrap:wrap}}
.tab{{padding:5px 10px;border-radius:6px;border:1px solid #ddd;background:white;cursor:pointer;font-size:11px;color:#555}}
.tab.on{{background:#0d9488;color:white;border-color:#0d9488}}
table{{width:100%;border-collapse:collapse;background:white;border-radius:10px;overflow:hidden;box-shadow:0 1px 2px rgba(0,0,0,.08)}}
th,td{{padding:5px 8px;text-align:left;border-bottom:1px solid #f0f0f0;font-size:11px}}
th{{background:#f8f9fa;font-weight:600;color:#666}}
#heatmap{{height:280px;border-radius:10px;box-shadow:0 1px 2px rgba(0,0,0,.08)}}
</style></head><body>

<h1>Catch a Prayer</h1>
<p class="sub">{stats['server']['date']} &mdash; <span id="refresh-timer">refreshes in 60s</span></p>

<!-- Key metrics -->
<div class="row">
  <div class="c"><div class="n">{m.get('total',0):,}</div><div class="l">Mosques</div></div>
  <div class="c {'w' if real_pct < 50 else ''}"><div class="n">{real_pct}%</div><div class="l">Real Data</div></div>
  <div class="c"><div class="n">{ua.get('users_today',0)}</div><div class="l">Users Today</div></div>
  <div class="c {'b' if usage.get('errors_5xx',0) > 0 else ''}"><div class="n">{usage.get('errors_5xx',0)}</div><div class="l">Errors</div></div>
</div>
<div class="row">
  <div class="c"><div class="n">{p.get('real_data',0):,}</div><div class="l">Real</div></div>
  <div class="c"><div class="n">{p.get('calculated',0):,}</div><div class="l">Calculated</div></div>
  <div class="c"><div class="n">{wh.get('alive',0):,}</div><div class="l">Sites Alive</div></div>
  <div class="c"><div class="n">{vt.get('total_issues',0)}</div><div class="l">Validation</div></div>
</div>

<!-- Trend chart with tabs -->
<div class="sect">
<h2>Trends</h2>
<div class="tabs">
  <div class="tab on" onclick="showTrend('real')">Data Quality</div>
  <div class="tab" onclick="showTrend('traffic')">Traffic</div>
  <div class="tab" onclick="showTrend('scraper')">Scraper</div>
</div>
<div class="chart-box">
  <canvas id="trend-chart" height="160"></canvas>
</div>
</div>

<!-- Heatmap -->
<div class="sect">
<h2>Map</h2>
<div class="tabs">
  <div class="tab on" id="btn-mosques" onclick="showLayer('mosques')">Mosques</div>
  <div class="tab" id="btn-searches" onclick="showLayer('searches')">Searches</div>
  <div class="tab" id="btn-routes" onclick="showLayer('routes')">Routes</div>
  <div class="tab" id="btn-gaps" onclick="showLayer('gaps')" title="Areas where users searched but fewer than 3 mosques nearby">Gaps</div>
</div>
<div id="heatmap"></div>
<p id="heatmap-label" style="font-size:10px;color:#888;margin:4px 0 0;"></p>
</div>

<!-- Data sources + scraper health -->
<div class="sect">
<h2>Data Sources</h2>
<table>
<tr><th>Source</th><th>Count</th><th>Source</th><th>Count</th></tr>
<tr><td>Calculated</td><td>{p.get('calculated',0):,}</td><td>IslamicFinder</td><td>{p.get('islamicfinder',0)}</td></tr>
<tr><td>HTML Scraper</td><td>{p.get('old_scraper',0) + p.get('html_parse',0)}</td><td>Mawaqit API</td><td>{p.get('mawaqit',0)}</td></tr>
<tr><td>Playwright</td><td>{stats.get('scraper_methods',{}).get('playwright_scrape',0)}</td><td>Jina Reader</td><td>{stats.get('scraper_methods',{}).get('jina_reader',0)}</td></tr>
</table>
</div>

<!-- Scraper + User Activity side by side -->
<div class="sect">
<h2>Activity</h2>
<table>
<tr><th>Metric</th><th>Today</th><th>This Week</th></tr>
<tr><td>Unique Users</td><td>{ua.get('users_today',0)}</td><td>{ua.get('users_this_week',0)}</td></tr>
<tr><td>Searches</td><td>{ua.get('searches_today',0)}</td><td>-</td></tr>
<tr><td>Routes Planned</td><td>{ua.get('routes_today',0)}</td><td>-</td></tr>
<tr><td>Scrapes</td><td>{scraper_h.get('scraped_today',0)}</td><td>{scraper_h.get('scraped_this_week',0)}</td></tr>
<tr><td>Prayer Spots</td><td>{ps.get('added_today',0)}</td><td>{ps.get('added_this_week',0)} / {ps.get('total',0)} total</td></tr>
<tr><td>Suggestions</td><td>-</td><td>{suggestions.get('pending',0)} pending / {suggestions.get('approved',0)} approved</td></tr>
</table>
</div>

<!-- Coverage by state (collapsible) -->
<div class="sect">
<details>
<summary style="cursor:pointer;font-weight:600;color:#2e3d44;font-size:14px;">Coverage by State</summary>
<table style="margin-top:8px">
<tr><th>State</th><th>Mosques</th><th>Real</th><th>%</th><th>Bar</th></tr>
{coverage_rows}
</table>
</details>
</div>

<!-- Review queue -->
<div class="sect">
<details {'open' if review_rows else ''}>
<summary style="cursor:pointer;font-weight:600;color:#2e3d44;font-size:14px;">Review Queue ({len(pending_suggestions)})</summary>
{f'<table style="margin-top:8px"><tr><th>Mosque</th><th>Field</th><th>Current</th><th>Suggested</th><th>Votes</th><th></th></tr>{review_rows}</table>' if review_rows else '<p style="color:#999;font-size:11px;margin-top:8px;">No pending suggestions</p>'}
</details>
</div>

<!-- System details (collapsible) -->
<div class="sect">
<details>
<summary style="cursor:pointer;font-weight:600;color:#2e3d44;font-size:14px;">System Details</summary>
<div style="margin-top:8px">
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Total Requests</td><td>{usage.get('total_requests',0):,}</td></tr>
<tr><td>Avg Latency</td><td>{usage.get('avg_latency_ms',0)}ms</td></tr>
<tr><td>Dead Websites</td><td>{wh.get('dead',0)}</td></tr>
<tr><td>Avg Data Age</td><td>{data_fresh.get('avg_age_days','?')} days</td></tr>
<tr><td>Last Scrape</td><td>{scraper_h.get('last_scrape','Never')}</td></tr>
<tr><td>Jumuah Mosques</td><td>{j.get('mosques_with_jumuah',0)}</td></tr>
<tr><td>With Website</td><td>{m.get('has_website',0):,}</td></tr>
<tr><td>With Phone</td><td>{m.get('has_phone',0):,}</td></tr>
</table>
</div>
</details>
</div>

<p style="color:#aaa;font-size:10px;text-align:center;margin-top:20px;">
{stats['server']['timestamp'][:19]} UTC
</p>

<script id="loc-data" type="application/json">""" + locations_json + """</script>
<script id="search-data" type="application/json">""" + _json.dumps(stats.get("user_searches", [])) + """</script>
<script id="route-data" type="application/json">""" + _json.dumps(stats.get("route_origins", [])) + """</script>
<script id="gap-data" type="application/json">""" + _json.dumps(stats.get("coverage_gaps", [])) + """</script>
<script id="hourly-labels" type="application/json">""" + hourly_labels_json + """</script>
<script id="hourly-reqs" type="application/json">""" + hourly_reqs_json + """</script>
<script id="hourly-latency" type="application/json">""" + hourly_latency_json + """</script>
<script id="hourly-errors" type="application/json">""" + hourly_errors_json + """</script>
<script id="daily-labels" type="application/json">""" + daily_labels_json + """</script>
<script id="daily-values" type="application/json">""" + daily_values_json + """</script>
<script id="trend-real-labels" type="application/json">""" + trend_real_labels + """</script>
<script id="trend-real-values" type="application/json">""" + trend_real_values + """</script>
<script id="trend-scraper-labels" type="application/json">""" + trend_scraper_labels + """</script>
<script id="trend-scraper-success" type="application/json">""" + trend_scraper_success + """</script>
<script id="trend-scraper-failed" type="application/json">""" + trend_scraper_failed + """</script>
<script id="trend-val-labels" type="application/json">""" + trend_val_labels + """</script>
<script id="trend-val-values" type="application/json">""" + trend_val_values + """</script>"""

    admin_key = ADMIN_API_KEY
    review_script = f"""<script>
function reviewAction(id, action) {{
    if (!confirm('Are you sure you want to ' + action + ' this suggestion?')) return;
    fetch('/api/admin/suggestions/' + id + '/' + action + '?key={admin_key}', {{method:'POST'}})
    .then(r => r.json())
    .then(d => {{ alert(action + 'ed!'); location.reload(); }})
    .catch(e => alert('Error: ' + e));
}}
</script>"""

    chart_script = """<script>
// --- Tabbed trend chart ---
var trendData = {
    real: {
        type:'line',
        data:{labels:JSON.parse(document.getElementById('trend-real-labels').textContent),
            datasets:[{label:'Real Data %',data:JSON.parse(document.getElementById('trend-real-values').textContent),
                borderColor:'#0d9488',backgroundColor:'rgba(13,148,136,0.1)',fill:true,tension:0.3,pointRadius:3}]},
        options:{responsive:true,plugins:{legend:{display:false}},
            scales:{y:{beginAtZero:true,max:100,ticks:{callback:function(v){return v+'%'}}},x:{ticks:{font:{size:9}}}}}
    },
    traffic: {
        type:'line',
        data:{labels:JSON.parse(document.getElementById('hourly-labels').textContent),
            datasets:[
                {label:'Requests',data:JSON.parse(document.getElementById('hourly-reqs').textContent),borderColor:'#0d9488',backgroundColor:'rgba(13,148,136,0.1)',fill:true,tension:0.3},
                {label:'Errors',data:JSON.parse(document.getElementById('hourly-errors').textContent),borderColor:'#dc2626',type:'bar'}]},
        options:{responsive:true,interaction:{intersect:false,mode:'index'},
            scales:{y:{beginAtZero:true},x:{ticks:{font:{size:8},maxRotation:45}}},
            plugins:{legend:{position:'bottom',labels:{boxWidth:8,font:{size:10}}}}}
    },
    scraper: {
        type:'bar',
        data:{labels:JSON.parse(document.getElementById('trend-scraper-labels').textContent),
            datasets:[
                {label:'Success',data:JSON.parse(document.getElementById('trend-scraper-success').textContent),backgroundColor:'rgba(13,148,136,0.7)',borderRadius:3},
                {label:'Failed',data:JSON.parse(document.getElementById('trend-scraper-failed').textContent),backgroundColor:'rgba(220,38,38,0.5)',borderRadius:3}]},
        options:{responsive:true,scales:{x:{stacked:true,ticks:{font:{size:9}}},y:{stacked:true,beginAtZero:true}},
            plugins:{legend:{position:'bottom',labels:{boxWidth:8,font:{size:10}}}}}
    }
};

var trendChart = null;
function showTrend(name) {
    if(trendChart) trendChart.destroy();
    var cfg = trendData[name];
    trendChart = new Chart(document.getElementById('trend-chart'), cfg);
    document.querySelectorAll('.tabs .tab').forEach(function(t){
        if(t.closest('.sect').querySelector('#trend-chart')){
            t.classList.toggle('on', t.textContent.toLowerCase().indexOf(name.substring(0,4))>=0 ||
                (name==='real' && t.textContent.indexOf('Quality')>=0));
        }
    });
}
showTrend('real');

// --- Auto-refresh every 60 seconds ---
var countdown = 60;
setInterval(function() {
    countdown--;
    var el = document.getElementById('refresh-timer');
    if (el) el.textContent = 'auto-refresh in ' + countdown + 's';
    if (countdown <= 0) location.reload();
}, 1000);
</script>"""

    map_script = """<script>
var map = L.map('heatmap').fitBounds([[24.5, -130], [55, -55]]);  // US + Canada
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18, attribution: '&copy; OpenStreetMap'
}).addTo(map);

var mosqueData = JSON.parse(document.getElementById('loc-data').textContent);
var searchData = JSON.parse(document.getElementById('search-data').textContent);
var routeData = JSON.parse(document.getElementById('route-data').textContent);
var gapData = JSON.parse(document.getElementById('gap-data').textContent);

var layers = {
    mosques: L.heatLayer(mosqueData, {radius: 15, blur: 20, maxZoom: 10,
        gradient: {0.2: '#0d9488', 0.4: '#14b8a6', 0.6: '#f59e0b', 0.8: '#ef4444', 1.0: '#dc2626'}}),
    searches: L.heatLayer(searchData.map(function(p){return [p[0],p[1],p[2]||1]}), {radius: 25, blur: 25, maxZoom: 12,
        gradient: {0.2: '#3b82f6', 0.4: '#2563eb', 0.6: '#1d4ed8', 0.8: '#1e40af', 1.0: '#1e3a8a'}}),
    routes: L.heatLayer(routeData.map(function(p){return [p[0],p[1],p[2]||1]}), {radius: 30, blur: 30, maxZoom: 12,
        gradient: {0.2: '#8b5cf6', 0.4: '#7c3aed', 0.6: '#6d28d9', 0.8: '#5b21b6', 1.0: '#4c1d95'}}),
    gaps: L.heatLayer(gapData.map(function(p){return [p[0],p[1],p[2]||1]}), {radius: 35, blur: 30, maxZoom: 12,
        gradient: {0.2: '#f87171', 0.4: '#ef4444', 0.6: '#dc2626', 0.8: '#b91c1c', 1.0: '#991b1b'}})
};

var labels = {
    mosques: mosqueData.length + ' mosques in database',
    searches: searchData.length + ' unique search locations (last 30 days)',
    routes: routeData.length + ' route planning origins (last 30 days)',
    gaps: gapData.length + ' areas where users searched but fewer than 3 mosques exist nearby'
};

var activeLayer = 'mosques';
layers.mosques.addTo(map);
document.getElementById('heatmap-label').textContent = labels.mosques;

function showLayer(name) {
    if (layers[activeLayer]) map.removeLayer(layers[activeLayer]);
    activeLayer = name;
    layers[name].addTo(map);
    document.getElementById('heatmap-label').textContent = labels[name];
    // Update tab styles
    ['mosques','searches','routes','gaps'].forEach(function(n) {
        var btn = document.getElementById('btn-'+n);
        btn.classList.toggle('on', n === name);
    });
}
</script>"""

    html += review_script + chart_script + map_script + "</body></html>"

    return HTMLResponse(content=html)
