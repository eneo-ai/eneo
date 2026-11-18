from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.authentication.api_key_policy import ApiKeyPolicyService
from eneo.authentication.api_key_resolver import ApiKeyValidationError
from eneo.authentication.auth_models import (
    ApiKeyCreateRequest,
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyType,
    ResourcePermissionLevel,
    ResourcePermissions,
)
from eneo.roles.permissions import Permission


class DummyOriginRepo:
    def __init__(self, patterns: list[str]):
        self.patterns = patterns

    async def get_by_tenant(self, tenant_id):
        return []


class DummySpaceService:
    pass


def _service_with_user(patterns: list[str], *, permissions: list[object] | None = None):
    """patterns is unused after the central allowlist gate was dropped — kept
    in the signature for back-compat with existing call sites."""
    del patterns  # noqa: keep signature stable
    tenant = SimpleNamespace(api_key_policy={})
    user = SimpleNamespace(
        tenant=tenant, permissions=permissions or [], tenant_id=uuid4()
    )
    return ApiKeyPolicyService(
        api_key_repo=MagicMock(
            scope_is_flow_managed_assistant=AsyncMock(return_value=False)
        ),
        space_service=DummySpaceService(),
        user=user,
    )


@pytest.mark.asyncio
async def test_service_key_rejected_for_non_admin():
    """Non-admin user creating ownership=SERVICE gets ApiKeyValidationError with 403."""
    service = _service_with_user([], permissions=[])

    request = ApiKeyCreateRequest(
        name="Service key",
        key_type=ApiKeyType.SK,
        permission=ApiKeyPermission.READ,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        ownership=ApiKeyOwnership.SERVICE,
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.validate_create_request(request=request)

    assert exc.value.status_code == 403
    assert exc.value.code == "insufficient_permission"


@pytest.mark.asyncio
async def test_service_key_tenant_write_rejected_without_guardrails():
    """Admin user creating service + tenant scope + WRITE without IP or expiry gets 400."""
    service = _service_with_user([], permissions=[Permission.ADMIN])

    request = ApiKeyCreateRequest(
        name="Service key write",
        key_type=ApiKeyType.SK,
        permission=ApiKeyPermission.WRITE,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        ownership=ApiKeyOwnership.SERVICE,
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.validate_create_request(request=request)

    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_request"
    assert "IP allowlist or expiration" in exc.value.message


@pytest.mark.asyncio
async def test_service_key_tenant_admin_rejected_without_guardrails():
    """Admin user creating service + tenant scope + ADMIN without IP or expiry gets 400."""
    service = _service_with_user([], permissions=[Permission.ADMIN])

    request = ApiKeyCreateRequest(
        name="Service key admin",
        key_type=ApiKeyType.SK,
        permission=ApiKeyPermission.ADMIN,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        ownership=ApiKeyOwnership.SERVICE,
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.validate_create_request(request=request)

    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_request"
    assert "IP allowlist or expiration" in exc.value.message


@pytest.mark.asyncio
async def test_service_key_tenant_write_accepted_with_ip():
    """Admin user creating service + tenant + WRITE + allowed_ips passes validation."""
    service = _service_with_user([], permissions=[Permission.ADMIN])

    request = ApiKeyCreateRequest(
        name="Service key with IP",
        key_type=ApiKeyType.SK,
        permission=ApiKeyPermission.WRITE,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        ownership=ApiKeyOwnership.SERVICE,
        allowed_ips=["10.0.0.0/24"],
    )

    service.ensure_creator_authorized = AsyncMock(return_value=None)
    await service.validate_create_request(request=request)


@pytest.mark.asyncio
async def test_service_key_tenant_write_accepted_with_expiry():
    """Admin user creating service + tenant + ADMIN + expires_at passes validation."""
    service = _service_with_user([], permissions=[Permission.ADMIN])

    request = ApiKeyCreateRequest(
        name="Service key with expiry",
        key_type=ApiKeyType.SK,
        permission=ApiKeyPermission.ADMIN,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        ownership=ApiKeyOwnership.SERVICE,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )

    service.ensure_creator_authorized = AsyncMock(return_value=None)
    await service.validate_create_request(request=request)


@pytest.mark.asyncio
async def test_service_key_tenant_read_accepted_without_guardrails():
    """Admin user creating service + tenant + READ (no guardrail needed) passes."""
    service = _service_with_user([], permissions=[Permission.ADMIN])

    request = ApiKeyCreateRequest(
        name="Service key read",
        key_type=ApiKeyType.SK,
        permission=ApiKeyPermission.READ,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        ownership=ApiKeyOwnership.SERVICE,
    )

    service.ensure_creator_authorized = AsyncMock(return_value=None)
    await service.validate_create_request(request=request)


@pytest.mark.asyncio
async def test_service_key_uses_derived_resource_permission_for_guardrail():
    """Service keys cannot bypass guardrails with read permission + write/admin resources."""
    service = _service_with_user([], permissions=[Permission.ADMIN])

    request = ApiKeyCreateRequest(
        name="Service key derived admin",
        key_type=ApiKeyType.SK,
        permission=ApiKeyPermission.READ,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        ownership=ApiKeyOwnership.SERVICE,
        resource_permissions=ResourcePermissions(
            assistants=ResourcePermissionLevel.READ,
            apps=ResourcePermissionLevel.ADMIN,
            spaces=ResourcePermissionLevel.NONE,
            knowledge=ResourcePermissionLevel.NONE,
        ),
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await service.validate_create_request(request=request)

    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_request"
    assert "IP allowlist or expiration" in exc.value.message


@pytest.mark.asyncio
async def test_service_key_space_scoped_write_rejected_without_guardrails():
    """Service + space + ADMIN without IP/expiry is rejected (guardrail applies to all write/admin)."""
    service = _service_with_user([], permissions=[Permission.ADMIN])
    scope_id = uuid4()

    request = ApiKeyCreateRequest(
        name="Service key space",
        key_type=ApiKeyType.SK,
        permission=ApiKeyPermission.ADMIN,
        scope_type=ApiKeyScopeType.SPACE,
        scope_id=scope_id,
        ownership=ApiKeyOwnership.SERVICE,
    )

    service.ensure_creator_authorized = AsyncMock(return_value=None)
    with pytest.raises(ApiKeyValidationError, match="IP allowlist or expiration"):
        await service.validate_create_request(request=request)


@pytest.mark.asyncio
async def test_service_key_space_scoped_read_accepted_without_guardrails():
    """Service + space + READ (no guardrail needed for read) passes."""
    service = _service_with_user([], permissions=[Permission.ADMIN])
    scope_id = uuid4()

    request = ApiKeyCreateRequest(
        name="Service key space read",
        key_type=ApiKeyType.SK,
        permission=ApiKeyPermission.READ,
        scope_type=ApiKeyScopeType.SPACE,
        scope_id=scope_id,
        ownership=ApiKeyOwnership.SERVICE,
    )

    service.ensure_creator_authorized = AsyncMock(return_value=None)
    await service.validate_create_request(request=request)


def _space(*, personal: bool):
    return SimpleNamespace(is_personal=lambda: personal)


class _SpaceServiceStub:
    """ensure_creator_authorized reads the space and asks its actor."""

    def __init__(self, space, *, can_manage_api_keys: bool):
        self._space = space
        actor = SimpleNamespace(can_manage_api_keys=lambda: can_manage_api_keys)
        self.actor_manager = SimpleNamespace(
            get_space_actor_from_space=lambda space: actor
        )

    async def get_space(self, space_id):
        return self._space


@pytest.mark.asyncio
async def test_space_scope_is_decided_by_api_key_management_of_the_space():
    """A personal space can never be edited, so can_edit_space would refuse
    its owner; the creator check asks who manages the space's keys instead."""
    service = _service_with_user([], permissions=[])
    space = _space(personal=True)

    service.space_service = _SpaceServiceStub(space, can_manage_api_keys=True)
    assert (
        await service.ensure_creator_authorized(
            scope_type=ApiKeyScopeType.SPACE, scope_id=uuid4()
        )
        is space
    )

    service.space_service = _SpaceServiceStub(space, can_manage_api_keys=False)
    with pytest.raises(ApiKeyValidationError) as exc:
        await service.ensure_creator_authorized(
            scope_type=ApiKeyScopeType.SPACE, scope_id=uuid4()
        )
    assert exc.value.status_code == 403
    assert exc.value.code == "insufficient_permission"


@pytest.mark.asyncio
async def test_service_key_rejected_for_a_personal_space():
    """A personal space answers to its owner only, so an ownerless key scoped
    to one would authenticate and reach nothing."""
    service = _service_with_user([], permissions=[Permission.ADMIN])
    request = ApiKeyCreateRequest(
        name="Service key personal space",
        key_type=ApiKeyType.SK,
        permission=ApiKeyPermission.READ,
        scope_type=ApiKeyScopeType.SPACE,
        scope_id=uuid4(),
        ownership=ApiKeyOwnership.SERVICE,
    )

    service.ensure_creator_authorized = AsyncMock(return_value=_space(personal=True))
    with pytest.raises(ApiKeyValidationError) as exc:
        await service.validate_create_request(request=request)
    assert exc.value.status_code == 400
    assert "personal space" in exc.value.message

    service.ensure_creator_authorized = AsyncMock(return_value=_space(personal=False))
    await service.validate_create_request(request=request)


@pytest.mark.asyncio
async def test_user_key_accepted_for_a_personal_space():
    service = _service_with_user([], permissions=[])
    request = ApiKeyCreateRequest(
        name="My personal space key",
        key_type=ApiKeyType.SK,
        permission=ApiKeyPermission.WRITE,
        scope_type=ApiKeyScopeType.SPACE,
        scope_id=uuid4(),
        ownership=ApiKeyOwnership.USER,
    )
    space = _space(personal=True)
    service.ensure_creator_authorized = AsyncMock(return_value=space)
    assert await service.validate_create_request(request=request) is space
