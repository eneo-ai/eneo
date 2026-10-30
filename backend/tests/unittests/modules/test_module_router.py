from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.authentication.auth_models import ApiKeyListResponse, ApiKeyV2
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


def make_client_config(**overrides) -> ModuleTenantClientConfig:
    values = {
        "tenant_id": TENANT_ID,
        "module_id": MODULE_ID,
        "redirect_uris": [REDIRECT_URI],
        "service_key_id": SERVICE_KEY_ID,
    }
    values.update(overrides)
    return ModuleTenantClientConfig(**values)


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
    module_repo.get_module_client_config.return_value = make_client_config()
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


async def test_list_service_keys_delegates_bounded_query_to_module_owner():
    service, _module_repo, _tenant_service, broker, _audit_service = make_service()
    expected = ApiKeyListResponse(items=[], limit=50, next_cursor=None)
    broker.list_client_config_service_keys.return_value = expected

    result = await service.list_service_keys(
        limit=50,
        cursor=None,
        search="reports",
    )

    assert result == expected
    broker.list_client_config_service_keys.assert_awaited_once_with(
        tenant_id=TENANT_ID,
        limit=50,
        cursor=None,
        search="reports",
    )


async def test_get_service_key_delegates_exact_lookup_to_module_owner():
    service, _module_repo, _tenant_service, broker, _audit_service = make_service()
    key = MagicMock(spec=ApiKeyV2)
    broker.get_client_config_service_key.return_value = key

    result = await service.get_service_key(service_key_id=SERVICE_KEY_ID)

    assert result is key
    broker.get_client_config_service_key.assert_awaited_once_with(
        tenant_id=TENANT_ID,
        service_key_id=SERVICE_KEY_ID,
    )


async def test_invalid_service_key_prevents_binding_and_audit():
    """The key is validated (and locked) last, immediately before the config
    write; the function-scoped transaction rolls back the registry and
    assignment writes that precede it."""
    service, module_repo, tenant_service, broker, audit_service = make_service()
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

    module_repo.get_or_add.assert_awaited_once()
    tenant_service.enable_module.assert_awaited_once()
    module_repo.update_client_config.assert_not_awaited()
    audit_service.log.assert_not_awaited()


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
    module_repo.update_client_config.assert_awaited_once_with(
        tenant_id=TENANT_ID,
        module_id=MODULE_ID,
        redirect_uris=[REDIRECT_URI],
        service_key_id=SERVICE_KEY_ID,
    )
    assert audit_service.log.await_count == 2


async def test_fresh_install_audits_true_null_before_image():
    """A row created by this transaction has no pre-image: the config audit
    event must record before=None, not a fabricated empty config."""
    service, module_repo, _tenant_service, _broker, audit_service = make_service()

    await service.install(
        module_key="test-module",
        config=ModuleInstallationConfig(
            redirect_uris=[REDIRECT_URI],
            service_key_id=SERVICE_KEY_ID,
        ),
    )

    module_repo.get_module_client_config.assert_not_awaited()
    config_log = audit_service.log.await_args_list[-1].kwargs
    assert config_log["metadata"]["before"] is None
    assert config_log["metadata"]["after"] == make_client_config().model_dump(
        mode="json"
    )


async def test_repeated_identical_install_is_an_audit_noop():
    service, module_repo, tenant_service, _broker, audit_service = make_service()
    tenant_service.enable_module.return_value = ModuleTenantAssignment(
        tenant_id=TENANT_ID,
        module_id=MODULE_ID,
        module_key="test-module",
        enabled=True,
        changed=False,
    )

    result = await service.install(
        module_key="test-module",
        config=ModuleInstallationConfig(
            redirect_uris=[REDIRECT_URI],
            service_key_id=SERVICE_KEY_ID,
        ),
    )

    assert result == make_installation()
    module_repo.get_module_client_config.assert_awaited_once()
    audit_service.log.assert_not_awaited()


async def test_install_with_null_service_key_unbinds_without_validation():
    service, module_repo, _tenant_service, broker, _audit_service = make_service()
    module_repo.update_client_config.return_value = make_client_config(
        service_key_id=None
    )

    result = await service.install(
        module_key="test-module",
        config=ModuleInstallationConfig(
            redirect_uris=[REDIRECT_URI],
            service_key_id=None,
        ),
    )

    broker.validate_client_config_service_key.assert_not_awaited()
    persisted = module_repo.update_client_config.await_args.kwargs
    assert persisted["service_key_id"] is None
    assert result.service_key_id is None
    assert result.configured is False


async def test_uninstall_unknown_module_is_not_found():
    service, module_repo, tenant_service, _broker, _audit_service = make_service()
    module_repo.get_module_by_key.return_value = None

    with pytest.raises(NotFoundException, match="not installed"):
        await service.uninstall(module_key="missing-module")

    tenant_service.disable_module.assert_not_awaited()


async def test_uninstall_of_module_installed_elsewhere_is_the_same_not_found():
    """The global registry must not be a cross-tenant existence oracle: a key
    another organization registered answers exactly like an unknown key."""
    service, module_repo, tenant_service, _broker, _audit_service = make_service()
    module_repo.get_module_by_key.return_value = make_module()
    module_repo.get_module_client_config.return_value = None

    with pytest.raises(NotFoundException, match="not installed"):
        await service.uninstall(module_key="test-module")

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
