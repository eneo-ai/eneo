# Multi-Tenant LLM Credentials Guide

Enable tenant-specific API credentials for LLM providers in Eneo AI platform.

## Overview

**What this enables:**
- Each municipality configures their own LLM provider API keys
- Dedicated infrastructure per tenant (separate VLLM/Azure endpoints)
- Regional infrastructure sharing (multiple tenants, same endpoint)
- Strict billing isolation (no cross-tenant credential usage)

**When to use:**
- ✅ Multi-municipality SaaS deployment (each needs own keys)
- ✅ Mixed infrastructure (some tenants on-prem, others cloud)
- ✅ GDPR compliance (separate processing infrastructure)
- ❌ Single organization with shared infrastructure (use single-tenant mode)

---

## Deployment Modes

### Single-Tenant Mode (Default)
**Use when:** All tenants share same infrastructure and billing.

```bash
# .env
TENANT_CREDENTIALS_ENABLED=false
OPENAI_API_KEY=sk-proj-shared-key
VLLM_MODEL_URL=http://shared-vllm:8000
```

**Behavior:** All tenants automatically use global .env credentials.

### Multi-Tenant Mode (Strict)
**Use when:** Each tenant needs their own credentials and infrastructure.

```bash
# .env
TENANT_CREDENTIALS_ENABLED=true
ENCRYPTION_KEY=<44-character-base64-key>
```

**Behavior:** Each tenant MUST configure credentials explicitly. No fallback to global.

---

## Quick Setup (Multi-Tenant)

### Step 1: Generate Encryption Key
```bash
cd backend
poetry run python -m intric.cli.generate_encryption_key
```

**Output:**
```
Generated encryption key: FNVdDyfq0lBPAvjz_WS-9PB2UQzkbqCnwuA4KU9UbPU=

Add to .env:
ENCRYPTION_KEY=FNVdDyfq0lBPAvjz_WS-9PB2UQzkbqCnwuA4KU9UbPU=
```

⚠️ **Backup this key securely** - cannot decrypt credentials without it.

### Step 2: Enable Multi-Tenant Mode
```bash
# .env
TENANT_CREDENTIALS_ENABLED=true
ENCRYPTION_KEY=FNVdDyfq0lBPAvjz_WS-9PB2UQzkbqCnwuA4KU9UbPU=
```

### Step 3: Restart Backend
```bash
poetry run start
```

### Step 4: Configure Tenant Credentials
```bash
# Get INTRIC_SUPER_API_KEY from .env
export API_KEY="your-super-api-key"

# Configure Stockholm municipality
curl -X PUT http://localhost:8123/api/v1/sysadmin/tenants/{stockholm_id}/credentials/openai \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"api_key": "sk-stockholm-api-key"}'

# Configure Göteborg with dedicated VLLM
curl -X PUT http://localhost:8123/api/v1/sysadmin/tenants/{goteborg_id}/credentials/vllm \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"api_key": "goteborg-vllm-key", "endpoint": "http://goteborg-vllm.internal:8000"}'
```

### Step 5: Verify Configuration
```bash
# List credentials (keys are masked)
curl -X GET http://localhost:8123/api/v1/sysadmin/tenants/{tenant_id}/credentials \
  -H "X-API-Key: $API_KEY"

# Response:
{
  "credentials": [
    {
      "provider": "openai",
      "masked_key": "...key9",
      "encryption_status": "encrypted",
      "configured_at": "2025-10-08T10:00:00Z"
    }
  ]
}
```

---

## Supported Providers

| Provider | Credential Fields | Model Types | Example Use Case |
|----------|-------------------|-------------|------------------|
| `openai` | api_key | GPT-4, GPT-3.5, embeddings | OpenAI-hosted models |
| `anthropic` | api_key | Claude 3.x | Anthropic-hosted models |
| `azure` | api_key, endpoint, api_version, deployment_name | GPT-4, embeddings (Azure) | Sweden data residency |
| `vllm` | api_key, endpoint | Llama, Mistral, embeddings | On-prem GPU infrastructure |
| `berget` | api_key | E5 embeddings | Swedish-hosted models |
| `mistral` | api_key | Mistral Large | Mistral AI-hosted |
| `ovhcloud` | api_key | Llama 3.3 | EU-hosted models |

---

## Configuration Examples

### OpenAI (Simple)
```bash
PUT /api/v1/sysadmin/tenants/{tenant_id}/credentials/openai
```
```json
{
  "api_key": "sk-proj-abc123xyz789..."
}
```

**What you get:**
- ✅ GPT models (4, 4o, 3.5-turbo)
- ✅ OpenAI embeddings (text-embedding-3-small/large)
- ✅ Hosted by OpenAI (USA)

### Azure OpenAI (Complex - All 4 fields required)
```bash
PUT /api/v1/sysadmin/tenants/{tenant_id}/credentials/azure
```
```json
{
  "api_key": "abc123def456...",
  "endpoint": "https://sweden-openai.openai.azure.com",
  "api_version": "2024-02-15-preview",
  "deployment_name": "gpt-4"
}
```

**What you get:**
- ✅ GPT models via Azure (Sweden data residency)
- ✅ Azure embeddings (text-embedding-3-large-azure)
- ✅ Tenant-specific Azure resource (billing isolation)

**Notes:**
- Get from Azure Portal → Azure OpenAI Service → Keys and Endpoint
- `deployment_name` must match your Azure deployment
- Each tenant can use different Azure resources

### VLLM Self-Hosted (Flexible)

**Option A: Tenant uses shared regional VLLM**
```bash
PUT /api/v1/sysadmin/tenants/{tenant_id}/credentials/vllm
```
```json
{
  "api_key": "regional-secret",
  "endpoint": "http://stockholm-region-vllm:8000"
}
```

**Option B: Tenant uses dedicated on-prem GPU**
```json
{
  "api_key": "tenant-onprem-secret",
  "endpoint": "https://tenant.municipality.se:8000"
}
```

**Model configuration required** (ai_models.yml):
```yaml
- name: 'llama-3.1-70b'
  family: 'vllm'
  litellm_model_name: 'vllm/meta-llama/Meta-Llama-3.1-70B-Instruct'
  # litellm_model_name enables tenant credential support
```

⚠️ **Important:** Legacy VLLM models (without `litellm_model_name`) only use global .env configuration.

---

## How It Works

### Credential Resolution Flow

```
1. User makes LLM request (completion or embedding)
   ↓
2. System checks: TENANT_CREDENTIALS_ENABLED?
   ↓
3a. TRUE (Multi-Tenant):
    - Check tenant.api_credentials for provider
    - If exists: Use tenant credential (decrypt if needed)
    - If missing: ERROR - "Configure credential via API"
    - NO fallback to global .env
   ↓
3b. FALSE (Single-Tenant):
    - All tenants use global .env credentials
    - No per-tenant configuration needed
   ↓
4. Call LLM provider with credential
```

### Database Storage

**Table:** `tenants` (existing table)
**Column:** `api_credentials` (JSONB type, added via migration)
**Default:** `{}` (empty JSON object for new/existing tenants)
**Index:** GIN index on JSONB for fast provider lookups (<1ms)

**How it's stored:**
- Single JSONB column holds ALL provider credentials for a tenant
- Provider name is the top-level key (`"openai"`, `"azure"`, `"vllm"`)
- Each provider's value is a dict with `api_key` + optional fields
- Only `api_key` is encrypted, other fields (endpoint, api_version) are plain text
- PostgreSQL JSONB operators enable efficient updates (don't reload entire object)

**Example row in database:**
```
tenants table:
id: abc-123-tenant-uuid
name: "Stockholm Municipality"
api_credentials: {
  "openai": {
    "api_key": "enc:fernet:v1:gAAAAABm..."  ← Encrypted
  },
  "azure": {
    "api_key": "enc:fernet:v1:gAAAAABm...",  ← Encrypted
    "endpoint": "https://sweden.openai.azure.com",  ← Plain text
    "api_version": "2024-02-15-preview",  ← Plain text
    "deployment_name": "gpt-4"  ← Plain text
  },
  "vllm": {
    "api_key": "enc:fernet:v1:gAAAAABm...",  ← Encrypted
    "endpoint": "http://stockholm-vllm:8000"  ← Plain text
  }
}
```

**Why JSONB:**
- Flexible schema (add providers without migrations)
- Fast queries with GIN index
- Atomic updates using PostgreSQL's `jsonb_set` function
- Supports complex nested structures (Azure's 4 fields)

---

## API Reference

### Set/Update Credential
```http
PUT /api/v1/sysadmin/tenants/{tenant_id}/credentials/{provider}
```

**Headers:**
- `X-API-Key`: Your `INTRIC_SUPER_API_KEY`
- `Content-Type`: `application/json`

**Body:**
```json
{
  "api_key": "required-for-all-providers",
  "endpoint": "optional-for-vllm-azure",
  "api_version": "required-for-azure-only",
  "deployment_name": "required-for-azure-only"
}
```

**Response:**
```json
{
  "tenant_id": "uuid",
  "provider": "openai",
  "masked_key": "...xyz9",
  "message": "API credential for openai set successfully"
}
```

### List Credentials
```http
GET /api/v1/sysadmin/tenants/{tenant_id}/credentials
```

**Response:**
```json
{
  "credentials": [
    {
      "provider": "openai",
      "masked_key": "...xyz9",
      "encryption_status": "encrypted",
      "configured_at": "2025-10-08T10:00:00Z",
      "config": {}
    },
    {
      "provider": "azure",
      "masked_key": "...abc3",
      "encryption_status": "encrypted",
      "configured_at": "2025-10-08T11:30:00Z",
      "config": {
        "endpoint": "https://sweden.openai.azure.com",
        "api_version": "2024-02-15-preview",
        "deployment_name": "gpt-4"
      }
    }
  ]
}
```

### Delete Credential
```http
DELETE /api/v1/sysadmin/tenants/{tenant_id}/credentials/{provider}
```

**Response:**
```json
{
  "tenant_id": "uuid",
  "provider": "openai",
  "message": "API credential for openai deleted successfully"
}
```

---

## Common Patterns

### Pattern 1: Regional VLLM Sharing
**Scenario:** Multiple municipalities share regional GPU infrastructure.

```bash
# Configure same regional VLLM for Stockholm municipalities
for tenant_id in stockholm1 stockholm2 stockholm3; do
  curl -X PUT /api/v1/sysadmin/tenants/$tenant_id/credentials/vllm \
    -H "X-API-Key: $API_KEY" \
    -d '{"api_key": "stockholm-regional", "endpoint": "http://stockholm-vllm:8000"}'
done

# Separate Göteborg region
curl -X PUT /api/v1/sysadmin/tenants/goteborg1/credentials/vllm \
  -H "X-API-Key: $API_KEY" \
  -d '{"api_key": "goteborg-regional", "endpoint": "http://goteborg-vllm:8000"}'
```

**Result:**
- Stockholm municipalities: Share Stockholm VLLM infrastructure
- Göteborg municipality: Uses Göteborg VLLM infrastructure
- Geographic data residency maintained

### Pattern 2: Mixed Cloud Providers
**Scenario:** Different tenants use different LLM providers.

```bash
# Tenant A: Uses OpenAI (international, cost-effective)
PUT /tenants/tenant_a/credentials/openai
{"api_key": "sk-tenant-a-key"}

# Tenant B: Uses Azure (Sweden data residency required)
PUT /tenants/tenant_b/credentials/azure
{"api_key": "azure-key", "endpoint": "https://sweden.openai.azure.com", ...}

# Tenant C: Uses on-prem VLLM (high security requirements)
PUT /tenants/tenant_c/credentials/vllm
{"api_key": "onprem-key", "endpoint": "https://tenant-c.municipality.se:8000"}
```

### Pattern 3: Dedicated Infrastructure per Tenant
**Scenario:** Large municipalities with their own Azure subscriptions.

```bash
# Each tenant has their own Azure OpenAI resource
PUT /tenants/stockholm/credentials/azure
{
  "api_key": "stockholm-azure-key",
  "endpoint": "https://stockholm.openai.azure.com",
  "api_version": "2024-02-15-preview",
  "deployment_name": "gpt-4-stockholm"
}

PUT /tenants/goteborg/credentials/azure
{
  "api_key": "goteborg-azure-key",
  "endpoint": "https://goteborg.openai.azure.com",
  "api_version": "2024-02-15-preview",
  "deployment_name": "gpt-4-goteborg"
}
```

**Result:** Complete billing and infrastructure isolation.

---

## Security

### Encryption at Rest
- **Algorithm:** Fernet (AES-128-CBC + HMAC SHA256)
- **What's encrypted:** Only `api_key` fields
- **What's NOT encrypted:** Endpoints, versions (infrastructure addresses, not secrets)
- **Key storage:** `ENCRYPTION_KEY` environment variable

**Encryption format in database:**
```
enc:fernet:v1:gAAAAABm2xYz1234567890abcdef...
│   │      │  └─ Encrypted payload (base64)
│   │      └─ Version (v1 for future algorithm upgrades)
│   └─ Algorithm identifier (fernet)
└─ Prefix (indicates encrypted value)
```

### Credential Masking
- **API responses:** Show last 4 characters only (`"...xyz9"`)
- **Logs:** Show last 4 characters only (`"...xyz9"`)
- **Database:** Full encrypted value stored
- **Memory:** Decrypted only during LLM API call, discarded after

### Access Control
- **Endpoints:** Require `INTRIC_SUPER_API_KEY` (sysadmin only)
- **Planned:** Individual sysadmin accounts with audit trail (future)
- **Current limitation:** All sysadmins share same API key

---

## Strict Mode Behavior

**When `TENANT_CREDENTIALS_ENABLED=true`:**

| Situation | Behavior | Reason |
|-----------|----------|--------|
| Tenant configured credential | ✅ Uses tenant credential | Expected behavior |
| Tenant has NO credential | ❌ Error: "Configure via API" | Forces explicit configuration |
| Tenant credential INVALID | ❌ Error: "Invalid key" | No silent fallback |
| Tenant credential MISSING field | ❌ Returns None/Error | No cross-tenant contamination |

**Why no fallback?**
```
Bad scenario (if fallback existed):
1. Sundsvall configures their own VLLM endpoint
2. Admin typo in configuration → invalid endpoint
3. System silently falls back to Eneo's shared VLLM
4. Sundsvall thinks they use their GPU, actually using Eneo's
5. Billing confusion + potential data residency violation
```

**Good scenario (current strict mode):**
```
1. Sundsvall configures VLLM endpoint
2. Admin typo in configuration
3. System raises error immediately: "Invalid endpoint"
4. Admin fixes typo
5. Clear which infrastructure is being used
```

---

## Model Configuration (ai_models.yml)

### For Tenant Credential Support

**Models MUST have `litellm_model_name` to support tenant credentials:**

```yaml
# ✅ Supports tenant credentials
- name: 'gpt-5-azure'
  family: 'azure'
  litellm_model_name: 'azure/gpt-5'  # ← Enables tenant support

# ✅ Supports tenant credentials
- name: 'llama-3.1-vllm'
  family: 'vllm'
  litellm_model_name: 'vllm/meta-llama/Meta-Llama-3.1-70B'  # ← Enables tenant support

# ❌ Only uses global .env (legacy)
- name: 'old-vllm-model'
  family: 'vllm'
  # NO litellm_model_name - uses legacy adapter
```

**Rule:** `litellm_model_name` present = tenant-capable, absent = global-only

### Provider Detection

LiteLLM model names use `provider/model` format:
- `azure/gpt-5` → Looks up `credentials/azure`
- `vllm/llama-3.1-70b` → Looks up `credentials/vllm`
- `berget/multilingual-e5` → Looks up `credentials/berget`

---

## FAQ

### Setup Questions

**Q: Do I need multi-tenant mode for single organization?**
A: No. Use `TENANT_CREDENTIALS_ENABLED=false` for shared infrastructure.

**Q: Can I enable multi-tenant mode without configuring all tenants immediately?**
A: No. When enabled, ALL tenants must have credentials configured before they can use LLM features.

**Q: Can some tenants use OpenAI while others use Azure?**
A: Yes. Each tenant configures only the providers they need.

**Q: Can two tenants share the same API key?**
A: Yes. Configure the same credential for both tenants explicitly.

### Credentials Questions

**Q: What happens if tenant has no credential in multi-tenant mode?**
A: Error raised: "No API key configured for provider X. Please configure via API." No silent fallback.

**Q: What happens if tenant credential is invalid?**
A: Error raised immediately. No fallback to global to prevent billing confusion.

**Q: Can I use global .env keys as fallback?**
A: Only in single-tenant mode (`TENANT_CREDENTIALS_ENABLED=false`). In multi-tenant mode, no fallback.

**Q: How do I share infrastructure across 3 tenants?**
A: Configure the same credentials (api_key + endpoint) for all 3 tenants explicitly.

### Embedding Questions

**Q: Do embedding models use tenant credentials?**
A: Yes. Both completion and embedding models use the same credential system.

**Q: Can I use Berget embeddings for one tenant and Azure for another?**
A: Yes. Configure different credentials per tenant.

**Q: Can I host VLLM embedding model on-prem for one tenant only?**
A: Yes. Configure VLLM credential with on-prem endpoint for that tenant. Other tenants use different providers.

### Security Questions

**Q: Are API keys encrypted in the database?**
A: Yes, using Fernet (AES-128-CBC + HMAC) when `TENANT_CREDENTIALS_ENABLED=true`.

**Q: What if I lose the ENCRYPTION_KEY?**
A: Cannot decrypt existing credentials. Backup key securely. All tenants must reconfigure if lost.

**Q: Are endpoints encrypted?**
A: No. Endpoints are infrastructure addresses (not secrets), stored as plain text for efficiency.

**Q: Can I see API keys in API responses?**
A: No. Only last 4 characters shown (e.g., `"...xyz9"`).

**Q: Are API keys logged?**
A: No. Logs show masked keys only (`"...xyz9"`).

---

## Troubleshooting

### Error: "No API key configured for provider X"

**Cause:** Tenant has no credential configured and multi-tenant mode is enabled.

**Fix:**
```bash
# Configure credential for that tenant
PUT /api/v1/sysadmin/tenants/{tenant_id}/credentials/{provider}
```

### Error: "Failed to decrypt credential"

**Cause:** `ENCRYPTION_KEY` changed or corrupted database value.

**Fix:**
```bash
# Reconfigure credential (will re-encrypt with current key)
PUT /api/v1/sysadmin/tenants/{tenant_id}/credentials/{provider}
```

### Error: "Invalid API credentials for provider X"

**Cause:** Tenant credential configured but API key is invalid/expired.

**Fix:**
```bash
# Update with valid API key
PUT /api/v1/sysadmin/tenants/{tenant_id}/credentials/{provider}
{"api_key": "new-valid-key", ...}
```

### Error: "Azure provider missing required fields"

**Cause:** Azure requires 4 fields, not just api_key.

**Fix:**
```bash
# Include all 4 required fields
PUT /api/v1/sysadmin/tenants/{tenant_id}/credentials/azure
{
  "api_key": "...",
  "endpoint": "https://....openai.azure.com",
  "api_version": "2024-02-15-preview",
  "deployment_name": "gpt-4"
}
```

### VLLM Embeddings Not Working

**Cause:** Model missing `litellm_model_name` or endpoint not configured.

**Check:**
1. Model has `litellm_model_name: 'vllm/...'` in ai_models.yml
2. Tenant credential includes `"endpoint"` field
3. In multi-tenant mode, endpoint cannot fall back to global

**Fix:**
```bash
# Ensure endpoint is configured
PUT /api/v1/sysadmin/tenants/{tenant_id}/credentials/vllm
{"api_key": "...", "endpoint": "http://vllm:8000"}  # ← Must include endpoint
```

---

## Limitations & Future Features

### Current Limitations

**Authentication:**
- ✅ Sysadmin endpoints use shared `INTRIC_SUPER_API_KEY`
- ❌ No individual sysadmin user accounts
- ❌ No audit trail showing which admin made changes
- **Planned:** Individual sysadmin authentication with audit log

**Identity Providers:**
- ✅ MobilityGuard SSO supported (single IDP for all tenants)
- ❌ Per-tenant OIDC/SAML providers not supported
- ❌ Cannot use Stockholm's Azure AD for Stockholm tenant only
- **Planned:** Multi-tenant identity federation (each tenant configures own IDP)

**Credential Rotation:**
- ✅ Can update credentials via API
- ❌ No automatic key rotation
- ❌ No rotation scheduling/reminders
- **Planned:** Automated credential rotation with notifications

### Future Enhancements

**Phase 2 (Planned):**
- Individual sysadmin user accounts
- Credential change audit trail (who, when, what)
- Per-tenant OIDC/SAML identity providers
- Self-service credential management (tenant admins configure own keys)

**Phase 3 (Under Consideration):**
- Credential usage analytics (cost tracking per tenant)
- Automated credential rotation
- Credential health monitoring (expiration warnings)
- Multi-region credential replication

---

## Migration Guide

### From Single-Tenant to Multi-Tenant

**Prerequisites:**
- Identify all tenants in database
- Collect LLM credentials for each tenant
- Backup `ENCRYPTION_KEY` securely

**Steps:**

1. **Generate encryption key:**
   ```bash
   poetry run python -m intric.cli.generate_encryption_key
   ```

2. **Update .env:**
   ```bash
   TENANT_CREDENTIALS_ENABLED=true
   ENCRYPTION_KEY=<generated-key>
   ```

3. **Configure credentials for ALL tenants BEFORE restart:**
   ```bash
   # Must configure for every tenant that uses LLM features
   for tenant_id in {tenant1} {tenant2} {tenant3}; do
     curl -X PUT /api/v1/sysadmin/tenants/$tenant_id/credentials/openai \
       -H "X-API-Key: $API_KEY" \
       -d "{\"api_key\": \"$OPENAI_KEY\"}"
   done
   ```

4. **Restart backend:**
   ```bash
   poetry run start
   ```

5. **Verify each tenant:**
   ```bash
   # Check credentials configured
   curl /api/v1/sysadmin/tenants/{tenant_id}/credentials \
     -H "X-API-Key: $API_KEY"
   ```

⚠️ **Important:** Do NOT restart between step 2 and 3. Configure all tenants first, then restart.

### From Multi-Tenant to Single-Tenant

1. **Update .env:**
   ```bash
   TENANT_CREDENTIALS_ENABLED=false
   # ENCRYPTION_KEY can be removed (not used)
   ```

2. **Ensure global keys configured:**
   ```bash
   OPENAI_API_KEY=sk-proj-global-key
   VLLM_MODEL_URL=http://shared-vllm:8000
   VLLM_API_KEY=shared-key
   ```

3. **Restart backend**

**Result:** All tenant credentials ignored, global keys used for everyone.

---

## Performance Notes

- **Credential lookup:** <1ms (GIN index on JSONB)
- **Decryption overhead:** ~0.5ms per API key
- **Total per-request:** ~1.5ms additional latency
- **Caching:** Credentials cached per request (not across requests for security)

---

## Support

**Questions or issues?**
- Check logs: `LOGLEVEL=DEBUG` shows credential resolution details
- GitHub Issues: [eneo-ai/eneo](https://github.com/eneo-ai/eneo/issues)
- Documentation: See `backend/.env.template` for all configuration options
