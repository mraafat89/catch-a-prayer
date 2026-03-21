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

    # Endpoint latency table
    ep_latency_rows = ""
    for ep in stats.get("endpoint_latency", []):
        color = "#dc2626" if float(ep.get("p95_ms", 0)) > 500 else "#666"
        ep_latency_rows += f"<tr><td><code>{ep['endpoint']}</code></td><td>{ep['hits']}</td><td>{ep['avg_ms']}ms</td><td style='color:{color}'>{ep['p95_ms']}ms</td><td>{ep['max_ms']}ms</td></tr>"

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
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
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
<h2>🗺️ Heatmaps</h2>
<div style="margin-bottom:8px;">
<button onclick="showLayer('mosques')" id="btn-mosques" style="padding:6px 12px;border-radius:8px;border:1px solid #0d9488;background:#0d9488;color:white;cursor:pointer;margin-right:4px;font-size:12px;">Mosques</button>
<button onclick="showLayer('searches')" id="btn-searches" style="padding:6px 12px;border-radius:8px;border:1px solid #2563eb;background:white;color:#2563eb;cursor:pointer;margin-right:4px;font-size:12px;">User Searches</button>
<button onclick="showLayer('routes')" id="btn-routes" style="padding:6px 12px;border-radius:8px;border:1px solid #7c3aed;background:white;color:#7c3aed;cursor:pointer;margin-right:4px;font-size:12px;">Route Planning</button>
<button onclick="showLayer('gaps')" id="btn-gaps" style="padding:6px 12px;border-radius:8px;border:1px solid #dc2626;background:white;color:#dc2626;cursor:pointer;font-size:12px;">Coverage Gaps</button>
</div>
<div id="heatmap"></div>
<p id="heatmap-label" style="font-size:11px;color:#666;margin-top:4px;"></p>
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

<div class="section">
<h2>📈 Live Traffic (Hourly — Last 48h)</h2>
<div style="background:white;border-radius:12px;padding:14px;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
<canvas id="traffic-chart" height="180"></canvas>
</div>
</div>

<div class="section two-col">
<div>
<h2>📊 Daily Volume (Last 30 Days)</h2>
<div style="background:white;border-radius:12px;padding:14px;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
<canvas id="daily-chart" height="200"></canvas>
</div>
</div>
<div>
<h2>⚡ Latency by Endpoint (24h)</h2>
<table>
<tr><th>Endpoint</th><th>Hits</th><th>Avg</th><th>P95</th><th>Max</th></tr>
{ep_latency_rows if ep_latency_rows else '<tr><td colspan="5" style="color:#999">No data yet</td></tr>'}
</table>
</div>
</div>

<div class="section" style="color:#999;font-size:11px;text-align:center;margin-top:20px;">
Updated: {stats['server']['timestamp'][:19]} UTC — <span id="refresh-timer">auto-refresh in 60s</span>
</div>

<script id="loc-data" type="application/json">""" + locations_json + """</script>
<script id="search-data" type="application/json">""" + _json.dumps(stats.get("user_searches", [])) + """</script>
<script id="route-data" type="application/json">""" + _json.dumps(stats.get("route_origins", [])) + """</script>
<script id="gap-data" type="application/json">""" + _json.dumps(stats.get("coverage_gaps", [])) + """</script>
<script id="hourly-labels" type="application/json">""" + hourly_labels_json + """</script>
<script id="hourly-reqs" type="application/json">""" + hourly_reqs_json + """</script>
<script id="hourly-latency" type="application/json">""" + hourly_latency_json + """</script>
<script id="hourly-errors" type="application/json">""" + hourly_errors_json + """</script>
<script id="daily-labels" type="application/json">""" + daily_labels_json + """</script>
<script id="daily-values" type="application/json">""" + daily_values_json + """</script>"""

    chart_script = """<script>
// --- Traffic chart (requests + latency dual axis) ---
var hLabels = JSON.parse(document.getElementById('hourly-labels').textContent);
var hReqs = JSON.parse(document.getElementById('hourly-reqs').textContent);
var hLatency = JSON.parse(document.getElementById('hourly-latency').textContent);
var hErrors = JSON.parse(document.getElementById('hourly-errors').textContent);

new Chart(document.getElementById('traffic-chart'), {
    type: 'line',
    data: {
        labels: hLabels,
        datasets: [
            {label:'Requests', data:hReqs, borderColor:'#0d9488', backgroundColor:'rgba(13,148,136,0.1)', fill:true, tension:0.3, yAxisID:'y'},
            {label:'Avg Latency (ms)', data:hLatency, borderColor:'#f59e0b', borderDash:[5,3], tension:0.3, yAxisID:'y1'},
            {label:'Errors', data:hErrors, borderColor:'#dc2626', backgroundColor:'rgba(220,38,38,0.2)', type:'bar', yAxisID:'y'}
        ]
    },
    options: {
        responsive:true, interaction:{intersect:false, mode:'index'},
        scales: {
            y: {position:'left', title:{display:true, text:'Requests / Errors'}, beginAtZero:true},
            y1: {position:'right', title:{display:true, text:'Latency (ms)'}, beginAtZero:true, grid:{drawOnChartArea:false}}
        },
        plugins: {legend:{position:'bottom', labels:{boxWidth:12, font:{size:11}}}}
    }
});

// --- Daily volume bar chart ---
var dLabels = JSON.parse(document.getElementById('daily-labels').textContent);
var dValues = JSON.parse(document.getElementById('daily-values').textContent);

new Chart(document.getElementById('daily-chart'), {
    type: 'bar',
    data: {
        labels: dLabels,
        datasets: [{label:'Daily Requests', data:dValues, backgroundColor:'rgba(13,148,136,0.6)', borderRadius:4}]
    },
    options: {
        responsive:true, plugins:{legend:{display:false}},
        scales: {x:{ticks:{maxRotation:45, font:{size:9}}}, y:{beginAtZero:true}}
    }
});

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
var map = L.map('heatmap').setView([39.8, -98.5], 4);
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
    gaps: gapData.length + ' areas with few nearby mosques (coverage gaps)'
};

var activeLayer = 'mosques';
layers.mosques.addTo(map);
document.getElementById('heatmap-label').textContent = labels.mosques;

function showLayer(name) {
    if (layers[activeLayer]) map.removeLayer(layers[activeLayer]);
    activeLayer = name;
    layers[name].addTo(map);
    document.getElementById('heatmap-label').textContent = labels[name];
    // Update button styles
    var colors = {mosques:'#0d9488', searches:'#2563eb', routes:'#7c3aed', gaps:'#dc2626'};
    ['mosques','searches','routes','gaps'].forEach(function(n) {
        var btn = document.getElementById('btn-'+n);
        if (n === name) { btn.style.background = colors[n]; btn.style.color = 'white'; }
        else { btn.style.background = 'white'; btn.style.color = colors[n]; }
    });
}
</script>"""

    html += chart_script + map_script + "</body></html>"

    return HTMLResponse(content=html)
