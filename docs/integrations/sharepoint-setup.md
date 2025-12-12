# SharePoint Integration Setup

Quick setup guide for SharePoint integration in Eneo. For technical details, see [sharepoint-implementation.md](./technical/sharepoint-implementation.md).

## Prerequisites

- Azure AD tenant with admin access
- HTTPS domain for webhook callbacks
- PostgreSQL with pgvector extension
- Redis for webhook deduplication

## Authentication Methods

- **Personal spaces** → User OAuth (delegated permissions)
- **Org/Shared spaces** → Tenant App (application permissions) when configured

## Setup Steps

### 1. Generate Encryption Key (IF NOT ALREADY SET)

```bash
cd backend
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 2. Configure Environment

Add to `backend/.env`:

```env
ENCRYPTION_KEY=<from-step-1>
OAUTH_CALLBACK_URL=https://your-domain.com/api/v1/integrations/auth/callback/
SHAREPOINT_WEBHOOK_CLIENT_STATE=<random-32-char-string>
```

Generate webhook state: `openssl rand -hex 32`

### 3. Run Migrations

```bash
cd backend
uv run alembic upgrade head
```

### 4. Create Azure AD Application

**For Personal Spaces (User OAuth):**
1. Azure Portal → Azure AD → App registrations → New
2. Add **Delegated permissions**: `Files.Read.All`, `Sites.Read.All`, `offline_access`
3. Set Redirect URI to your `OAUTH_CALLBACK_URL`
4. Grant admin consent

**For Org/Shared Spaces (Tenant App):**
1. Azure Portal → Azure AD → App registrations → New
2. Add **Application permissions**: `Sites.Read.All`, `Files.Read.All`
3. Grant admin consent
4. Note: Client ID, Client Secret, Tenant Domain

### 5. Configure Tenant App

1. Navigate to **Admin → Integrations → Configure SharePoint App**
2. Enter:
   - Tenant Domain (e.g., `contoso.onmicrosoft.com`)
   - Client ID
   - Client Secret
3. Click **Test Connection** to verify
4. Click **Save**

### 6. Verify Setup

**Test Org Space:**
```bash
# Create org space
# Add SharePoint integration
# Check logs show: "Using tenant app authentication"
grep "tenant app" backend/logs/app.log
```

**Test Personal Space:**
```bash
# Create personal space
# Add SharePoint integration
# Complete OAuth flow
# Verify files sync
```

## Webhook Management

Webhooks expire every 24 hours. System auto-renews every 20 hours.

### List Active Subscriptions

```bash
GET /api/v1/admin/sharepoint/subscriptions
Authorization: Bearer <admin-token>
```

### Renew Expired Subscriptions

```bash
POST /api/v1/admin/sharepoint/subscriptions/renew-expired
Authorization: Bearer <admin-token>
```

Use after server downtime to restore webhook monitoring.

### Recreate Single Subscription

```bash
POST /api/v1/admin/sharepoint/subscriptions/{subscription_id}/recreate
Authorization: Bearer <admin-token>
```

## Common Issues

### Webhooks Not Working
- **Check:** Subscription status in Admin → Integrations → Manage webhooks
- **Fix:** Run bulk renewal endpoint
- **Verify:** HTTPS certificate valid, firewall allows Microsoft Graph

### Authentication Fails
- **Check:** Azure AD app credentials not expired
- **Fix:** Regenerate client secret in Azure Portal, update via Admin Panel
- **Verify:** Permissions granted and admin consent given

### Files Not Syncing
- **Check:** Logs for errors: `grep "SharePoint" backend/logs/app.log`
- **Fix:** Verify integration scope matches SharePoint structure
- **Verify:** User/tenant app has access to the target files

## Migration from .env to Admin Panel

Old environment variables are **deprecated**:
- `SHAREPOINT_CLIENT_ID` → Configure via Admin Panel
- `SHAREPOINT_CLIENT_SECRET` → Configure via Admin Panel

Existing integrations will continue working. New integrations must use Admin Panel configuration.
