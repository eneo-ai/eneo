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

# 2. Edit docker-compose.yml (replace your-domain.com with your actual domain):
#    - Line 38: your-email@domain.com (Let's Encrypt email)
#    - Lines 65, 68, 91, 94: your-domain.com (4 locations)

# 3. Configure env_db.env:
#    - POSTGRES_PASSWORD=your-secure-password

# 4. Configure env_backend.env:
#    - JWT_SECRET=$(openssl rand -hex 32)
#    - PUBLIC_ORIGIN=https://your-domain.com
#    - Add at least one LLM key: OPENAI_API_KEY or ANTHROPIC_API_KEY
#    - Set initial user credentials (creates login user):
#        DEFAULT_TENANT_NAME=ExampleTenant
#        DEFAULT_USER_EMAIL=user@example.com
#        DEFAULT_USER_PASSWORD=Password1!

# 5. Configure env_frontend.env:
#    - JWT_SECRET=<same as backend>
#    - INTRIC_BACKEND_URL=https://your-domain.com
#    - INTRIC_BACKEND_SERVER_URL=http://backend:8000
#    - PUBLIC_INTRIC_BACKEND_URL=https://your-domain.com
#    - ORIGIN=https://your-domain.com
#    - PUBLIC_ORIGIN=https://your-domain.com

# 6. Deploy
docker network create proxy_tier
docker compose up -d

# 7. Login with DEFAULT_USER_EMAIL / DEFAULT_USER_PASSWORD (change password immediately!)
```

## Full Documentation

**Step-by-Step Guide:** [DEPLOYMENT.md](../DEPLOYMENT.md)

**Multi-Tenancy Setup:** See [Advanced Configuration](../DEPLOYMENT.md#advanced-configuration--features) for per-tenant credentials and federation
