# Audit Logging - Usage Guide

## Quick Start

The audit logging system is **ready to use** but requires **instrumentation** in your endpoints.

## Why No Logs Appeared

When you created a user, **no audit log was created** because:

1. ✅ Audit logging **infrastructure** is ready
2. ✅ Audit logging **API endpoints** work
3. ❌ User creation endpoint **NOT INSTRUMENTED** yet

**You need to add audit logging calls to your existing endpoints!**

## How to Instrument User Creation

### Step 1: Find Your User Creation Endpoint

Look for: `backend/src/intric/users/user_router.py` or similar

### Step 2: Add Audit Logging

```python
from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from intric.database.database import get_session_with_transaction

# In your endpoint
@router.post("/users")
async def create_user(
    user_data: UserCreate,
    current_user: UserInDB = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session_with_transaction),
):
    # Create the user (your existing code)
    new_user = await user_service.create_user(user_data)

    # ADD THIS: Log the action
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.USER_CREATED,
        entity_type=EntityType.USER,
        entity_id=new_user.id,
        description=f"Created user {new_user.email}",
        metadata={
            "actor": {
                "id": str(current_user.id),
                "name": current_user.username,
                "email": current_user.email
            },
            "target": {
                "id": str(new_user.id),
                "name": new_user.username,
                "email": new_user.email,
                "role": new_user.role
            }
        }
    )

    return new_user
```

## How to Query Audit Logs (With Authentication)

### Option 1: Using JWT Token

```bash
# First, login to get a token
curl -X POST "http://localhost:8123/api/v1/users/login/token/" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@yourtenant.com&password=yourpassword"

# Response: {"access_token": "eyJhbGc...", "token_type": "bearer"}

# Then query audit logs with the token
curl -X GET \
  "http://localhost:8123/api/v1/audit/logs?action=user_created&page=1&page_size=100" \
  -H "Authorization: Bearer eyJhbGc..."
```

### Option 2: Using API Key (Recommended!)

```bash
# API key authentication works for all audit endpoints:
curl -X GET \
  "http://localhost:8123/api/v1/audit/logs?action=user_created&page=1&page_size=100" \
  -H "X-API-Key: YOUR_API_KEY_HERE"

# Export to CSV
curl -X GET \
  "http://localhost:8123/api/v1/audit/logs/export?action=user_created" \
  -H "X-API-Key: YOUR_API_KEY_HERE" \
  --output audit_logs.csv

# Get user logs (GDPR)
curl -X GET \
  "http://localhost:8123/api/v1/audit/logs/user/{user_id}" \
  -H "X-API-Key: YOUR_API_KEY_HERE"
```

**Note:**
- ✅ API key authentication is **fully working**
- ✅ No need to pass `tenant_id` - automatically extracted from your API key
- ⚠️ Swagger UI may not show the 🔑 icon, but it works!

## Retention Policy Configuration

**Configure automatic audit log purging:**

```bash
# Get current retention policy
curl -X GET "http://localhost:8123/api/v1/audit/retention-policy" \
  -H "X-API-Key: YOUR_API_KEY"

# Set retention to 30 days (monthly purge)
curl -X PUT "http://localhost:8123/api/v1/audit/retention-policy?retention_days=30" \
  -H "X-API-Key: YOUR_API_KEY"

# Set retention to 90 days (recommended for compliance)
curl -X PUT "http://localhost:8123/api/v1/audit/retention-policy?retention_days=90" \
  -H "X-API-Key: YOUR_API_KEY"

# Set retention to 365 days (default - Swedish Arkivlagen)
curl -X PUT "http://localhost:8123/api/v1/audit/retention-policy?retention_days=365" \
  -H "X-API-Key: YOUR_API_KEY"
```

**Constraints:**
- Minimum: 1 day (for testing or aggressive purging)
- Maximum: 2555 days (7 years - Swedish statute of limitations)
- Default: 365 days
- **Recommended: 90+ days** for compliance and audit trail purposes

**Automatic Purge:**
- Runs daily at 02:00 UTC (03:00 Swedish time)
- Soft-deletes logs older than retention period
- Logs remain in database with `deleted_at` timestamp for forensics

## Authentication is Now Required

All audit endpoints now require authentication:
- ✅ `GET /audit/logs` - Requires auth, uses current_user.tenant_id
- ✅ `GET /audit/logs/user/{user_id}` - Requires auth, tenant_id from current_user
- ✅ `GET /audit/logs/export` - Requires auth, tenant_id from current_user
- ✅ `GET /audit/retention-policy` - Requires auth
- ✅ `PUT /audit/retention-policy` - Requires auth + admin permissions

**Swagger UI will now show the 🔒 lock icon** indicating authentication is required.

## Next Steps

### To See Audit Logs:

1. **Instrument your user creation endpoint** (see Step 2 above)
2. **Create a user** (triggers audit logging)
3. **Query with authentication**:
   ```bash
   curl -X GET "http://localhost:8123/api/v1/audit/logs" \
     -H "Authorization: Bearer YOUR_TOKEN"
   ```

### To Instrument Other Endpoints:

Tasks T053-T083 in `tasks.md` list all endpoints to instrument:
- User CRUD operations
- Assistant operations
- Space operations
- File uploads
- etc.

## Performance

- **Sync logging**: `await audit_service.log()` - ~20-50ms
- **Async logging**: `await audit_service.log_async()` - ~<10ms ⚡ (recommended)

Async returns immediately after enqueueing to Redis. ARQ worker persists in background.
