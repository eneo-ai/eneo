from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from eneo.model_providers.domain.model_provider_service import ModelProviderService
from eneo.settings.encryption_service import EncryptionService


def _service(
    provider: SimpleNamespace,
    *,
    encryption_key: str | None = None,
) -> tuple[ModelProviderService, MagicMock]:
    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=provider)
    repository.get_by_name = AsyncMock(return_value=None)
    repository.update = AsyncMock(return_value=provider)
    repository.clear_strict_tool_schema_declarations = AsyncMock(return_value=1)
    service = ModelProviderService(
        repository=repository,
        encryption=EncryptionService(encryption_key),
    )
    return service, repository


def _provider(
    *,
    endpoint: str | None,
    credential_endpoint: str | None = None,
) -> SimpleNamespace:
    # Encrypted material this service instance cannot read: comparing the
    # endpoint must never depend on it.
    credentials: dict[str, str] = {"api_key": "gAAAAABunreadable-ciphertext"}
    if credential_endpoint is not None:
        credentials["endpoint"] = credential_endpoint
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Self-hosted",
        provider_type="openai",
        credentials=credentials,
        config={"endpoint": endpoint} if endpoint is not None else {},
        is_active=True,
    )


@pytest.mark.asyncio
async def test_moving_the_endpoint_withdraws_strict_tool_schema_declarations():
    provider = _provider(endpoint="https://gateway.invalid/v1")
    service, repository = _service(provider)

    await service.update(
        provider.id,
        config={"endpoint": "https://other-gateway.invalid/v1"},
    )

    repository.clear_strict_tool_schema_declarations.assert_awaited_once_with(
        provider.id
    )


@pytest.mark.asyncio
async def test_editing_a_provider_without_moving_the_endpoint_keeps_declarations():
    provider = _provider(endpoint="https://gateway.invalid/v1")
    service, repository = _service(provider)

    await service.update(provider.id, name="Renamed provider", is_active=False)

    repository.clear_strict_tool_schema_declarations.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_credential_endpoint_decides_like_it_does_at_request_time():
    # The credential resolver reads credentials before config, so a config-only
    # edit under a credential endpoint does not move the route.
    provider = _provider(
        endpoint="https://config.invalid/v1",
        credential_endpoint="https://credentials.invalid/v1",
    )
    service, repository = _service(provider)

    await service.update(provider.id, config={"endpoint": "https://other.invalid/v1"})

    repository.clear_strict_tool_schema_declarations.assert_not_awaited()


@pytest.mark.asyncio
async def test_replacing_the_credential_endpoint_withdraws_declarations():
    provider = _provider(
        endpoint="https://config.invalid/v1",
        credential_endpoint="https://credentials.invalid/v1",
    )
    service, repository = _service(
        provider,
        encryption_key=Fernet.generate_key().decode(),
    )

    await service.update(
        provider.id,
        credentials={"api_key": "rotated", "endpoint": "https://moved.invalid/v1"},
    )

    repository.clear_strict_tool_schema_declarations.assert_awaited_once_with(
        provider.id
    )


@pytest.mark.asyncio
async def test_an_empty_credential_endpoint_shadows_config_like_it_does_at_request_time():
    # Runtime stops at the empty credential value, so the config endpoint is not
    # in use and editing it moves nothing.
    provider = _provider(endpoint="https://config.invalid/v1", credential_endpoint="")
    service, repository = _service(provider)

    await service.update(provider.id, config={"endpoint": "https://other.invalid/v1"})

    repository.clear_strict_tool_schema_declarations.assert_not_awaited()


@pytest.mark.asyncio
async def test_dropping_an_empty_credential_endpoint_exposes_config_and_withdraws():
    provider = _provider(endpoint="https://config.invalid/v1", credential_endpoint="")
    service, repository = _service(
        provider,
        encryption_key=Fernet.generate_key().decode(),
    )

    await service.update(provider.id, credentials={"api_key": "rotated"})

    repository.clear_strict_tool_schema_declarations.assert_awaited_once_with(
        provider.id
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_type", "field", "withdraws"),
    [
        pytest.param("openai", "api_type", True, id="openai-api-type"),
        pytest.param("openai", "organization", True, id="openai-organization"),
        # OpenAI never sends api_version, so changing it moves no request.
        pytest.param("openai", "api_version", False, id="openai-api-version"),
        pytest.param("azure", "api_version", True, id="azure-api-version"),
    ],
)
async def test_only_settings_this_provider_sends_count_as_a_move(
    provider_type: str,
    field: str,
    withdraws: bool,
):
    provider = _provider(endpoint="https://gateway.invalid/v1")
    provider.provider_type = provider_type
    provider.config[field] = "before"
    service, repository = _service(provider)

    await service.update(provider.id, config={field: "after"})

    assert (
        repository.clear_strict_tool_schema_declarations.await_count == 1
    ) is withdraws


@pytest.mark.asyncio
async def test_a_provider_without_any_endpoint_keeps_declarations():
    provider = _provider(endpoint=None)
    service, repository = _service(provider)

    await service.update(provider.id, is_active=False)

    repository.clear_strict_tool_schema_declarations.assert_not_awaited()
