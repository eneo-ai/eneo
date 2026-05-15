from __future__ import annotations

from collections.abc import Iterable

from intric.authentication.auth_models import ApiKeyV2InDB
from intric.roles.permissions import Permission
from intric.roles.role import RoleInDB
from intric.tenants.tenant import TenantInDB
from intric.users.user import UserInDB, UserState


def build_service_key_user(
    *,
    key: ApiKeyV2InDB,
    tenant: TenantInDB,
    permissions: Iterable[Permission] | None = None,
) -> UserInDB:
    """Build an in-memory execution user for service-key principals."""

    synthetic_role = None
    if permissions is not None:
        synthetic_role = RoleInDB(
            id=key.id,
            tenant_id=key.tenant_id,
            name=f"Service Key Role ({key.name})",
            permissions=sorted(permissions, key=lambda permission: permission.value),
        )

    key_suffix = key.key_suffix or key.id.hex[:8]
    return UserInDB(
        id=key.id,
        email=f"sk-{key_suffix}@service.key",
        username=f"Service Key ({key.name})",
        state=UserState.ACTIVE,
        tenant_id=key.tenant_id,
        tenant=tenant,
        active_api_key=key,
        roles=[] if synthetic_role is None else [synthetic_role],
        used_tokens=0,
        email_verified=True,
        is_active=True,
    )
