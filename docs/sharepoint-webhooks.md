# SharePoint Integration - Setup Guide

## Overview

Eneo can synchronize files from SharePoint automatically. When users add a SharePoint site to Eneo, files are imported and kept in sync.

## Prerequisites

- SharePoint Online subscription with Microsoft 365
- Azure AD tenant
- HTTPS domain for Eneo (webhooks require HTTPS)
- Firewall access to Microsoft Graph endpoints

## Step 1: Register Azure App

Register an application in Azure AD to get credentials for SharePoint access.

### In Azure Portal:

1. Go to **Azure Active Directory** → **App registrations**
2. Click **New registration**
3. Fill in:
   - **Name:** `Eneo SharePoint Integration`
   - **Supported account types:** `Accounts in this organizational directory only`
   - **Redirect URI:** `https://<your-eneo-domain>/api/v1/integrations/auth/callback/`
4. Click **Register**
5. Note the values:
   - **Application (client) ID** → goes in `SHAREPOINT_CLIENT_ID`
   - **Directory (tenant) ID** → goes in `SHAREPOINT_TENANT_ID`

### Add Client Secret:

1. Go to **Certificates & secrets**
2. Click **New client secret**
3. Set expiration (e.g., 24 months)
4. Copy the secret value → goes in `SHAREPOINT_CLIENT_SECRET`
5. **Important:** Save this immediately - you won't see it again!

### Add API Permissions:

1. Go to **API permissions**
2. Click **Add a permission**
3. Select **Microsoft Graph**
4. Select **Delegated permissions**
5. Add these permissions:
   - `Files.Read.All` - Read all SharePoint files
   - `Sites.Read.All` - Read all SharePoint sites
   - `offline_access` - Keep access even when user is offline
6. Click **Add permissions**
7. Click **Grant admin consent for [your organization]**

## Step 2: Environment Variables

Set these values in your `.env` file:

```env
# Azure/SharePoint Configuration
SHAREPOINT_CLIENT_ID=<your-application-id>
SHAREPOINT_CLIENT_SECRET=<your-client-secret>
SHAREPOINT_TENANT_ID=<your-tenant-id>

# OAuth Callback URL (must match Azure redirect URI)
OAUTH_CALLBACK_URL=https://<your-eneo-domain>/api/v1/integrations/auth/callback/

# Optional: Specific scopes (defaults to Files.Read)
SHAREPOINT_SCOPES=Files.Read.All Sites.Read.All offline_access

# Webhook validation token (random string, used internally)
SHAREPOINT_WEBHOOK_CLIENT_STATE=<random-secure-string>
```

**Example values:**
```env
SHAREPOINT_CLIENT_ID=a1b2c3d4-e5f6-7890-abcd-ef1234567890
SHAREPOINT_CLIENT_SECRET=abc~def.GhiJKlMnOpQrStUvWxYz1234567890
SHAREPOINT_TENANT_ID=12345678-1234-1234-1234-123456789012
OAUTH_CALLBACK_URL=https://eneo.example.com/api/v1/integrations/auth/callback/
SHAREPOINT_SCOPES=Files.Read.All Sites.Read.All offline_access
SHAREPOINT_WEBHOOK_CLIENT_STATE=your-secret-webhook-token
```

## Step 3: Configure Webhook (Optional - for Real-Time Sync)

If you want SharePoint files to update in Eneo automatically (in seconds instead of hours):

### In Azure Portal:

1. Go back to your **Eneo SharePoint Integration** app
2. Go to **API permissions**
3. Verify you have `Subscription.Read.All` permission added
4. If not, add it from **Microsoft Graph** → **Application permissions** (not delegated)

### In Eneo Configuration:

Webhook endpoint is automatically: `https://<your-eneo-domain>/api/v1/integrations/sharepoint/webhook/`

This must be:
- **HTTPS only** (not HTTP)
- **Publicly accessible** from the internet
- **Valid certificate** (no self-signed)

## Step 4: Test the Integration

### User-side:

1. Log in to Eneo
2. Go to **Integrations** → **My Integrations**
3. Click **Log in with Microsoft**
4. You should be redirected to Microsoft login
5. Grant permissions when asked
6. You should see a list of your SharePoint sites

### Admin-side:

Check logs for errors:
```bash
# If running with Docker
docker logs <container-id> | grep -i sharepoint

# Or check application logs for:
# - "Successfully authenticated with SharePoint"
# - "Failed to authenticate"
```

## How It Works

### User Imports SharePoint Site:

1. User selects a SharePoint site in Eneo
2. Eneo imports all files from that site
3. System creates a "sync log" recording what was imported
4. Files are now searchable in Eneo

### Files Stay in Sync:

**Option A: Automatic Webhook (Real-time) - Recommended**
- When user changes a file in SharePoint
- Microsoft notifies Eneo within seconds
- Eneo automatically updates that file
- User sees changes instantly
- **Requires:** Webhook configured (Step 3)

### Duplicate Protection:

The system prevents processing the same change twice if Microsoft sends duplicate notifications. This is automatic and invisible.

## Troubleshooting

### "Invalid client credentials" error

- Check `SHAREPOINT_CLIENT_ID` matches Azure app ID
- Check `SHAREPOINT_CLIENT_SECRET` is correct and not expired
- Check `SHAREPOINT_TENANT_ID` matches your Azure tenant

### "Redirect URI mismatch" error

- Make sure `OAUTH_CALLBACK_URL` in `.env` matches exactly what you set in Azure
- Both must use `https://`
- Both must end with `/api/v1/integrations/auth/callback/`

### "Permission denied" when accessing SharePoint

- Check Azure app has `Files.Read.All` and `Sites.Read.All` permissions
- Check "Grant admin consent" was clicked
- Wait a few minutes for permissions to propagate

### Files not updating automatically

- Check webhook endpoint is reachable: `curl https://<your-domain>/api/v1/integrations/sharepoint/webhook/`
- Check firewall allows incoming requests from Microsoft (IP ranges: https://microsoft.com/download/details.aspx?id=56519)
- Check `SHAREPOINT_WEBHOOK_CLIENT_STATE` is set in `.env`

### "Token expired after 90 days"

Microsoft requires users to log in again after 90 days of inactivity. This is normal:
1. User clicks "Log in with Microsoft" again
2. Quick re-authorization
3. Everything works again

No files are lost - just need to re-authenticate.

## Network Requirements

For webhooks to work, ensure:

- **Firewall:** Inbound HTTPS from Microsoft allowed
- **DNS:** Both internal and external DNS can resolve your domain
- **TLS:** Valid certificate (not self-signed)
- **URL:** HTTPS only, no HTTP

## Monitoring

Monitor these log messages to ensure everything works:

- ✅ `"Successfully authenticated with SharePoint"` - Auth works
- ✅ `"Webhook validation successful"` - Webhooks are working
- ✅ `"Sync completed: X files processed"` - Sync is working
- ⚠️ `"ChangeKey validation skipped duplicate"` - Duplicate notifications handled
- ❌ `"Token refresh failed"` - User needs to re-authenticate
- ❌ `"Webhook validation failed"` - Check webhook configuration

## Security Notes

- **Client Secret:** Treat like a password. Never share or commit to git.
- **Webhook Token:** Use a random, secure string
- **Permissions:** Only request necessary permissions (Files.Read is minimum)
- **HTTPS Only:** Webhooks must use HTTPS, never HTTP
- **User Data:** Eneo only reads files the authenticated user has access to
