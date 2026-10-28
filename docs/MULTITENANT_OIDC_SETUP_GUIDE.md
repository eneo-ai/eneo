# Multi-Tenant OIDC Setup Guide

**Updated:** 2026-10-28
**Audience:** Platform & support engineers
**Goal:** Let each tenant authenticate against its own IdP while keeping a single Eneo deployment.

---

## When to Use This Guide

This guide applies when `FEDERATION_ENABLED=true` (`FEDERATION_PER_TENANT_ENABLED` is a deprecated alias). Use this mode if:
- **Multi-tenant:** Each tenant needs their own IdP (Entra ID, Okta, Auth0, etc.)
- **Single-tenant with API management:** You want to manage OIDC via API instead of environment variables (changes take effect without restart)

**Not using federation?** For simple single-tenant deployments, keep `FEDERATION_ENABLED=false` and configure OIDC via environment variables (`OIDC_DISCOVERY_ENDPOINT`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`). See the [deployment templates](./deployment/env_backend.template).

---

## 1. Before You Start
- `FEDERATION_ENABLED=true` in backend `.env`
- Super admin API key available (needed for every `/api/v1/sysadmin/...` call)
- Redis running (recommended for the debug toggle; file fallback works)
- Each tenant has a slug (`tenant.slug`). Backfill once with:
  ```bash
  cd backend
  uv run python -m eneo.cli.backfill_tenant_slugs
  ```

Terminology
- **tenant_id** – UUID in admin APIs (e.g., `123e4567-e89b-12d3-a456-426614174000`)
- **tenant slug** – URL-safe label exposed to the frontend (e.g., `examplea`)

---

## 2. Configure a Tenant IdP (Example: MunicipalityExampleA using Entra ID)
1. **Provide a new federation config**
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
   `https://examplea.eneo.local/login/callback`

3. **Smoke test** the configuration (dry run; no user interaction):
   ```bash
   curl -X POST \
     -H "X-API-Key: {SUPER_API_KEY}" \
     https://api.eneo.local/api/v1/sysadmin/tenants/{tenant_id}/federation/test
   ```

Repeat for each tenant (e.g., MunicipalityExampleB with Auth0, MunicipalityExampleC with Okta). Only the IdP-specific fields change.

To update the current setup later without resending every field, use `PATCH /api/v1/sysadmin/tenants/{tenant_id}/federation`. Omitted fields stay unchanged:

```bash
curl -X PATCH "https://api.eneo.local/api/v1/sysadmin/tenants/{tenant_id}/federation" \
  -H "X-API-Key: {SUPER_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "allowed_domains": ["examplea.gov", "examplea.se"]
  }'
```

Use `PUT` when you want to provide a full new federation definition or replace the current one.

### 2.1 What the organisation's admins can change themselves
Once the operator has registered an IdP, an admin of that organisation (`Permission.ADMIN`, in a signed-in session; API keys are refused) reads it with `GET /api/v1/admin/federation` and changes it with `PATCH /api/v1/admin/federation`:

| Setting | Org admin | Operator (super API key) |
|---|---|---|
| Provider label, client ID, allowed email domains | read and edit | edit |
| Client secret | replace (write-only; never read) | edit |
| Discovery endpoint | read | edit |
| Issuer, token auth method and the other endpoints | issuer and token auth method: read | set from the discovery document whenever the discovery endpoint is set |
| Scopes, claim mapping | scopes: read | defaults (`openid email profile`; email from `email`); not editable through this API |
| `canonical_public_origin`, `redirect_path`, `additional_redirect_uris` | the resulting redirect URIs: read | edit |
| First registration, replacing the IdP, delete | no | yes |

- The admin never sees the secret, not even its last characters: only that one is set and when it was replaced. A value that looks like a masked secret is refused (`400 federation_secret_looks_masked`).
- A field the admin may not change is refused with `422`, and nothing is stored.
- Each `PATCH` sends the `revision` from `GET`; a save against settings someone else changed meanwhile gets `409 federation_config_revision_conflict`.
- Every change, from either door, is written to the audit log as `federation_updated` with each field from what to what (the secret only as `{"replaced": true}`). This action is logged even when the organisation switched off auditing, the admin-actions category or the action itself.

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

## 4. Recovery: SSO sign-in broke after a settings change
A wrong client ID, secret or domain list stops SSO sign-in for everyone in that organisation. The admin who saved it keeps their current session until it expires; local-password accounts still sign in at `/login?showUsernameAndPassword=true`.

1. **Find the change.** In the organisation's audit log, filter on `federation_updated`. The newest entry names who changed which field from what to what.
2. **Restore it with one operator call.** Send the previous values (a replaced secret is not in the log; take the current one from the IdP's client registration):
   ```bash
   curl -X PATCH "https://api.eneo.local/api/v1/sysadmin/tenants/{tenant_id}/federation" \
     -H "X-API-Key: {SUPER_API_KEY}" \
     -H "Content-Type: application/json" \
     -d '{"client_id": "{previous-client-id}", "client_secret": "{secret-from-the-idp}"}'
   ```
   The operator call is audited too.
3. **Verify** with a fresh SSO sign-in; if it still fails, use the correlation-ID flow in section 3.

---

## 5. Support Playbook (TL;DR)
1. **Report comes in** → enable debug toggle (10 min window)
2. **Reproduce or ask user to retry** → capture `correlationId`
3. **Filter logs** → identify breadcrumb from table above
4. **Fix config**
   - Add tenant credential (`/sysadmin/tenants/{id}/credentials/...`) if LLM access is missing
   - Adjust federation settings (`/federation` endpoints)
5. **Disable toggle** → confirm resolution with tenant

---

## 6. References
- [`FEDERATION_PER_TENANT.md`](./FEDERATION_PER_TENANT.md) – architecture & migration notes
- [AI Providers](https://docs.eneo.ai/guides/ai-providers) – provider configuration & credential management
- [`TROUBLESHOOTING.md`](./TROUBLESHOOTING.md) – incident catalogue
