from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from litellm.exceptions import BadRequestError
from tenacity import wait_fixed

from eneo.embedding_models.infrastructure.adapters.litellm_embeddings import (
    LiteLLMEmbeddingAdapter,
)
from eneo.main.exceptions import (
    APIKeyNotConfiguredException,
    ProviderRejectedRequestException,
)
from eneo.model_providers.infrastructure import litellm_transport
from eneo.model_providers.infrastructure.litellm_provider import (
    build_litellm_model_name,
    build_litellm_provider_kwargs,
)
from eneo.model_providers.infrastructure.litellm_transport import (
    INVALID_REQUEST_MESSAGE,
    is_provider_unavailable_error,
    raise_provider_unavailable,
    raise_public_litellm_error,
)
from eneo.tenants.provider_field_config import get_required_fields


def test_build_litellm_model_name_is_canonical():
    assert (
        build_litellm_model_name("anthropic", "claude-sonnet-4")
        == "anthropic/claude-sonnet-4"
    )


def test_hosted_vllm_does_not_require_api_key():
    resolver = Mock(provider_type="hosted_vllm")
    resolver.get_api_key.return_value = None
    resolver.get_credential_field.side_effect = lambda *, field, required=False: (
        "https://models.example/v1" if field == "endpoint" else None
    )

    kwargs = build_litellm_provider_kwargs(resolver)

    resolver.get_api_key.assert_called_once_with(required=False)
    assert kwargs == {"api_base": "https://models.example/v1"}
    assert get_required_fields("hosted_vllm") == {"endpoint"}


def test_azure_provider_fields_are_resolved_once_from_canonical_definition():
    values = {
        "endpoint": "https://azure.example",
        "api_version": "2026-01-01",
        "deployment_name": "gpt-4o-prod",
    }
    resolver = Mock(provider_type="azure")
    resolver.get_api_key.return_value = "secret"
    resolver.get_credential_field.side_effect = (
        lambda *, field, required=False: values.get(field)
    )

    kwargs = build_litellm_provider_kwargs(resolver)

    assert kwargs == {
        "api_key": "secret",
        "api_base": "https://azure.example",
        "api_version": "2026-01-01",
    }


def test_bad_request_error_does_not_leak_provider_details():
    provider_error = BadRequestError(
        message="secret upstream deployment details",
        model="gpt-4o",
        llm_provider="openai",
    )

    with pytest.raises(ProviderRejectedRequestException) as exc_info:
        raise_public_litellm_error(
            provider_error,
            provider_type="openai",
            is_unavailable=is_provider_unavailable_error,
            raise_unavailable=raise_provider_unavailable,
        )

    assert str(exc_info.value) == INVALID_REQUEST_MESSAGE
    assert "secret upstream" not in str(exc_info.value)
    assert exc_info.value.code == "provider_rejected_request"


@pytest.mark.asyncio
async def test_provider_rejected_embedding_request_is_not_retried(monkeypatch):
    attempts = 0

    async def rejecting_aembedding(**kwargs):
        nonlocal attempts
        attempts += 1
        raise BadRequestError(
            message="invalid dimensions", model="m", llm_provider="openai"
        )

    monkeypatch.setattr(litellm_transport, "aembedding", rejecting_aembedding)
    adapter = LiteLLMEmbeddingAdapter(
        model=SimpleNamespace(
            name="m",
            family=None,
            litellm_model_name="openai/m",
            dimensions=None,
            max_batch_size=None,
            max_input=None,
        ),
        credential_resolver=None,
    )
    # wait_fixed(0) keeps the test fast if the no-retry contract regresses
    get_embeddings = LiteLLMEmbeddingAdapter._get_embeddings.retry_with(
        wait=wait_fixed(0)
    )

    with pytest.raises(ProviderRejectedRequestException):
        await get_embeddings(adapter, ["hello"])

    assert attempts == 1


def test_credential_resolution_error_does_not_leak_internal_details():
    resolver = Mock(provider_type="openai")
    resolver.get_api_key.side_effect = ValueError(
        "Failed to decrypt provider 123 with key material xyz"
    )

    with pytest.raises(APIKeyNotConfiguredException) as exc_info:
        build_litellm_provider_kwargs(resolver)

    assert "decrypt" not in str(exc_info.value).lower()
    assert "123" not in str(exc_info.value)
