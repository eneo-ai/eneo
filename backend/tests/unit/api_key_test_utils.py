from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from intric.authentication.auth_models import (
    ApiKeyHashVersion,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyV2InDB,
)


def make_api_key(
    *,
    default_permission: ApiKeyPermission = ApiKeyPermission.READ,
    created_at: datetime | None = None,
    **overrides: Any,
) -> ApiKeyV2InDB:
    base: dict[str, Any] = {
        "id": uuid4(),
        "key_prefix": ApiKeyType.SK.value,
        "key_suffix": "abcd1234",
        "name": "Test Key",
        "description": None,
        "key_type": ApiKeyType.SK,
        "permission": default_permission,
        "scope_type": ApiKeyScopeType.TENANT,
        "scope_id": None,
        "allowed_origins": None,
        "allowed_ips": None,
        "state": ApiKeyState.ACTIVE,
        "expires_at": None,
        "last_used_at": None,
        "revoked_at": None,
        "revoked_reason_code": None,
        "revoked_reason_text": None,
        "suspended_at": None,
        "suspended_reason_code": None,
        "suspended_reason_text": None,
        "rotation_grace_until": None,
        "rate_limit": None,
        "created_at": created_at,
        "updated_at": None,
        "rotated_from_key_id": None,
        "tenant_id": uuid4(),
        "owner_user_id": uuid4(),
        "created_by_user_id": None,
        "created_by_key_id": None,
        "delegation_depth": 0,
        "key_hash": "hash",
        "hash_version": ApiKeyHashVersion.HMAC_SHA256.value,
        "resource_permissions": None,
    }
    if created_at is None:
        base["created_at"] = None
    else:
        base["created_at"] = created_at

    base.update(overrides)
    return ApiKeyV2InDB(**base)


def make_api_key_with_timestamp(**overrides: Any) -> ApiKeyV2InDB:
    return make_api_key(created_at=datetime.now(timezone.utc), **overrides)
