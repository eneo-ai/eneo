from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.modules.module import (
    ModuleInDB,
    ModuleInstallation,
    ModuleInstallationConfig,
    ModuleTenantAssignment,
    ModuleTenantClientConfig,
)
from eneo.modules.module_installation_service import ModuleInstallationService

TENANT_ID = uuid4()
OTHER_TENANT_ID = uuid4()
USER_ID = uuid4()
MODULE_ID = uuid4()
SERVICE_KEY_ID = uuid4()
REDIRECT_URI = "https://module.example.com/auth/callback"


def make_module() -> ModuleInDB:
    return ModuleInDB(
        id=MODULE_ID,
        name="test-module",
        created_at=None,
        updated_at=None,
    )


def make_client_config() -> ModuleTenantClientConfig:
    return ModuleTenantClientConfig(
        tenant_id=TENANT_ID,
        module_id=MODULE_ID,
        redirect_uris=[REDIRECT_URI],
        service_key_id=SERVICE_KEY_ID,
    )


def make_installation() -> ModuleInstallation:
    return ModuleInstallation(
        module_id=MODULE_ID,
        module_key="test-module",
        redirect_uris=[REDIRECT_URI],
        service_key_id=SERVICE_KEY_ID,
    )


def make_service() -> tuple[
    ModuleInstallationService,
    AsyncMock,
    AsyncMock,
    AsyncMock,
    AsyncMock,
]:
    user = MagicMock(id=USER_ID, tenant_id=TENANT_ID)
    module_repo = AsyncMock()
    module_repo.get_or_add.return_value = make_module()
    module_repo.get_installation.return_value = make_installation()
    module_repo.update_client_config.return_value = make_client_config()
    tenant_service = AsyncMock()
    tenant_service.enable_module.return_value = ModuleTenantAssignment(
        tenant_id=TENANT_ID,
        module_id=MODULE_ID,
        module_key="test-module",
        enabled=True,
        changed=True,
    )
    module_auth_broker = AsyncMock()
    audit_service = AsyncMock()
    service = ModuleInstallationService(
        user=user,
        module_repo=module_repo,
        tenant_service=tenant_service,
        module_auth_broker=module_auth_broker,
        audit_service=audit_service,
    )
    return service, module_repo, tenant_service, module_auth_broker, audit_service


async def test_list_installations_derives_tenant_from_authenticated_user():
    service, module_repo, _tenant_service, _broker, _audit_service = make_service()
    module_repo.get_installations.return_value = [make_installation()]

    result = await service.list_installations()

    assert result == [make_installation()]
    module_repo.get_installations.assert_awaited_once_with(TENANT_ID)


async def test_invalid_service_key_stops_before_registry_or_assignment_writes():
    service, module_repo, tenant_service, broker, _audit_service = make_service()
    broker.validate_client_config_service_key.side_effect = BadRequestException(
        "invalid module key"
    )

    with pytest.raises(BadRequestException, match="invalid module key"):
        await service.install(
            module_key="test-module",
            config=ModuleInstallationConfig(
                redirect_uris=[REDIRECT_URI],
                service_key_id=SERVICE_KEY_ID,
            ),
        )

    module_repo.get_or_add.assert_not_awaited()
    tenant_service.enable_module.assert_not_awaited()
    module_repo.update_client_config.assert_not_awaited()


async def test_install_uses_one_tenant_implicit_complete_command():
    service, module_repo, tenant_service, broker, audit_service = make_service()

    result = await service.install(
        module_key="test-module",
        config=ModuleInstallationConfig(
            redirect_uris=[REDIRECT_URI],
            service_key_id=SERVICE_KEY_ID,
        ),
    )

    assert result == make_installation()
    broker.validate_client_config_service_key.assert_awaited_once_with(
        tenant_id=TENANT_ID,
        service_key_id=SERVICE_KEY_ID,
    )
    tenant_service.enable_module.assert_awaited_once_with(
        tenant_id=TENANT_ID,
        module_id=MODULE_ID,
    )
    persisted = module_repo.update_client_config.await_args.kwargs
    assert persisted["tenant_id"] == TENANT_ID
    assert persisted["module_id"] == MODULE_ID
    assert persisted["config"].update_values() == {
        "redirect_uris": [REDIRECT_URI],
        "service_key_id": SERVICE_KEY_ID,
    }
    assert audit_service.log.await_count == 2


async def test_repeated_identical_install_is_an_audit_noop():
    service, module_repo, tenant_service, _broker, audit_service = make_service()
    tenant_service.enable_module.return_value = ModuleTenantAssignment(
        tenant_id=TENANT_ID,
        module_id=MODULE_ID,
        module_key="test-module",
        enabled=True,
        changed=False,
    )
    module_repo.get_module_client_config.return_value = make_client_config()

    result = await service.install(
        module_key="test-module",
        config=ModuleInstallationConfig(
            redirect_uris=[REDIRECT_URI],
            service_key_id=SERVICE_KEY_ID,
        ),
    )

    assert result == make_installation()
    audit_service.log.assert_not_awaited()


async def test_uninstall_missing_module_does_not_touch_tenant_assignment():
    service, module_repo, tenant_service, _broker, _audit_service = make_service()
    module_repo.get_module_by_key.return_value = None

    with pytest.raises(NotFoundException, match="Module not found"):
        await service.uninstall(module_key="missing-module")

    tenant_service.disable_module.assert_not_awaited()


async def test_uninstall_derives_tenant_and_returns_tenant_free_result():
    service, module_repo, tenant_service, _broker, audit_service = make_service()
    module_repo.get_module_by_key.return_value = make_module()
    tenant_service.disable_module.return_value = ModuleTenantAssignment(
        tenant_id=OTHER_TENANT_ID,
        module_id=MODULE_ID,
        module_key="test-module",
        enabled=False,
        changed=True,
    )

    result = await service.uninstall(module_key="test-module")

    tenant_service.disable_module.assert_awaited_once_with(
        tenant_id=TENANT_ID,
        module_id=MODULE_ID,
    )
    assert result.model_dump() == {
        "module_id": MODULE_ID,
        "module_key": "test-module",
        "enabled": False,
        "changed": True,
    }
    audit_service.log.assert_awaited_once()
