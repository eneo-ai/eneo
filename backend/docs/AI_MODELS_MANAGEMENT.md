# AI Models Management

## Overview

AI models (completion, embedding, and transcription) are now managed through API endpoints and the UI, rather than being automatically synced from configuration files at server startup.

## What Changed

### Before (Legacy Behavior)
- ✅ Models automatically synced from `ai_models.yml` on every server startup
- ✅ New tenants automatically had default models enabled
- ❌ No API to create/update/delete models
- ❌ Required server restart to add new models
- ❌ Tight coupling between deployment and model availability

### After (Current Behavior)
- ✅ Models managed via `/sysadmin/` API endpoints (requires super admin API key)
- ✅ No automatic syncing on server startup
- ✅ Create/update/delete models without restarting the server
- ✅ Explicit control over which models are available
- ⚠️ New tenants start with **no models enabled** (admins must explicitly assign)

## API Endpoints

All endpoints require the `X-API-Key` header with the value from `INTRIC_SUPER_API_KEY`.

### Completion Models

#### Create Completion Model
```http
POST /api/v1/sysadmin/completion-models/create
Content-Type: application/json
X-API-Key: <super_admin_key>

{
  "name": "gpt-4-turbo",
  "nickname": "GPT-4 Turbo",
  "family": "openai",
  "token_limit": 128000,
  "is_deprecated": false,
  "stability": "stable",
  "hosting": "usa",
  "open_source": false,
  "org": "OpenAI",
  "vision": true,
  "reasoning": false,
  "base_url": "https://api.openai.com/v1",
  "litellm_model_name": "gpt-4-turbo"
}
```

#### Update Completion Model
```http
PUT /api/v1/sysadmin/completion-models/{model_id}/metadata
Content-Type: application/json
X-API-Key: <super_admin_key>

{
  "nickname": "GPT-4 Turbo (Updated)",
  "description": "Updated description",
  "is_deprecated": true
}
```

**Note:** Only update fields that need to change. Unspecified fields remain unchanged.

#### Delete Completion Model
```http
DELETE /api/v1/sysadmin/completion-models/{model_id}
X-API-Key: <super_admin_key>
```

**Warning:** Deletion is system-wide and affects all tenants. Ensure the model is not in use.

### Embedding Models

#### Create Embedding Model
```http
POST /api/v1/sysadmin/embedding-models/create
Content-Type: application/json
X-API-Key: <super_admin_key>

{
  "name": "text-embedding-3-large",
  "family": "openai",
  "is_deprecated": false,
  "open_source": false,
  "dimensions": 3072,
  "max_input": 8191,
  "max_batch_size": 100,
  "stability": "stable",
  "hosting": "usa",
  "org": "OpenAI",
  "litellm_model_name": "text-embedding-3-large"
}
```

#### Update Embedding Model
```http
PUT /api/v1/sysadmin/embedding-models/{model_id}/metadata
Content-Type: application/json
X-API-Key: <super_admin_key>

{
  "description": "Updated embedding model",
  "dimensions": 1536
}
```

#### Delete Embedding Model
```http
DELETE /api/v1/sysadmin/embedding-models/{model_id}
X-API-Key: <super_admin_key>
```

### Enabling Models for Tenants

After creating models, you must explicitly enable them for each tenant:

```http
POST /api/v1/completion-models/{model_id}/
Authorization: Bearer <tenant_admin_token>

{
  "is_org_enabled": true,
  "is_org_default": false
}
```

## CLI Seed Script (Backwards Compatibility)

For backwards compatibility or initial setup, you can seed models from the `ai_models.yml` file:

```bash
uv run python -m intric.cli.seed_ai_models
```

**What it does:**
- Loads models from `src/intric/server/dependencies/ai_models.yml`
- Creates new models that don't exist
- Updates existing models with new configuration
- Deletes models no longer in the config
- **Does NOT enable models for tenants** (must be done via API/UI)

**When to use:**
- Initial deployment setup
- Migrating from legacy auto-sync behavior
- Bulk importing models from configuration

## Migration Guide

### For Existing Deployments

If you're upgrading from a version that auto-synced models:

1. **No action required for existing models** - They remain in the database
2. **New tenants won't have models** - You must enable models for new tenants via API/UI
3. **Optional: Run seed script** - If you need to sync changes from `ai_models.yml`

### For New Deployments

1. **Option 1: Seed from YAML (recommended for getting started)**
   ```bash
   uv run python -m intric.cli.seed_ai_models
   ```

2. **Option 2: Use API endpoints**
   - Create models via `POST /sysadmin/completion-models/create`
   - Enable for tenants via tenant-scoped endpoints

## Important Notes

### Model Name Uniqueness

**Completion & Embedding Models:**
- **Removed unique constraint on `name` field** (as of migration `20251104_remove_unique`)
- Multiple models can have the same name (e.g., "gpt-4" from different providers)
- Models are identified by UUID, not by name

**Transcription Models:**
- **Unique constraint remains** (hardcoded models only, no CRUD endpoints)
- Only 2 models exist (Whisper and KB-Whisper)

### Tenant-Scoped vs System-Wide

**System-Wide Operations** (require `INTRIC_SUPER_API_KEY`):
- Create/update/delete model metadata
- Available under `/sysadmin/` endpoints

**Tenant-Scoped Operations** (require tenant admin permissions):
- Enable/disable models for a specific tenant
- Set default model for a tenant
- Available under `/completion-models/` and `/embedding-models/` endpoints

### Response Models

The sysadmin endpoints return **Sparse** response models:
- ✅ Include: `id`, `name`, `nickname`, `family`, `token_limit`, etc. (global metadata)
- ❌ Exclude: `is_org_enabled`, `is_org_default`, `security_classification` (tenant-specific fields)

This ensures the API only returns/accepts fields that can actually be set at the system level.

## Testing

### Integration Tests

Default models are automatically seeded for integration tests via the `seed_default_models` fixture:
- Creates GPT-4 (completion model)
- Creates text-embedding-ada-002 (embedding model)
- Auto-enables models for all test tenants (including dynamically created ones)

This behavior is **test-only** and does not affect production deployments.

### Writing Tests

When writing tests that create tenants:
```python
async def test_my_feature(client, super_admin_token):
    # Create tenant via API
    tenant = await _create_tenant(client, super_admin_token, "test-tenant")

    # Models are automatically enabled for this tenant (test fixture behavior)
    # Create assistant will work without additional setup
    assistant = await _create_assistant(client, token, {...})
```

## Transcription Models

**Transcription models remain hardcoded** and are managed via database migrations:
- Only 2 models: Whisper (OpenAI) and KB-Whisper (Berget)
- Seeded via migration `202503111059_65ff84b31e90`
- No CRUD endpoints (infrastructure doesn't support dynamic providers)
- Auto-enabled for all tenants at creation time (via migration logic)

This is intentional due to infrastructure limitations. See the architecture decision in the original discussion.

## Troubleshooting

### "Model not found" errors

**Symptom:** API returns 404 when updating/deleting a model

**Solution:** Verify the model UUID exists in the database:
```sql
SELECT id, name FROM completion_models;
```

### New tenants have no models

**Expected behavior.** Admins must explicitly enable models:
1. List available models: `GET /api/v1/completion-models/`
2. Enable for tenant: `POST /api/v1/completion-models/{id}/`

### Tests failing with "completion_model is None"

**Symptom:** Tests fail with `AttributeError: 'NoneType' object has no attribute 'id'`

**Solution:** Ensure the `seed_default_models` fixture is running. It should run automatically for all integration tests.

## API Reference

### Enum Values

**ModelFamily (Completion Models):**
- `openai`, `mistral`, `vllm`, `claude`, `azure`, `ovhcloud`, `e5`

**ModelFamily (Embedding Models):**
- `openai`, `mini_lm`, `e5`

**ModelStability:**
- `stable`, `experimental`

**ModelHostingLocation:**
- `usa`, `eu`, `swe`

**ModelOrg:**
- `OpenAI`, `Meta`, `Microsoft`, `Anthropic`, `Mistral`, `KBLab`, `Google`, `Berget`, `GDM`

### Response Codes

- `200 OK` - Success
- `401 Unauthorized` - Missing or invalid API key
- `404 Not Found` - Model doesn't exist
- `422 Unprocessable Entity` - Validation error (invalid field values)

## Examples

### Complete Workflow: Adding a New Model

1. **Create the model (system admin)**
   ```bash
   curl -X POST https://api.example.com/api/v1/sysadmin/completion-models/create \
     -H "X-API-Key: $SUPER_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{
       "name": "claude-3-opus",
       "nickname": "Claude 3 Opus",
       "family": "claude",
       "token_limit": 200000,
       "is_deprecated": false,
       "stability": "stable",
       "hosting": "usa",
       "open_source": false,
       "org": "Anthropic",
       "vision": true,
       "reasoning": false,
       "litellm_model_name": "claude-3-opus-20240229"
     }'
   ```

2. **Enable for a tenant (tenant admin)**
   ```bash
   curl -X POST https://api.example.com/api/v1/completion-models/{model_id}/ \
     -H "Authorization: Bearer $TENANT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "is_org_enabled": true,
       "is_org_default": false
     }'
   ```

3. **Verify in UI**
   - Navigate to Settings → AI Models
   - Confirm new model is visible and enabled

## Future Enhancements

Potential improvements for future versions:

- [ ] Add usage tracking before deletion (prevent deleting in-use models)
- [ ] Bulk enable/disable operations across multiple tenants
- [ ] Model templates for common configurations
- [ ] Automatic model discovery from provider APIs
- [ ] Model cost tracking and quotas
- [ ] UI for model management (currently API-only)

## Related Files

- `src/intric/sysadmin/sysadmin_router.py` - API endpoints
- `src/intric/server/dependencies/ai_models.yml` - Model configuration (legacy)
- `src/intric/cli/seed_ai_models.py` - CLI seed script
- `src/intric/database/tables/ai_models_table.py` - Database schema
- `alembic/versions/20251104_remove_unique_constraint_on_model_names.py` - Migration removing unique constraint
- `tests/integration/sysadmin/test_ai_models_crud.py` - Integration tests
