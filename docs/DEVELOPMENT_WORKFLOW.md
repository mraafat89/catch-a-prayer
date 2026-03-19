# Development Workflow

## Branch Strategy

```
main (production)
 └── dev (integration / staging)
      ├── feature/mosque-suggestions
      ├── feature/push-notifications
      └── fix/iqama-parsing
```

**Rules:**
- `main` = production. Every commit on main is deployed. Never push directly.
- `dev` = integration branch. All feature branches merge here first. Points to local/staging server.
- Feature branches branch off `dev`, merge back into `dev` via PR.
- When `dev` is stable and tested, merge `dev → main` via PR.

**Why not merge features directly to main?**
You need to test features together before they hit production. A feature that works alone might break when combined with another. `dev` is where you catch that.

---

## Environment Configuration

### The Problem

The API URL is baked into the client build at compile time (`REACT_APP_API_URL`). You need different URLs for:

| Environment | API URL | Database |
|-------------|---------|----------|
| Local dev | `http://localhost:8000` | Local PostgreSQL |
| Device testing | `http://<your-mac-ip>:8000` | Local PostgreSQL |
| Production | `https://catchaprayer.com` | Production PostgreSQL |

### The Solution: Environment Files (already in `.gitignore`)

Your `.env` files are already git-ignored. The workflow is:

1. **`client/.env`** — always set to your current working environment
2. **`client/.env.production`** — always set to production (used by `npm run build` automatically)
3. **Never commit `.env` files** — they're in `.gitignore`

Create `client/.env.production` (this file is NOT committed):
```
REACT_APP_API_URL=https://catchaprayer.com
REACT_APP_GOOGLE_MAPS_API_KEY=your_key
```

Create `client/.env.development` (for `npm start`):
```
REACT_APP_API_URL=http://localhost:8000
REACT_APP_GOOGLE_MAPS_API_KEY=your_key
```

**How React Scripts handles this:**
- `npm start` → loads `.env.development` (local server)
- `npm run build` → loads `.env.production` (production server)

This means you never need to manually switch URLs. Just run the right command.

### Testing on a Physical Device (Xcode/Android Studio)

When testing on your phone via Xcode, the app runs the **built** web assets. To point at your local server:

1. Find your Mac's local IP: `ipconfig getifaddr en0` (e.g., `192.168.1.42`)
2. Set `client/.env` to:
   ```
   REACT_APP_API_URL=http://192.168.1.42:8000
   ```
3. Build and sync:
   ```bash
   cd client
   npm run build
   npx cap sync ios
   ```
4. Run from Xcode

**Important:** Your phone and Mac must be on the same Wi-Fi network.

To switch back to production:
```bash
# Set client/.env back to production URL
REACT_APP_API_URL=https://catchaprayer.com
npm run build && npx cap sync ios
```

### Shortcut Scripts

Add these to `client/package.json` scripts:

```json
{
  "scripts": {
    "build:dev": "REACT_APP_API_URL=http://192.168.1.42:8000 react-scripts build",
    "build:prod": "REACT_APP_API_URL=https://catchaprayer.com react-scripts build",
    "sync:ios": "npm run build:prod && npx cap sync ios",
    "sync:ios:dev": "npm run build:dev && npx cap sync ios",
    "sync:android": "npm run build:prod && npx cap sync android",
    "sync:android:dev": "npm run build:dev && npx cap sync android"
  }
}
```

Then:
- `npm run sync:ios:dev` → build + sync for local testing
- `npm run sync:ios` → build + sync for production / App Store submission

---

## Daily Development Flow

### Starting a new feature

```bash
git checkout dev
git pull origin dev
git checkout -b feature/my-feature

# Work on the feature...
# Test locally with npm start (uses .env.development → localhost)
# Test on device with npm run sync:ios:dev

# When done:
git push origin feature/my-feature
# Create PR: feature/my-feature → dev
```

### Testing on dev

```bash
git checkout dev
git merge feature/my-feature

# Run full test locally
# Test on device
# If issues found, fix on the feature branch and re-merge
```

### Deploying to production

```bash
# When dev is stable:
git checkout main
git merge dev
git push origin main

# Deploy server (SSH to production):
ssh your-server
cd /path/to/app
git pull
docker-compose -f docker-compose.prod.yml up -d --build

# Build client for App Store:
cd client
npm run build:prod
npx cap sync ios
# Open Xcode → Archive → Upload to App Store Connect
```

---

## Server ↔ Client Version Sync

This is the most critical part. Your server can be updated instantly, but App Store review takes 24-48 hours. During that gap, old app versions call new server endpoints.

### Rule: The Server Must Always Support the Current Live App Version

### Strategy: Backwards-Compatible API Changes

**Safe changes (deploy server anytime):**
- Adding new endpoints (old app doesn't call them — no effect)
- Adding optional fields to responses (old app ignores them)
- Adding optional fields to requests (old app doesn't send them — server uses defaults)
- Bug fixes that don't change the API contract

**Dangerous changes (require coordination):**
- Removing or renaming endpoints
- Removing or renaming response fields
- Changing required request fields
- Changing response field types

### How to Handle Breaking Changes

Use a **two-phase deploy**:

**Phase 1: Deploy server with backwards compatibility**
```
Server supports BOTH old and new API behavior.
Old app continues to work.
Submit new app to App Store.
```

**Phase 2: After new app is approved and live (wait ~1 week for most users to update)**
```
Remove old API compatibility code.
```

### Practical Example

Say you want to rename `spot_type` to `location_type`:

**Phase 1 (server):**
```python
# Return BOTH fields in the response
return {
    "spot_type": spot.spot_type,       # old field (keep for old app)
    "location_type": spot.spot_type,   # new field (for new app)
}
```

**Phase 1 (client):**
```typescript
// New app reads the new field
const type = spot.location_type;
```

Submit new app. Wait for approval.

**Phase 2 (server, 1-2 weeks later):**
```python
# Remove old field
return {
    "location_type": spot.spot_type,
}
```

### Version Header (Optional but Recommended)

Add an app version header to all API requests:

```typescript
// client/src/services/api.ts
const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'X-App-Version': '2.1.0',  // bump with each release
  },
});
```

The server can then use this to serve different responses if needed:
```python
app_version = request.headers.get("X-App-Version", "1.0.0")
```

### Release Checklist

Before every release:

```
[ ] All changes on dev branch, tested locally and on device
[ ] Server changes are backwards-compatible with current live app
[ ] Merge dev → main
[ ] Deploy server first (it supports both old and new app)
[ ] Build client: npm run build:prod && npx cap sync ios && npx cap sync android
[ ] Bump version in Xcode (General → Version + Build)
[ ] Bump version in android/app/build.gradle (versionCode + versionName)
[ ] Archive and upload to App Store Connect
[ ] Generate signed AAB and upload to Google Play Console
[ ] Submit both for review
[ ] After both apps are approved and live, wait 1 week
[ ] Remove backwards-compat code from server if applicable
```

---

## Database Migrations in Production

Migrations must run BEFORE the new server code starts using the new tables/columns.

```bash
# On production server:
cd /path/to/app/server

# Run migrations first
alembic upgrade head

# Then restart the server
docker-compose -f docker-compose.prod.yml up -d --build api
```

**Rule:** Migrations must be additive (add columns/tables). Never drop columns that the current live server uses. Use two-phase: add new column → deploy new code → remove old column later.

---

## Summary

| Action | Command |
|--------|---------|
| Start local dev | `cd client && npm start` + `cd server && uvicorn app.main:app --reload` |
| Test on iPhone (local) | `cd client && npm run sync:ios:dev` → Xcode Run |
| Test on iPhone (prod) | `cd client && npm run sync:ios` → Xcode Run |
| Deploy server | SSH → `git pull && docker-compose up -d --build` |
| Submit to App Store | Xcode → Archive → Distribute → App Store Connect |
| Submit to Play Store | Android Studio → Build → Generate Signed AAB → Upload |
