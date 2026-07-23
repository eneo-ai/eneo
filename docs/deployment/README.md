# Eneo Production Deployment

Quick deployment reference for Eneo using Docker Compose.

> **First time deploying?** See the [Full Deployment Guide](../DEPLOYMENT.md) for detailed explanations and troubleshooting.

## Files in This Directory

- `docker-compose.yml` - Complete production stack (Traefik, frontend, backend, worker, PostgreSQL, Redis)
- `docker-compose.object-content.yml` - Optional bundled SeaweedFS profile
- `.env.template` - Optional object-store profile, endpoint, and secret inputs
- `docker-compose.modules.yml` - Optional module overlay (inert unless a `--profile` is passed; see [MODULES.md](MODULES.md))
- `env_backend.template` - Backend configuration (API keys, OIDC, multi-tenancy)
- `env_frontend.template` - Frontend configuration (URLs, OIDC)
- `env_db.template` - Database credentials
- `env_modules.template` / `env_module_ttt.template` - Module configuration (only needed when enabling modules)
- `OBJECT_CONTENT.md` - Offline object-content operations reference

## Quick Start

```bash
# 1. Copy templates
cp env_backend.template env_backend.env
cp env_frontend.template env_frontend.env
cp env_db.template env_db.env
cp .env.template .env
chmod 600 .env env_backend.env env_frontend.env env_db.env

# 2. Edit docker-compose.yml (replace your-domain.com with your actual domain):
#    - Line 55: your-email@domain.com (Let's Encrypt email)
#    - Lines 88, 91, 116, 119: your-domain.com (4 locations)

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

# 4b. Optional object storage:
#    - The default deployment uses bounded PostgreSQL-inline content
#    - Follow https://docs.eneo.ai/guides/object-content-storage before enabling it

# 5. Configure env_frontend.env:
#    - JWT_SECRET=<same as backend>
#    - ENEO_BACKEND_URL=https://your-domain.com
#    - ENEO_BACKEND_SERVER_URL=http://backend:8000
#    - PUBLIC_ENEO_BACKEND_URL=https://your-domain.com
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

The default stack does not require a separate object store. Eneo can keep
bounded durable content in PostgreSQL until an administrator explicitly chooses
the bundled SeaweedFS profile or an external compatible endpoint. Each content
record has one byte authority; Eneo never silently copies or falls back between
backends. Use the [Choose Content Storage
guide](https://docs.eneo.ai/guides/object-content-storage) before enabling the
profile or restoring a deployment that already owns object-store content. The
local [operations reference](OBJECT_CONTENT.md) remains available for offline
installations.

## Network Isolation

The stack uses four Docker networks:

| Network | Services | Purpose |
|---|---|---|
| `proxy_tier` (external, created in step 6) | Traefik, frontend, backend, worker | Ingress and outbound access (LLM APIs, OIDC, crawling) |
| `data_net` (`internal: true`) | db, redis, backend, worker, db-init | Data layer — no internet egress, unreachable from Traefik/frontend |
| `object_content_net` (`internal: true`) | optional object-content, backend, worker | Private S3-compatible byte plane when enabled; no public route |
| `module_net` | Traefik, backend, optional modules | Module traffic — modules reach the backend only (see [MODULES.md](MODULES.md)) |

The backend is the only service on all four networks. PostgreSQL, Redis, and
the optional object-content service are not reachable from the frontend or
Traefik containers and have no outbound internet access.

### Upgrading an existing installation

Installations created from an earlier version of this file had every service on `proxy_tier`. The new topology is applied by recreating the containers:

```bash
docker compose up -d
```

Containers are recreated with new network membership; the Compose-managed PostgreSQL and Redis volumes are untouched (normally `eneo_eneo_postgres_data` and `eneo_eneo_redis_data` as Docker volumes). Expected downtime is a few seconds.

**Check before upgrading:** anything *outside* this compose file that connected to `db:5432` or `redis:6379` over `proxy_tier` (external backup jobs, admin tools) will lose access. Run such tools with `docker exec` (e.g. `docker exec eneo_db pg_dump ...`) or attach them to `eneo_data_net` explicitly.

**Verify after upgrading:**

```bash
# Should FAIL (frontend can no longer resolve the database):
docker exec eneo_frontend getent hosts db

# Should succeed:
docker exec eneo_backend python -c "import socket; socket.getaddrinfo('db', 5432)"
curl -fsS https://your-domain.com/version
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
