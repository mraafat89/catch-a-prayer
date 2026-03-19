#!/bin/bash
# ─── Production Deployment Script ─────────────────────────────────────────────
# Run on the Hetzner VPS after initial setup
# Usage: ./scripts/deploy.sh [first-time|update]

set -euo pipefail

REPO_DIR="/opt/cap"
COMPOSE_FILE="docker-compose.prod.yml"

cd "$REPO_DIR"

case "${1:-update}" in
  first-time)
    echo "═══ First-time setup ═══"

    # Pull latest code
    git pull origin main

    # Build the frontend
    echo "→ Building frontend..."
    cd client
    npm ci --production=false
    npm run build
    cd ..

    # Create .env.prod if it doesn't exist
    if [ ! -f server/.env.prod ]; then
      cp server/.env.prod.example server/.env.prod
      echo "⚠️  Edit server/.env.prod with real values before continuing!"
      echo "   Then run: ./scripts/deploy.sh first-time"
      exit 1
    fi

    # Start everything
    echo "→ Starting services..."
    docker compose -f "$COMPOSE_FILE" up --build -d

    # Wait for DB to be ready
    echo "→ Waiting for database..."
    sleep 10

    # Run migrations
    echo "→ Running database migrations..."
    docker compose -f "$COMPOSE_FILE" exec api alembic upgrade head

    # Set up cron jobs
    echo "→ Setting up cron jobs..."
    (crontab -l 2>/dev/null; cat <<'CRON'
# ─── Catch a Prayer Cron Jobs ───
# Daily: refresh prayer schedules for active mosques
0 3 * * * cd /opt/cap && docker compose -f docker-compose.prod.yml exec -T api python -m pipeline.refresh_schedules >> /var/log/cap/daily_refresh.log 2>&1

# Weekly (Tuesday 2 AM): full scraping pipeline
0 2 * * 2 cd /opt/cap && docker compose -f docker-compose.prod.yml exec -T api python -m pipeline.run_weekly_update >> /var/log/cap/weekly_update.log 2>&1

# Monthly (1st, 3 AM): discover new mosques
0 3 1 * * cd /opt/cap && docker compose -f docker-compose.prod.yml exec -T api python -m pipeline.seed_from_web_sources >> /var/log/cap/monthly_seed.log 2>&1

# Daily (4 AM): database backup
0 4 * * * /opt/cap/scripts/backup.sh >> /var/log/cap/backup.log 2>&1
CRON
    ) | sort -u | crontab -

    # Create log directory
    mkdir -p /var/log/cap

    echo "✅ First-time setup complete!"
    echo "   API: https://$(grep DOMAIN server/.env.prod | cut -d= -f2)/api"
    echo "   Health: https://$(grep DOMAIN server/.env.prod | cut -d= -f2)/health"
    ;;

  update)
    echo "═══ Updating deployment ═══"

    # Pull latest code
    git pull origin main

    # Rebuild frontend
    echo "→ Building frontend..."
    cd client
    npm ci --production=false
    npm run build
    cd ..

    # Rebuild and restart API (zero-downtime: new container starts before old stops)
    echo "→ Rebuilding API..."
    docker compose -f "$COMPOSE_FILE" up --build -d api

    # Run any new migrations
    echo "→ Running migrations..."
    docker compose -f "$COMPOSE_FILE" exec api alembic upgrade head

    echo "✅ Update complete!"
    ;;

  *)
    echo "Usage: $0 [first-time|update]"
    exit 1
    ;;
esac
