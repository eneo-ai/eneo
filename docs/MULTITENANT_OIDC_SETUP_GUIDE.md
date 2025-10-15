# Multi-Tenant OIDC Setup Guide

**Last Updated**: 2025-10-15
**Target Audience**: System Administrators
**Prerequisites**: SUPER_API_KEY access, FEDERATION_PER_TENANT_ENABLED=true

---

## Overview

This guide shows how to configure multiple tenants with different OIDC identity providers in Eneo. Each tenant can have:
- **Their own IdP** (Azure AD, Okta, Keycloak, OneGate, etc.)
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

---

## Configuration Examples

### Example 1: Sundsvall (OneGate Proxy)

**Real Production Setup**

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
- `discovery_endpoint` = OneGate's OIDC discovery endpoint
- `allowed_domains` = Only allow @sundsvall.se emails

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
  "provider": "entra_id|okta|mobilityguard|generic_oidc",
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
| `provider` | IdP provider name | `"entra_id"`, `"okta"`, `"mobilityguard"` |
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

# 3. Check logs for errors
docker logs eneo-backend | grep "correlation_id"
```

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
- Validation happens at startup (application fails if HTTP)

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

---

## Summary

**Key Takeaways**:
1. Each tenant can have **different IdPs** (Azure AD, Okta, OneGate, etc.)
2. Use `canonical_public_origin` to specify **externally-reachable URL** (proxy or direct)
3. Register redirect URI in IdP: `{canonical_public_origin}/login/callback`
4. Use `allowed_domains` to restrict access by email domain
5. All secrets are **encrypted at rest** with Fernet
6. **HTTPS enforced** in production
7. Correlation IDs enable **end-to-end request tracing**

**Next Steps**:
1. Enable `FEDERATION_PER_TENANT_ENABLED=true`
2. Generate `ENCRYPTION_KEY` and strong `JWT_SECRET`
3. Configure federation for each tenant via API
4. Register redirect URIs in each IdP
5. Test authentication flow
6. Monitor logs with correlation IDs

---

**Need Help?**
- Review technical details: `docs/OIDC_FINAL_IMPLEMENTATION_SUMMARY.md`
- Check API reference above
- Search logs by correlation_id
- Contact support with correlation_id for faster resolution
