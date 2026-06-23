from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from intric.main.exceptions import BadRequestException
from intric.roles.permissions import Permission
from intric.roles.role import RoleInDB
from intric.tenants.tenant import TenantInDB, TenantUpdatePublic
from intric.tenants.tenant_service import TenantService


def _make_tenant(tenant_id: UUID | None = None) -> TenantInDB:
    return TenantInDB(
        id=tenant_id or uuid4(),
        name="tenant",
        display_name="Tenant",
        quota_limit=1000,
    )


def _make_role(tenant_id: UUID) -> RoleInDB:
    return RoleInDB(
        id=uuid4(),
        name="User",
        permissions=[Permission.ASSISTANTS],
        tenant_id=tenant_id,
        predefined_source="User",
    )


def _make_service(tenant: TenantInDB, role: RoleInDB | None) -> TenantService:
    repo = AsyncMock()
    repo.get.return_value = tenant
    repo.update_tenant.return_value = tenant

    role_repo = AsyncMock()
    role_repo.get_role.return_value = role

    return TenantService(
        repo=repo,
        completion_model_repo=AsyncMock(),
        embedding_model_repo=AsyncMock(),
        transcription_model_enable_service=AsyncMock(),
        role_repo=role_repo,
    )


async def test_update_tenant_accepts_default_role_from_same_tenant():
    tenant = _make_tenant()
    role = _make_role(tenant.id)
    service = _make_service(tenant, role)

    result = await service.update_tenant(
        TenantUpdatePublic(default_role_id=role.id),
        tenant.id,
    )

    assert result == tenant
    service.repo.update_tenant.assert_awaited_once()


async def test_update_tenant_rejects_default_role_from_other_tenant():
    tenant = _make_tenant()
    other_tenant_role = _make_role(uuid4())
    service = _make_service(tenant, other_tenant_role)

    with pytest.raises(BadRequestException, match="must belong to the tenant"):
        await service.update_tenant(
            TenantUpdatePublic(default_role_id=other_tenant_role.id),
            tenant.id,
        )

    service.repo.update_tenant.assert_not_awaited()


async def test_update_tenant_rejects_missing_default_role():
    tenant = _make_tenant()
    service = _make_service(tenant, None)

    with pytest.raises(BadRequestException, match="must belong to the tenant"):
        await service.update_tenant(
            TenantUpdatePublic(default_role_id=uuid4()),
            tenant.id,
        )

    service.repo.update_tenant.assert_not_awaited()


async def test_set_credential_rejects_missing_provider_fields_as_bad_request():
    tenant = _make_tenant()
    service = _make_service(tenant, None)

    with pytest.raises(BadRequestException, match="Credential validation failed"):
        await service.set_credential(
            tenant_id=tenant.id,
            provider="azure",
            api_key="azure-key",
            strict_mode=True,
        )

    service.repo.update_api_credential.assert_not_awaited()
