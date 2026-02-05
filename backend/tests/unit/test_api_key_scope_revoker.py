from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.audit.domain.action_types import ActionType
from intric.authentication.api_key_scope_revoker import ApiKeyScopeRevoker
from intric.authentication.auth_models import (
    ApiKeyHashVersion,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyStateReasonCode,
    ApiKeyType,
    ApiKeyV2InDB,
)


def _make_key(**overrides: object) -> ApiKeyV2InDB:
    base = {
        "id": uuid4(),
        "key_prefix": ApiKeyType.SK.value,
        "key_suffix": "abcd1234",
        "name": "Test Key",
        "description": None,
        "key_type": ApiKeyType.SK,
        "permission": ApiKeyPermission.WRITE,
        "scope_type": ApiKeyScopeType.ASSISTANT,
        "scope_id": uuid4(),
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
        "created_at": datetime.now(timezone.utc),
        "updated_at": None,
        "rotated_from_key_id": None,
        "tenant_id": uuid4(),
        "owner_user_id": uuid4(),
        "created_by_user_id": None,
        "created_by_key_id": None,
        "delegation_depth": 0,
        "key_hash": "hash",
        "hash_version": ApiKeyHashVersion.HMAC_SHA256.value,
    }
    base.update(overrides)
    return ApiKeyV2InDB(**base)


@pytest.mark.asyncio
async def test_scope_revoker_updates_and_audits():
    key = _make_key()
    repo = AsyncMock()
    repo.list_by_scope.return_value = [key]
    repo.update.return_value = key
    audit = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=key.tenant_id)

    revoker = ApiKeyScopeRevoker(repo, audit, user)
    revoked = await revoker.revoke_scope(
        scope_type=ApiKeyScopeType.ASSISTANT,
        scope_id=key.scope_id,
        reason_code=ApiKeyStateReasonCode.SCOPE_REMOVED,
        reason_text="Assistant deleted",
    )

    assert revoked == 1
    repo.update.assert_awaited()
    assert (
        repo.update.call_args.kwargs["revoked_reason_code"]
        == ApiKeyStateReasonCode.SCOPE_REMOVED.value
    )
    audit.log_async.assert_awaited()
    assert audit.log_async.call_args.kwargs["action"] == ActionType.API_KEY_REVOKED
