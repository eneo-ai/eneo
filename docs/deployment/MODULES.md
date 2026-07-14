# Eneo Modules — Operator Guide

Modules are **optional add-on web apps** that run next to your Eneo installation: each module is its own container on its own domain (e.g. `ttt.your-domain.com`), enabled per instance with a Docker Compose profile. The core Eneo images are never modified — enabling or removing a module never touches your main deployment.

> Modules are being rolled out incrementally. This guide documents the platform; each module's catalog entry lists its image, version and minimum Eneo version.

## Security model

Three properties, in order of importance:

1. **Scoped credentials.** Each module holds one Eneo **service key** (`sk_`) with the narrowest possible scope and permission. The key lives only in the module's env file on the server — it is never sent to the browser. Compromising a module's UI session cannot yield more access than that one key grants.
2. **Network isolation.** Modules join only `module_net`, which is `internal` — they can reach the backend at `http://backend:8000` and **nothing else**: no PostgreSQL, no Redis, and no outbound internet. Even a fully compromised module container has no path to the data layer and no way to exfiltrate directly.
3. **BFF pattern.** The browser only ever talks to the module's own domain. The module's server side (backend-for-frontend) holds the credentials and forwards requests to Eneo.

Note: modules are not network-isolated *from each other* — the authorization boundary between modules is key scoping, which is why step 2 below matters. A module that needs an external API cannot call it directly; such calls go through the Eneo backend.

## User login (SSO via Eneo)

Modules have **no login of their own and no IdP configuration**. Eneo is the single OIDC client in the installation, and module login rides on the user's Eneo session:

1. An unauthenticated user on the module domain is redirected to Eneo.
2. Eneo authenticates the user as usual (existing session, or your IdP), verifies that the user may use the module, and redirects back with a one-time, short-lived ticket.
3. The module's server side exchanges the ticket with the backend over the internal network and establishes its own session cookie.

For operators this means: no extra client registration in your IdP per module, and users already signed in to Eneo reach modules without seeing a login screen. Each module's catalog entry states the minimum Eneo version that supports this handoff.

## Enabling a module

Using **Tal till text** as the example (module id `tal-till-text`):

### 1. DNS

Point the module domain at the same server as your Eneo installation:

```
ttt.your-domain.com  A  <your-server-ip>
```

Traefik picks up TLS via Let's Encrypt automatically once the container starts.

### 2. Mint a scoped service key

Create an `sk_` key as a tenant admin (a user whose role has the API keys permission). Log in, then create the key:

```bash
ENEO_URL=https://your-domain.com

# 1. Get a session token (admin user)
TOKEN=$(curl -fsS -X POST "$ENEO_URL/api/v1/users/login/token/" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@your-company.com&password=..." | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2. Create the module's service key
curl -fsS -X POST "$ENEO_URL/api/v1/api-keys" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "mod-tal-till-text",
    "description": "Service key for the Tal till text module",
    "key_type": "sk_",
    "ownership": "service",
    "permission": "write",
    "scope_type": "space",
    "scope_id": "<uuid-of-the-space-the-module-works-in>",
    "rate_limit": 1000
  }'
```

The response contains the secret **once** (`"secret": "sk_..."`). Store it directly in the module's env file — it cannot be retrieved again, only rotated.

**Scoping guidance:**

- Use the **narrowest** `scope_type` that covers the module's documented needs — each module's catalog entry states what it requires (e.g. a dedicated space). Avoid `tenant`-scoped keys for modules.
- `permission`: `write` is normally enough. Never `admin` for a module.
- Set a `rate_limit` matching expected usage; the backend enforces it per hour (Redis-backed).
- Consider `expires_at` + calendar-driven rotation for high-sensitivity modules. Rotation has a grace period (default 24 h), so it is zero-downtime: rotate, update the env file, `docker compose up -d` the module.

### 3. Configure env files

```bash
cp env_modules.template env_modules.env          # shared defaults (first module only)
cp env_module_ttt.template env_module_ttt.env    # module secrets
# Fill in: ENEO_MODULE_API_KEY (from step 2), SESSION_SECRET
```

Edit `docker-compose.modules.yml` and replace the `CHANGE THIS` placeholders (module domain in 3 label locations + `MODULE_PUBLIC_URL` + `ENEO_PUBLIC_URL`).

### 4. Start

```bash
docker compose -f docker-compose.yml -f docker-compose.modules.yml \
  --profile tal-till-text up -d
```

Pin the module version in production by setting `MODULE_TTT_VERSION` (defaults to `latest`). Module versions are pinned **independently** of your Eneo version — check the module's compatibility notes before upgrading either.

### 5. Verify

```bash
# Module is healthy and routed with TLS
curl -fsS https://ttt.your-domain.com/health

# Module can reach the backend...
docker exec eneo_mod_tal_till_text wget -q -O- http://backend:8000/version

# ...but not the data layer (both must FAIL)
docker exec eneo_mod_tal_till_text getent hosts db
docker exec eneo_mod_tal_till_text getent hosts redis

# ...and has no internet egress (must FAIL)
docker exec eneo_mod_tal_till_text wget -q --spider -T 5 https://example.com
```

## Disabling a module

```bash
# 1. Stop and remove the container
# (do NOT use `down` with a profile - that would stop the whole stack)
docker compose -f docker-compose.yml -f docker-compose.modules.yml \
  --profile tal-till-text stop mod-tal-till-text
docker compose -f docker-compose.yml -f docker-compose.modules.yml \
  --profile tal-till-text rm -f mod-tal-till-text

# 2. Revoke its key (API keys admin UI, or the API)
curl -fsS -X POST "$ENEO_URL/api/v1/api-keys/<key-id>/revoke" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason_code": "decommissioned", "reason_text": "Module disabled"}'
```

Always do both — a stopped container with a live key is a dormant credential.

## Running several modules

- One profile, one env file, one domain per module. Use `--profile all-modules` only in test environments.
- Each module's key is scoped to its own resources — never share a key between modules.
- Module images upgrade independently: `MODULE_<X>_VERSION` per module, `docker compose ... pull mod-<x> && ... up -d mod-<x>`.

## Troubleshooting

**Module container never becomes healthy / keeps restarting**
Check `docker logs eneo_mod_tal_till_text`. The most common causes are a missing/invalid `ENEO_MODULE_API_KEY` (the module fails fast on startup) or an Eneo backend below the module's minimum version.

**404 or certificate errors on the module domain**
Verify DNS points at the server, the domain is identical in all `CHANGE THIS` locations, and the router names in the Traefik labels don't collide with another module's.

**Module gets 401/403 from the backend**
The key is revoked, expired, or scoped to the wrong resource. Check the key's state and scope in the API keys admin. 429 means the key's `rate_limit` is too low for real usage.
