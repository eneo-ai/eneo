from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException
from eneo.modules.module import (
    ModuleClientConfig,
    ModuleInDB,
    ModuleTenantClientConfig,
)
from eneo.modules.module_router import update_module_client_config

TENANT_ID = uuid4()
MODULE_ID = uuid4()
SERVICE_KEY_ID = uuid4()
REDIRECT_URI = "https://module.example.com/auth/callback"
UPDATED_REDIRECT_URI = "https://module.example.com/login/callback"


def make_module() -> ModuleInDB:
    return ModuleInDB(
        id=MODULE_ID,
        name="test-module",
        created_at=None,
        updated_at=None,
    )


def make_config(**overrides) -> ModuleTenantClientConfig:
    values = {
        "tenant_id": TENANT_ID,
        "module_id": MODULE_ID,
        "redirect_uris": [REDIRECT_URI],
        "service_key_id": SERVICE_KEY_ID,
    }
    values.update(overrides)
    return ModuleTenantClientConfig(**values)


def make_container():
    module_repo = AsyncMock()
    module_repo.get_module.return_value = make_module()
    module_repo.get_module_client_config.return_value = make_config()
    module_repo.update_client_config.return_value = make_config()

    broker = AsyncMock()
    audit_service = AsyncMock()

    container = MagicMock()
    container.module_repo.return_value = module_repo
    container.module_auth_broker.return_value = broker
    container.audit_service.return_value = audit_service
    return container, module_repo, broker, audit_service


async def test_partial_patch_preserves_omitted_service_key_contract():
    container, module_repo, broker, _audit_service = make_container()
    updated = make_config(redirect_uris=[UPDATED_REDIRECT_URI])
    module_repo.update_client_config.return_value = updated
    patch = ModuleClientConfig(redirect_uris=[UPDATED_REDIRECT_URI])

    result = await update_module_client_config(
        tenant_id=TENANT_ID,
        module_id=MODULE_ID,
        config=patch,
        container=container,
    )

    assert result.service_key_id == SERVICE_KEY_ID
    assert result.redirect_uris == [UPDATED_REDIRECT_URI]
    broker.validate_client_config_service_key.assert_not_awaited()
    persisted_patch = module_repo.update_client_config.await_args.kwargs["config"]
    assert persisted_patch.update_values() == {"redirect_uris": [UPDATED_REDIRECT_URI]}


async def test_new_service_key_is_validated_before_persistence():
    container, module_repo, broker, _audit_service = make_container()
    replacement_key_id = uuid4()
    patch = ModuleClientConfig(service_key_id=replacement_key_id)

    await update_module_client_config(
        tenant_id=TENANT_ID,
        module_id=MODULE_ID,
        config=patch,
        container=container,
    )

    broker.validate_client_config_service_key.assert_awaited_once_with(
        tenant_id=TENANT_ID,
        service_key_id=replacement_key_id,
    )
    module_repo.update_client_config.assert_awaited_once()


async def test_invalid_service_key_is_not_persisted():
    container, module_repo, broker, _audit_service = make_container()
    broker.validate_client_config_service_key.side_effect = BadRequestException(
        "invalid module key"
    )

    with pytest.raises(BadRequestException, match="invalid module key"):
        await update_module_client_config(
            tenant_id=TENANT_ID,
            module_id=MODULE_ID,
            config=ModuleClientConfig(service_key_id=uuid4()),
            container=container,
        )

    module_repo.update_client_config.assert_not_awaited()


async def test_explicit_null_clears_service_key_without_validation():
    container, module_repo, broker, _audit_service = make_container()
    module_repo.update_client_config.return_value = make_config(service_key_id=None)

    result = await update_module_client_config(
        tenant_id=TENANT_ID,
        module_id=MODULE_ID,
        config=ModuleClientConfig(service_key_id=None),
        container=container,
    )

    assert result.service_key_id is None
    broker.validate_client_config_service_key.assert_not_awaited()


async def test_empty_patch_is_rejected_before_database_access():
    container, module_repo, _broker, _audit_service = make_container()

    with pytest.raises(BadRequestException, match="at least one field"):
        await update_module_client_config(
            tenant_id=TENANT_ID,
            module_id=MODULE_ID,
            config=ModuleClientConfig(),
            container=container,
        )

    module_repo.get_module.assert_not_awaited()
