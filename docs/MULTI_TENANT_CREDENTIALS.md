# Multi-Tenant LLM Credentials Setup Guide

Configure tenant-specific API credentials for LLM providers (OpenAI, Azure, Anthropic, VLLM, etc.).

## Quick Start

**1. Enable the feature:**
```bash
# .env
TENANT_CREDENTIALS_ENABLED=true
ENCRYPTION_KEY=<generate-with-command-below>
```

**2. Generate encryption key:**
```bash
poetry run python -m intric.cli.generate_encryption_key
```

**3. Configure tenant credentials:**
```bash
# Set OpenAI key for tenant
curl -X PUT https://api.eneo.ai/api/v1/sysadmin/tenants/{tenant_id}/credentials/openai \
  -H "X-API-Key: $INTRIC_SUPER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"api_key": "sk-proj-abc123..."}'

# Set VLLM endpoint for tenant
curl -X PUT https://api.eneo.ai/api/v1/sysadmin/tenants/{tenant_id}/credentials/vllm \
  -H "X-API-Key: $INTRIC_SUPER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"api_key": "vllm-secret", "endpoint": "http://tenant-vllm:8000"}'
```

## Supported Providers

| Provider | API Key Required | Additional Fields | Use Case |
|----------|------------------|-------------------|----------|
| `openai` | ✓ | - | GPT models via OpenAI |
| `anthropic` | ✓ | - | Claude models |
| `mistral` | ✓ | - | Mistral models |
| `ovhcloud` | ✓ | - | OVHCloud hosted models |
| `berget` | ✓ | - | Swedish-hosted models |
| `azure` | ✓ | endpoint, api_version, deployment_name | Azure OpenAI |
| `vllm` | ✓ | endpoint | Self-hosted VLLM instances |

## API Endpoints

### Set/Update Credential
```http
PUT /api/v1/sysadmin/tenants/{tenant_id}/credentials/{provider}
Headers: X-API-Key: <INTRIC_SUPER_API_KEY>
Body: {"api_key": "...", "endpoint": "..." (optional)}
```

### List Credentials (Masked)
```http
GET /api/v1/sysadmin/tenants/{tenant_id}/credentials
Headers: X-API-Key: <INTRIC_SUPER_API_KEY>

Response:
{
  "credentials": [
    {
      "provider": "openai",
      "masked_key": "...xyz9",
      "encryption_status": "encrypted",
      "configured_at": "2025-10-08T10:00:00Z"
    }
  ]
}
```

### Delete Credential
```http
DELETE /api/v1/sysadmin/tenants/{tenant_id}/credentials/{provider}
Headers: X-API-Key: <INTRIC_SUPER_API_KEY>
```

## Provider-Specific Examples

### OpenAI
```json
{"api_key": "sk-proj-abc123xyz789..."}
```

### Azure OpenAI (All 4 fields required)
```json
{
  "api_key": "abc123...",
  "endpoint": "https://sweden.openai.azure.com",
  "api_version": "2024-02-15-preview",
  "deployment_name": "gpt-4"
}
```

### VLLM (Self-Hosted)

**Single shared VLLM (all tenants):**
```json
{"api_key": "regional-secret"}
```
Uses global `VLLM_MODEL_URL` from .env

**Dedicated VLLM per tenant:**
```json
{
  "api_key": "tenant-dedicated-secret",
  "endpoint": "http://tenant-vllm.internal:8000"
}
```

**Model configuration required (ai_models.yml):**
```yaml
- name: 'llama-3.1-70b'
  family: 'vllm'
  litellm_model_name: 'vllm/meta-llama/Meta-Llama-3.1-70B-Instruct'
  # litellm_model_name triggers multi-tenant support
```

## Deployment Patterns

### Single-Tenant (All tenants share global keys)
```bash
# .env
TENANT_CREDENTIALS_ENABLED=false
OPENAI_API_KEY=sk-proj-...
VLLM_MODEL_URL=http://localhost:8000
VLLM_API_KEY=my-key

# All tenants automatically use global keys from .env
# No credential configuration needed
```

### Multi-Tenant (Each tenant has their own credentials)
```bash
# .env
TENANT_CREDENTIALS_ENABLED=true
ENCRYPTION_KEY=<44-char-key>
# Global keys optional (not used when strict mode enabled)

# IMPORTANT: Each tenant MUST configure their own credentials
# No automatic fallback - prevents billing confusion

# Configure for each tenant:
PUT /api/v1/sysadmin/tenants/{stockholm_id}/credentials/openai
{"api_key": "sk-stockholm-key"}

PUT /api/v1/sysadmin/tenants/{goteborg_id}/credentials/openai
{"api_key": "sk-goteborg-key"}

# For shared key across multiple tenants, configure same key for each:
PUT /api/v1/sysadmin/tenants/{tenant_a_id}/credentials/azure
{"api_key": "shared-azure-key", ...}

PUT /api/v1/sysadmin/tenants/{tenant_b_id}/credentials/azure
{"api_key": "shared-azure-key", ...}  # Same key, explicit configuration
```

## Credential Isolation Rules

**Strict mode when TENANT_CREDENTIALS_ENABLED=true:**

✅ **Tenant has configured credential:** Uses tenant credential exclusively
❌ **Tenant has NO credential:** Raises error (forces explicit configuration)
❌ **Tenant has INVALID credential:** Raises error (no silent fallback)

**Single-tenant mode when TENANT_CREDENTIALS_ENABLED=false:**

✅ **All tenants use global .env keys** (shared infrastructure)

**Why strict mode:** Prevents billing confusion. Tenants know exactly which credentials they're using - no silent fallback to organization's global key.

## Security & Encryption

**How it works:**
1. API keys encrypted using **Fernet (AES-128-CBC + HMAC)** before database storage
2. Encryption key stored in `ENCRYPTION_KEY` environment variable
3. Keys decrypted on-the-fly during LLM API calls (never stored in memory)
4. Keys masked in API responses (show last 4 characters only)
5. Keys masked in logs (prevent accidental exposure)

**Encryption format:**
```
Database: enc:fernet:v1:gAAAAA...encrypted-data...
Decrypted: sk-proj-abc123xyz789...
API response: ...xyz9
Logs: ...xyz9
```

**Key rotation:** Change `ENCRYPTION_KEY` → re-encrypt all credentials (future feature)

## FAQ

**Q: Can I use both global and tenant-specific credentials?**
A: No. When `TENANT_CREDENTIALS_ENABLED=true`, each tenant MUST configure their own credentials (no fallback to global). When `=false`, all tenants share global .env keys.

**Q: What happens if tenant has no credential configured?**
A: Strict mode (`TENANT_CREDENTIALS_ENABLED=true`): Raises error immediately. Single-tenant mode (`=false`): Uses global .env key.

**Q: What happens if tenant credential is invalid?**
A: Error raised immediately. No silent fallback to prevent billing confusion.

**Q: Do I need tenant credentials for single-tenant deployments?**
A: No. Set `TENANT_CREDENTIALS_ENABLED=false` and all tenants use global keys only.

**Q: Can two tenants share the same API key?**
A: Yes. Manually configure the same credential for both tenants via the API.

**Q: Can I configure VLLM endpoint per tenant?**
A: Yes, if model uses LiteLLM (`litellm_model_name: "vllm/..."`). Legacy VLLM adapter uses global only.

**Q: How do I know which model uses which adapter?**
A: Check ai_models.yml: `litellm_model_name` present = LiteLLM adapter (tenant-capable), absent = legacy adapter (global only).

**Q: Are credentials encrypted at rest?**
A: Yes, using Fernet (AES-128) when `TENANT_CREDENTIALS_ENABLED=true`.

**Q: What if I lose the ENCRYPTION_KEY?**
A: Cannot decrypt existing credentials. Backup `ENCRYPTION_KEY` securely. Tenants must reconfigure if lost.

**Q: Can I migrate from single-tenant to multi-tenant?**
A: Yes. Enable feature, set encryption key, restart. Existing deployments continue using global keys until tenants configure their own.
