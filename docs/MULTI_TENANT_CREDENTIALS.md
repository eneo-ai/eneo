# Multi-Tenant LLM Credentials

**Updated:** 2025-10-18  
**Audience:** Platform engineers & tenant admins  
**Purpose:** Give each municipality its own LLM provider credentials while keeping secrets encrypted per tenant.

---

## 1. Decide on Mode

| Mode                    | When to use                                          | Config                                     |
|-------------------------|------------------------------------------------------|---------------------------------------------|
| **Shared** (default)    | All tenants bill through the same keys               | `TENANT_CREDENTIALS_ENABLED=false` + globals in `.env` |
| **Per-tenant (strict)** | Tenants require isolated billing or infrastructure   | `TENANT_CREDENTIALS_ENABLED=true` + encryption key |

---

## 2. Enable Per-Tenant Credentials
1. Generate a Fernet key once and store it safely:
   ```bash
   cd backend
   uv run python -m intric.cli.generate_encryption_key
   ```
2. Set environment variables:
   ```bash
   TENANT_CREDENTIALS_ENABLED=true
   ENCRYPTION_KEY=<output from step 1>
   ```
3. Restart the backend service.

Now every tenant must configure its own credential before it can call LLM endpoints. Secrets are encrypted in `tenants.api_credentials` and responses only expose masked tails.

---

## 3. Manage Credentials via API
All endpoints require the super admin key (`X-API-Key`). Replace `{tenant_id}` with the tenant’s UUID.

### Add or update a credential
```bash
curl -X PUT \
  https://api.eneo.local/api/v1/sysadmin/tenants/{tenant_id}/credentials/openai \
  -H "X-API-Key: {SUPER_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"api_key": "sk-proj-municipalityA"}'
```

Azure-specific example (all fields required):
```json
{
  "api_key": "abc123",
  "endpoint": "https://municipalitya-openai.azure.com",
  "api_version": "2024-02-15-preview",
  "deployment_name": "gpt-4"
}
```

### Delete a credential
```bash
curl -X DELETE \
  https://api.eneo.local/api/v1/sysadmin/tenants/{tenant_id}/credentials/openai \
  -H "X-API-Key: {SUPER_API_KEY}"
```

### List configured credentials (masked output)
```bash
curl -X GET \
  https://api.eneo.local/api/v1/sysadmin/tenants/{tenant_id}/credentials \
  -H "X-API-Key: {SUPER_API_KEY}"
```
Example response:
```json
{
  "credentials": [
    {
      "provider": "openai",
      "masked_key": "...key9",
      "configured_at": "2025-10-08T10:00:00Z",
      "encryption_status": "encrypted",
      "config": {}
    }
  ]
}
```

---

## 4. Supported Providers & Fields

| Provider    | Required fields                                  | Typical use case                   |
|-------------|---------------------------------------------------|------------------------------------|
| `openai`    | `api_key`                                         | OpenAI hosted GPT & embeddings     |
| `anthropic` | `api_key`                                         | Claude models                      |
| `azure`     | `api_key`, `endpoint`, `api_version`, `deployment_name` | Azure OpenAI with regional residency |
| `vllm`      | `api_key`, `endpoint`                             | Self-hosted / regional vLLM        |

> ⚠️ **Strict mode:** when `TENANT_CREDENTIALS_ENABLED=true`, both `api_key` and `endpoint`
> must be provided for VLLM. The API now returns HTTP 400 if either value is missing so
> misconfigured tenants never fall back to the shared global cluster by accident.
| `berget`    | `api_key`                                         | Swedish-hosted embeddings          |
| `mistral`   | `api_key`                                         | Mistral hosted models              |
| `ovhcloud`  | `api_key`                                         | EU-hosted models                   |

**Note:** For vLLM you must define `litellm_model_name` in `ai_models.yml` so tenant credentials are used. Legacy vLLM entries without it still rely on global `.env` values.

---

## 5. Operational Tips
- Credentials are encrypted using `ENCRYPTION_KEY`; losing the key means losing access to stored secrets.
- Audit logs record which admin set or removed credentials.
- Pair with federation config when tenants want full isolation (see [Federation Per Tenant](./FEDERATION_PER_TENANT.md)).
- Combine with the OIDC debug toggle to troubleshoot tenant-specific LLM onboarding issues quickly.
- If a tenant follows the checklist and still receives a 400 for VLLM, double-check that the
  endpoint URL is reachable from the backend and that it matches the per-tenant DNS you expect.

---

## 6. See Also
- [Federation Per Tenant](./FEDERATION_PER_TENANT.md) – tenant-specific IdPs
- [Multi-Tenant OIDC Setup Guide](./MULTITENANT_OIDC_SETUP_GUIDE.md) – correlation-based troubleshooting
- [Troubleshooting](./TROUBLESHOOTING.md) – incident catalogue
