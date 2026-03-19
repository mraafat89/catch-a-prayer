# Monitoring & Observability — Catch a Prayer

## Architecture

```
                                    ┌──────────────────────┐
                                    │   Grafana Cloud       │
                                    │   (dashboards + ML    │
                                    │    anomaly detection) │
                                    └──────────▲───────────┘
                                               │
App ──► FastAPI Middleware ──► Prometheus ──────┘
              │                    │
              │                    └──► AlertManager ──► OpenClaw ──► WhatsApp
              │
              ├──► Structured Logs ──► Better Stack (log aggregation + AI)
              │
              └──► PostHog (client-side) ──► Product Analytics

Cloudflare ──► Cloudflare Analytics (request metrics, geography)

OpenClaw (AI Agent on VPS)
├── Scheduled: daily digest, weekly report ──► WhatsApp (personal)
├── Alerts: scraper failure, API down, error spike ──► WhatsApp (instant)
└── On-demand: "How's the server?" ──► reply in WhatsApp
```

---

## Metrics to Instrument

### 1. Usage Metrics

```python
# app/middleware/metrics.py

from prometheus_client import Counter, Histogram, Gauge
import hashlib

# Active users (approximate via hashed IP or session token)
active_sessions = Gauge(
    "cap_active_sessions",
    "Approximate active sessions in the last 5 minutes",
)

locations_served = Counter(
    "cap_locations_served_total",
    "Total location lookups",
    ["city", "state"],
)

mosque_views = Counter(
    "cap_mosque_views_total",
    "Mosque detail views",
    ["mosque_id"],
)

search_radius = Histogram(
    "cap_search_radius_miles",
    "Search radius distribution",
    buckets=[1, 2, 5, 10, 15, 20, 30, 50],
)

mode_requests = Counter(
    "cap_mode_requests_total",
    "Requests by prayer mode",
    ["mode"],  # "muqeem" or "musafir"
)

prayer_marks = Counter(
    "cap_prayer_marks_total",
    "I prayed button taps",
    ["prayer"],  # fajr, dhuhr, asr, maghrib, isha
)

request_hour = Histogram(
    "cap_request_hour",
    "Request distribution by hour of day (UTC)",
    buckets=list(range(25)),
)
```

**What to watch**:
- DAU / WAU ratio (healthy > 0.3 for a utility app)
- Geographic spread — are we serving just one city or growing?
- Mode split — Musafir usage indicates travel feature adoption
- Peak hours should align with prayer times (Fajr, Dhuhr, Asr, Maghrib, Isha)

### 2. Trip Planning Metrics

```python
routes_requested = Counter(
    "cap_routes_requested_total",
    "Route planning requests",
)

route_corridors = Counter(
    "cap_route_corridors_total",
    "Origin-destination corridors",
    ["origin_city", "dest_city"],
)

waypoint_usage = Histogram(
    "cap_waypoints_per_route",
    "Number of prayer stop waypoints per route",
    buckets=[0, 1, 2, 3, 4, 5, 7, 10],
)

itinerary_option_selected = Counter(
    "cap_itinerary_option_selected_total",
    "Which itinerary option the user picked",
    ["option_type"],  # "fastest", "most_mosques", "balanced"
)

navigate_clicks = Counter(
    "cap_navigate_clicks_total",
    "Navigate button taps (handoff to Google/Apple Maps)",
)

musafir_conversions = Counter(
    "cap_musafir_conversions_total",
    "Users who switched from Muqeem to Musafir mode during a session",
)
```

### 3. Prayer Spot Metrics

```python
spots_submitted = Counter(
    "cap_spots_submitted_total",
    "Prayer spots submitted by users",
    ["spot_type"],  # "rest_area", "park", "gas_station", "other"
)

spot_verifications = Counter(
    "cap_spot_verifications_total",
    "Prayer spot verification votes",
    ["vote"],  # "positive", "negative"
)

spot_survival_days = Histogram(
    "cap_spot_survival_days",
    "How long spots remain active before removal",
    buckets=[1, 7, 14, 30, 60, 90, 180, 365],
)

coverage_gap_queries = Counter(
    "cap_coverage_gap_queries_total",
    "Queries where no mosques or spots were found within search radius",
    ["region"],
)
```

### 4. Data Quality Metrics

```python
scrape_success = Gauge(
    "cap_scrape_success_rate",
    "Scraping success rate (0.0-1.0) from last pipeline run",
)

schedule_age_hours = Histogram(
    "cap_schedule_age_hours",
    "Age of prayer schedule data in hours",
    buckets=[1, 6, 12, 24, 48, 72, 168, 336, 720],
)

calculated_vs_scraped = Gauge(
    "cap_calculated_vs_scraped_ratio",
    "Ratio of mosques using calculated times vs scraped times",
)

new_mosques_found = Gauge(
    "cap_new_mosques_found",
    "New mosques discovered in last pipeline run",
)

extractor_confidence = Histogram(
    "cap_extractor_confidence",
    "Confidence scores from prayer time extractors",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0],
)
```

### 5. Server Health

```python
from prometheus_client import Summary

request_latency = Histogram(
    "cap_request_latency_seconds",
    "API request latency",
    ["method", "endpoint", "status_code"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)

error_count = Counter(
    "cap_errors_total",
    "Server errors",
    ["status_code", "endpoint"],
)

db_pool_size = Gauge(
    "cap_db_pool_size",
    "Database connection pool size",
)

db_pool_checked_out = Gauge(
    "cap_db_pool_checked_out",
    "Database connections currently in use",
)

endpoint_hits = Counter(
    "cap_endpoint_hits_total",
    "Endpoint hit counts",
    ["method", "endpoint"],
)

scrape_job_duration = Histogram(
    "cap_scrape_job_duration_seconds",
    "Scraping job duration",
    ["job_type"],  # "refresh", "full_scrape", "discover"
    buckets=[10, 30, 60, 120, 300, 600, 1800, 3600],
)
```

### 6. Business / Growth

These are tracked in PostHog (client-side) rather than Prometheus:

- **Retention**: 1-day, 7-day, 30-day (PostHog cohort analysis)
- **Coverage gaps**: queries returning 0 results (logged as `coverage_gap_queries` counter above)
- **Feature adoption**: % of users who use trip planning, prayer spots, Musafir mode
- **Funnel**: app open -> search -> view mosque -> tap "I prayed"

---

## FastAPI Middleware Implementation

```python
# app/middleware/observability.py

import time
import logging
import json
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

from app.middleware.metrics import (
    request_latency,
    error_count,
    endpoint_hits,
    request_hour,
)

logger = logging.getLogger("cap.api")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        method = request.method
        path = request.url.path

        # Normalize path to avoid cardinality explosion
        # /mosques/123 -> /mosques/{id}
        normalized = self._normalize_path(path)

        try:
            response = await call_next(request)
            status = response.status_code
        except Exception as exc:
            status = 500
            logger.exception("Unhandled exception", extra={
                "method": method,
                "path": path,
                "error": str(exc),
            })
            raise
        finally:
            duration = time.perf_counter() - start

            # Prometheus metrics
            request_latency.labels(
                method=method,
                endpoint=normalized,
                status_code=status,
            ).observe(duration)

            endpoint_hits.labels(method=method, endpoint=normalized).inc()

            if status >= 500:
                error_count.labels(
                    status_code=status, endpoint=normalized
                ).inc()

            # Structured log (picked up by Better Stack)
            logger.info(
                "request",
                extra={
                    "method": method,
                    "path": path,
                    "status": status,
                    "duration_ms": round(duration * 1000, 2),
                    "user_agent": request.headers.get("user-agent", ""),
                    "cf_country": request.headers.get("cf-ipcountry", ""),
                },
            )

        return response

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Replace dynamic path segments with placeholders."""
        parts = path.strip("/").split("/")
        normalized = []
        for part in parts:
            if part.isdigit():
                normalized.append("{id}")
            else:
                normalized.append(part)
        return "/" + "/".join(normalized)
```

### Prometheus Metrics Endpoint

```python
# app/routes/metrics.py

from fastapi import APIRouter
from starlette.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

router = APIRouter()


@router.get("/metrics")
async def metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
```

### Structured Logging Setup

```python
# app/core/logging.py

import logging
import json
import sys


class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge extra fields
        if hasattr(record, "method"):
            log_entry["method"] = record.method
        if hasattr(record, "path"):
            log_entry["path"] = record.path
        if hasattr(record, "status"):
            log_entry["status"] = record.status
        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms
        if hasattr(record, "error"):
            log_entry["error"] = record.error

        return json.dumps(log_entry)


def setup_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger("cap")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
```

---

## AI-Powered Monitoring

### Anomaly Detection with Grafana ML

Grafana Cloud (free tier) includes ML-powered anomaly detection. After connecting Prometheus as a data source:

1. Open a dashboard panel (e.g., `cap_request_latency_seconds`)
2. Click "ML" tab -> "Enable anomaly detection"
3. Grafana learns the normal pattern over 2 weeks, then highlights deviations

**Key patterns to teach it are normal**:
- Usage dip between midnight and Fajr
- Spike at Dhuhr and Asr prayer times
- Friday Jumu'ah spike (higher Dhuhr traffic)
- Ramadan usage pattern shift (later nights, higher Fajr)
- Scraper batch load on Sunday 2 AM (weekly pipeline)

### AI Agents for Monitoring

#### Grafana Sift

Built into Grafana Cloud. When an anomaly fires, click "Explain" and Sift provides a natural-language root cause analysis by correlating across metrics.

#### Better Stack AI

Better Stack's free tier includes AI log summarization. Configure log shipping:

```bash
# In docker-compose.prod.yml, add to api service:
    logging:
      driver: "fluentd"
      options:
        fluentd-address: "localhost:24224"
        tag: "cap.api"

# Or simpler — use Better Stack's Docker log drain:
    logging:
      driver: "syslog"
      options:
        syslog-address: "tcp+tls://in.logs.betterstack.com:18103"
        syslog-format: "rfc5424"
        tag: "cap-api"
```

Better Stack AI will:
- Group related errors automatically
- Summarize error patterns ("3 new error types appeared in the last hour, all related to mosque ID 4521")
- Suggest fixes based on error context

#### PagerDuty AIOps (Free Tier)

- Groups related alerts (e.g., high latency + DB pool exhaustion = single incident)
- Reduces alert noise by 70%+
- Free for up to 5 users

#### OpenClaw — AI Agent with WhatsApp Integration

OpenClaw is an open-source AI agent that runs on the server and communicates via WhatsApp (personal account — no Business API needed). It executes tasks, runs shell commands, and sends/receives messages through your personal WhatsApp by scanning a QR code.

##### Docker Setup

```yaml
# In docker-compose.prod.yml, add:

  openclaw:
    image: openclaw/openclaw:latest
    container_name: cap-openclaw
    restart: unless-stopped
    volumes:
      - openclaw-data:/app/data
      - ./scripts:/app/scripts:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro  # for container health checks
    environment:
      - OPENCLAW_GATEWAY_TOKEN=${OPENCLAW_GATEWAY_TOKEN}  # auto-generated, save securely
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - WHATSAPP_NUMBER=${WHATSAPP_NUMBER}  # your personal number
    ports:
      - "127.0.0.1:3100:3000"  # local only — admin UI
    networks:
      - cap-network

volumes:
  openclaw-data:
```

##### Initial Setup

```bash
# 1. Start OpenClaw
docker-compose up -d openclaw

# 2. Access the web interface
# Local: open http://localhost:3100
# Remote: SSH tunnel first: ssh -L 3100:localhost:3100 user@your-server-ip
# Then open http://localhost:3100

# 3. Connect WhatsApp:
#    - In OpenClaw web UI → Channels → Click "Show QR"
#    - On your phone: WhatsApp → Settings → Linked Devices → Link a Device
#    - Scan the QR code
#    - If connection fails: Settings → Config → click Update, try again

# 4. Set your Anthropic API key in Settings → Config → ANTHROPIC_API_KEY

# 5. OpenClaw is now connected — message it on WhatsApp to test
```

##### Scheduled Tasks Configuration

Create `/opt/cap/scripts/openclaw-tasks.yaml`:

```yaml
# ─── Scheduled Tasks ──────────────────────────────────────────────────────────

tasks:
  # Daily morning digest (8 AM ET)
  daily_digest:
    schedule: "0 8 * * *"
    description: |
      You are monitoring the Catch a Prayer app. Run these commands to gather
      metrics, then send me a WhatsApp summary.

      1. Query Prometheus for yesterday's stats:
         curl -s 'http://prometheus:9090/api/v1/query?query=increase(cap_endpoint_hits_total[24h])'
         curl -s 'http://prometheus:9090/api/v1/query?query=increase(cap_routes_requested_total[24h])'
         curl -s 'http://prometheus:9090/api/v1/query?query=cap_scrape_success_rate'
         curl -s 'http://prometheus:9090/api/v1/query?query=increase(cap_errors_total[24h])'
         curl -s 'http://prometheus:9090/api/v1/query?query=increase(cap_spots_submitted_total[24h])'

      2. Query the database for user stats:
         docker exec cap-db psql -U cap -d catchaprayer -c "SELECT count(DISTINCT session_id) FROM request_logs WHERE created_at > now() - interval '24 hours';"

      3. Analyze the numbers, compare with yesterday, and send me a WhatsApp
         message with 3-5 bullet points covering:
         - Key numbers with trends
         - Any anomalies
         - Scraper health
         - One actionable recommendation
    send_to: whatsapp

  # Hourly health check
  health_check:
    schedule: "*/30 * * * *"
    description: |
      Check if the API is healthy:
        curl -sf http://api:8000/health || echo "API DOWN"
      Check if DB is responsive:
        docker exec cap-db pg_isready || echo "DB DOWN"
      Only message me if something is DOWN.
    send_to: whatsapp
    only_on_failure: true

  # After weekly scrape (Sunday 4 AM)
  scrape_report:
    schedule: "0 4 * * 0"
    description: |
      The weekly mosque scraper just ran. Check the results:
        tail -50 /var/log/cap/weekly_update.log
      Then query:
        docker exec cap-db psql -U cap -d catchaprayer -c "SELECT count(*) as total_mosques, count(*) filter (where updated_at > now() - interval '7 days') as updated_this_week FROM mosques;"

      Send me a WhatsApp summary: how many mosques scraped, success rate,
      any failures, and how many have fresh data.
    send_to: whatsapp

  # Weekly growth report (Monday 9 AM)
  weekly_report:
    schedule: "0 9 * * 1"
    description: |
      Generate a weekly growth report. Query Prometheus for 7-day totals:
        curl -s 'http://prometheus:9090/api/v1/query?query=increase(cap_endpoint_hits_total[7d])'
        curl -s 'http://prometheus:9090/api/v1/query?query=increase(cap_routes_requested_total[7d])'
        curl -s 'http://prometheus:9090/api/v1/query?query=increase(cap_spots_submitted_total[7d])'

      Also query DB:
        docker exec cap-db psql -U cap -d catchaprayer -c "
          SELECT
            count(DISTINCT session_id) as weekly_users,
            count(*) filter (where endpoint = '/api/travel/plan') as routes,
            count(*) filter (where response_code >= 500) as errors
          FROM request_logs
          WHERE created_at > now() - interval '7 days';
        "

      Send me a WhatsApp message with:
      - Weekly active users (and % change from last week)
      - Routes planned
      - Prayer spots submitted
      - Top 3 cities by usage
      - Any trends or concerns
      - Mosque coverage: areas with users but no mosques nearby
    send_to: whatsapp
```

##### On-Demand Commands (via WhatsApp)

You can message OpenClaw on WhatsApp anytime:

| You send | OpenClaw does |
|----------|--------------|
| "How's the server?" | Checks API health, DB, CPU/memory, responds with status |
| "How many users today?" | Queries DB for today's unique sessions |
| "Run scraper" | Triggers the scraping pipeline, reports progress |
| "Show errors" | Tails the last 20 error log lines, summarizes |
| "DB status" | Checks connection pool, table sizes, disk usage |
| "Restart API" | Runs `docker-compose restart api`, confirms |

##### Alert Routing

Configure Prometheus AlertManager to notify OpenClaw, which forwards to WhatsApp:

```yaml
# prometheus/alertmanager.yml
route:
  receiver: openclaw-whatsapp
  group_wait: 30s
  group_interval: 5m

receivers:
  - name: openclaw-whatsapp
    webhook_configs:
      - url: 'http://openclaw:3000/webhook/alert'
        send_resolved: true
```

When an alert fires, OpenClaw receives it, uses AI to write a human-readable summary, and sends it to your WhatsApp:

```
🚨 API Alert

The API p99 latency has been above 2 seconds for 5 minutes.
Current: 3.4s. Normal range: 0.2-0.8s.

This started at 14:32 UTC. Possible causes:
- DB connection pool might be saturated
- A slow query or scraper job running

I checked — DB pool is at 87% utilization. The weekly
scraper is currently running which explains the load.
Should resolve in ~20 minutes when the scrape completes.

Reply "restart api" if you want me to restart it.
```

##### Example Daily Digest (WhatsApp message you receive at 8 AM)

```
📊 Catch a Prayer — Daily Digest (Mar 18)

• 342 sessions yesterday (+12% vs Monday, +28% vs last week)
  Peak at 12:45 PM (Dhuhr) and 3:30 PM (Asr)

• 89 routes planned (SF→LA most popular corridor)
  65% Musafir mode, 35% Muqeem

• Scraper: 94% success (was 97%) — 3 mosques changed
  their website. IDs: 4521, 892, 1103

• 4 new prayer spots submitted (2 in Houston, 1 Dallas, 1 Austin)
  All verified positive ✓

• ⚠️ 12 zero-result queries in Denver area — no mosques
  in DB within 25km. Consider running discovery pipeline
  for Colorado.

Reply "details" for full metrics or "fix scrapers" to
investigate the 3 broken mosques.
```

### Smart Alerting Rules

```yaml
# prometheus/alerts.yml

groups:
  - name: cap_alerts
    rules:
      # Scraper health
      - alert: ScraperFailureHigh
        expr: cap_scrape_success_rate < 0.9
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Scraper success rate dropped below 90%"
          description: "Current rate: {{ $value | humanizePercentage }}"

      # API latency
      - alert: APILatencyHigh
        expr: histogram_quantile(0.99, rate(cap_request_latency_seconds_bucket[5m])) > 2
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "API p99 latency above 2 seconds for 5 minutes"

      # Zero results for known-good locations
      - alert: CoverageGapSpike
        expr: increase(cap_coverage_gap_queries_total[1h]) > 20
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Spike in zero-result queries — possible data issue"

      # Error rate
      - alert: ErrorRateHigh
        expr: rate(cap_errors_total[5m]) > 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "5xx error rate above 0.1/sec"

      # DB connection pool exhaustion
      - alert: DBPoolExhausted
        expr: cap_db_pool_checked_out / cap_db_pool_size > 0.9
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Database connection pool >90% utilized"

      # Container health
      - alert: ContainerDown
        expr: up{job="cap-api"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "API container is down"
```

**Intentionally NOT alerting on**:
- Low traffic between midnight and Fajr (normal)
- Usage spike at Dhuhr/Asr (normal — prayer times)
- Friday Dhuhr spike (Jumu'ah)
- Sunday 2 AM scraper load spike (scheduled job)

### Weekly AI Report

Add a weekly version of the digest script that compares week-over-week trends and generates a summary email. Run on Monday mornings:

```crontab
# Weekly AI report (Monday 9:00 AM ET)
0 9 * * 1 cd /opt/cap && python scripts/weekly_report.py >> /var/log/cap/report.log 2>&1
```

---

## Implementation Priority

### Week 1: Instrumentation + Prometheus

- [ ] Add `ObservabilityMiddleware` to FastAPI app
- [ ] Define all Prometheus metrics (counters, histograms, gauges)
- [ ] Add `/metrics` endpoint
- [ ] Deploy Prometheus in Docker Compose
- [ ] Verify metrics are being scraped: `curl localhost:9090/api/v1/targets`

### Week 2: Dashboards + Uptime

- [ ] Connect Prometheus to Grafana Cloud (free remote write)
- [ ] Build Grafana dashboard with panels for: request rate, latency percentiles, error rate, scraper health
- [ ] Set up Better Stack uptime monitor on `https://api.catchaprayer.com/health`
- [ ] Configure log shipping to Better Stack
- [ ] Create alert rules in Prometheus
- [ ] Set up Slack webhook for alerts

### Week 3: Product Analytics

- [ ] Integrate PostHog JS SDK in mobile app (or React Native SDK)
- [ ] Track key events: search, view_mosque, tap_pray, plan_route, submit_spot
- [ ] Set up PostHog funnels: search -> view -> pray
- [ ] Enable session replay (PostHog free tier includes this)
- [ ] Create retention cohort analysis

### Week 4: OpenClaw AI Agent + WhatsApp

- [ ] Deploy OpenClaw container (`docker-compose up -d openclaw`)
- [ ] Scan WhatsApp QR code via admin UI (SSH tunnel for remote)
- [ ] Configure scheduled tasks (`openclaw-tasks.yaml`)
- [ ] Set up AlertManager webhook to OpenClaw
- [ ] Test on-demand commands ("How's the server?", "Show errors")
- [ ] Tune prompts for digest quality over 1 week

### Ongoing

- Refine alert thresholds based on real traffic patterns
- Add metrics for new features as they ship
- Tune Grafana ML anomaly detection after 2 weeks of data
- Review and prune noisy alerts monthly

---

## Tools Summary

| Tool | Purpose | Cost | Phase |
|------|---------|------|-------|
| Prometheus | Metrics collection + alerting | Free (self-hosted) | Week 1 |
| Grafana Cloud | Dashboards + ML anomaly detection | Free (10K metrics) | Week 2 |
| Better Stack | Uptime monitoring + log aggregation + AI summaries | Free tier | Week 2 |
| PostHog | Product analytics + session replay + funnels | Free (1M events/mo) | Week 3 |
| OpenClaw | AI agent — WhatsApp alerts, digests, on-demand commands | Free (self-hosted) + ~$5/mo Claude API | Week 4 |
| Cloudflare Analytics | Request metrics, geography, cache hit rate | Free | Day 1 |
| PagerDuty AIOps | Alert grouping + noise reduction | Free (5 users) | Week 2 |

**Total monitoring cost at launch: ~$5/mo** (OpenClaw is free, Claude API for AI analysis ~$5/mo, everything else free tier).
