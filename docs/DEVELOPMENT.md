# Development Workflow — Catch a Prayer

## Environments

| Environment | API URL | Database | Purpose |
|-------------|---------|----------|---------|
| **Local dev** | `http://192.168.0.26:8000` | Docker on laptop | Day-to-day coding, debugging |
| **Production** | `http://5.78.187.171` (→ domain later) | Hetzner VPS | Live users |

---

## Local Development Setup

### Start local services

```bash
cd /Users/mahmoud/projects/cap/repo/cap/catch-a-prayer

# Start DB + API (local Docker)
docker-compose up -d

# Frontend dev server (hot reload)
cd client
npm start
# Opens http://localhost:3000 with hot reload
```

### Client `.env` for local dev

```env
REACT_APP_API_URL=http://192.168.0.26:8000
```

### Test on phone via Xcode (local)

```bash
cd client
npm run build
npx cap sync ios
# Open Xcode → Run on device/simulator
```

---

## Development Workflow

### 1. Work on a feature

```bash
# Always start from latest main
git pull origin main

# Make changes to client/ and/or server/
# Test locally with hot reload (npm start) or Xcode
```

### 2. Test locally

**Frontend changes:**
```bash
cd client
npm start                    # hot reload at localhost:3000
```

**Server changes:**
- Docker auto-restarts the API container (if using `--reload`)
- Or restart manually: `docker-compose restart api`

**Full integration test (phone):**
```bash
cd client
npm run build && npx cap sync ios
# Run from Xcode on your phone
```

### 3. Commit

```bash
git add -A
git commit -m "feat: description of what changed"
```

### 4. Push to production

```bash
# Push code
git push origin main

# Deploy to Hetzner
ssh root@5.78.187.171 "cd /opt/cap && ./scripts/deploy.sh update"
```

That's it. The deploy script:
1. Pulls latest code on the server
2. Rebuilds the frontend (`npm run build`)
3. Rebuilds the API Docker container
4. Runs any new DB migrations
5. Zero downtime — new container starts before old one stops

---

## Switching Between Local and Production

### Test with local server (default for development)

```bash
# client/.env
REACT_APP_API_URL=http://192.168.0.26:8000
```

Then rebuild: `npm run build && npx cap sync ios`

### Test with production server

```bash
# client/.env
REACT_APP_API_URL=http://5.78.187.171
```

Then rebuild: `npm run build && npx cap sync ios`

**Important:** Don't commit the `.env` change when pointing to production for testing. Keep it pointing to local for day-to-day development.

---

## Quick Reference

### Daily development cycle

```
1. docker-compose up -d          ← start local DB + API
2. cd client && npm start        ← frontend hot reload
3. make changes, test in browser
4. npm run build && npx cap sync ios  ← test on phone
5. git add && git commit && git push
6. ssh root@5.78.187.171 "cd /opt/cap && ./scripts/deploy.sh update"  ← deploy
```

### One-liner deploy

```bash
# From your laptop — push and deploy in one command
git push origin main && ssh root@5.78.187.171 "cd /opt/cap && ./scripts/deploy.sh update"
```

### Check production health

```bash
curl -s http://5.78.187.171/health
```

### View production logs

```bash
ssh root@5.78.187.171 "docker logs cap-api --tail 50"
```

### Restart production API

```bash
ssh root@5.78.187.171 "cd /opt/cap && docker compose -f docker-compose.prod.yml restart api"
```

---

## Server-Side Changes

When you change server code (`server/` directory):

1. The local Docker container picks up changes automatically (if using `--reload`)
2. For production: the deploy script rebuilds the container
3. **Database migrations**: if you change models, create a migration:
   ```bash
   # Locally
   cd server
   alembic revision --autogenerate -m "description"
   alembic upgrade head

   # The deploy script runs migrations automatically on the server
   ```

## Client-Side Changes

When you change client code (`client/src/`):

1. `npm start` gives you hot reload in the browser
2. For phone testing: `npm run build && npx cap sync ios` then run from Xcode
3. For production: the deploy script rebuilds the frontend on the server

---

## File Structure

```
catch-a-prayer/
├── client/                    # React frontend
│   ├── .env                   # ← API URL (local vs production)
│   ├── src/                   # Source code
│   ├── build/                 # Built frontend (gitignored)
│   └── ios/                   # Capacitor iOS project
├── server/                    # FastAPI backend
│   ├── .env                   # Local dev env
│   ├── .env.prod              # Production env (gitignored, lives on server)
│   ├── .env.prod.example      # Template for production env
│   ├── app/                   # API code
│   └── pipeline/              # Scraping pipeline
├── docker-compose.yml         # Local development
├── docker-compose.prod.yml    # Production
├── Caddyfile                  # Production reverse proxy
├── prometheus/                # Monitoring config
├── scripts/
│   ├── deploy.sh              # Production deployment
│   ├── backup.sh              # Database backup
│   └── setup-server.sh        # One-time VPS setup
└── docs/
    ├── DEVELOPMENT.md          # This file
    ├── DEPLOYMENT.md           # Production infrastructure
    ├── MONITORING.md           # Observability plan
    └── FRONTEND_DESIGN.md      # UI/UX design decisions
```

---

## Publishing to App Stores

### Apple App Store

**One-time setup:**
1. **Apple Developer Account** — $99/year at https://developer.apple.com/programs/enroll/
2. **App Store Connect** — Create app listing at https://appstoreconnect.apple.com
   - App name: "Catch a Prayer"
   - Bundle ID: `com.catchaprayer.app` (must match `capacitor.config.json`)
   - Category: Lifestyle or Reference
3. **Signing certificate** — In Xcode: Signing & Capabilities → Team → your Apple Developer account
4. **Screenshots** — Required sizes: 6.7" (iPhone 15 Pro Max), 6.5" (iPhone 11 Pro Max), 5.5" (iPhone 8 Plus), iPad Pro 12.9"

**Release process:**
```bash
# 1. Update version in capacitor.config.json and Info.plist
#    Bump version number for each release (e.g., 1.0.0 → 1.1.0)

# 2. Build production frontend
cd client
REACT_APP_API_URL=http://5.78.187.171 npm run build
npx cap sync ios

# 3. In Xcode:
#    - Select "Any iOS Device (arm64)" as destination
#    - Product → Archive
#    - Window → Organizer → Distribute App → App Store Connect
#    - Upload

# 4. In App Store Connect:
#    - Select the uploaded build
#    - Fill in release notes
#    - Submit for Review (usually 24-48 hours)
```

**App Store checklist:**
- [ ] App icon (1024x1024 — already set up)
- [ ] Screenshots for required device sizes
- [ ] App description, keywords, privacy policy URL
- [ ] Privacy policy page (required — host at your domain)
- [ ] Support URL
- [ ] Age rating: 4+ (no objectionable content)
- [ ] Set pricing: Free

### Google Play Store

**One-time setup:**
1. **Google Play Developer Account** — $25 one-time fee at https://play.google.com/console/signup
2. **Generate signed APK/AAB** — Android requires a signing key

**Add Android to the project:**
```bash
cd client
npx cap add android
npx cap sync android
```

**Release process:**
```bash
# 1. Build production frontend
REACT_APP_API_URL=http://5.78.187.171 npm run build
npx cap sync android

# 2. Open in Android Studio
npx cap open android

# 3. In Android Studio:
#    - Build → Generate Signed Bundle/APK
#    - Choose Android App Bundle (AAB)
#    - Create or select signing key
#    - Build release AAB

# 4. In Google Play Console:
#    - Create app → fill in listing details
#    - Upload AAB to Production track
#    - Fill in content rating questionnaire
#    - Set pricing: Free
#    - Submit for review (usually a few hours to 3 days)
```

**Play Store checklist:**
- [ ] App icon (512x512)
- [ ] Feature graphic (1024x500)
- [ ] Screenshots (phone + tablet)
- [ ] Short description (80 chars) + full description (4000 chars)
- [ ] Privacy policy URL
- [ ] Content rating questionnaire
- [ ] Data safety form (what data you collect)
- [ ] Target audience and content
- [ ] Set pricing: Free

### Version Management

Use semantic versioning: `MAJOR.MINOR.PATCH`

```
1.0.0  — Initial App Store release
1.1.0  — New feature (e.g., trip planning)
1.1.1  — Bug fix
1.2.0  — Next feature release
```

Update version in:
- `client/ios/App/App/Info.plist` (iOS)
- `client/android/app/build.gradle` (Android, after adding)
- `client/package.json` (for reference)

### App Store Release Workflow

```
1. Develop + test locally
2. git push origin main
3. Deploy server: ssh root@5.78.187.171 "cd /opt/cap && ./scripts/deploy.sh update"
4. Build iOS archive in Xcode → upload to App Store Connect
5. Build Android AAB in Android Studio → upload to Play Console
6. Submit both for review
7. Once approved, release to users
```

### Costs

| Item | Cost | Frequency |
|------|------|-----------|
| Apple Developer Program | $99 | Yearly |
| Google Play Developer | $25 | One-time |
| Hetzner VPS | $5-6 | Monthly |
| Domain (optional) | $10-15 | Yearly |
| **Total Year 1** | **~$150** | |
| **Total Year 2+** | **~$170** | |

---

## Troubleshooting

### Local API not responding
```bash
docker-compose logs api --tail 20
docker-compose restart api
```

### Production API not responding
```bash
ssh root@5.78.187.171 "docker logs cap-api --tail 30"
ssh root@5.78.187.171 "cd /opt/cap && docker compose -f docker-compose.prod.yml restart api"
```

### Phone can't reach local server
- Check your Mac's IP: `ipconfig getifaddr en0`
- Update `client/.env` with the correct IP
- Make sure phone and Mac are on the same WiFi

### Database migration failed
```bash
# Check current migration state
cd server && alembic current

# If stuck, stamp the current state and retry
alembic stamp head
alembic upgrade head
```
