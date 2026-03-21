#!/bin/bash
# ─── Production Cron Setup ────────────────────────────────────────────────────
# Run this on the production server to set up all automated jobs.
# Usage: ssh root@5.78.187.171 "bash /opt/cap/scripts/production_cron.sh"

set -euo pipefail

echo "Setting up production cron jobs..."

# Create log directory
mkdir -p /var/log/cap

# Install crontab
(crontab -l 2>/dev/null | grep -v "cap/docker" | grep -v "# CAP"; cat << 'CRON'
# === CAP: Catch a Prayer Automated Jobs ===

# Daily 1 AM UTC (8 PM ET): Generate calculated prayer times for all mosques
0 1 * * * cd /opt/cap && docker compose -f docker-compose.prod.yml exec -T api python -m pipeline.daily_calculated >> /var/log/cap/daily_calculated.log 2>&1

# Weekly Sunday 2 AM UTC: Run free scraper on all websites
0 2 * * 0 cd /opt/cap && docker compose -f docker-compose.prod.yml exec -T api python -m pipeline.free_scraper --all >> /var/log/cap/weekly_scraper.log 2>&1

# Daily 4 AM UTC: Database backup
0 4 * * * /opt/cap/scripts/backup.sh >> /var/log/cap/backup.log 2>&1

# Every 6 months (Jan 1 + Jul 1) at 3 AM UTC: Full mosque discovery (Google + OSM + Mawaqit)
0 3 1 1,7 * cd /opt/cap && docker compose -f docker-compose.prod.yml exec -T api python -m pipeline.full_discovery --all --save >> /var/log/cap/discovery.log 2>&1

# Daily 2 PM UTC (9 AM ET): Send daily digest to WhatsApp
0 14 * * * bash /opt/cap/scripts/daily-alerts.sh --digest >> /var/log/cap/daily_alerts.log 2>&1

# Every hour: Smart alerts — only sends if thresholds breached
0 * * * * bash /opt/cap/scripts/daily-alerts.sh >> /var/log/cap/hourly_alerts.log 2>&1
CRON
) | crontab -

echo "Cron jobs installed:"
crontab -l | grep -E "CAP|daily|weekly|backup|discover"
echo ""
echo "Done!"
