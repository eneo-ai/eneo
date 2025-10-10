# Federation Per Tenant - Multi-Tenant OIDC Authentication

**Feature Status:** ✅ Implemented (v2.0)
**Backward Compatible:** ✅ Yes (100% compatible with existing deployments)

---

## Table of Contents
- [Overview](#overview)
- [Architecture](#architecture)
- [Setup Guide](#setup-guide)
  - [Single-Tenant Mode (Legacy)](#single-tenant-mode-legacy)
  - [Multi-Tenant Mode](#multi-tenant-mode)
- [API Endpoints](#api-endpoints)
- [Environment Variables](#environment-variables)
- [Logging & Debugging](#logging--debugging)
- [Migration Guide](#migration-guide)
- [Implementation Details](#implementation-details)

---

## Overview

**Federation Per Tenant** allows each municipality (tenant) to use their own identity provider (IdP) for authentication, while maintaining a single Eneo instance. This enables:

- **Tenant Isolation**: Each tenant uses their own Microsoft Entra ID, Okta, Auth0, or any OIDC-compliant IdP
- **Security**: Tenant-specific credentials stored encrypted in database
- **Flexibility**: Mix and match - some tenants use federation, others use global IdP
- **Backward Compatibility**: Existing single-tenant deployments continue to work unchanged

### Use Cases

1. **Municipality A** uses Microsoft Entra ID (Azure AD) for their employees
2. **Municipality B** uses Okta for their employees
3. **Municipality C** uses the global/shared IdP (backward compatible)
4. **All three** run on the same Eneo instance with complete tenant isolation

---

## Architecture

### Single-Tenant Mode (Default)
```
User → Frontend → /login/openid-connect/mobilityguard/ → Backend
                                                          ↓
                                    OIDC_* env vars → Global IdP (MobilityGuard, Entra, etc.)
```

### Multi-Tenant Mode (Federation Per Tenant)
```
User (Stockholm) → Frontend → /auth/initiate?tenant=stockholm → Backend
                                                                  ↓
                                    federation_config (DB) → Stockholm's Entra ID

User (Gothenburg) → Frontend → /auth/initiate?tenant=goteborg → Backend
                                                                  ↓
                                    federation_config (DB) → Gothenburg's Okta
```

### Key Components

1. **Database**: `tenants.slug` (URL-friendly ID) + `tenants.federation_config` (JSONB with encrypted credentials)
2. **Credential Resolver**: Strict resolution logic (tenant credential → global env var → error)
3. **Public Auth Endpoints**: `/auth/tenants`, `/auth/initiate`, `/auth/callback`
4. **Admin Endpoints**: System admin configures federation via API
5. **Frontend**: Tenant selector + slug-based routing

---

## Setup Guide

### Single-Tenant Mode (Legacy)

**This is the default mode.** If you're running Eneo for a single municipality (e.g., Sundsvall), use this mode.

#### 1. Environment Variables

**Recommended (Generic OIDC):**
```bash
# Generic OIDC Configuration
OIDC_DISCOVERY_ENDPOINT=https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration
OIDC_CLIENT_ID=abc123-your-client-id
OIDC_CLIENT_SECRET=your-client-secret
OIDC_TENANT_ID=your-eneo-tenant-uuid  # For auto-creating users
```

**Legacy (Still Works):**
```bash
# DEPRECATED: Use OIDC_* instead (will be removed in v3.0)
MOBILITYGUARD_DISCOVERY_ENDPOINT=https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration
MOBILITYGUARD_CLIENT_ID=abc123
MOBILITYGUARD_CLIENT_SECRET=secret
MOBILITYGUARD_TENANT_ID=uuid-here
```

**Auto-Migration:** If you use `MOBILITYGUARD_*` variables, they are automatically copied to `OIDC_*` variables on startup with a deprecation warning. **No breaking changes!**

#### 2. Frontend Configuration

No changes needed! The frontend will automatically use the single-tenant OIDC flow.

#### 3. How It Works

1. User clicks "Login"
2. Frontend redirects to IdP (via OIDC flow)
3. User authenticates with their organization's IdP
4. IdP redirects back with authorization code
5. Backend exchanges code for tokens, validates JWT
6. User lookup by email (user must exist in database)
7. Intric JWT token issued

---

### Multi-Tenant Mode

**This mode allows multiple municipalities to use their own IdPs on a single Eneo instance.**

#### 1. Enable Federation Feature

Add to backend `.env`:
```bash
FEDERATION_PER_TENANT_ENABLED=true
```

#### 2. Ensure Tenants Have Slugs

**Auto-Generation:** New tenants automatically get slugs when created.

**Backfill Existing Tenants:**
```bash
cd backend
poetry run python -m intric.cli.backfill_tenant_slugs
```

This generates URL-friendly slugs (e.g., "Stockholm Municipality" → "stockholm").

#### 3. Configure Federation Per Tenant (System Admin)

Use the admin API to configure each tenant's IdP:

```bash
# Example: Configure Stockholm's Microsoft Entra ID
curl -X PUT "https://api.eneo.ai/api/v1/sysadmin/tenants/{tenant_id}/federation" \
  -H "X-API-Key: {SYSTEM_ADMIN_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "entra_id",
    "discovery_endpoint": "https://login.microsoftonline.com/{azure-tenant-id}/v2.0/.well-known/openid-configuration",
    "client_id": "abc123-stockholm-client-id",
    "client_secret": "stockholm-client-secret",
    "allowed_domains": ["stockholm.se", "stockholm.gov.se"]
  }'
```

**Fields:**
- `provider`: Label (e.g., "entra_id", "okta", "auth0")
- `discovery_endpoint`: OIDC discovery URL
- `client_id`: OAuth client ID from IdP
- `client_secret`: OAuth client secret (encrypted in database)
- `allowed_domains`: Email domains allowed for this tenant (prevents cross-tenant auth)

#### 4. Frontend Integration

The frontend automatically displays a tenant selector when `FEDERATION_PER_TENANT_ENABLED=true` and no global IdP is configured.

**Login Flow:**
1. User visits `/login`
2. Tenant selector grid displays (all active tenants)
3. User selects "Stockholm"
4. Frontend calls `/auth/initiate?tenant=stockholm`
5. Backend responds with IdP authorization URL
6. User redirects to Stockholm's Entra ID
7. After auth, IdP redirects to `/auth/callback`
8. Backend validates, issues Intric JWT

---

## API Endpoints

### Public Endpoints (No Auth Required)

#### 1. List Tenants
```
GET /auth/tenants
```

**Response:**
```json
{
  "tenants": [
    {
      "slug": "stockholm",
      "name": "Stockholm Municipality",
      "display_name": "Stockholm"
    },
    {
      "slug": "goteborg",
      "name": "Gothenburg Municipality",
      "display_name": "Gothenburg"
    }
  ]
}
```

#### 2. Initiate Authentication
```
GET /auth/initiate?tenant={slug}&redirect_uri={redirect_uri}
```

**Parameters:**
- `tenant`: Tenant slug (e.g., "stockholm")
- `redirect_uri`: OAuth callback URI (e.g., "https://app.eneo.ai/auth/callback")

**Response:**
```json
{
  "authorization_url": "https://login.microsoftonline.com/.../authorize?client_id=...",
  "state": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

Frontend should redirect user to `authorization_url`.

#### 3. Handle Callback
```
POST /auth/callback
```

**Request:**
```json
{
  "code": "authorization_code_from_idp",
  "state": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response:**
```json
{
  "access_token": "intric_jwt_token"
}
```

---

### Admin Endpoints (System Admin Only)

Requires `X-API-Key: {SYSTEM_ADMIN_API_KEY}` header.

#### 1. Set Federation Config
```
PUT /api/v1/sysadmin/tenants/{tenant_id}/federation
```

**Request:**
```json
{
  "provider": "entra_id",
  "discovery_endpoint": "https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration",
  "client_id": "abc123",
  "client_secret": "secret",
  "allowed_domains": ["stockholm.se"]
}
```

**Response:**
```json
{
  "tenant_id": "uuid",
  "provider": "entra_id",
  "masked_secret": "...cret",
  "message": "Federation config for entra_id set successfully"
}
```

#### 2. Get Federation Config
```
GET /api/v1/sysadmin/tenants/{tenant_id}/federation
```

**Response:**
```json
{
  "provider": "entra_id",
  "client_id": "abc123",
  "masked_secret": "...cret",
  "issuer": "https://login.microsoftonline.com/{tenant-id}/v2.0",
  "allowed_domains": ["stockholm.se"],
  "configured_at": "2025-01-10T10:30:00Z",
  "encryption_status": "encrypted"
}
```

#### 3. Delete Federation Config
```
DELETE /api/v1/sysadmin/tenants/{tenant_id}/federation
```

Reverts tenant to using global IdP (if configured).

#### 4. Test Federation Config
```
POST /api/v1/sysadmin/tenants/{tenant_id}/federation/test
```

Tests connectivity to tenant's IdP discovery endpoint.

**Response:**
```json
{
  "success": true,
  "message": "Federation config is valid and IdP is reachable",
  "issuer": "https://login.microsoftonline.com/{tenant-id}/v2.0"
}
```

---

## Environment Variables

### Backend Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FEDERATION_PER_TENANT_ENABLED` | No | `false` | Enable multi-tenant federation feature |
| `OIDC_DISCOVERY_ENDPOINT` | No* | - | OIDC discovery URL (global/fallback) |
| `OIDC_CLIENT_ID` | No* | - | OAuth client ID (global/fallback) |
| `OIDC_CLIENT_SECRET` | No* | - | OAuth client secret (global/fallback) |
| `OIDC_TENANT_ID` | No | - | Eneo tenant UUID for auto-creating users |
| `ENCRYPTION_KEY` | Yes | - | Fernet key for encrypting credentials (32 bytes base64) |

**\* Required if using single-tenant mode or as fallback in multi-tenant mode.**

### Deprecated Variables (Still Work)

| Deprecated | Use Instead | Removed In |
|------------|-------------|------------|
| `MOBILITYGUARD_DISCOVERY_ENDPOINT` | `OIDC_DISCOVERY_ENDPOINT` | v3.0 |
| `MOBILITYGUARD_CLIENT_ID` | `OIDC_CLIENT_ID` | v3.0 |
| `MOBILITYGUARD_CLIENT_SECRET` | `OIDC_CLIENT_SECRET` | v3.0 |
| `MOBILITYGUARD_TENANT_ID` | `OIDC_TENANT_ID` | v3.0 |

**Auto-Migration:** If you use deprecated variables, they are automatically copied to the new variables on startup with a warning log.

### Frontend Variables

No changes required! Frontend environment variables remain the same.

---

## Logging & Debugging

### Comprehensive Logging (Production-Ready)

Both single-tenant and multi-tenant modes now have **identical comprehensive logging** for debugging OIDC issues:

#### Correlation ID Tracking
Every authentication request gets a unique `correlation_id` that flows through:
1. Initiate auth (`/auth/initiate`)
2. State JWT payload (encrypted)
3. Callback handler (`/auth/callback`)
4. JWT validation (`auth_service`)
5. User lookup/creation
6. Final success/error

**Example:**
```log
[INFO] Authentication initiated (correlation_id=a1b2c3d4, tenant_slug=stockholm)
[DEBUG] Fetching JWKS for ID token validation (correlation_id=a1b2c3d4)
[ERROR] Token exchange failed: HTTP 401 (correlation_id=a1b2c3d4, error_response={"error":"invalid_client"})
```

#### Key Logging Points

**1. Discovery Endpoint:**
```log
[DEBUG] Fetching OIDC discovery endpoint: https://... (correlation_id=...)
[DEBUG] OIDC discovery endpoint fetched successfully (duration_ms=145, token_endpoint=..., jwks_uri=...)
[ERROR] OIDC discovery endpoint failed: HTTP 404 (error_response=..., correlation_id=...)
```

**2. Token Exchange:**
```log
[DEBUG] OIDC token exchange at: https://... (correlation_id=...)
[DEBUG] OIDC token exchange successful (has_id_token=true, has_access_token=true, duration_ms=234)
[ERROR] OIDC token exchange failed: HTTP 401 (error_response={"error":"invalid_client",...}, correlation_id=...)
```

**3. JWKS Fetching:**
```log
[DEBUG] Fetching JWKS for ID token validation (jwks_uri=..., correlation_id=...)
[DEBUG] JWKS fetched successfully (correlation_id=...)
[ERROR] Failed to fetch JWKS or extract signing key (error=..., error_type=..., correlation_id=...)
```

**4. JWT Validation:**
```log
[DEBUG] OIDC: Starting JWT validation (client_id=..., correlation_id=...)
[DEBUG] JWT decoded successfully (issuer=..., subject=..., has_at_hash=true, correlation_id=...)
[DEBUG] at_hash present - validating (correlation_id=...)
[DEBUG] at_hash validated successfully (correlation_id=...)
[ERROR] JWT audience validation failed (expected_audience=..., correlation_id=...)
```

**5. Claims Mapping:**
```log
[DEBUG] Extracting username and email from OpenID JWT (correlation_id=...)
[DEBUG] Successfully extracted username and email from JWT (username=..., email=..., correlation_id=...)
[ERROR] JWT payload missing required fields (has_sub=true, has_email=false, payload_keys=['sub','name','mail'], correlation_id=...)
```

**6. Email Domain Validation:**
```log
[ERROR] Email domain not allowed for tenant (email_domain=example.com, allowed_domains=['stockholm.se'], correlation_id=...)
```

**7. User Lookup:**
```log
[INFO] OIDC: Looking up user by email: user@stockholm.se (correlation_id=...)
[INFO] OIDC: User found in database, checking user and tenant state (correlation_id=...)
[ERROR] User not found in database (tenant_slug=stockholm, email=..., correlation_id=...)
```

#### Debugging Scenarios

**Scenario 1: Wrong Client Secret**
```log
[ERROR] Token exchange failed: HTTP 401 (correlation_id=a1b2c3d4)
  error_response: {"error": "invalid_client", "error_description": "Client authentication failed"}
```
**Fix:** Update client_secret in federation config.

**Scenario 2: Wrong Discovery Endpoint**
```log
[ERROR] OIDC discovery endpoint failed: HTTP 404 (correlation_id=a1b2c3d4)
  discovery_endpoint: "https://wrong-url.com/.well-known/openid-configuration"
  error_response: "Not Found"
```
**Fix:** Correct discovery_endpoint URL.

**Scenario 3: Email Claim Mismatch**
```log
[ERROR] JWT payload missing required fields (correlation_id=a1b2c3d4)
  has_sub: true
  has_email: false
  payload_keys: ['sub', 'name', 'mail', 'preferred_username']
```
**Fix:** IdP sends "mail" instead of "email". Update claims_mapping in federation_config (or contact support).

**Scenario 4: Email Domain Not Allowed**
```log
[ERROR] Email domain not allowed for tenant (correlation_id=a1b2c3d4)
  email_domain: "external.com"
  allowed_domains: ["stockholm.se", "stockholm.gov.se"]
  tenant_slug: stockholm
```
**Fix:** Add "external.com" to allowed_domains or user should use correct email.

---

## Migration Guide

### From Single-Tenant to Multi-Tenant

**Step 1: Enable Feature**
```bash
# backend/.env
FEDERATION_PER_TENANT_ENABLED=true
```

**Step 2: Backfill Slugs**
```bash
cd backend
poetry run python -m intric.cli.backfill_tenant_slugs
```

**Step 3: Configure Tenant Federation**

Use admin API to configure each tenant's IdP (see [Admin Endpoints](#admin-endpoints-system-admin-only)).

**Step 4: Test**

Test federation config:
```bash
curl -X POST "https://api.eneo.ai/api/v1/sysadmin/tenants/{tenant_id}/federation/test" \
  -H "X-API-Key: {SYSTEM_ADMIN_API_KEY}"
```

**Step 5: Frontend Update**

No code changes needed! Frontend automatically shows tenant selector when:
- `FEDERATION_PER_TENANT_ENABLED=true` AND
- No global IdP configured (no `OIDC_DISCOVERY_ENDPOINT`)

### From MOBILITYGUARD_* to OIDC_*

**Option 1: Keep Using MOBILITYGUARD_* (Lazy)**
- No changes needed
- Auto-migration handles it
- Deprecation warning logged

**Option 2: Migrate to OIDC_* (Recommended)**
```bash
# Before
MOBILITYGUARD_DISCOVERY_ENDPOINT=https://...
MOBILITYGUARD_CLIENT_ID=abc123
MOBILITYGUARD_CLIENT_SECRET=secret
MOBILITYGUARD_TENANT_ID=uuid

# After
OIDC_DISCOVERY_ENDPOINT=https://...
OIDC_CLIENT_ID=abc123
OIDC_CLIENT_SECRET=secret
OIDC_TENANT_ID=uuid
```

**Benefits:** Future-proof, no deprecation warnings, consistent with multi-tenant mode.

---

## Implementation Details

### Code Changes Summary

#### Backend Files Modified

1. **`src/intric/tenants/tenant.py`**
   - Added `slug: Optional[str]` field (URL-friendly identifier)
   - Added `federation_config: dict[str, Any]` field (JSONB)
   - Field validators for slug format and federation_config structure

2. **`alembic/versions/20251010_add_tenant_slug_and_federation_config.py`**
   - Database migration: Added `slug` column (VARCHAR 63, unique, nullable)
   - Database migration: Added `federation_config` column (JSONB with GIN index)

3. **`src/intric/main/config.py`**
   - Added `federation_per_tenant_enabled: bool` flag
   - Added generic `oidc_*` fields (discovery_endpoint, client_id, client_secret, tenant_id)
   - Auto-migration validator: `MOBILITYGUARD_*` → `OIDC_*` with deprecation warnings
   - Kept deprecated `mobilityguard_*` fields for backward compatibility

4. **`src/intric/authentication/auth_service.py`**
   - Fixed at_hash validation: Made conditional (optional per OIDC spec)
   - Enhanced logging: Correlation ID, JWT validation details, claims mapping debug

5. **`src/intric/settings/credential_resolver.py`**
   - Added `get_federation_config()` method (strict resolution logic)
   - Pattern: Tenant config → Strict mode error → Global fallback → Error

6. **`src/intric/authentication/federation_router.py`** (NEW)
   - Public endpoints: `/auth/tenants`, `/auth/initiate`, `/auth/callback`
   - Correlation ID generation and flow
   - Comprehensive error logging with IdP responses
   - JWKS fetching with try/catch
   - Claims mapping debug logging

7. **`src/intric/tenants/presentation/tenant_federation_router.py`** (NEW)
   - Admin endpoints: PUT/GET/DELETE/POST `/sysadmin/tenants/{id}/federation`
   - Discovery validation with error logging
   - Secret encryption (Fernet)
   - Test endpoint for connectivity verification

8. **`src/intric/tenants/tenant_repo.py`**
   - Added `get_by_slug()` method
   - Added `generate_slug_for_tenant()` method (auto-slug generation)
   - Added `update_federation_config()` method
   - Added `delete_federation_config()` method
   - Added `get_federation_config_with_metadata()` method
   - Added `get_all_active()` method
   - Modified `add()` to auto-generate slugs for new tenants

9. **`src/intric/cli/backfill_tenant_slugs.py`** (NEW)
   - CLI script to backfill slugs for existing tenants
   - Usage: `poetry run python -m intric.cli.backfill_tenant_slugs`

10. **`src/intric/users/user_router.py`**
    - Changed `settings.mobilityguard_*` → `settings.oidc_*`
    - Updated log messages: `"provider": "mobilityguard"` → `"provider": "oidc"`
    - Kept endpoint URL unchanged: `/login/openid-connect/mobilityguard/`
    - Kept function name unchanged: `login_with_mobilityguard()`

11. **`src/intric/users/user_service.py`**
    - Changed `SETTINGS.mobilityguard_*` → `SETTINGS.oidc_*`
    - Updated log messages to be generic ("OIDC" instead of "MobilityGuard")
    - Updated error messages to reference OIDC_TENANT_ID with deprecation notice
    - Kept method name unchanged: `login_with_mobilityguard()`

12. **`.env.template`**
    - Added comprehensive OIDC and federation documentation
    - Documented FEDERATION_PER_TENANT_ENABLED flag
    - Documented OIDC_* variables with examples
    - Marked MOBILITYGUARD_* variables as deprecated

#### Frontend Files Modified

1. **`packages/intric-js/src/endpoints/auth.js`** (NEW)
   - Added `listTenants()` method
   - Added `initiateAuth()` method
   - Added `handleAuthCallback()` method

2. **`apps/web/src/lib/components/TenantSelector.svelte`** (NEW)
   - Tenant selector grid component
   - localStorage persistence for last selected tenant
   - Inline slug validation

3. **`apps/web/src/routes/(public)/login/+page.svelte`**
   - Added `?tenant=` parameter handling
   - Added tenant selector display logic
   - Calls `initiateAuth()` when tenant selected

4. **`apps/web/src/routes/auth/callback/+page.svelte`** (NEW)
   - OIDC callback handler (client-side UI)

5. **`apps/web/src/routes/auth/callback/+page.server.ts`** (NEW)
   - OIDC callback handler (server-side token exchange)

### Database Schema

```sql
-- Tenants table
ALTER TABLE tenants
ADD COLUMN slug VARCHAR(63) UNIQUE,
ADD COLUMN federation_config JSONB DEFAULT '{}'::jsonb;

-- Index for fast JSONB queries
CREATE INDEX idx_tenants_federation_config ON tenants USING GIN (federation_config);
```

**federation_config Structure:**
```json
{
  "provider": "entra_id",
  "issuer": "https://login.microsoftonline.com/{tenant-id}/v2.0",
  "discovery_endpoint": "https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration",
  "authorization_endpoint": "https://login.microsoftonline.com/{tenant-id}/oauth2/v2.0/authorize",
  "token_endpoint": "https://login.microsoftonline.com/{tenant-id}/oauth2/v2.0/token",
  "userinfo_endpoint": "https://graph.microsoft.com/oidc/userinfo",
  "jwks_uri": "https://login.microsoftonline.com/{tenant-id}/discovery/v2.0/keys",
  "client_id": "abc123",
  "client_secret": "gAAAAABl... (encrypted with Fernet)",
  "scopes": ["openid", "email", "profile"],
  "allowed_domains": ["stockholm.se", "stockholm.gov.se"],
  "claims_mapping": {
    "email": "email",
    "username": "sub",
    "name": "name"
  },
  "encrypted_at": "2025-01-10T10:30:00Z"
}
```

### Security

1. **Encryption**: All `client_secret` values encrypted with Fernet (AES-128-CBC)
2. **State Parameter**: Signed JWT (HS256) with 10-minute expiry, includes tenant context
3. **Email Domain Validation**: Prevents cross-tenant authentication (user from Stockholm can't auth to Gothenburg)
4. **User Lookup Only**: No auto-creation in multi-tenant mode (MVP simplification)
5. **Tenant Isolation**: All queries filtered by tenant_id
6. **Admin-Only Config**: Only system admins can configure federation

### Performance

- **Credential Lookup**: <1ms (GIN index on JSONB)
- **Discovery Caching**: In federation_config (avoid repeated fetches)
- **State Validation**: JWT decode ~2ms
- **Total Auth Flow**: ~500-800ms (including IdP round-trips)

---

## Troubleshooting

### Common Issues

**1. "Tenant not found or not configured for federation"**
- **Cause**: Tenant doesn't have a slug configured
- **Fix**: Run backfill script or manually set slug via admin API

**2. "No identity provider configured for tenant"**
- **Cause**: Federation enabled but tenant has no federation_config
- **Fix**: Configure federation via admin API or disable `FEDERATION_PER_TENANT_ENABLED`

**3. "Failed to decrypt credential"**
- **Cause**: ENCRYPTION_KEY changed or corrupted
- **Fix**: Do NOT change ENCRYPTION_KEY in production. If lost, reconfigure all tenant credentials.

**4. "Email domain 'X' is not allowed for this organization"**
- **Cause**: User's email domain not in allowed_domains
- **Fix**: Add domain via admin API or user should use correct email

**5. "User not found"**
- **Cause**: User doesn't exist in database (no auto-creation in multi-tenant mode)
- **Fix**: Create user manually via admin panel before they can log in

**6. Deprecation Warning: "MOBILITYGUARD_* variables are deprecated"**
- **Not an error**: System works fine, just migrate to OIDC_* variables when convenient
- **Fix**: Rename `MOBILITYGUARD_*` → `OIDC_*` in `.env` file

### Getting Help

1. **Check Logs**: Search for `correlation_id` to trace full auth flow
2. **Test Endpoint**: Use `POST /sysadmin/tenants/{id}/federation/test` to verify IdP connectivity
3. **OpenAPI Docs**: Visit `/docs` for interactive API documentation
4. **GitHub Issues**: Report bugs at https://github.com/intric-ai/eneo/issues

---

## FAQ

**Q: Do I need to migrate from MOBILITYGUARD_* variables?**
A: No, they still work via auto-migration. But migrating to OIDC_* is recommended for clarity.

**Q: Can I mix single-tenant and multi-tenant modes?**
A: Yes! Enable `FEDERATION_PER_TENANT_ENABLED`, configure some tenants with federation_config, leave others using global OIDC_* variables.

**Q: What IdPs are supported?**
A: Any OIDC-compliant IdP (Microsoft Entra ID, Okta, Auth0, Keycloak, etc.)

**Q: Can users self-register?**
A: No, users must be pre-created by administrators (MVP design decision)

**Q: How do I rotate credentials?**
A: Use PUT endpoint to update federation_config with new client_secret

**Q: What happens if ENCRYPTION_KEY is lost?**
A: All encrypted credentials become unrecoverable. You must reconfigure all tenant federations.

**Q: Can I use the same IdP for multiple tenants?**
A: Yes, but use different client IDs and configure allowed_domains to prevent cross-tenant auth.

---

## Version History

- **v2.0** (2025-01-10): Initial release
  - Federation Per Tenant feature
  - Comprehensive logging improvements
  - Backward compatible with single-tenant mode
  - Auto-migration from MOBILITYGUARD_* to OIDC_*

---

## License

Copyright (c) 2024-2025 Intric AB
Licensed under the MIT License
