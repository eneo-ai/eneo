import logging
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from litellm.exceptions import BadRequestError
from tenacity import wait_fixed

from eneo.embedding_models.infrastructure import (
    create_embeddings_service as create_embeddings_service_module,
)
from eneo.embedding_models.infrastructure.adapters import base as embedding_adapter_base
from eneo.embedding_models.infrastructure.adapters import (
    litellm_embeddings as litellm_embeddings_module,
)
from eneo.embedding_models.infrastructure.adapters.litellm_embeddings import (
    LiteLLMEmbeddingAdapter,
)
from eneo.embedding_models.infrastructure.create_embeddings_service import (
    CreateEmbeddingsService,
)
from eneo.main.exceptions import (
    APIKeyNotConfiguredException,
    ProviderRejectedRequestException,
)
from eneo.model_providers.domain.model_route import resolve_model_route
from eneo.model_providers.infrastructure import litellm_transport
from eneo.model_providers.infrastructure.litellm_provider import (
    build_litellm_provider_kwargs,
)
from eneo.model_providers.infrastructure.litellm_transport import (
    INVALID_REQUEST_MESSAGE,
    is_provider_unavailable_error,
    raise_provider_unavailable,
    raise_public_litellm_error,
)
from eneo.tenants.provider_field_config import get_required_fields


def test_resolve_model_route_is_canonical():
    assert (
        resolve_model_route(
            provider_type="anthropic",
            model_name="claude-sonnet-4",
        )
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


@pytest.mark.asyncio
async def test_embedding_logs_omit_credentials_and_stay_below_info(
    monkeypatch,
    caplog,
):
    async def successful_aembedding(**_kwargs):
        return SimpleNamespace(data=[{"embedding": [0.25, 0.75]}])

    monkeypatch.setattr(litellm_transport, "aembedding", successful_aembedding)
    caplog.set_level(logging.DEBUG)
    module_loggers = (
        embedding_adapter_base.logger,
        litellm_embeddings_module.logger,
        create_embeddings_service_module.logger,
    )
    for module_logger in module_loggers:
        monkeypatch.setattr(module_logger, "level", logging.DEBUG)
        monkeypatch.setattr(module_logger, "_cache", {})
        module_logger.addHandler(caplog.handler)

    resolver = Mock(provider_type="openai")
    resolver.get_api_key.return_value = "super-secret-unique-TAIL"
    resolver.get_credential_field.return_value = None
    adapter = LiteLLMEmbeddingAdapter(
        model=SimpleNamespace(
            name="m",
            family=None,
            litellm_model_name="openai/m",
            dimensions=None,
            max_batch_size=None,
            max_input=None,
        ),
        credential_resolver=resolver,
    )
    chunks = [SimpleNamespace(text="hello")]

    try:
        service = CreateEmbeddingsService(encryption_service=Mock())
        await service._get_adapter(
            SimpleNamespace(
                id=uuid4(),
                name="m",
                provider_id=uuid4(),
                provider_type="openai",
                provider_credentials={"api_key": "encrypted"},
                provider_config={},
                family=None,
                litellm_model_name="openai/m",
                dimensions=None,
                max_batch_size=None,
                max_input=None,
                open_source=False,
            )
        )
        result = await adapter.get_embeddings(chunks)
    finally:
        for module_logger in module_loggers:
            module_logger.removeHandler(caplog.handler)

    assert list(result)[0][1] == [0.25, 0.75]
    messages = [record.getMessage() for record in caplog.records]
    assert any("Making embedding request" in message for message in messages)
    assert any("EmbeddingBatch" in message for message in messages)
    assert any("Using LiteLLMEmbeddingAdapter" in message for message in messages)
    assert all("super-secret-unique-TAIL" not in message for message in messages)
    assert all("TAIL" not in message for message in messages)
    assert all("api_key" not in message for message in messages)
    assert not any(
        record.levelno >= logging.INFO
        and (
            "EmbeddingBatch" in record.getMessage()
            or "Using LiteLLMEmbeddingAdapter" in record.getMessage()
        )
        for record in caplog.records
    )


def test_credential_resolution_error_does_not_leak_internal_details():
    resolver = Mock(provider_type="openai")
    resolver.get_api_key.side_effect = ValueError(
        "Failed to decrypt provider 123 with key material xyz"
    )

    with pytest.raises(APIKeyNotConfiguredException) as exc_info:
        build_litellm_provider_kwargs(resolver)

    assert "decrypt" not in str(exc_info.value).lower()
    assert "123" not in str(exc_info.value)
