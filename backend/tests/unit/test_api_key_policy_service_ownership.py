from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.authentication.api_key_policy import ApiKeyPolicyService
from intric.authentication.api_key_resolver import ApiKeyValidationError
from intric.authentication.auth_models import (
    ApiKeyCreateRequest,
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyType,
    ResourcePermissionLevel,
    ResourcePermissions,
)
from intric.roles.permissions import Permission


class DummyOriginRepo:
    def __init__(self, patterns: list[str]):
        self.patterns = patterns

    async def get_by_tenant(self, tenant_id):
        return []


class DummySpaceService:
    pass


def _service_with_user(patterns: list[str], *, permissions: list[object] | None = None):
    tenant = SimpleNamespace(api_key_policy={})
    user = SimpleNamespace(
        tenant=tenant, permissions=permissions or [], tenant_id=uuid4()
    )
    return ApiKeyPolicyService(
        allowed_origin_repo=DummyOriginRepo(patterns),
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
