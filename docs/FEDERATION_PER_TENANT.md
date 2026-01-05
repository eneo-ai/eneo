# Federation Per Tenant

**Status:** ✅ GA (since v2.0)  
**Compatibility:** Works alongside single-tenant deployments  
**Audience:** Architects & engineers integrating external IdPs per tenant

---

## 1. When to Use This Feature

### Multi-Tenant Deployments
- Each municipality/organization can bring its own IdP (Entra ID, Okta, Auth0, MobilityGuard, …)
- Secrets stay tenant-scoped and encrypted at rest (`tenants.federation_config` JSONB)
- Frontend automatically powers a tenant selector when multi-tenant mode is on

### Single-Tenant with API Management
Even with a single tenant, you may want `FEDERATION_PER_TENANT_ENABLED=true` if you prefer to:
- Manage OIDC settings via the sysadmin API instead of environment variables
- Change IdP configuration without restarting the backend
- Use the same API-based workflow as multi-tenant deployments

### Single-Tenant via Environment Variables (Default)
If you don't need the above, keep `FEDERATION_PER_TENANT_ENABLED=false` and use:
- `OIDC_DISCOVERY_ENDPOINT`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` in your `.env`
- Simpler setup, but requires backend restart to change OIDC settings

---

## 2. Architecture Snapshot

```
Browser ──► /auth/tenants ──► Tenant selector grid
        └─► /auth/initiate?tenant=examplea
Backend ──► Resolve tenant slug → federation_config → IdP discovery
        └─► /auth/callback exchanges code & validates JWT
```

Key components
1. **Database** – `tenants.slug`, `tenants.federation_config` (Fernet-encrypted client secrets)
2. **CredentialResolver** – deterministic lookup order: tenant config → global env → error
3. **Public endpoints** – `/auth/tenants`, `/auth/initiate`, `/auth/callback`
4. **Admin endpoints** – `/api/v1/sysadmin/tenants/{tenant_id}/federation[...]`
5. **Observability toggle** – `/api/v1/sysadmin/observability/oidc-debug/` for correlation-based triage

---

## 3. Implementation Checklist
1. Flip feature flag: `FEDERATION_PER_TENANT_ENABLED=true`
2. Ensure every tenant has a slug (backfill command provided in the setup guide)
3. Call `PUT /api/v1/sysadmin/tenants/{tenant_id}/federation` for each tenant (see [Multi-Tenant OIDC Setup Guide](./MULTITENANT_OIDC_SETUP_GUIDE.md))
4. Register the resulting redirect URI with the tenant’s IdP
5. Optional health probe: `POST /federation/test` (pulls OIDC discovery document and validates required fields)

Admin APIs (super API key required)

| Endpoint                                                | Purpose                            |
|---------------------------------------------------------|------------------------------------|
| `PUT /federation`                                       | Create or update IdP config        |
| `GET /federation`                                       | View masked config & metadata      |
| `DELETE /federation`                                    | Remove per-tenant IdP              |
| `POST /federation/test`                                 | Dry-run discovery + field checks   |

Secrets (`client_secret`) are encrypted; responses only return masked tails.

---

## 4. Debugging & Operations
- Use the runtime debug toggle to capture `[OIDC DEBUG] …` breadcrumbs. Full workflow documented in [Multi-Tenant OIDC Setup Guide](./MULTITENANT_OIDC_SETUP_GUIDE.md#3-runtime-debugging-correlation-id-based).
- Typical failure modes: domain mismatch, user assigned to wrong tenant, stale Redis cache (§3.2 table).
- Logs are JSON by default (`JSON_LOGS=true`). Toggle to plain text for local dev if desired.

---

## 5. Migration Notes (From Single-Tenant)
- Legacy `MOBILITYGUARD_*` env vars are still read; on startup they populate the generic `OIDC_*` settings. Plan to migrate before v3.0.
- Tenants without federation continue to use the global IdP.
- Frontend detects `FEDERATION_PER_TENANT_ENABLED` and shows the selector automatically; no manual UI work required.

---

## 6. Related Documents
- [Multi-Tenant OIDC Setup Guide](./MULTITENANT_OIDC_SETUP_GUIDE.md) – step-by-step provisioning & support playbook
- [Multi-Tenant Credentials](./MULTI_TENANT_CREDENTIALS.md) – per-tenant LLM API keys
- [Troubleshooting](./TROUBLESHOOTING.md) – incident catalogue
