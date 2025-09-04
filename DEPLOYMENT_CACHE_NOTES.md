# Docker Cache Prevention Strategy

## Problem
Docker and NPM caching can prevent code changes from taking effect during development and deployment.

## Cache Clearing Commands

### Complete Cache Clear (Use when changes aren't taking effect)
```bash
# Stop all services
docker-compose down

# Remove all containers, networks, and volumes  
docker system prune -af --volumes

# Remove all build cache
docker builder prune -af

# Rebuild completely without cache
docker-compose build --no-cache

# Start services
docker-compose up -d
```

### Quick Cache Clear (For most development changes)
```bash
# Rebuild specific service without cache
docker-compose build --no-cache api
docker-compose build --no-cache web

# Restart services
docker-compose up -d
```

## Prevention Strategies

1. **Use .dockerignore**: Properly configured to exclude unnecessary files from build context
2. **Layer Optimization**: Dependencies installed in separate layer before copying code
3. **Build Arguments**: Use build args to bust cache when needed

## When to Use Cache Clearing

- Code changes not reflecting in running containers
- Environment variable changes not taking effect  
- New dependencies not being installed
- TypeScript compilation errors hidden by cache
- Prayer timing logic changes not working

## Notes

- Always use `--no-cache` flag when debugging deployment issues
- The `.dockerignore` file helps prevent cache invalidation from irrelevant file changes
- Consider using multi-stage builds for more efficient caching in production