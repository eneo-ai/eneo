from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.audit.domain.action_types import ActionType
from intric.authentication.api_key_lifecycle import ApiKeyLifecycleService
from intric.authentication.api_key_resolver import ApiKeyValidationError
from intric.authentication.auth_models import (
    ApiKeyExtendRequest,
    ApiKeyPermission,
    ApiKeyRotateRequest,
    ApiKeyState,
    ApiKeyStateChangeRequest,
    ApiKeyStateReasonCode,
    ApiKeyType,
    ApiKeyUpdateRequest,
    ApiKeyV2InDB,
    ResourcePermissionLevel,
    ResourcePermissions,
)
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
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(), ensure_ownership_authorized=AsyncMock()
    )
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
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(), ensure_ownership_authorized=AsyncMock()
    )
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
        ensure_manage_authorized=AsyncMock(),
        ensure_ownership_authorized=AsyncMock(),
        validate_key_state=AsyncMock(),
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
    metadata = audit.log_async.call_args.kwargs["metadata"]
    assert metadata["extra"]["grace_period_disabled"] is False


@pytest.mark.asyncio
async def test_rotate_disable_grace_period_collapses_grace_window(user):
    key = _make_key(tenant_id=user.tenant_id)
    new_key = _make_key(tenant_id=user.tenant_id, rotated_from_key_id=key.id)
    repo = AsyncMock()
    repo.get.return_value = key
    repo.create.return_value = new_key
    repo.update.return_value = key
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(),
        ensure_ownership_authorized=AsyncMock(),
        validate_key_state=AsyncMock(),
    )
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )

    await service.rotate_key(
        key_id=key.id,
        request=ApiKeyRotateRequest(disable_grace_period=True),
    )

    grace_until = repo.update.call_args.kwargs["rotation_grace_until"]
    assert grace_until <= datetime.now(timezone.utc)

    metadata = audit.log_async.call_args.kwargs["metadata"]
    assert metadata["extra"]["grace_period_disabled"] is True


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
        ensure_ownership_authorized=AsyncMock(),
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
        ensure_ownership_authorized=AsyncMock(),
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
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(), ensure_ownership_authorized=AsyncMock()
    )
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
        ensure_manage_authorized=AsyncMock(),
        ensure_ownership_authorized=AsyncMock(),
        validate_key_state=AsyncMock(),
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
async def test_rotate_key_uses_default_when_policy_grace_period_is_null(user):
    """Explicit null policy value falls back to settings default, while avoiding timedelta(None)."""
    user.tenant = SimpleNamespace(api_key_policy={"rotation_grace_hours": None})
    key = _make_key(tenant_id=user.tenant_id)
    new_key = _make_key(tenant_id=user.tenant_id, rotated_from_key_id=key.id)
    repo = AsyncMock()
    repo.get.return_value = key
    repo.create.return_value = new_key
    repo.update.return_value = key
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(),
        ensure_ownership_authorized=AsyncMock(),
        validate_key_state=AsyncMock(),
    )
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )
    service.settings = SimpleNamespace(
        api_key_hash_secret="test-api-key-hash-secret",
        api_key_length=32,
        api_key_rotation_grace_hours=24,
        jwt_secret="test-jwt-secret",
    )

    before = datetime.now(timezone.utc)
    await service.rotate_key(key_id=key.id)

    grace_until = repo.update.call_args.kwargs["rotation_grace_until"]
    assert before + timedelta(hours=23, minutes=59) < grace_until
    assert grace_until < before + timedelta(hours=24, minutes=1)


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
        ensure_manage_authorized=AsyncMock(),
        ensure_ownership_authorized=AsyncMock(),
        validate_key_state=AsyncMock(),
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


def _extend_policy_mock() -> SimpleNamespace:
    return SimpleNamespace(
        ensure_manage_authorized=AsyncMock(),
        ensure_ownership_authorized=AsyncMock(),
        validate_update_request=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_extend_expiration_updates_and_logs(user):
    original = datetime.now(timezone.utc) + timedelta(days=1)
    new_date = datetime.now(timezone.utc) + timedelta(days=90)
    key = _make_key(tenant_id=user.tenant_id, expires_at=original)
    updated = _make_key(id=key.id, tenant_id=user.tenant_id, expires_at=new_date)
    repo = AsyncMock()
    repo.get.return_value = key
    repo.update.return_value = updated
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=_extend_policy_mock(),
        audit_service=audit,
        user=user,
    )

    response = await service.extend_expiration(
        key_id=key.id,
        request=ApiKeyExtendRequest(expires_at=new_date),
    )

    assert response.expires_at == new_date
    repo.update.assert_awaited_once()
    assert repo.update.call_args.kwargs["expires_at"] == new_date

    audit.log_async.assert_awaited_once()
    call = audit.log_async.call_args.kwargs
    assert call["action"] == ActionType.API_KEY_EXPIRATION_EXTENDED
    metadata = call["metadata"]
    assert metadata["changes"]["expires_at"]["old"] == original
    assert metadata["changes"]["expires_at"]["new"] == new_date
    assert metadata["extra"]["via"] == "standalone"


@pytest.mark.asyncio
async def test_extend_expiration_to_null_when_policy_permits(user):
    key = _make_key(
        tenant_id=user.tenant_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    updated = _make_key(id=key.id, tenant_id=user.tenant_id, expires_at=None)
    repo = AsyncMock()
    repo.get.return_value = key
    repo.update.return_value = updated
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=_extend_policy_mock(),
        audit_service=audit,
        user=user,
    )

    response = await service.extend_expiration(
        key_id=key.id,
        request=ApiKeyExtendRequest(expires_at=None),
    )

    assert response.expires_at is None
    assert repo.update.call_args.kwargs["expires_at"] is None


@pytest.mark.asyncio
async def test_extend_expiration_no_change_is_noop(user):
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    key = _make_key(tenant_id=user.tenant_id, expires_at=expires)
    repo = AsyncMock()
    repo.get.return_value = key
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=_extend_policy_mock(),
        audit_service=audit,
        user=user,
    )

    await service.extend_expiration(
        key_id=key.id,
        request=ApiKeyExtendRequest(expires_at=expires),
    )

    repo.update.assert_not_awaited()
    audit.log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_extend_expiration_rejects_revoked_key(user):
    key = _make_key(
        tenant_id=user.tenant_id,
        revoked_at=datetime.now(timezone.utc),
        state=ApiKeyState.REVOKED,
    )
    repo = AsyncMock()
    repo.get.return_value = key
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=_extend_policy_mock(),
        audit_service=audit,
        user=user,
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.extend_expiration(
            key_id=key.id,
            request=ApiKeyExtendRequest(
                expires_at=datetime.now(timezone.utc) + timedelta(days=30)
            ),
        )

    assert "revoked or expired" in exc.value.message
    repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_extend_expiration_rejects_expired_key(user):
    past = datetime.now(timezone.utc) - timedelta(days=1)
    key = _make_key(tenant_id=user.tenant_id, expires_at=past)
    repo = AsyncMock()
    repo.get.return_value = key
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=_extend_policy_mock(),
        audit_service=audit,
        user=user,
    )

    with pytest.raises(ApiKeyValidationError):
        await service.extend_expiration(
            key_id=key.id,
            request=ApiKeyExtendRequest(
                expires_at=datetime.now(timezone.utc) + timedelta(days=30)
            ),
        )
    repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_extend_expiration_rejects_past_date(user):
    key = _make_key(
        tenant_id=user.tenant_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=10),
    )
    repo = AsyncMock()
    repo.get.return_value = key
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=_extend_policy_mock(),
        audit_service=audit,
        user=user,
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.extend_expiration(
            key_id=key.id,
            request=ApiKeyExtendRequest(
                expires_at=datetime.now(timezone.utc) - timedelta(days=1)
            ),
        )
    assert "future" in exc.value.message


@pytest.mark.asyncio
async def test_extend_expiration_propagates_policy_violation(user):
    key = _make_key(
        tenant_id=user.tenant_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=10),
    )
    repo = AsyncMock()
    repo.get.return_value = key
    policy = _extend_policy_mock()
    policy.validate_update_request = AsyncMock(
        side_effect=ApiKeyValidationError(
            status_code=400,
            code="invalid_request",
            message="expires_at exceeds tenant max_expiration_days policy.",
        )
    )
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.extend_expiration(
            key_id=key.id,
            request=ApiKeyExtendRequest(
                expires_at=datetime.now(timezone.utc) + timedelta(days=400)
            ),
        )

    assert "max_expiration_days" in exc.value.message
    repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_rotate_with_update_expiration_logs_two_audits(user):
    original = datetime.now(timezone.utc) + timedelta(days=1)
    new_date = datetime.now(timezone.utc) + timedelta(days=90)
    key = _make_key(tenant_id=user.tenant_id, expires_at=original)
    rotated = _make_key(
        tenant_id=user.tenant_id, rotated_from_key_id=key.id, expires_at=new_date
    )
    repo = AsyncMock()
    repo.get.return_value = key
    repo.create.return_value = rotated
    repo.update.return_value = key
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(),
        ensure_ownership_authorized=AsyncMock(),
        validate_key_state=AsyncMock(),
        validate_update_request=AsyncMock(),
    )
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )

    await service.rotate_key(
        key_id=key.id,
        request=ApiKeyRotateRequest(update_expiration=True, expires_at=new_date),
    )

    create_kwargs = repo.create.call_args.kwargs
    assert create_kwargs["expires_at"] == new_date

    actions = [c.kwargs["action"] for c in audit.log_async.call_args_list]
    assert ActionType.API_KEY_ROTATED in actions
    assert ActionType.API_KEY_EXPIRATION_EXTENDED in actions

    extension_call = next(
        c
        for c in audit.log_async.call_args_list
        if c.kwargs["action"] == ActionType.API_KEY_EXPIRATION_EXTENDED
    )
    metadata = extension_call.kwargs["metadata"]
    assert metadata["extra"]["via"] == "rotation"


@pytest.mark.asyncio
async def test_purge_revoked_key_deletes_and_audits(user):
    key = _make_key(
        tenant_id=user.tenant_id,
        revoked_at=datetime.now(timezone.utc),
        state=ApiKeyState.REVOKED,
    )
    repo = AsyncMock()
    repo.get.return_value = key
    repo.delete.return_value = True
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(),
        ensure_ownership_authorized=AsyncMock(),
    )
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )

    await service.purge_key(key_id=key.id)

    repo.delete.assert_awaited_once_with(key_id=key.id, tenant_id=key.tenant_id)
    audit.log_async.assert_awaited_once()
    call = audit.log_async.call_args.kwargs
    assert call["action"] == ActionType.API_KEY_PURGED
    metadata = call["metadata"]
    assert metadata["extra"]["previous_state"] == "revoked"


@pytest.mark.asyncio
async def test_purge_expired_key_deletes(user):
    key = _make_key(
        tenant_id=user.tenant_id,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    repo = AsyncMock()
    repo.get.return_value = key
    repo.delete.return_value = True
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(),
        ensure_ownership_authorized=AsyncMock(),
    )
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )

    await service.purge_key(key_id=key.id)

    repo.delete.assert_awaited_once()
    metadata = audit.log_async.call_args.kwargs["metadata"]
    assert metadata["extra"]["previous_state"] == "expired"


@pytest.mark.asyncio
async def test_purge_active_key_rejected(user):
    key = _make_key(tenant_id=user.tenant_id)
    repo = AsyncMock()
    repo.get.return_value = key
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(),
        ensure_ownership_authorized=AsyncMock(),
    )
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.purge_key(key_id=key.id)

    assert "revoked or expired" in exc.value.message
    repo.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_purge_suspended_key_rejected(user):
    key = _make_key(
        tenant_id=user.tenant_id,
        suspended_at=datetime.now(timezone.utc),
        state=ApiKeyState.SUSPENDED,
    )
    repo = AsyncMock()
    repo.get.return_value = key
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(),
        ensure_ownership_authorized=AsyncMock(),
    )
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )

    with pytest.raises(ApiKeyValidationError):
        await service.purge_key(key_id=key.id)
    repo.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_rotate_with_update_expiration_but_same_date_skips_extension_event(user):
    """When update_expiration=true but the date is unchanged, only the rotation
    event is emitted — there is no expiration change to record."""
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    key = _make_key(tenant_id=user.tenant_id, expires_at=expires)
    rotated = _make_key(
        tenant_id=user.tenant_id, rotated_from_key_id=key.id, expires_at=expires
    )
    repo = AsyncMock()
    repo.get.return_value = key
    repo.create.return_value = rotated
    repo.update.return_value = key
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(),
        ensure_ownership_authorized=AsyncMock(),
        validate_key_state=AsyncMock(),
        validate_update_request=AsyncMock(),
    )
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )

    await service.rotate_key(
        key_id=key.id,
        request=ApiKeyRotateRequest(update_expiration=True, expires_at=expires),
    )

    actions = [c.kwargs["action"] for c in audit.log_async.call_args_list]
    assert actions == [ActionType.API_KEY_ROTATED]


@pytest.mark.asyncio
async def test_rotate_without_update_expiration_preserves_existing(user):
    original = datetime.now(timezone.utc) + timedelta(days=10)
    key = _make_key(tenant_id=user.tenant_id, expires_at=original)
    rotated = _make_key(
        tenant_id=user.tenant_id, rotated_from_key_id=key.id, expires_at=original
    )
    repo = AsyncMock()
    repo.get.return_value = key
    repo.create.return_value = rotated
    repo.update.return_value = key
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(),
        ensure_ownership_authorized=AsyncMock(),
        validate_key_state=AsyncMock(),
        validate_update_request=AsyncMock(),
    )
    audit = AsyncMock()

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )

    await service.rotate_key(key_id=key.id)

    assert repo.create.call_args.kwargs["expires_at"] == original
    actions = [c.kwargs["action"] for c in audit.log_async.call_args_list]
    assert actions == [ActionType.API_KEY_ROTATED]
    policy.validate_update_request.assert_not_awaited()
