# Multi-Tenant OIDC Setup Guide

**Updated:** 2025-10-18  
**Audience:** Platform & support engineers  
**Goal:** Let each tenant authenticate against its own IdP while keeping a single Eneo deployment.

---

## 1. Before You Start
- `FEDERATION_PER_TENANT_ENABLED=true` in backend `.env`
- Super admin API key available (needed for every `/api/v1/sysadmin/...` call)
- Redis running (recommended for the debug toggle; file fallback works)
- Each tenant has a slug (`tenant.slug`). Backfill once with:
  ```bash
  cd backend
  poetry run python -m intric.cli.backfill_tenant_slugs
  ```

Terminology
- **tenant_id** – UUID in admin APIs (e.g., `123e4567-e89b-12d3-a456-426614174000`)
- **tenant slug** – URL-safe label exposed to the frontend (e.g., `examplea`)

---

## 2. Configure a Tenant IdP (Example: MunicipalityExampleA using Entra ID)
1. **Create/update federation config**
   ```bash
   curl -X PUT "https://api.eneo.local/api/v1/sysadmin/tenants/{tenant_id}/federation" \
     -H "X-API-Key: {SUPER_API_KEY}" \
     -H "Content-Type: application/json" \
     -d '{
       "provider": "entra_id",
       "canonical_public_origin": "https://examplea.eneo.local",
       "discovery_endpoint": "https://login.microsoftonline.com/{azure-tenant-id}/v2.0/.well-known/openid-configuration",
       "client_id": "{azure-client-id}",
       "client_secret": "{azure-client-secret}",
       "allowed_domains": ["examplea.gov"],
       "scopes": ["openid", "email", "profile"]
     }'
   ```

2. **Register redirect URI with the IdP** (must match `canonical_public_origin`):  
   `https://examplea.eneo.local/auth/callback`

3. **Smoke test** the configuration (dry run; no user interaction):
   ```bash
   curl -X POST \
     -H "X-API-Key: {SUPER_API_KEY}" \
     https://api.eneo.local/api/v1/sysadmin/tenants/{tenant_id}/federation/test
   ```

Repeat for each tenant (e.g., MunicipalityExampleB with Auth0, MunicipalityExampleC with Okta). Only the IdP-specific fields change.

---

## 3. Runtime Debugging (Correlation-ID Based)
Use this flow when a tenant reports “login failed”. Everything happens on the backend; no code redeploy needed.

### 3.1 Toggle verbose logging
```bash
curl -X POST https://api.eneo.local/api/v1/sysadmin/observability/oidc-debug/ \
  -H "X-API-Key: {SUPER_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "duration_minutes": 10, "reason": "Case #452"}'
```
- Auto-expires after the requested duration (max 120 minutes)
- Stored in Redis (`observability:oidc_debug`) or `/app/data/debug_flags/oidc_debug.json` fallback

Check status:  
`GET /api/v1/sysadmin/observability/oidc-debug/`

### 3.2 Trace the correlation ID
Ask the user for the `correlationId` surfaced in the UI. Filter server logs:
```bash
journalctl -u backend.service -o cat | jq 'select(.correlation_id=="fa4fdb8fdbeee426")'
```

| Breadcrumb (log message)           | Typical cause                                | Next action                                             |
|------------------------------------|-----------------------------------------------|---------------------------------------------------------|
| `callback.domain_rejected`         | Email domain not in tenant `allowed_domains`  | Add domain or ask user to use approved account          |
| `callback.user_missing`            | Email not found in tenant user table          | Invite/import the user for that tenant                  |
| `callback.user_tenant_mismatch`    | User exists but belongs to another tenant     | Move user to correct tenant or adjust login link        |
| `callback.state_cache_error`       | Redis unavailable during login                | Check Redis health; retry once cache is restored        |
| `initiate.state_cache_failed`      | Redis write failed during initiate            | Investigate Redis/file permissions, then retry          |

Turn off logging once the incident is resolved:
```bash
curl -X POST https://api.eneo.local/api/v1/sysadmin/observability/oidc-debug/ \
  -H "X-API-Key: {SUPER_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false, "reason": "Case #452 closed"}'
```

---

## 4. Support Playbook (TL;DR)
1. **Report comes in** → enable debug toggle (10 min window)
2. **Reproduce or ask user to retry** → capture `correlationId`
3. **Filter logs** → identify breadcrumb from table above
4. **Fix config**
   - Add tenant credential (`/sysadmin/tenants/{id}/credentials/...`) if LLM access is missing
   - Adjust federation settings (`/federation` endpoints)
5. **Disable toggle** → confirm resolution with tenant

---

## 5. References
- [`FEDERATION_PER_TENANT.md`](./FEDERATION_PER_TENANT.md) – architecture & migration notes
- [`MULTI_TENANT_CREDENTIALS.md`](./MULTI_TENANT_CREDENTIALS.md) – per-tenant LLM API keys
- [`TROUBLESHOOTING.md`](./TROUBLESHOOTING.md) – incident catalogue
