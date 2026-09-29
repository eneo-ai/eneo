"""A provider's stored key is never sent to a destination it was not entered for."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException
from eneo.model_providers.domain.model_provider import ModelProvider
from eneo.model_providers.domain.model_provider_service import (
    ModelProviderService,
    effective_endpoint,
    normalize_destination,
)


def _provider(
    provider_type: str = "openai",
    *,
    config: dict | None = None,
    credentials: dict | None = None,
) -> ModelProvider:
    now = datetime.now(timezone.utc)
    return ModelProvider(
        id=uuid4(),
        tenant_id=uuid4(),
        name="provider",
        provider_type=provider_type,
        credentials={"api_key": "encrypted"} if credentials is None else credentials,
        config={} if config is None else config,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def _service(provider: ModelProvider) -> tuple[ModelProviderService, AsyncMock]:
    repository = AsyncMock()
    repository.get_by_id.return_value = provider
    repository.get_by_name.return_value = None
    repository.update.side_effect = lambda p: p
    repository.session = MagicMock()
    encryption = MagicMock()
    encryption.encrypt.side_effect = lambda value: f"enc({value})"
    return ModelProviderService(
        repository=repository, encryption=encryption
    ), repository


class TestDestinationNormalization:
    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("https://api.example.com", "https://api.example.com/"),
            ("https://api.example.com", "HTTPS://API.Example.com"),
            ("https://api.example.com", "https://api.example.com:443"),
            ("http://vllm:8000", "http://vllm:8000/"),
            ("http://vllm", "http://vllm:80"),
            ("https://api.example.com/v1", "https://api.example.com/v1/"),
        ],
    )
    def test_equivalent_destinations_compare_equal(self, left: str, right: str):
        assert normalize_destination(left) == normalize_destination(right)

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("https://api.example.com", "http://api.example.com"),
            ("https://api.example.com", "https://api.example.org"),
            ("https://api.example.com", "https://api.example.com:8443"),
            ("https://api.example.com", "https://api.example.com/v1"),
            ("https://api.example.com/v1", "https://api.example.com/v2"),
            ("https://api.example.com", "https://api.example.com?region=eu"),
        ],
    )
    def test_different_destinations_compare_unequal(self, left: str, right: str):
        assert normalize_destination(left) != normalize_destination(right)

    def test_blank_and_missing_are_no_destination(self):
        assert normalize_destination(None) is None
        assert normalize_destination("   ") is None

    def test_effective_endpoint_falls_back_to_the_provider_default(self):
        assert effective_endpoint("openai", {}) == "https://api.openai.com"
        assert (
            effective_endpoint("openai", {"endpoint": " "}) == "https://api.openai.com"
        )
        assert effective_endpoint("openai", {"endpoint": "https://x"}) == "https://x"
        assert effective_endpoint("hosted_vllm", {}) is None


class TestUpdateWithNewDestination:
    async def test_endpoint_change_without_credentials_is_rejected_before_writing(self):
        provider = _provider(config={"endpoint": "https://api.example.com"})
        service, repository = _service(provider)

        with pytest.raises(BadRequestException, match="new API key"):
            await service.update(
                provider.id, config={"endpoint": "https://other.example.com"}
            )

        repository.update.assert_not_awaited()
        assert provider.config == {"endpoint": "https://api.example.com"}
        assert provider.credentials == {"api_key": "encrypted"}

    @pytest.mark.parametrize("api_key", ["", "   ", "...abcd", "****", "••••"])
    async def test_blank_or_masked_replacement_is_rejected(self, api_key: str):
        provider = _provider(config={"endpoint": "https://api.example.com"})
        service, repository = _service(provider)

        with pytest.raises(BadRequestException):
            await service.update(
                provider.id,
                config={"endpoint": "https://other.example.com"},
                credentials={"api_key": api_key},
            )

        repository.update.assert_not_awaited()

    async def test_masked_value_is_rejected_even_without_destination_change(self):
        provider = _provider(config={"endpoint": "https://api.example.com"})
        service, repository = _service(provider)

        with pytest.raises(BadRequestException, match="masked"):
            await service.update(provider.id, credentials={"api_key": "...abcd"})

        repository.update.assert_not_awaited()

    async def test_endpoint_change_with_replacement_key_is_stored_encrypted(self):
        provider = _provider(config={"endpoint": "https://api.example.com"})
        service, repository = _service(provider)

        updated = await service.update(
            provider.id,
            config={"endpoint": "https://other.example.com"},
            credentials={"api_key": "sk-new"},
        )

        repository.update.assert_awaited_once()
        assert updated.config["endpoint"] == "https://other.example.com"
        assert updated.credentials["api_key"] == "enc(sk-new)"

    @pytest.mark.parametrize(
        "equivalent",
        [
            "https://api.example.com/",
            "HTTPS://API.EXAMPLE.COM",
            "https://api.example.com:443",
        ],
    )
    async def test_equivalent_endpoint_keeps_the_stored_key(self, equivalent: str):
        provider = _provider(config={"endpoint": "https://api.example.com"})
        service, repository = _service(provider)

        updated = await service.update(provider.id, config={"endpoint": equivalent})

        repository.update.assert_awaited_once()
        assert updated.credentials == {"api_key": "encrypted"}

    async def test_name_only_edit_keeps_the_stored_key(self):
        provider = _provider(config={"endpoint": "https://api.example.com"})
        service, repository = _service(provider)

        updated = await service.update(provider.id, name="renamed")

        repository.update.assert_awaited_once()
        assert updated.name == "renamed"
        assert updated.credentials == {"api_key": "encrypted"}

    async def test_setting_the_default_endpoint_explicitly_is_not_a_change(self):
        provider = _provider("openai", config={})
        service, repository = _service(provider)

        await service.update(
            provider.id, config={"endpoint": "https://api.openai.com/"}
        )

        repository.update.assert_awaited_once()

    async def test_leaving_the_default_endpoint_requires_a_new_key(self):
        provider = _provider("openai", config={})
        service, repository = _service(provider)

        with pytest.raises(BadRequestException, match="new API key"):
            await service.update(
                provider.id, config={"endpoint": "https://proxy.example.com"}
            )

        repository.update.assert_not_awaited()

    async def test_credentialless_provider_may_change_endpoint(self):
        provider = _provider(
            "hosted_vllm", config={"endpoint": "http://vllm-a:8000"}, credentials={}
        )
        service, repository = _service(provider)

        updated = await service.update(
            provider.id, config={"endpoint": "http://vllm-b:8000"}
        )

        repository.update.assert_awaited_once()
        assert updated.config["endpoint"] == "http://vllm-b:8000"
