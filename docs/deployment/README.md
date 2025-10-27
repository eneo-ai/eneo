# Eneo Production Deployment

Quick deployment reference for Eneo using Docker Compose.

> **First time deploying?** See the [Full Deployment Guide](../DEPLOYMENT.md) for detailed explanations and troubleshooting.

## Files in This Directory

- `docker-compose.yml` - Complete production stack (Traefik, frontend, backend, worker, PostgreSQL, Redis)
- `env_backend.template` - Backend configuration (API keys, OIDC, multi-tenancy)
- `env_frontend.template` - Frontend configuration (URLs, OIDC)
- `env_db.template` - Database credentials

## Quick Start

```bash
# 1. Copy templates
cp env_backend.template env_backend.env
cp env_frontend.template env_frontend.env
cp env_db.template env_db.env

# 2. Edit these 4 locations in docker-compose.yml:
#    - Line 15: your-email@domain.com (Let's Encrypt email)
#    - Lines 39, 42, 65, 68: your-domain.com (replace all 4)

# 3. Configure environment files:
#    - env_backend.env: Add OPENAI_API_KEY or ANTHROPIC_API_KEY
#    - env_backend.env: Generate JWT_SECRET (openssl rand -hex 32)
#    - env_frontend.env: Copy same JWT_SECRET from backend
#    - env_frontend.env: Update domain URLs
#    - env_db.env: Set POSTGRES_PASSWORD

# 4. Deploy
docker network create proxy_tier
docker compose up -d

# 5. Login: user@example.com / Password1! (change password immediately!)
```

## Full Documentation

**Step-by-Step Guide:** [DEPLOYMENT.md](../DEPLOYMENT.md)

**Multi-Tenancy Setup:** See [Advanced Configuration](../DEPLOYMENT.md#advanced-configuration--features) for per-tenant credentials and federation
