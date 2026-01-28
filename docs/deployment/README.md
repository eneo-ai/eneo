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

# 7. Verify db-init completed successfully (wait ~30 seconds for startup)
docker logs eneo_db_init
# Should see: "Great! Your Tenant and User are all set up."

# 8. Login with DEFAULT_USER_EMAIL / DEFAULT_USER_PASSWORD (change password immediately!)
```

## Troubleshooting

### Can't login with default credentials (401 error)

1. **Check if db-init succeeded:**
   ```bash
   docker logs eneo_db_init
   ```
   You should see `"Great! Your Tenant and User are all set up."`

2. **Check if user exists in database:**
   ```bash
   docker exec -it eneo_db psql -U postgres -d eneo -c "SELECT email, state FROM users;"
   ```

3. **If user doesn't exist**, the db-init likely failed. Reset and try again:
   ```bash
   docker compose down -v
   docker compose up -d
   sleep 30
   docker logs eneo_db_init
   ```

### db-init fails with migration errors

This usually means db-init started before PostgreSQL was ready. The docker-compose.yml includes healthchecks to prevent this, but if you're using a custom configuration, ensure:

- `db` service has a healthcheck
- `db-init` depends on `db` with `condition: service_healthy`

## Full Documentation

**Step-by-Step Guide:** [DEPLOYMENT.md](../DEPLOYMENT.md)

**Multi-Tenancy Setup:** See [Advanced Configuration](../DEPLOYMENT.md#advanced-configuration--features) for per-tenant credentials and federation
