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

    # === Server info ===
    stats["server"] = {
        "timestamp": datetime.utcnow().isoformat(),
        "date": today.isoformat(),
    }

    return stats


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

    # Top endpoints
    top_ep_rows = ""
    for ep, count in list(usage.get("top_endpoints", {}).items())[:8]:
        top_ep_rows += f"<tr><td><code>{ep}</code></td><td>{count}</td></tr>"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Catch a Prayer — Dashboard</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.heat/dist/leaflet-heat.js"></script>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 1000px; margin: 20px auto; padding: 0 15px; background: #f8fafb; color: #1a1a1a; }}
h1 {{ color: #0d9488; margin-bottom: 5px; }}
.subtitle {{ color: #666; margin-bottom: 20px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 16px; }}
.card {{ background: white; border-radius: 12px; padding: 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.card .number {{ font-size: 24px; font-weight: 700; color: #0d9488; }}
.card .label {{ font-size: 11px; color: #666; margin-top: 3px; }}
.card.warn .number {{ color: #d97706; }}
.card.bad .number {{ color: #dc2626; }}
table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
th, td {{ padding: 6px 10px; text-align: left; border-bottom: 1px solid #f0f0f0; font-size: 12px; }}
th {{ background: #f8fafb; font-weight: 600; color: #555; }}
.section {{ margin-top: 20px; }}
h2 {{ color: #2e3d44; font-size: 15px; margin-bottom: 8px; }}
#heatmap {{ height: 350px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
@media (max-width: 700px) {{ .two-col {{ grid-template-columns: 1fr; }} }}
</style></head><body>
<h1>🕌 Catch a Prayer</h1>
<p class="subtitle">Admin Dashboard — {stats['server']['date']}</p>

<div class="grid">
  <div class="card"><div class="number">{m.get('total',0):,}</div><div class="label">Total Mosques</div></div>
  <div class="card"><div class="number">{m.get('has_website',0):,}</div><div class="label">With Website</div></div>
  <div class="card"><div class="number">{m.get('has_phone',0):,}</div><div class="label">With Phone</div></div>
  <div class="card {'warn' if real_pct < 50 else ''}"><div class="number">{real_pct}%</div><div class="label">Real Data Rate</div></div>
  <div class="card"><div class="number">{p.get('real_data',0):,}</div><div class="label">Real (Today)</div></div>
  <div class="card"><div class="number">{p.get('calculated',0):,}</div><div class="label">Calculated</div></div>
  <div class="card"><div class="number">{j.get('mosques_with_jumuah',0)}</div><div class="label">Jumuah</div></div>
  <div class="card"><div class="number">{suggestions.get('total',0)}</div><div class="label">Suggestions</div></div>
</div>

<div class="section">
<h2>🗺️ Mosque Coverage Heatmap</h2>
<div id="heatmap"></div>
</div>

<div class="section two-col">
<div>
<h2>📊 Data Sources (Today)</h2>
<table>
<tr><th>Source</th><th>Count</th></tr>
<tr><td>Calculated (estimated)</td><td>{p.get('calculated',0):,}</td></tr>
<tr><td>IslamicFinder</td><td>{p.get('islamicfinder',0)}</td></tr>
<tr><td>Old Scraper (HTML/JS)</td><td>{p.get('old_scraper',0)}</td></tr>
<tr><td>Free HTML Parser</td><td>{p.get('html_parse',0)}</td></tr>
<tr><td>Mawaqit API</td><td>{p.get('mawaqit',0)}</td></tr>
<tr><td>Claude AI</td><td>{p.get('claude_ai',0)}</td></tr>
<tr><td>Iframe Widget</td><td>{p.get('iframe_widget',0)}</td></tr>
</table>
</div>
<div>
<h2>🔧 Scraper Health</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Last scrape</td><td>{scraper_h.get('last_scrape','Never')}</td></tr>
<tr><td>Scraped this week</td><td>{scraper_h.get('scraped_this_week',0)}</td></tr>
<tr><td>Scraped today</td><td>{scraper_h.get('scraped_today',0)}</td></tr>
<tr><td>Avg data age</td><td>{data_fresh.get('avg_age_days','?')} days</td></tr>
<tr><td>Dead websites</td><td>{stats.get('scraper',{}).get('dead_websites',0)}</td></tr>
</table>
</div>
</div>

<div class="section">
<h2>📍 Coverage by State</h2>
<table>
<tr><th>State</th><th>Mosques</th><th>Real Data</th><th>%</th><th>Coverage</th></tr>
{coverage_rows}
</table>
</div>

<div class="section two-col">
<div>
<h2>🌐 API Usage</h2>
<div class="grid" style="grid-template-columns: repeat(3, 1fr);">
  <div class="card"><div class="number">{usage.get('total_requests',0):,}</div><div class="label">Requests</div></div>
  <div class="card"><div class="number">{usage.get('unique_locations',0)}</div><div class="label">Unique Locations</div></div>
  <div class="card"><div class="number">{usage.get('avg_latency_ms',0)}ms</div><div class="label">Avg Latency</div></div>
  <div class="card"><div class="number">{usage.get('routes_planned',0)}</div><div class="label">Routes</div></div>
  <div class="card {'bad' if usage.get('errors_5xx',0) > 0 else ''}"><div class="number">{usage.get('errors_5xx',0)}</div><div class="label">5xx Errors</div></div>
  <div class="card"><div class="number">{usage.get('spots_submitted',0)}</div><div class="label">Spots</div></div>
</div>
</div>
<div>
<h2>🔥 Top Endpoints</h2>
<table>
<tr><th>Endpoint</th><th>Hits</th></tr>
{top_ep_rows if top_ep_rows else '<tr><td colspan="2" style="color:#999">No requests yet</td></tr>'}
</table>
</div>
</div>

<div class="section" style="color:#999;font-size:11px;text-align:center;margin-top:20px;">
Updated: {stats['server']['timestamp'][:19]} UTC
</div>

<script id="loc-data" type="application/json">""" + locations_json + """</script>"""

    # JavaScript outside the f-string to avoid curly brace conflicts
    map_script = """<script>
var map = L.map('heatmap').setView([39.8, -98.5], 4);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18, attribution: '&copy; OpenStreetMap'
}).addTo(map);
var locs = JSON.parse(document.getElementById('loc-data').textContent);
if (locs.length > 0) {
    L.heatLayer(locs, {radius: 15, blur: 20, maxZoom: 10, max: 1.0,
        gradient: {0.2: '#0d9488', 0.4: '#14b8a6', 0.6: '#f59e0b', 0.8: '#ef4444', 1.0: '#dc2626'}
    }).addTo(map);
}
</script>"""

    html += map_script + "</body></html>"

    return HTMLResponse(content=html)
