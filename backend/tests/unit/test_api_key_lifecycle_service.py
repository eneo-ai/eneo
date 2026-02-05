from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

from intric.audit.domain.action_types import ActionType
from intric.authentication.auth_models import (
    ApiKeyHashVersion,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyStateChangeRequest,
    ApiKeyStateReasonCode,
    ApiKeyType,
    ApiKeyV2InDB,
)
from intric.authentication.api_key_lifecycle import ApiKeyLifecycleService


def _make_key(**overrides: object) -> ApiKeyV2InDB:
    base = {
        "id": uuid4(),
        "key_prefix": ApiKeyType.SK.value,
        "key_suffix": "abcd1234",
        "name": "Test Key",
        "description": None,
        "key_type": ApiKeyType.SK,
        "permission": ApiKeyPermission.WRITE,
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
        "created_at": None,
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


@pytest.fixture()
def user():
    return SimpleNamespace(id=uuid4(), email="user@example.com", tenant_id=uuid4())


@pytest.mark.asyncio
async def test_suspend_logs_audit(user):
    key = _make_key(tenant_id=user.tenant_id)
    repo = AsyncMock()
    repo.get.return_value = key
    repo.update.return_value = key
    policy = SimpleNamespace(ensure_manage_authorized=AsyncMock())
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )

    request = ApiKeyStateChangeRequest(
        reason_code=ApiKeyStateReasonCode.SECURITY_CONCERN,
        reason_text="Suspicious activity",
    )

    await service.suspend_key(key_id=key.id, request=request)

    audit.log_async.assert_awaited()
    assert audit.log_async.call_args.kwargs["action"] == ActionType.API_KEY_SUSPENDED


@pytest.mark.asyncio
async def test_revoke_logs_audit(user):
    key = _make_key(tenant_id=user.tenant_id)
    repo = AsyncMock()
    repo.get.return_value = key
    repo.update.return_value = key
    policy = SimpleNamespace(ensure_manage_authorized=AsyncMock())
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )

    request = ApiKeyStateChangeRequest(
        reason_code=ApiKeyStateReasonCode.USER_REQUEST,
        reason_text="Requested by user",
    )

    await service.revoke_key(key_id=key.id, request=request)

    audit.log_async.assert_awaited()
    assert audit.log_async.call_args.kwargs["action"] == ActionType.API_KEY_REVOKED


@pytest.mark.asyncio
async def test_rotate_logs_audit(user):
    key = _make_key(tenant_id=user.tenant_id)
    new_key = _make_key(tenant_id=user.tenant_id, rotated_from_key_id=key.id)
    repo = AsyncMock()
    repo.get.return_value = key
    repo.create.return_value = new_key
    repo.update.return_value = key
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(), validate_key_state=AsyncMock()
    )
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )

    response = await service.rotate_key(key_id=key.id)

    audit.log_async.assert_awaited()
    assert audit.log_async.call_args.kwargs["action"] == ActionType.API_KEY_ROTATED
    assert response.secret.startswith(ApiKeyType.SK.value)
