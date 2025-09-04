# 🚀 CATCH A PRAYER - DEPLOYMENT GUIDE

This document outlines the necessary deployment steps to take **every time** you make changes to client or server code.

## 🔄 **COMPLETE DEPLOYMENT STEPS**

Follow these steps **in order** after making any code changes:

### 1. **Stop Running Containers**
```bash
docker-compose down
```
**Why**: Stops all running containers to prepare for rebuild

### 2. **Remove Old Images (Force Rebuild)**
```bash
docker-compose build --no-cache
```
**Why**: Forces Docker to rebuild images from scratch, ignoring cache. This ensures all code changes are included.

**Alternative** (more aggressive if needed):
```bash
# Remove all images related to this project
docker-compose down --rmi all
# Or remove specific images
docker rmi catch-a-prayer-api catch-a-prayer-web
```

### 3. **Start Services with Fresh Build**
```bash
docker-compose up -d
```
**Why**: 
- `-d` runs in detached mode (background)
- Uses freshly built images with latest code

### 4. **Verify Deployment**
```bash
# Check containers are running
docker-compose ps

# Check logs for any issues
docker-compose logs api
docker-compose logs web

# Test endpoints
curl http://localhost:8000/health
curl http://localhost:3000
```

### 5. **Monitor Real-time Logs (Optional)**
```bash
# Follow logs in real-time
docker-compose logs -f api
# Or for both services
docker-compose logs -f
```

---

## ⚡ **QUICK COMMANDS**

### Development Mode (Instant Changes)
```bash
# Start development with hot reload
docker-compose -f docker-compose.dev.yml up -d

# Stop development
docker-compose -f docker-compose.dev.yml down
```

### Production Deployment (One Command)
```bash
# Complete redeployment in one command
docker-compose down && docker-compose build --no-cache && docker-compose up -d
```

---

## 🔧 **TROUBLESHOOTING DEPLOYMENT ISSUES**

### Problem: "Changes not reflected after deployment"

**Solution**: Ensure you're doing a complete rebuild
```bash
docker-compose down
docker system prune -f  # Remove unused containers/images
docker-compose build --no-cache
docker-compose up -d
```

### Problem: "Port already in use"

**Solution**: Make sure old containers are stopped
```bash
docker-compose down
docker ps  # Should show no catch-a-prayer containers
docker-compose up -d
```

### Problem: "Build fails with dependency issues"

**Solution**: Check Docker build context and dependencies
```bash
# Server dependencies
cat server/requirements.txt
# Client dependencies  
cat client/package.json

# Force rebuild with verbose output
docker-compose build --no-cache --progress=plain
```

### Problem: "Environment variables not working"

**Solution**: Verify .env files exist and are properly configured
```bash
# Check server environment
ls -la server/.env
# Check client environment (created during build)
cat client/.env.example
```

---

## 📋 **DEPLOYMENT CHECKLIST**

Use this checklist **every time** you deploy:

- [ ] Code changes committed to git
- [ ] Docker containers stopped (`docker-compose down`)
- [ ] Images rebuilt without cache (`docker-compose build --no-cache`)
- [ ] Services started (`docker-compose up -d`)
- [ ] Containers running (`docker-compose ps`)
- [ ] Health checks passing (`curl http://localhost:8000/health`)
- [ ] Client accessible (`curl http://localhost:3000`)
- [ ] Functionality tested in browser

---

## 🛠 **DEVELOPMENT VS PRODUCTION**

### Development (Local) - FAST ITERATION 🚀
For active development with instant code changes (no rebuilds needed):

```bash
# Start development mode with hot reload
docker-compose -f docker-compose.dev.yml up -d

# Your changes to server/ and client/ files are instantly reflected!
# API: Changes auto-reload with uvicorn --reload
# Web: React hot reload works automatically
```

**Benefits:**
- ✅ Code changes reflected instantly (no rebuild)
- ✅ Hot reload for both API and frontend
- ✅ Volume mounts sync your local files with containers
- ✅ Perfect for development iteration

**Stop development containers:**
```bash
docker-compose -f docker-compose.dev.yml down
```

### Production Deployment
```bash
# Always use --no-cache for production deployments
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

---

## 📝 **WHEN TO USE FULL REBUILD**

**Always use `--no-cache` when**:
- ✅ Server Python code changes (prayer_service.py, main.py, etc.)
- ✅ Client TypeScript/React code changes (App.tsx, components, etc.)
- ✅ Dependency changes (requirements.txt, package.json)
- ✅ Configuration changes (.env, docker-compose.yml)
- ✅ Dockerfile changes
- ✅ Any code logic changes

**Can skip `--no-cache` when**:
- ❌ Only documentation changes (README.md, etc.)
- ❌ Only git commit messages or version tags

---

## 🔍 **VERIFICATION COMMANDS**

After deployment, always verify:

```bash
# 1. Check containers are healthy
docker-compose ps

# 2. Check server API is responding
curl -X POST http://localhost:8000/api/mosques/nearby \
  -H "Content-Type: application/json" \
  -d '{
    "latitude": 37.7749,
    "longitude": -122.4194,
    "radius_km": 5,
    "client_timezone": "America/Los_Angeles",
    "client_current_time": "'$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)'"
  }'

# 3. Check client is accessible
curl http://localhost:3000
```

---

## 🚨 **CRITICAL REMINDER**

**NEVER SKIP THE `--no-cache` FLAG** when deploying code changes. Docker's layer caching can prevent new code from being included in the build, leading to the exact issue we experienced where the app was still running old prayer logic.

This is especially important for:
- Bug fixes (like the prayer timing issue)
- New features
- Logic changes
- Dependency updates

---

**Remember**: When in doubt, always do a complete rebuild with `--no-cache` to ensure your latest changes are deployed!