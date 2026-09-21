import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
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
from eneo.embedding_models.infrastructure.adapters.base import (
    PartialEmbeddingBatchError,
)
from eneo.embedding_models.infrastructure.adapters.litellm_embeddings import (
    LiteLLMEmbeddingAdapter,
)
from eneo.embedding_models.infrastructure.create_embeddings_service import (
    CreateEmbeddingsService,
)
from eneo.main.exceptions import (
    APIKeyNotConfiguredException,
    OpenAIException,
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


@pytest.mark.asyncio
async def test_embedding_failure_carries_the_completed_prefix():
    chunks = [SimpleNamespace(text=f"text {index}") for index in range(4)]
    adapter = LiteLLMEmbeddingAdapter(
        model=SimpleNamespace(
            name="m",
            family=None,
            litellm_model_name="openai/m",
            dimensions=None,
            max_batch_size=2,
            max_input=None,
        ),
        credential_resolver=None,
    )
    adapter._get_embeddings = AsyncMock(
        side_effect=[[[0.1], [0.2]], TimeoutError("provider request timed out")]
    )

    with pytest.raises(PartialEmbeddingBatchError) as exc_info:
        await adapter.get_embeddings(chunks)

    error = exc_info.value
    assert error.completed_count == 2
    assert error.cause.args == ("provider request timed out",)
    assert [(chunk.text, vector) for chunk, vector in error.completed] == [
        ("text 0", [0.1]),
        ("text 1", [0.2]),
    ]


@pytest.mark.asyncio
async def test_embedding_timeout_starts_after_a_request_slot_is_available(
    monkeypatch,
):
    async def successful_aembedding(**kwargs):
        return SimpleNamespace(data=[{"embedding": [0.5]} for _ in kwargs["input"]])

    monkeypatch.setattr(litellm_transport, "aembedding", successful_aembedding)
    request_slots = asyncio.Semaphore(1)
    await request_slots.acquire()
    adapter = LiteLLMEmbeddingAdapter(
        model=SimpleNamespace(
            name="m",
            family=None,
            litellm_model_name="openai/m",
            dimensions=None,
            max_batch_size=1,
            max_input=None,
        ),
        credential_resolver=None,
        request_semaphore=request_slots,
        request_timeout_seconds=0.01,
    )

    embedding_task = asyncio.create_task(
        adapter.get_embeddings([SimpleNamespace(text="hello")])
    )
    await asyncio.sleep(0.03)
    assert not embedding_task.done()

    request_slots.release()
    result = await asyncio.wait_for(embedding_task, timeout=1)
    assert list(result)[0][1] == [0.5]


@pytest.mark.asyncio
async def test_embedding_request_slot_is_released_between_batches(monkeypatch):
    calls: list[str] = []
    first_request_started = asyncio.Event()
    release_first_request = asyncio.Event()

    async def controlled_aembedding(**kwargs):
        text = kwargs["input"][0]
        calls.append(text)
        if len(calls) == 1:
            first_request_started.set()
            await release_first_request.wait()
        return SimpleNamespace(data=[{"embedding": [0.5]}])

    monkeypatch.setattr(litellm_transport, "aembedding", controlled_aembedding)
    request_slots = asyncio.Semaphore(1)

    def create_adapter() -> LiteLLMEmbeddingAdapter:
        return LiteLLMEmbeddingAdapter(
            model=SimpleNamespace(
                name="m",
                family=None,
                litellm_model_name="openai/m",
                dimensions=None,
                max_batch_size=1,
                max_input=None,
            ),
            credential_resolver=None,
            request_semaphore=request_slots,
        )

    first_crawl = asyncio.create_task(
        create_adapter().get_embeddings(
            [SimpleNamespace(text="crawl-a-1"), SimpleNamespace(text="crawl-a-2")]
        )
    )
    await first_request_started.wait()
    second_crawl = asyncio.create_task(
        create_adapter().get_embeddings([SimpleNamespace(text="crawl-b-1")])
    )
    await asyncio.sleep(0)
    release_first_request.set()

    first_result, second_result = await asyncio.gather(first_crawl, second_crawl)
    assert len(list(first_result)) == 2
    assert len(list(second_result)) == 1
    assert calls.index("crawl-b-1") < calls.index("crawl-a-2")


@pytest.mark.asyncio
async def test_provider_credentials_are_resolved_once_per_adapter(monkeypatch):
    async def successful_aembedding(**kwargs):
        return SimpleNamespace(data=[{"embedding": [0.5]} for _ in kwargs["input"]])

    monkeypatch.setattr(litellm_transport, "aembedding", successful_aembedding)
    resolver = Mock(provider_type="openai")
    resolver.get_api_key.return_value = "secret"
    resolver.get_credential_field.return_value = None
    adapter = LiteLLMEmbeddingAdapter(
        model=SimpleNamespace(
            name="m",
            family=None,
            litellm_model_name="openai/m",
            dimensions=None,
            max_batch_size=1,
            max_input=None,
        ),
        credential_resolver=resolver,
    )

    result = await adapter.get_embeddings(
        [SimpleNamespace(text="first"), SimpleNamespace(text="second")]
    )

    assert len(list(result)) == 2
    assert resolver.get_api_key.call_count == 1


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
async def test_embedding_timeout_is_not_retried(monkeypatch):
    attempts = 0

    async def slow_aembedding(**_kwargs):
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(0.02)

    monkeypatch.setattr(litellm_transport, "aembedding", slow_aembedding)
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
        request_timeout_seconds=0.001,
    )
    # Keep a regression fast if the timeout is retried again.
    get_embeddings = LiteLLMEmbeddingAdapter._get_embeddings.retry_with(
        wait=wait_fixed(0)
    )

    with pytest.raises(TimeoutError):
        await get_embeddings(adapter, ["hello"])

    assert attempts == 1


@pytest.mark.asyncio
async def test_provider_timeout_without_crawler_deadline_keeps_existing_retry(
    monkeypatch,
):
    attempts = 0

    async def flaky_aembedding(**_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("provider timed out before accepting the request")
        return SimpleNamespace(data=[{"embedding": [0.5]}])

    monkeypatch.setattr(litellm_transport, "aembedding", flaky_aembedding)
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
    get_embeddings = LiteLLMEmbeddingAdapter._get_embeddings.retry_with(
        wait=wait_fixed(0)
    )

    result = await get_embeddings(adapter, ["hello"])

    assert result == [[0.5]]
    assert attempts == 2


@pytest.mark.asyncio
async def test_provider_timeout_with_crawler_deadline_keeps_existing_retry(
    monkeypatch,
):
    attempts = 0

    async def flaky_aembedding(**_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("provider timed out before accepting the request")
        return SimpleNamespace(data=[{"embedding": [0.5]}])

    monkeypatch.setattr(litellm_transport, "aembedding", flaky_aembedding)
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
        request_timeout_seconds=1,
    )
    get_embeddings = LiteLLMEmbeddingAdapter._get_embeddings.retry_with(
        wait=wait_fixed(0)
    )

    result = await get_embeddings(adapter, ["hello"])

    assert result == [[0.5]]
    assert attempts == 2


@pytest.mark.asyncio
async def test_terminal_provider_timeout_keeps_public_error_mapping(monkeypatch):
    attempts = 0

    async def timing_out_aembedding(**_kwargs):
        nonlocal attempts
        attempts += 1
        raise TimeoutError("provider timed out before accepting the request")

    monkeypatch.setattr(litellm_transport, "aembedding", timing_out_aembedding)
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
    get_embeddings = LiteLLMEmbeddingAdapter._get_embeddings.retry_with(
        wait=wait_fixed(0)
    )

    with pytest.raises(OpenAIException) as exc_info:
        await get_embeddings(adapter, ["hello"])

    assert exc_info.value.code == "provider_unavailable"
    assert attempts == 3


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
