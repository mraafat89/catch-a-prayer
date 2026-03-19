# Deployment Guide — Catch a Prayer

## Infrastructure Overview

| Component | Choice | Cost |
|-----------|--------|------|
| VPS | Hetzner CX22 (2 vCPU, 4 GB RAM, 40 GB NVMe) | $5/mo |
| Location | Ashburn, VA (us-east) | — |
| DNS/CDN | Cloudflare Free | $0 |
| Backups | Hetzner Storage Box (100 GB) | $1/mo |
| **Total** | | **$6/mo** |

### Why Hetzner CX22

- 4 GB RAM is enough for FastAPI + Postgres + PostGIS + Caddy + Prometheus on a single box
- Ashburn, VA puts us close to the US East Coast population center
- NVMe storage keeps PostGIS spatial queries fast
- Hetzner's network is solid — 20 TB/mo outbound included

### Why Cloudflare in Front

- Free SSL termination (Full Strict mode with Caddy's Let's Encrypt cert)
- DDoS protection at L3/L4/L7
- Edge caching for static assets and API responses with appropriate `Cache-Control` headers
- Analytics (request volume, geography) at no cost
- DNS propagation in seconds

---

## Production Docker Compose

```yaml
# docker-compose.prod.yml

version: "3.9"

services:
  api:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: cap-api
    restart: unless-stopped
    env_file: .env
    environment:
      - DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
      - ENVIRONMENT=production
    depends_on:
      db:
        condition: service_healthy
    networks:
      - internal
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: "1.0"

  db:
    image: postgis/postgis:16-3.4-alpine
    container_name: cap-db
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - pgdata:/var/lib/postgresql/data
    networks:
      - internal
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    deploy:
      resources:
        limits:
          memory: 1.5G
          cpus: "0.5"

  caddy:
    image: caddy:2-alpine
    container_name: cap-caddy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      api:
        condition: service_healthy
    networks:
      - internal
    healthcheck:
      test: ["CMD", "caddy", "validate", "--config", "/etc/caddy/Caddyfile"]
      interval: 60s
      timeout: 5s
      retries: 3

  prometheus:
    image: prom/prometheus:v2.51.0
    container_name: cap-prometheus
    restart: unless-stopped
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    networks:
      - internal
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:9090/-/healthy"]
      interval: 30s
      timeout: 5s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "0.25"

volumes:
  pgdata:
    driver: local
  caddy_data:
    driver: local
  caddy_config:
    driver: local
  prometheus_data:
    driver: local

networks:
  internal:
    driver: bridge
```

### Caddyfile

```caddyfile
# Caddyfile
api.catchaprayer.com {
    reverse_proxy api:8000

    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
    }

    log {
        output file /var/log/caddy/access.log
        format json
    }
}
```

Caddy automatically obtains and renews Let's Encrypt certificates. With Cloudflare in front (Full Strict SSL mode), traffic is encrypted end-to-end: `User -> Cloudflare (edge TLS) -> Caddy (origin TLS) -> FastAPI`.

### Prometheus Config

```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: "cap-api"
    static_configs:
      - targets: ["api:8000"]
    metrics_path: /metrics
    scrape_interval: 10s
```

### Environment File

```bash
# .env (do NOT commit this file)
POSTGRES_USER=cap
POSTGRES_PASSWORD=<generate-with-openssl-rand-base64-32>
POSTGRES_DB=catchaprayer
SECRET_KEY=<generate-with-openssl-rand-hex-32>
ENVIRONMENT=production
```

---

## Cron Jobs

All cron jobs run on the host and execute inside the `cap-api` container via `docker exec`.

### Crontab Entries

```crontab
# Edit with: crontab -e

# ---- Catch a Prayer Scheduled Jobs ----

# Daily: Refresh prayer schedules for all active mosques (4:00 AM ET)
0 4 * * * docker exec cap-api python -m app.jobs.refresh_schedules >> /var/log/cap/refresh.log 2>&1

# Weekly: Run full scraping pipeline for existing mosques (Sunday 2:00 AM ET)
0 2 * * 0 docker exec cap-api python -m app.jobs.scrape_pipeline >> /var/log/cap/scrape.log 2>&1

# Monthly: Discover new mosques via Google Places API (1st of month, 1:00 AM ET)
0 1 1 * * docker exec cap-api python -m app.jobs.discover_mosques >> /var/log/cap/discover.log 2>&1

# Daily: Backup database (3:00 AM ET)
0 3 * * * /opt/cap/scripts/backup.sh >> /var/log/cap/backup.log 2>&1
```

### Log Rotation

```bash
# /etc/logrotate.d/cap
/var/log/cap/*.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
}
```

---

## Backup & Disaster Recovery

### Backup Layers

Three independent layers — any one of them can restore the full system:

```
Layer 1: Database dumps (daily)     → restores mosque data + prayer schedules
Layer 2: Hetzner VPS snapshots      → restores entire server (OS + Docker + data)
Layer 3: Git repo + DB dump on laptop → rebuild from scratch in 15 minutes
```

| Layer | What | Frequency | Retention | Restore Time | Cost |
|-------|------|-----------|-----------|--------------|------|
| DB dump (local on VPS) | PostgreSQL custom dump | Daily 4 AM | 7 daily + 4 weekly | 2 min | $0 |
| DB dump (off-server) | Copy to Hetzner Storage Box | Daily 5 AM | 30 days | 5 min | $1/mo |
| VPS snapshot | Full disk image | Weekly (auto) | 3 snapshots | 5 min | ~$1/mo |
| Local laptop | git repo + manual DB export | On demand | Always | 15 min | $0 |

### Layer 1: Database Dumps (on server)

Already set up via `scripts/backup.sh` and cron:

```bash
# Runs daily at 4 AM UTC via cron
0 4 * * * /opt/cap/scripts/backup.sh >> /var/log/cap/backup.log 2>&1
```

Backups stored at `/opt/cap/backups/`:
```
backups/
├── daily/
│   ├── cap_20260319_040000.dump   ← today
│   ├── cap_20260318_040000.dump   ← yesterday
│   └── ... (7 days)
└── weekly/
    ├── cap_20260316_040000.dump   ← last Sunday
    └── ... (4 weeks)
```

### Layer 2: Off-Server Backup (Hetzner Storage Box)

```bash
# One-time setup: order a Storage Box ($1/mo for 100GB) from Hetzner
# Then add SSH key and rsync daily backups off-server

# Add to crontab (runs 1 hour after backup):
0 5 * * * rsync -avz /opt/cap/backups/ u123456@u123456.your-storagebox.de:cap-backups/ 2>> /var/log/cap/backup.log
```

**Why this matters:** If the VPS disk fails or gets compromised, backups on the same disk are lost. The Storage Box is independent hardware.

### Layer 3: Hetzner VPS Snapshots

```bash
# Enable via Hetzner Cloud Console:
# Cloud Console → Server → Backups → Enable Backups
# Cost: ~$1/mo (20% of server price)
# Hetzner takes automatic weekly snapshots, keeps last 3

# Or take a manual snapshot before risky changes:
hcloud server create-image catchaprayer --type=snapshot --description="pre-migration"
```

### Layer 4: Local Laptop (Manual)

```bash
# Export production DB to laptop (before risky deploys)
ssh root@5.78.187.171 "docker exec cap-db pg_dump -U cap -d catchaprayer --format=custom" > ~/cap-backup-$(date +%Y%m%d).dump

# This + git repo = can rebuild the entire server from scratch
```

---

### Restore Procedures

#### Scenario 1: Bad deploy broke the app (most common)

```bash
# Option A: Roll back code (fastest — 30 seconds)
ssh root@5.78.187.171 << 'EOF'
cd /opt/cap
git log --oneline -5                    # find the last good commit
git checkout <good-commit-hash>         # revert code
docker compose -f docker-compose.prod.yml up --build -d api
EOF

# Option B: If the deploy also broke the DB (migration issue)
ssh root@5.78.187.171 << 'EOF'
cd /opt/cap
# Restore yesterday's DB
docker compose -f docker-compose.prod.yml exec -T db pg_restore \
  -U cap -d catchaprayer --clean --if-exists \
  < /opt/cap/backups/daily/cap_LATEST.dump
# Roll back code
git checkout <good-commit-hash>
docker compose -f docker-compose.prod.yml up --build -d api
EOF
```

#### Scenario 2: Scraper corrupted mosque data

```bash
# Restore DB from before the scrape ran (scraper runs Tuesday 2 AM)
ssh root@5.78.187.171 << 'EOF'
# Find Monday's backup
ls -la /opt/cap/backups/daily/

# Restore it
docker compose -f docker-compose.prod.yml exec -T db pg_restore \
  -U cap -d catchaprayer --clean --if-exists \
  < /opt/cap/backups/daily/cap_20260317_040000.dump

echo "DB restored to Monday backup"
EOF
```

#### Scenario 3: VPS disk failure / server compromised

```bash
# 1. Create new VPS from Hetzner Console (using VPS snapshot)
#    Cloud Console → Snapshots → select latest → Rebuild Server
#    Takes ~2 minutes. Server comes back exactly as it was.

# 2. OR rebuild from scratch + Storage Box backup:
#    a. Create fresh VPS
#    b. Run setup script
curl -sSL https://raw.githubusercontent.com/mraafat89/catch-a-prayer/main/scripts/setup-server.sh | bash
#    c. Copy .env.prod, deploy, restore DB from Storage Box
rsync -avz u123456@u123456.your-storagebox.de:cap-backups/daily/LATEST.dump /opt/cap/
./scripts/deploy.sh first-time
docker compose -f docker-compose.prod.yml exec -T db pg_restore \
  -U cap -d catchaprayer --clean --if-exists < /opt/cap/LATEST.dump
```

#### Scenario 4: Total loss (VPS + Storage Box both gone)

```bash
# Rebuild from laptop (git repo + local DB dump)
# 1. Provision new VPS
# 2. Run setup, deploy
# 3. Upload local DB dump:
scp ~/cap-backup-20260318.dump root@NEW_SERVER_IP:/opt/cap/
ssh root@NEW_SERVER_IP "cd /opt/cap && docker compose -f docker-compose.prod.yml exec -T db pg_restore -U cap -d catchaprayer --clean --if-exists < /opt/cap/cap-backup-20260318.dump"
```

---

### Pre-Deploy Safety Checklist

Run before any risky deploy (DB migrations, major features):

```bash
# 1. Take a manual snapshot
ssh root@5.78.187.171 "cd /opt/cap && ./scripts/backup.sh"

# 2. Download backup to laptop
scp root@5.78.187.171:/opt/cap/backups/daily/cap_$(date +%Y%m%d)*.dump ~/cap-pre-deploy.dump

# 3. Deploy
git push origin main
ssh root@5.78.187.171 "cd /opt/cap && ./scripts/deploy.sh update"

# 4. Verify
curl -sf http://5.78.187.171/health && echo "✅ OK" || echo "❌ ROLLBACK!"

# 5. If broken:
ssh root@5.78.187.171 "cd /opt/cap && docker compose -f docker-compose.prod.yml exec -T db pg_restore -U cap -d catchaprayer --clean --if-exists < /opt/cap/backups/daily/cap_$(date +%Y%m%d)*.dump && git checkout HEAD~1 && docker compose -f docker-compose.prod.yml up --build -d api"
```

### Backup Monitoring

OpenClaw checks backup health daily:

```
Backup report: ✅
- Latest DB dump: 2026-03-19 04:00 UTC (6 hours ago, 1.2 MB)
- Storage Box sync: 2026-03-19 05:00 UTC
- VPS snapshot: 2026-03-16 (3 days ago)
- Backup disk usage: 45 MB / 40 GB (0.1%)
```

Alert if: no backup in 48 hours, backup size drops >50% (empty dump), Storage Box unreachable.

---

## Deployment Steps

### 1. Provision Hetzner VPS

```bash
# Using hcloud CLI (or do this in the web console)
hcloud server create \
  --name cap-vps \
  --type cx22 \
  --location ash \
  --image ubuntu-24.04 \
  --ssh-key your-key-name
```

### 2. Install Docker

```bash
ssh root@<server-ip>

# Install Docker
curl -fsSL https://get.docker.com | sh
systemctl enable docker

# Install Docker Compose plugin
apt-get install -y docker-compose-plugin

# Verify
docker compose version
```

### 3. Configure Cloudflare DNS

In Cloudflare dashboard:

1. Add `A` record: `api.catchaprayer.com` -> `<server-ip>` (Proxied, orange cloud)
2. SSL/TLS mode: **Full (Strict)**
3. Under Caching > Configuration: set Browser Cache TTL to "Respect Existing Headers"
4. Enable "Always Use HTTPS"

### 4. Clone Repo and Configure

```bash
# Create app directory
mkdir -p /opt/cap && cd /opt/cap

# Clone
git clone https://github.com/your-org/catch-a-prayer.git .

# Create .env from template
cp .env.example .env
nano .env  # Fill in POSTGRES_PASSWORD, SECRET_KEY, etc.

# Create log directory
mkdir -p /var/log/cap
```

### 5. Start Services

```bash
cd /opt/cap
docker compose -f docker-compose.prod.yml up -d --build

# Watch logs until everything is healthy
docker compose -f docker-compose.prod.yml logs -f

# Verify all services are up
docker compose -f docker-compose.prod.yml ps
```

### 6. Run Initial Data Load

```bash
# Apply database migrations
docker exec cap-api alembic upgrade head

# Run initial mosque discovery (first time only)
docker exec cap-api python -m app.jobs.discover_mosques

# Run initial scrape
docker exec cap-api python -m app.jobs.scrape_pipeline
```

### 7. Set Up Cron Jobs

```bash
# Install crontab entries
crontab -e
# Paste the crontab entries from the Cron Jobs section above

# Mount storage box for backups
apt-get install -y cifs-utils
mkdir -p /mnt/storage-box
# Add credentials and fstab entry as shown in Backups section
mount /mnt/storage-box
```

### 8. Verify Health

```bash
# API health check
curl -s https://api.catchaprayer.com/health | jq .

# Expected response:
# {
#   "status": "healthy",
#   "database": "connected",
#   "mosque_count": 1234,
#   "latest_scrape": "2026-03-18T04:00:00Z"
# }

# Check all containers are running
docker compose -f docker-compose.prod.yml ps

# Check Prometheus targets
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[].health'
```

---

## Scaling Path

### Stage 1: Single Box (0–1K DAU) — Current Setup

**Cost: $6/mo**

The CX22 handles this comfortably. Postgres with PostGIS spatial indexes can serve hundreds of concurrent queries. FastAPI on uvicorn with 2 workers saturates at roughly 500 req/s for our workload.

**No changes needed.**

### Stage 2: Bigger Box (1K–10K DAU)

**Trigger**: API p95 latency > 500ms consistently, or DB CPU > 70%.

**Changes**:
- Upgrade to Hetzner CX32 (4 vCPU, 8 GB RAM) — $9/mo
- Add Redis for caching (prayer times don't change intra-day, mosque lists are stable)
- Add connection pooling with PgBouncer
- Enable Cloudflare API caching with 5-min TTL on `/mosques/nearby` responses

```yaml
# Add to docker-compose.prod.yml
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    networks:
      - internal
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 256M
```

**Cost: ~$10/mo**

### Stage 3: Separate DB (10K–50K DAU)

**Trigger**: DB and API competing for CPU/RAM on the same box.

**Changes**:
- Hetzner CX32 for API + Redis + Caddy — $9/mo
- Hetzner CX22 for Postgres (dedicated) — $5/mo
- Or use Hetzner Managed Postgres if available
- Add read replica if read-heavy
- Multiple uvicorn workers (4–8)
- Consider Hetzner Load Balancer if running multiple API instances — $6/mo

**Cost: ~$20/mo**

### Stage 4: Multi-Instance (50K+ DAU)

**Trigger**: Single API instance can't keep up even with caching.

**Changes**:
- 2–3 API instances behind Hetzner Load Balancer
- Dedicated managed Postgres with read replicas
- Redis cluster or Hetzner Managed Redis
- Move cron jobs to a separate worker instance
- Consider CDN for static/pre-computed prayer schedule JSON

**Cost: ~$50–80/mo**

---

## Cost Breakdown

| Stage | DAU | VPS | Storage | DNS/CDN | Other | Total |
|-------|-----|-----|---------|---------|-------|-------|
| 1 | 0–1K | $5 (CX22) | $1 | $0 | — | **$6/mo** |
| 2 | 1K–10K | $9 (CX32) | $1 | $0 | — | **$10/mo** |
| 3 | 10K–50K | $14 (2x VPS) | $1 | $0 | $6 (LB) | **$21/mo** |
| 4 | 50K+ | $27 (3x VPS) | $3 | $0 | $6 (LB) + $15 (managed DB) | **$51/mo** |

These are estimates. Actual costs depend on traffic patterns, data size, and whether you use managed services vs self-hosted.

---

## Firewall Rules

```bash
# Using hcloud CLI or Hetzner Cloud Console
hcloud firewall create --name cap-fw

# Allow SSH
hcloud firewall add-rule cap-fw --direction in --protocol tcp --port 22 --source-ips 0.0.0.0/0

# Allow HTTP/HTTPS (Cloudflare IPs only for production)
# See https://www.cloudflare.com/ips/ for current list
hcloud firewall add-rule cap-fw --direction in --protocol tcp --port 80 \
  --source-ips 173.245.48.0/20,103.21.244.0/22,103.22.200.0/22,103.31.4.0/22,141.101.64.0/18,108.162.192.0/18,190.93.240.0/20,188.114.96.0/20,197.234.240.0/22,198.41.128.0/17,162.158.0.0/15,104.16.0.0/13,104.24.0.0/14,172.64.0.0/13,131.0.72.0/22

# Same for port 443
hcloud firewall add-rule cap-fw --direction in --protocol tcp --port 443 \
  --source-ips 173.245.48.0/20,103.21.244.0/22,103.22.200.0/22,103.31.4.0/22,141.101.64.0/18,108.162.192.0/18,190.93.240.0/20,188.114.96.0/20,197.234.240.0/22,198.41.128.0/17,162.158.0.0/15,104.16.0.0/13,104.24.0.0/14,172.64.0.0/13,131.0.72.0/22

# Apply firewall to server
hcloud firewall apply-to-resource cap-fw --type server --server cap-vps
```

---

## Quick Reference

```bash
# Start all services
docker compose -f docker-compose.prod.yml up -d

# Stop all services
docker compose -f docker-compose.prod.yml down

# View logs (all services)
docker compose -f docker-compose.prod.yml logs -f

# View logs (single service)
docker compose -f docker-compose.prod.yml logs -f api

# Restart single service
docker compose -f docker-compose.prod.yml restart api

# Deploy new version
cd /opt/cap && git pull
docker compose -f docker-compose.prod.yml up -d --build api

# Shell into API container
docker exec -it cap-api bash

# Psql into database
docker exec -it cap-db psql -U cap -d catchaprayer

# Check disk usage
df -h && docker system df

# Clean up old Docker images
docker image prune -a --filter "until=168h"
```
