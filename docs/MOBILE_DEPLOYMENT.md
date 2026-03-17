# Mobile Deployment Plan — Catch a Prayer

## Strategy: Capacitor

Wrap the existing React + TypeScript frontend in a native iOS/Android shell using Capacitor.
No frontend rewrite. Single codebase ships to both stores.

---

## Phase 1: Local Device Testing (do this first)

**Goal**: App running on your physical iPhone/Android for testing.

### Prerequisites
- Xcode installed (Mac App Store, free)
- Android Studio installed (for Android testing, optional for now)
- iPhone connected via USB
- Free Apple ID (no paid account needed for direct device install)

### Steps
1. Install Capacitor in the client
2. Build the React app
3. Add iOS platform
4. Open in Xcode → select your device → Run
5. Trust developer on iPhone (Settings → General → VPN & Device Management)

---

## Phase 2: Backend Deployment

**Goal**: App talks to a real server, not localhost.

The mobile app can't hit `localhost:8000` — it needs a public URL.

### Recommended: Railway
- Connects to your git repo
- Deploys FastAPI backend + PostgreSQL + PostGIS in one click
- Free tier available, ~$5/month for always-on

### Steps
1. Push repo to GitHub if not already
2. Create Railway project → deploy from repo
3. Add environment variables (ANTHROPIC_API_KEY, MAPBOX_API_KEY, etc.)
4. Get the public backend URL (e.g. `https://catchaprayer-api.railway.app`)
5. Set `REACT_APP_API_URL` in `client/.env` to that URL
6. Rebuild and sync Capacitor

---

## Phase 3: App Store Submission (iOS)

**Goal**: Public listing on the Apple App Store.

### Prerequisites
- Apple Developer Program — $99/year (enroll at developer.apple.com)
- App icons (1024×1024 + all required sizes)
- Screenshots for App Store listing (6.5" iPhone required)
- Privacy policy URL (required by Apple)

### Steps
1. Register App ID in Apple Developer portal
2. Create provisioning profile + distribution certificate in Xcode
3. Set bundle ID (e.g. `com.catchaprayer.app`)
4. Build archive in Xcode → upload to App Store Connect
5. Fill in App Store listing (description, screenshots, category: Navigation or Utilities)
6. Submit for review (~1-3 days)

### App Store Metadata
- **Category**: Navigation (primary), Utilities (secondary)
- **Age rating**: 4+ (no objectionable content)
- **Privacy**: location data used (required disclosure)

---

## Phase 4: Google Play Submission (Android)

**Goal**: Public listing on Google Play Store.

### Prerequisites
- Google Play Developer account — $25 one-time (play.google.com/console)
- App icons + feature graphic (1024×500)
- Screenshots

### Steps
1. Add Android platform to Capacitor
2. Open in Android Studio → build signed APK/AAB
3. Upload AAB to Google Play Console
4. Fill in store listing
5. Submit for review (~1-3 days, usually faster than Apple)

---

## Phase 5: Production Hardening (before public launch)

- [ ] Analytics (Firebase or Plausible)
- [ ] Crash reporting (Sentry)
- [ ] Push notifications via FCM (already designed in backend)
- [ ] App icon + splash screen
- [ ] Offline mode: cache last known mosque list
- [ ] Rate limiting on backend API
- [ ] Backend autoscaling (Railway handles this)

---

## Current Status

| Phase | Status |
|---|---|
| Phase 1: Local device testing | ⬜ Not started |
| Phase 2: Backend deployment | ⬜ Not started |
| Phase 3: iOS App Store | ⬜ Not started |
| Phase 4: Google Play | ⬜ Not started |
| Phase 5: Production hardening | ⬜ Not started |

---

## Tech Stack Reference

| Layer | Technology |
|---|---|
| Mobile wrapper | Capacitor 6 |
| Frontend | React 18 + TypeScript + Tailwind CSS |
| Backend | FastAPI (Python) |
| Database | PostgreSQL 15 + PostGIS |
| Hosting | Railway (recommended) |
| Push notifications | Firebase Cloud Messaging (already integrated) |
| iOS distribution | Apple Developer Program ($99/yr) |
| Android distribution | Google Play Console ($25 one-time) |
