from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from intric.authentication.auth_models import ApiKeyV2InDB
from intric.tenants.tenant import TenantInDB
from intric.users.user import UserInDB, UserState


def build_service_key_user(*, key: ApiKeyV2InDB, tenant: TenantInDB) -> UserInDB:
    """Build an in-memory execution user for service-key principals.

    This is a compatibility adapter for code paths that still expect `UserInDB`
    while persisted ownership/execution identity is stored separately as a
    principal.
    """

    synthetic_id = uuid5(NAMESPACE_URL, f"service-key:{key.id}")
    key_suffix = key.key_suffix or key.id.hex[:8]
    return UserInDB(
        id=synthetic_id,
        email=f"sk-{key_suffix}@service.key",
        username=f"Service Key ({key.name})",
        state=UserState.ACTIVE,
        tenant_id=key.tenant_id,
        tenant=tenant,
        active_api_key=key,
        roles=[],
        used_tokens=0,
        email_verified=True,
        is_active=True,
    )
