#!/bin/bash
# ─── Hetzner VPS Initial Setup ────────────────────────────────────────────────
# Run this ONCE on a fresh Ubuntu 22.04/24.04 VPS
# Usage: curl -sSL https://raw.githubusercontent.com/mraafat89/catch-a-prayer/main/scripts/setup-server.sh | bash

set -euo pipefail

echo "═══ Catch a Prayer — Server Setup ═══"

# Update system
echo "→ Updating system..."
apt-get update && apt-get upgrade -y

# Install Docker
echo "→ Installing Docker..."
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker

# Install Docker Compose plugin
echo "→ Docker Compose already included with Docker Engine"

# Install useful tools
echo "→ Installing tools..."
apt-get install -y git curl htop ufw fail2ban

# Firewall
echo "→ Configuring firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Create app directory
echo "→ Setting up application..."
mkdir -p /opt/cap /var/log/cap

# Clone repo
cd /opt
git clone https://github.com/mraafat89/catch-a-prayer.git cap
cd cap

# Make scripts executable
chmod +x scripts/*.sh

echo ""
echo "═══ Setup complete! Next steps: ═══"
echo ""
echo "1. Edit server/.env.prod:"
echo "   cp server/.env.prod.example server/.env.prod"
echo "   nano server/.env.prod"
echo ""
echo "2. Point your domain to this server's IP in Cloudflare"
echo ""
echo "3. Run first-time deployment:"
echo "   ./scripts/deploy.sh first-time"
echo ""
echo "Server IP: $(curl -s ifconfig.me)"
