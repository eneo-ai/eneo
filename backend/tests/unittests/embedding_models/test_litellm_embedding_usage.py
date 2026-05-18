from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from intric.embedding_models.domain.embedding_batch import EmbeddingUsage
from intric.embedding_models.infrastructure.adapters.litellm_embeddings import (
    LiteLLMEmbeddingAdapter,
)
from intric.info_blobs.info_blob import InfoBlobChunk


@dataclass(frozen=True)
class _EmbeddingModel:
    id: UUID
    name: str = "text-embedding-3-small"
    provider_id: UUID | None = None
    litellm_model_name: str | None = "openai/text-embedding-3-small"
    family: str | None = None
    max_input: int | None = 8191
    max_batch_size: int | None = 32
    dimensions: int | None = 1536
    open_source: bool = False
    input_cost_per_token: Decimal | None = None


@dataclass(frozen=True)
class _LiteLLMUsage:
    total_tokens: int
    prompt_tokens: int | None = None


@dataclass(frozen=True)
class _LiteLLMResponse:
    data: list[dict[str, list[float]]]
    usage: object | None = None
    _hidden_params: dict[str, object] | None = None


def _chunk(text: str = "hello") -> InfoBlobChunk:
    return InfoBlobChunk(
        text=text,
        chunk_no=0,
        info_blob_id=uuid4(),
        tenant_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_litellm_adapter_returns_provider_reported_embedding_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def aembedding(**_params: object) -> _LiteLLMResponse:
        return _LiteLLMResponse(
            data=[{"embedding": [0.1, 0.2, 0.3]}],
            usage=_LiteLLMUsage(total_tokens=17, prompt_tokens=17),
        )

    monkeypatch.setattr(
        "intric.embedding_models.infrastructure.adapters.litellm_embeddings.litellm.aembedding",
        aembedding,
    )
    adapter = LiteLLMEmbeddingAdapter(_EmbeddingModel(id=uuid4()))

    result = await adapter.get_embeddings([_chunk()])

    assert result.usage == EmbeddingUsage(
        prompt_tokens=17,
        total_tokens=17,
        cost_usd=Decimal("0.000000340000"),
        source="provider_reported",
    )
    assert [embedding for _, embedding in result.embeddings] == [[0.1, 0.2, 0.3]]


@pytest.mark.asyncio
async def test_litellm_adapter_returns_missing_embedding_usage_when_provider_omits_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def aembedding(**_params: object) -> _LiteLLMResponse:
        return _LiteLLMResponse(data=[{"embedding": [0.1, 0.2, 0.3]}])

    monkeypatch.setattr(
        "intric.embedding_models.infrastructure.adapters.litellm_embeddings.litellm.aembedding",
        aembedding,
    )
    adapter = LiteLLMEmbeddingAdapter(_EmbeddingModel(id=uuid4()))

    result = await adapter.get_embeddings([_chunk()])

    assert result.usage == EmbeddingUsage(
        prompt_tokens=None,
        total_tokens=None,
        cost_usd=None,
        source="missing",
    )
    assert [embedding for _, embedding in result.embeddings] == [[0.1, 0.2, 0.3]]


@pytest.mark.asyncio
async def test_litellm_adapter_treats_malformed_embedding_usage_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @dataclass(frozen=True)
    class MalformedUsage:
        total_tokens: str
        prompt_tokens: str

    async def aembedding(**_params: object) -> _LiteLLMResponse:
        return _LiteLLMResponse(
            data=[{"embedding": [0.1, 0.2, 0.3]}],
            usage=MalformedUsage(total_tokens="17", prompt_tokens="11"),
        )

    monkeypatch.setattr(
        "intric.embedding_models.infrastructure.adapters.litellm_embeddings.litellm.aembedding",
        aembedding,
    )
    adapter = LiteLLMEmbeddingAdapter(_EmbeddingModel(id=uuid4()))

    result = await adapter.get_embeddings([_chunk()])

    assert result.usage == EmbeddingUsage(
        prompt_tokens=None,
        total_tokens=None,
        cost_usd=None,
        source="missing",
    )
    assert [embedding for _, embedding in result.embeddings] == [[0.1, 0.2, 0.3]]


@pytest.mark.asyncio
async def test_litellm_adapter_uses_custom_embedding_cost_when_model_defines_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def aembedding(**_params: object) -> _LiteLLMResponse:
        return _LiteLLMResponse(
            data=[{"embedding": [0.1, 0.2, 0.3]}],
            usage=_LiteLLMUsage(total_tokens=17, prompt_tokens=17),
        )

    monkeypatch.setattr(
        "intric.embedding_models.infrastructure.adapters.litellm_embeddings.litellm.aembedding",
        aembedding,
    )
    adapter = LiteLLMEmbeddingAdapter(
        _EmbeddingModel(
            id=uuid4(),
            litellm_model_name="custom-provider/custom-embedding",
            input_cost_per_token=Decimal("0.000001"),
        )
    )

    result = await adapter.get_embeddings([_chunk()])

    assert result.usage == EmbeddingUsage(
        prompt_tokens=17,
        total_tokens=17,
        cost_usd=Decimal("0.000017000000"),
        source="provider_reported",
    )


@pytest.mark.asyncio
async def test_litellm_adapter_uses_litellm_response_cost_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def aembedding(**_params: object) -> _LiteLLMResponse:
        return _LiteLLMResponse(
            data=[{"embedding": [0.1, 0.2, 0.3]}],
            usage=_LiteLLMUsage(total_tokens=17, prompt_tokens=17),
            _hidden_params={"response_cost": 0.1234567890123},
        )

    monkeypatch.setattr(
        "intric.embedding_models.infrastructure.adapters.litellm_embeddings.litellm.aembedding",
        aembedding,
    )
    adapter = LiteLLMEmbeddingAdapter(_EmbeddingModel(id=uuid4()))

    result = await adapter.get_embeddings([_chunk()])

    assert result.usage == EmbeddingUsage(
        prompt_tokens=17,
        total_tokens=17,
        cost_usd=Decimal("0.123456789012"),
        source="provider_reported",
    )
