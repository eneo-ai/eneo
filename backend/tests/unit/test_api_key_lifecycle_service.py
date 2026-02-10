from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

from intric.audit.domain.action_types import ActionType
from intric.authentication.auth_models import (
    ApiKeyPermission,
    ResourcePermissionLevel,
    ResourcePermissions,
    ApiKeyStateChangeRequest,
    ApiKeyStateReasonCode,
    ApiKeyState,
    ApiKeyUpdateRequest,
    ApiKeyType,
    ApiKeyV2InDB,
)
from intric.authentication.api_key_resolver import ApiKeyValidationError
from intric.authentication.api_key_lifecycle import ApiKeyLifecycleService
from tests.unit.api_key_test_utils import make_api_key


def _make_key(**overrides: object) -> ApiKeyV2InDB:
    return make_api_key(
        default_permission=ApiKeyPermission.WRITE,
        **overrides,
    )


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


@pytest.mark.asyncio
async def test_update_revoked_key_allows_metadata_only(user):
    key = _make_key(
        tenant_id=user.tenant_id,
        revoked_at=datetime.now(timezone.utc),
        state=ApiKeyState.REVOKED,
    )
    updated_key = _make_key(
        id=key.id,
        tenant_id=user.tenant_id,
        revoked_at=key.revoked_at,
        state=ApiKeyState.REVOKED,
        name="Renamed",
    )
    repo = AsyncMock()
    repo.get.return_value = key
    repo.update.return_value = updated_key
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(),
        validate_update_request=AsyncMock(),
    )
    audit = AsyncMock()
    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )

    response = await service.update_key(
        key_id=key.id,
        request=ApiKeyUpdateRequest(name="Renamed"),
    )

    assert response.name == "Renamed"
    repo.update.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_revoked_key_rejects_policy_fields(user):
    key = _make_key(
        tenant_id=user.tenant_id,
        revoked_at=datetime.now(timezone.utc),
        state=ApiKeyState.REVOKED,
    )
    repo = AsyncMock()
    repo.get.return_value = key
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(),
        validate_update_request=AsyncMock(),
    )
    audit = AsyncMock()
    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.update_key(
            key_id=key.id,
            request=ApiKeyUpdateRequest(rate_limit=1000),
        )

    assert exc.value.code == "invalid_request"
    assert "Only name and description" in exc.value.message


@pytest.mark.asyncio
async def test_double_revoke_is_idempotent(user):
    """Revoking an already-revoked key returns success without error."""
    key = _make_key(
        tenant_id=user.tenant_id,
        revoked_at=datetime.now(timezone.utc),
        state=ApiKeyState.REVOKED,
    )
    repo = AsyncMock()
    repo.get.return_value = key
    policy = SimpleNamespace(ensure_manage_authorized=AsyncMock())
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )

    result = await service.revoke_key(key_id=key.id)

    assert result.id == key.id
    repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_rotate_key_with_existing_grace_period(user):
    """Rotation of a key that already has rotation_grace_until overwrites the grace window."""
    key = _make_key(
        tenant_id=user.tenant_id,
        rotation_grace_until=datetime.now(timezone.utc),
    )
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

    assert response.secret.startswith(ApiKeyType.SK.value)
    repo.create.assert_awaited_once()
    repo.update.assert_awaited_once()
    update_kwargs = repo.update.call_args.kwargs
    assert "rotation_grace_until" in update_kwargs
    assert update_kwargs["rotation_grace_until"] > key.rotation_grace_until


@pytest.mark.asyncio
async def test_rotate_serializes_resource_permissions_for_repo_create(user):
    """Rotate passes JSON-serializable resource_permissions to repo.create."""
    key = _make_key(
        tenant_id=user.tenant_id,
        resource_permissions=ResourcePermissions(
            assistants=ResourcePermissionLevel.READ,
            apps=ResourcePermissionLevel.WRITE,
            spaces=ResourcePermissionLevel.NONE,
            knowledge=ResourcePermissionLevel.READ,
        ),
    )
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

    await service.rotate_key(key_id=key.id)

    create_kwargs = repo.create.call_args.kwargs
    assert isinstance(create_kwargs["resource_permissions"], dict)
    assert create_kwargs["resource_permissions"]["assistants"] == "read"
    assert create_kwargs["resource_permissions"]["apps"] == "write"
