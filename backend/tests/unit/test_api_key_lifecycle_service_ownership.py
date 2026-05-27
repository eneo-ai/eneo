from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from intric.authentication.api_key_lifecycle import ApiKeyLifecycleService
from intric.authentication.api_key_resolver import ApiKeyValidationError
from intric.authentication.auth_models import (
    ApiKeyCreateRequest,
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyRotateRequest,
    ApiKeyScopeType,
    ApiKeyType,
    ApiKeyUpdateRequest,
    ServicePrincipalInDB,
    ServicePrincipalState,
)
from tests.unit.api_key_test_utils import make_api_key


def _make_key(**overrides: object):
    return make_api_key(
        default_permission=ApiKeyPermission.WRITE,
        **overrides,
    )


def _make_service_principal(
    *, tenant_id: UUID, scope_type: ApiKeyScopeType = ApiKeyScopeType.TENANT
) -> ServicePrincipalInDB:
    return ServicePrincipalInDB(
        id=uuid4(),
        tenant_id=tenant_id,
        display_name="Service Principal",
        description=None,
        scope_type=scope_type,
        scope_id=None,
        state=ServicePrincipalState.ACTIVE,
    )


@pytest.fixture()
def user():
    return SimpleNamespace(id=uuid4(), email="user@example.com", tenant_id=uuid4())


@pytest.mark.asyncio
async def test_create_service_key_creates_and_links_service_principal(user):
    principal = _make_service_principal(tenant_id=user.tenant_id)
    key = _make_key(
        tenant_id=user.tenant_id,
        ownership=ApiKeyOwnership.SERVICE,
        owner_user_id=None,
        service_principal_id=principal.id,
    )
    repo = AsyncMock()
    repo.create_service_principal.return_value = principal
    repo.create.return_value = key
    policy = SimpleNamespace(validate_create_request=AsyncMock(return_value=None))

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=None,
        user=user,
    )

    request = ApiKeyCreateRequest(
        name="Service Key",
        key_type=ApiKeyType.SK,
        permission=ApiKeyPermission.WRITE,
        scope_type=ApiKeyScopeType.TENANT,
        ownership=ApiKeyOwnership.SERVICE,
    )

    await service.create_key(request)

    repo.create_service_principal.assert_awaited_once_with(
        tenant_id=user.tenant_id,
        display_name="Service Key",
        description=None,
        scope_type=ApiKeyScopeType.TENANT.value,
        scope_id=None,
        created_by_user_id=user.id,
    )
    repo.create.assert_awaited_once()
    assert repo.create.call_args.kwargs["owner_user_id"] is None
    assert repo.create.call_args.kwargs["service_principal_id"] == principal.id


@pytest.mark.asyncio
async def test_create_user_key_sets_owner(user):
    key = _make_key(tenant_id=user.tenant_id, owner_user_id=user.id)
    repo = AsyncMock()
    repo.create.return_value = key
    policy = SimpleNamespace(validate_create_request=AsyncMock(return_value=None))

    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=None,
        user=user,
    )

    request = ApiKeyCreateRequest(
        name="User Key",
        key_type=ApiKeyType.SK,
        permission=ApiKeyPermission.WRITE,
        scope_type=ApiKeyScopeType.TENANT,
        ownership=ApiKeyOwnership.USER,
    )

    await service.create_key(request)

    repo.create.assert_awaited_once()
    assert repo.create.call_args.kwargs["owner_user_id"] == user.id
    assert repo.create.call_args.kwargs["service_principal_id"] is None
    repo.create_service_principal.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_service_key_audit_uses_created_service_principal(user):
    principal = _make_service_principal(tenant_id=user.tenant_id)
    key = _make_key(
        tenant_id=user.tenant_id,
        ownership=ApiKeyOwnership.SERVICE,
        owner_user_id=None,
        service_principal_id=principal.id,
    )
    repo = AsyncMock()
    repo.create_service_principal.return_value = principal
    repo.create.return_value = key
    policy = SimpleNamespace(validate_create_request=AsyncMock(return_value=None))
    audit = AsyncMock()
    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )

    await service.create_key(
        ApiKeyCreateRequest(
            name="Audited Service",
            key_type=ApiKeyType.SK,
            permission=ApiKeyPermission.WRITE,
            scope_type=ApiKeyScopeType.TENANT,
            ownership=ApiKeyOwnership.SERVICE,
        )
    )

    audit.log_async.assert_awaited_once()
    metadata = audit.log_async.await_args.kwargs["metadata"]
    assert metadata["extra"]["service_principal_id"] == str(key.service_principal_id)


@pytest.mark.asyncio
async def test_rotate_service_key_keeps_service_principal_across_credentials(user):
    principal_id = uuid4()
    existing_key = _make_key(
        tenant_id=user.tenant_id,
        ownership=ApiKeyOwnership.SERVICE,
        owner_user_id=None,
        service_principal_id=principal_id,
    )
    rotated_key = _make_key(
        tenant_id=user.tenant_id,
        ownership=ApiKeyOwnership.SERVICE,
        owner_user_id=None,
        service_principal_id=principal_id,
        rotated_from_key_id=existing_key.id,
    )
    repo = AsyncMock()
    repo.get.return_value = existing_key
    repo.create.return_value = rotated_key
    repo.update.return_value = existing_key
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(return_value=None),
        ensure_ownership_authorized=AsyncMock(return_value=None),
        validate_key_state=AsyncMock(return_value=None),
    )
    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=None,
        user=user,
    )

    await service.rotate_key(key_id=existing_key.id, request=ApiKeyRotateRequest())

    repo.create.assert_awaited_once()
    assert repo.create.call_args.kwargs["service_principal_id"] == principal_id
    assert repo.create.call_args.kwargs["rotated_from_key_id"] == existing_key.id


@pytest.mark.asyncio
async def test_rotate_service_key_audit_uses_rotated_service_principal(user):
    principal_id = uuid4()
    existing_key = _make_key(
        tenant_id=user.tenant_id,
        ownership=ApiKeyOwnership.SERVICE,
        owner_user_id=None,
        service_principal_id=principal_id,
    )
    rotated_key = _make_key(
        tenant_id=user.tenant_id,
        ownership=ApiKeyOwnership.SERVICE,
        owner_user_id=None,
        service_principal_id=principal_id,
        rotated_from_key_id=existing_key.id,
    )
    repo = AsyncMock()
    repo.get.return_value = existing_key
    repo.create.return_value = rotated_key
    repo.update.return_value = existing_key
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(return_value=None),
        ensure_ownership_authorized=AsyncMock(return_value=None),
        validate_key_state=AsyncMock(return_value=None),
    )
    audit = AsyncMock()
    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=audit,
        user=user,
    )

    await service.rotate_key(key_id=existing_key.id, request=ApiKeyRotateRequest())

    audit.log_async.assert_awaited_once()
    metadata = audit.log_async.await_args.kwargs["metadata"]
    assert metadata["extra"]["service_principal_id"] == str(
        rotated_key.service_principal_id
    )


@pytest.mark.asyncio
async def test_rotate_service_key_without_service_principal_fails_closed(user):
    existing_key = _make_key(
        tenant_id=user.tenant_id,
        ownership=ApiKeyOwnership.SERVICE,
        owner_user_id=None,
        service_principal_id=None,
    )
    repo = AsyncMock()
    repo.get.return_value = existing_key
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(return_value=None),
        ensure_ownership_authorized=AsyncMock(return_value=None),
        validate_key_state=AsyncMock(return_value=None),
    )
    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=None,
        user=user,
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.rotate_key(key_id=existing_key.id, request=ApiKeyRotateRequest())

    assert exc.value.code == "service_principal_missing"
    repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_service_key_syncs_service_principal_display(user):
    principal_id = uuid4()
    existing_key = _make_key(
        tenant_id=user.tenant_id,
        ownership=ApiKeyOwnership.SERVICE,
        owner_user_id=None,
        service_principal_id=principal_id,
        name="Old Service",
        description="old description",
    )
    updated_key = _make_key(
        id=existing_key.id,
        tenant_id=user.tenant_id,
        ownership=ApiKeyOwnership.SERVICE,
        owner_user_id=None,
        service_principal_id=principal_id,
        name="New Service",
        description="new description",
    )
    repo = AsyncMock()
    repo.get.return_value = existing_key
    repo.update.return_value = updated_key
    repo.update_service_principal_display.return_value = _make_service_principal(
        tenant_id=user.tenant_id
    )
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(return_value=None),
        ensure_ownership_authorized=AsyncMock(return_value=None),
        validate_update_request=AsyncMock(return_value=None),
    )
    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=None,
        user=user,
    )

    await service.update_key(
        key_id=existing_key.id,
        request=ApiKeyUpdateRequest(name="New Service", description="new description"),
    )

    repo.update_service_principal_display.assert_awaited_once_with(
        service_principal_id=principal_id,
        tenant_id=user.tenant_id,
        display_name="New Service",
        description="new description",
    )


@pytest.mark.asyncio
async def test_concurrent_service_key_rotations_share_stable_principal(user):
    principal_id = uuid4()
    existing_key = _make_key(
        tenant_id=user.tenant_id,
        ownership=ApiKeyOwnership.SERVICE,
        owner_user_id=None,
        service_principal_id=principal_id,
    )
    repo = AsyncMock()
    repo.get.return_value = existing_key
    repo.create.side_effect = [
        _make_key(
            tenant_id=user.tenant_id,
            ownership=ApiKeyOwnership.SERVICE,
            owner_user_id=None,
            service_principal_id=principal_id,
            rotated_from_key_id=existing_key.id,
        ),
        _make_key(
            tenant_id=user.tenant_id,
            ownership=ApiKeyOwnership.SERVICE,
            owner_user_id=None,
            service_principal_id=principal_id,
            rotated_from_key_id=existing_key.id,
        ),
    ]
    repo.update.return_value = existing_key
    policy = SimpleNamespace(
        ensure_manage_authorized=AsyncMock(return_value=None),
        ensure_ownership_authorized=AsyncMock(return_value=None),
        validate_key_state=AsyncMock(return_value=None),
    )
    service = ApiKeyLifecycleService(
        api_key_repo=repo,
        policy_service=policy,
        audit_service=None,
        user=user,
    )

    await asyncio.gather(
        service.rotate_key(key_id=existing_key.id, request=ApiKeyRotateRequest()),
        service.rotate_key(key_id=existing_key.id, request=ApiKeyRotateRequest()),
    )

    assert repo.create.await_count == 2
    assert {
        call.kwargs["service_principal_id"] for call in repo.create.await_args_list
    } == {principal_id}
