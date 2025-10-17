# Multi-Tenant OIDC Setup Guide

**Last Updated**: 2025-10-16
**Target Audience**: System Administrators
**Prerequisites**: SUPER_API_KEY access, FEDERATION_PER_TENANT_ENABLED=true

---

## Overview

This guide shows how to configure multiple tenants with different OIDC identity providers in Eneo. Each tenant can have:
- **Their own IdP** (Azure AD, Okta, Auth0, Keycloak, MobilityGuard/OneGate, etc.)
- **Different public origins** (proxy URLs or direct URLs)
- **Email domain restrictions** (only allow specific domains per tenant)

**Important Terminology**:
- **`tenant_id`**: Unique identifier (UUID) used in API paths like `/api/v1/sysadmin/tenants/{tenant_id}/federation`
- **`tenant-slug`**: Human-readable identifier (string) used in public endpoints like `/auth/initiate?tenant=sundsvall`

---

## Quick Start

### 1. Enable Multi-Tenant Federation

**Backend `.env`**:
```bash
# Enable per-tenant federation
FEDERATION_PER_TENANT_ENABLED=true

# Encryption key for storing IdP client secrets
ENCRYPTION_KEY=<generate-with-fernet>

# JWT secret (32+ characters for production)
JWT_SECRET=<generate-strong-secret>
```

**Generate encryption key**:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Generate JWT secret**:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Optional: OIDC Safety Controls

**Backend `.env`** (optional tuning):
```bash
# [OPTIONAL] OIDC state JWT lifetime (default: 600 = 10 minutes)
# Limits time window for CSRF attacks
OIDC_STATE_TTL_SECONDS=600

# [OPTIONAL] Grace period for redirect URI changes (default: 600 = 10 minutes)
# Allows auth to complete if admin changes PUBLIC_ORIGIN during user login
OIDC_REDIRECT_GRACE_PERIOD_SECONDS=600

# [OPTIONAL] Strict redirect URI validation (default: true)
# Set to false ONLY if experiencing IdP-specific redirect issues
STRICT_OIDC_REDIRECT_VALIDATION=true
```

---

## Configuration Examples

### Example 1: Sundsvall (MobilityGuard/OneGate Proxy)

**Real Production Setup**

> **Note**: MobilityGuard and OneGate are the same platform. Use `"provider": "mobilityguard"` for both.

#### Step 1: Configure Federation for Sundsvall

```bash
PUT /api/v1/sysadmin/tenants/{sundsvall-tenant-id}/federation
Authorization: Bearer {SUPER_API_KEY}
Content-Type: application/json

{
  "provider": "mobilityguard",
  "canonical_public_origin": "https://m00-https-eneo-test.login.sundsvall.se",
  "discovery_endpoint": "https://m00-mg-local.login.sundsvall.se/mg-local/eneo/.well-known/openid-configuration",
  "client_id": "eneo",
  "client_secret": "<sundsvall-client-secret>",
  "allowed_domains": ["sundsvall.se"],
  "scopes": ["openid", "email", "profile"]
}
```

**Key Points**:
- `canonical_public_origin` = **externally-reachable URL** (the m00-https-* proxy URL)
- `discovery_endpoint` = MobilityGuard/OneGate OIDC discovery endpoint
- `allowed_domains` = Only allow @sundsvall.se emails
- MobilityGuard is OneGate's OIDC-compliant authentication platform

#### Step 2: Register in OneGate

**Redirect URI to register**:
```
https://m00-https-eneo-test.login.sundsvall.se/login/callback
```

#### Step 3: Test Login Flow

1. User navigates to: `https://m00-https-eneo-test.login.sundsvall.se`
2. Frontend calls: `GET /auth/initiate?tenant=sundsvall`
3. Backend returns authorization URL
4. User authenticates with OneGate/MobilityGuard
5. Callback to: `POST /auth/callback` with code & state
6. Backend issues JWT token

---

### Example 2: TenantB (Azure Entra ID - Direct URL)

**Scenario**: Stockholm municipality with Azure Entra ID, clean external URL

#### Step 1: Configure Federation for TenantB

```bash
PUT /api/v1/sysadmin/tenants/{tenantB-id}/federation
Authorization: Bearer {SUPER_API_KEY}
Content-Type: application/json

{
  "provider": "entra_id",
  "canonical_public_origin": "https://stockholm.eneo.se",
  "discovery_endpoint": "https://login.microsoftonline.com/{azure-tenant-id}/v2.0/.well-known/openid-configuration",
  "client_id": "{azure-client-id}",
  "client_secret": "{azure-client-secret}",
  "allowed_domains": ["stockholm.se"],
  "scopes": ["openid", "email", "profile"]
}
```

**Key Points**:
- `canonical_public_origin` = Direct public URL (no proxy)
- `discovery_endpoint` = Azure Entra ID discovery
- Replace `{azure-tenant-id}` with your Azure AD tenant ID

#### Step 2: Register in Azure AD

**App Registration**:
1. Go to Azure Portal → Azure Active Directory → App Registrations
2. Create new registration: "Eneo - Stockholm"
3. Set Redirect URI: `https://stockholm.eneo.se/login/callback`
4. Copy Client ID and Client Secret
5. API Permissions: `openid`, `email`, `profile`

#### Step 3: Test

```bash
# Get authorization URL
curl "https://stockholm.eneo.se/auth/initiate?tenant=stockholm"
```

---

### Example 3: TenantC (Okta)

**Scenario**: Gothenburg municipality with Okta

#### Step 1: Configure Federation for TenantC

```bash
PUT /api/v1/sysadmin/tenants/{tenantC-id}/federation
Authorization: Bearer {SUPER_API_KEY}
Content-Type: application/json

{
  "provider": "okta",
  "canonical_public_origin": "https://goteborg.eneo.se",
  "discovery_endpoint": "https://{your-okta-domain}.okta.com/.well-known/openid-configuration",
  "client_id": "{okta-client-id}",
  "client_secret": "{okta-client-secret}",
  "allowed_domains": ["goteborg.se", "gbg.se"],
  "scopes": ["openid", "email", "profile"]
}
```

**Key Points**:
- Multiple domains allowed: `["goteborg.se", "gbg.se"]`
- Okta discovery endpoint format

#### Step 2: Register in Okta

**Application Settings**:
1. Okta Admin Console → Applications → Create App Integration
2. Select "OIDC - OpenID Connect"
3. Application type: "Web Application"
4. Sign-in redirect URI: `https://goteborg.eneo.se/login/callback`
5. Copy Client ID and Client Secret

---

### Example 4: TenantD (Auth0)

**Scenario**: Malmö municipality with Auth0 as identity provider

#### Step 1: Configure Federation for TenantD

```bash
PUT /api/v1/sysadmin/tenants/{tenantD-id}/federation
Authorization: Bearer {SUPER_API_KEY}
Content-Type: application/json

{
  "provider": "auth0",
  "canonical_public_origin": "https://malmo.eneo.se",
  "discovery_endpoint": "https://{your-auth0-domain}.auth0.com/.well-known/openid-configuration",
  "client_id": "{auth0-client-id}",
  "client_secret": "{auth0-client-secret}",
  "allowed_domains": ["malmo.se"],
  "scopes": ["openid", "email", "profile"]
}
```

**Key Points**:
- Replace `{your-auth0-domain}` with your Auth0 tenant domain (e.g., `malmo-eneo.eu.auth0.com`)
- Auth0 discovery endpoint format: `https://{domain}.auth0.com/.well-known/openid-configuration`
- Auth0 automatically handles user management and MFA if configured

#### Step 2: Register in Auth0

**Application Settings**:
1. Auth0 Dashboard → Applications → Create Application
2. Select "Regular Web Application"
3. Name: "Eneo - Malmö"
4. Settings tab:
   - Allowed Callback URLs: `https://malmo.eneo.se/login/callback`
   - Allowed Logout URLs: `https://malmo.eneo.se/login`
   - Allowed Web Origins: `https://malmo.eneo.se`
5. Copy Domain, Client ID, and Client Secret
6. Save Changes

#### Step 3: Test

```bash
# Get authorization URL
curl "https://malmo.eneo.se/auth/initiate?tenant=malmo"

# Expected response includes Auth0 authorization URL
{
  "authorization_url": "https://malmo-eneo.eu.auth0.com/authorize?..."
}
```

---

## API Endpoints Reference

### System Admin Endpoints (Requires SUPER_API_KEY)

#### Configure Tenant Federation

```http
PUT /api/v1/sysadmin/tenants/{tenant_id}/federation
Authorization: Bearer {SUPER_API_KEY}
```

**Request Body**:
```json
{
  "provider": "entra_id|okta|auth0|mobilityguard|generic_oidc",
  "canonical_public_origin": "https://tenant.example.com",
  "discovery_endpoint": "https://idp.example.com/.well-known/openid-configuration",
  "client_id": "{client-id}",
  "client_secret": "{client-secret}",
  "allowed_domains": ["example.com"],
  "scopes": ["openid", "email", "profile"]
}
```

#### Get Tenant Federation Config

```http
GET /api/v1/sysadmin/tenants/{tenant_id}/federation
Authorization: Bearer {SUPER_API_KEY}
```

#### Delete Tenant Federation

```http
DELETE /api/v1/sysadmin/tenants/{tenant_id}/federation
Authorization: Bearer {SUPER_API_KEY}
```

#### List All Tenants (Get tenant_id)

To find a tenant's `{tenant_id}` for configuration:

```http
GET /api/v1/sysadmin/tenants
Authorization: Bearer {SUPER_API_KEY}
```

**Response**:
```json
{
  "tenants": [
    {
      "id": "123e4567-e89b-12d3-a456-426614174000",
      "slug": "sundsvall",
      "name": "Sundsvall Municipality",
      "display_name": "Sundsvall"
    },
    {
      "id": "987fcdeb-51a2-43f7-9876-543210fedcba",
      "slug": "stockholm",
      "name": "Stockholm Municipality",
      "display_name": "Stockholm"
    }
  ]
}
```

**Use the `id` field** as `{tenant_id}` in federation configuration endpoints.

---

### Public Endpoints (No Authentication)

#### List Available Tenants

```http
GET /auth/tenants
```

**Response**:
```json
{
  "tenants": [
    {
      "slug": "sundsvall",
      "name": "Sundsvall Municipality",
      "display_name": "Sundsvall"
    },
    {
      "slug": "stockholm",
      "name": "Stockholm Municipality",
      "display_name": "Stockholm"
    }
  ]
}
```

#### Initiate Authentication

```http
GET /auth/initiate?tenant={tenant-slug}
```

**Response**:
```json
{
  "authorization_url": "https://idp.example.com/authorize?client_id=...",
  "state": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Frontend Action**: Redirect user to `authorization_url`

#### Handle Callback

After the user authenticates with the IdP, they are redirected back to your application at the **frontend** route matching the registered redirect URI (`{canonical_public_origin}/login/callback`). The URL will contain `code` and `state` as query parameters.

**Two-Phase Callback Process**:

1. **IdP → Frontend**: IdP redirects user to frontend route (e.g., `/login/callback?code=...&state=...`)
2. **Frontend → Backend**: Frontend extracts `code` and `state`, then sends them to backend

**Frontend Implementation**:
```javascript
// Extract code and state from URL query parameters
const urlParams = new URLSearchParams(window.location.search);
const code = urlParams.get('code');
const state = urlParams.get('state');

// Send to backend
fetch('/auth/callback', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ code, state })
});
```

**Backend Endpoint**:
```http
POST /auth/callback
Content-Type: application/json

{
  "code": "{authorization-code-from-idp-redirect}",
  "state": "{state-from-idp-redirect}"
}
```

**Response**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Important**: The redirect URI you register in the IdP should point to your **frontend route** (e.g., `https://your-domain.com/login/callback`), not directly to the backend API endpoint.

---

## Configuration Fields

### Required Fields

| Field | Description | Example |
|-------|-------------|---------|
| `provider` | IdP provider name | `"entra_id"`, `"okta"`, `"auth0"`, `"mobilityguard"`, `"generic_oidc"` |
| `canonical_public_origin` | Externally-reachable URL | `"https://eneo.example.com"` |
| `client_id` | OAuth client ID from IdP | `"abc123..."` |
| `client_secret` | OAuth client secret from IdP | `"secret123..."` |

### Optional Fields

| Field | Description | Default |
|-------|-------------|---------|
| `discovery_endpoint` | OIDC discovery URL | Required if endpoints not explicit |
| `authorization_endpoint` | Direct auth endpoint | Fetched from discovery |
| `token_endpoint` | Direct token endpoint | Fetched from discovery |
| `jwks_uri` | JWKS endpoint | Fetched from discovery |
| `scopes` | OAuth scopes | `["openid", "email", "profile"]` |
| `allowed_domains` | Email domain whitelist | `[]` (allow all) |
| `claims_mapping` | Custom claim names | `{"email": "email"}` |
| `redirect_path` | Custom callback path | `"/login/callback"` |

---

## Testing

### Test Federation Config

```bash
# 1. Check tenant can be found
curl "https://your-domain.com/auth/tenants" | jq

# 2. Get authorization URL
curl "https://your-domain.com/auth/initiate?tenant=sundsvall" | jq

# 3. Check logs for errors (correlation_id included in all error responses)
docker logs eneo-backend | grep "correlation_id"

# 4. Test with correlation_id header tracking
curl -v "https://your-domain.com/auth/callback" \
  -H "Content-Type: application/json" \
  -d '{"code": "test", "state": "test"}' \
  2>&1 | grep -i "x-correlation-id"
```

**All error responses now include `X-Correlation-ID` header for debugging.**

### Common Issues

#### Issue: "Tenant not found or not configured for federation"
**Cause**: Tenant doesn't have `slug` set or federation_config missing
**Fix**:
```bash
# Ensure tenant has slug
PUT /api/v1/sysadmin/tenants/{tenant_id}
{"slug": "sundsvall"}

# Configure federation
PUT /api/v1/sysadmin/tenants/{tenant_id}/federation
{...}
```

#### Issue: "Redirect URI mismatch"
**Cause**: `canonical_public_origin` doesn't match registered redirect URI in IdP
**Fix**:
- Check IdP registration: `{canonical_public_origin}/login/callback`
- Verify canonical_public_origin is the **externally-reachable URL**

#### Issue: "Email domain not allowed"
**Cause**: User's email domain not in `allowed_domains` list
**Fix**:
```bash
# Update allowed domains
PUT /api/v1/sysadmin/tenants/{tenant_id}/federation
{"allowed_domains": ["example.com", "other-domain.com"]}
```

#### Issue: Logout redirect loop (auto-login after logout)
**Cause**: Single-tenant OIDC auto-redirects to IdP, ignoring logout message
**Symptoms**: After logout at `/login?message=logout`, user is immediately redirected back to IdP and logged in again
**Fix**: This was fixed in the latest version. Frontend now checks for query parameters before auto-redirecting. Update to latest version if experiencing this issue.

#### Issue: Loading spinner shown after logout
**Cause**: Login page shows loading screen instead of login button when query params present
**Symptoms**: Users see a spinning loader at `/login?message=logout` instead of the login form
**Fix**: This was fixed in the latest version. Update to latest if experiencing this issue.

---

## Security Considerations

### 1. Client Secret Storage
- Client secrets are **encrypted at rest** using Fernet encryption
- Encryption key must be set in `ENCRYPTION_KEY` env var
- Never commit encryption key to version control

### 2. Email Domain Validation
- Use `allowed_domains` to restrict which email domains can log in
- Empty array `[]` = allow all domains (not recommended)
- Example: `["sundsvall.se"]` = only @sundsvall.se emails

### 3. JWT Secret Strength
- `JWT_SECRET` must be **32+ characters** in production
- Used to sign state tokens and user session tokens
- Rotate regularly for security

### 4. HTTPS Enforcement
- `canonical_public_origin` **must be HTTPS** in production
- Exception: `http://localhost` and `http://127.0.0.1` allowed for development
- Validation happens at startup (application fails if HTTP in production)

---

## Migration Guide

### From Single-Tenant to Multi-Tenant

If you're currently using global OIDC config (`OIDC_DISCOVERY_ENDPOINT`, etc.):

**Step 1**: Enable federation per tenant
```bash
FEDERATION_PER_TENANT_ENABLED=true
```

**Step 2**: Configure your existing tenant
```bash
PUT /api/v1/sysadmin/tenants/{tenant_id}/federation
{
  "provider": "mobilityguard",
  "canonical_public_origin": "{your-current-PUBLIC_ORIGIN}",
  "discovery_endpoint": "{your-current-OIDC_DISCOVERY_ENDPOINT}",
  "client_id": "{your-current-OIDC_CLIENT_ID}",
  "client_secret": "{your-current-OIDC_CLIENT_SECRET}"
}
```

**Step 3**: (Optional) Keep global fallback for backward compatibility
- Keep `PUBLIC_ORIGIN`, `OIDC_*` env vars set
- Single-tenant endpoint `/login/openid-connect/mobilityguard` still works
- Multi-tenant endpoints `/auth/initiate`, `/auth/callback` use per-tenant config

---

## Monitoring

### Key Metrics to Track

```bash
# Successful logins per tenant
grep "Federated login successful" backend.log | grep "tenant_slug"

# Failed authentications
grep "correlation_id" backend.log | grep "error"

# Redirect URI mismatches (config drift)
grep "Redirect URI mismatch" backend.log
```

### Correlation ID Tracing

All authentication flows include `X-Correlation-ID` in error responses and logs:

```bash
# Trace a specific authentication flow
grep "abc123xyz" backend.log
```

When users report login issues, ask for the correlation ID from the error message.

---

## Advanced Configuration

### Custom Callback Path

**Default**: `/login/callback`

To use a custom path per tenant:
```json
{
  "canonical_public_origin": "https://tenant.example.com",
  "redirect_path": "/auth/oidc/callback"
}
```

**Redirect URI to register**: `https://tenant.example.com/auth/oidc/callback`

### Custom Claims Mapping

If your IdP uses different claim names:
```json
{
  "claims_mapping": {
    "email": "preferred_email",
    "name": "full_name"
  }
}
```

### Multiple Scopes

Request additional scopes from IdP:
```json
{
  "scopes": ["openid", "email", "profile", "groups", "roles"]
}
```

### Tenant-Specific LLM Credentials

**Strict Mode vs Single-Tenant Mode**

When `TENANT_CREDENTIALS_ENABLED=true`, each tenant must configure their own LLM API keys:

**Strict Mode (TENANT_CREDENTIALS_ENABLED=true)**:
- Tenant has configured key → tenant key is used
- Tenant has NO key → **ERROR** (no fallback to global)
- Tenant key is INVALID → **ERROR** (no fallback to global)
- Prevents billing confusion where tenant thinks they use their own key but actually use global

**Single-Tenant Mode (TENANT_CREDENTIALS_ENABLED=false)**:
- Tenant has configured key → tenant key is used
- Tenant has NO key → global key is used (fallback)
- Tenant key is INVALID → ERROR (no fallback to global)

**Configuration**:
```bash
# Backend .env
TENANT_CREDENTIALS_ENABLED=true
ENCRYPTION_KEY=<fernet-key>

# Configure tenant-specific OpenAI key
PUT /api/v1/sysadmin/tenants/{tenant_id}/credentials/openai
Authorization: Bearer {SUPER_API_KEY}
{
  "api_key": "sk-proj-tenant-specific-key"
}

# Configure tenant-specific Anthropic key
PUT /api/v1/sysadmin/tenants/{tenant_id}/credentials/anthropic
{
  "api_key": "sk-ant-api03-tenant-specific-key"
}
```

**Supported Providers**: `openai`, `anthropic`, `azure`, `berget`, `mistral`, `ovhcloud`, `vllm`

---

## Summary

**Key Takeaways**:
1. Each tenant can have **different IdPs** (Azure AD, Okta, Auth0, MobilityGuard/OneGate, etc.)
2. Use `canonical_public_origin` to specify **externally-reachable URL** (proxy or direct)
3. Register redirect URI in IdP: `{canonical_public_origin}/login/callback`
4. Use `allowed_domains` to restrict access by email domain
5. All secrets are **encrypted at rest** with Fernet encryption
6. **HTTPS enforced** in production (localhost exception for development)
7. **Correlation IDs** included in all error responses for debugging
8. **Strict mode** (`TENANT_CREDENTIALS_ENABLED=true`) prevents credential fallback to global keys
9. **Grace period** for PUBLIC_ORIGIN changes allows auth to complete during updates

**Next Steps**:
1. Enable `FEDERATION_PER_TENANT_ENABLED=true`
2. Generate `ENCRYPTION_KEY` and strong `JWT_SECRET` (32+ characters)
3. (Optional) Configure OIDC safety controls (state TTL, grace period)
4. (Optional) Enable strict mode with `TENANT_CREDENTIALS_ENABLED=true`
5. Configure federation for each tenant via API
6. Register redirect URIs in each IdP
7. Test authentication flow (check correlation_id in logs)
8. Monitor logs with correlation IDs for debugging

---

**Need Help?**
- Review technical details: `docs/OIDC_FINAL_IMPLEMENTATION_SUMMARY.md`
- Check API reference above
- Search logs by correlation_id
- Contact support with correlation_id for faster resolution
