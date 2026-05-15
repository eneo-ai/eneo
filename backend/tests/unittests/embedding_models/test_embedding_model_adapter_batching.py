from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from intric.embedding_models.infrastructure.adapters import base as adapter_base
from intric.embedding_models.infrastructure.adapters.base import EmbeddingModelAdapter
from intric.files.chunk_embedding_list import ChunkEmbeddingList
from intric.info_blobs.info_blob import InfoBlobChunk


@dataclass(frozen=True)
class _EmbeddingModel:
    id: UUID
    name: str
    provider_id: UUID | None
    litellm_model_name: str | None
    family: str | None
    max_input: int | None
    max_batch_size: int | None
    dimensions: int | None
    open_source: bool


class _BatchingAdapter(EmbeddingModelAdapter):
    def effective_batch_size(self) -> int:
        return self._effective_batch_size()

    def batches(self, chunks: list[InfoBlobChunk]) -> list[list[InfoBlobChunk]]:
        return list(self._chunk_chunks(chunks))

    async def get_embedding_for_query(self, query: str) -> list[float]:
        raise NotImplementedError

    async def get_embeddings(self, chunks: list[InfoBlobChunk]) -> ChunkEmbeddingList:
        raise NotImplementedError


def _model(*, max_batch_size: int | None) -> _EmbeddingModel:
    return _EmbeddingModel(
        id=uuid4(),
        name="text-embedding-3-small",
        provider_id=uuid4(),
        litellm_model_name="openai/text-embedding-3-small",
        family=None,
        max_input=8191,
        max_batch_size=max_batch_size,
        dimensions=1536,
        open_source=False,
    )


def _chunks(count: int) -> list[InfoBlobChunk]:
    return [
        InfoBlobChunk(
            text=f"chunk {index}",
            chunk_no=index,
            info_blob_id=uuid4(),
            tenant_id=uuid4(),
        )
        for index in range(count)
    ]


@pytest.mark.parametrize(
    ("max_batch_size", "expected", "expected_warnings"),
    [
        pytest.param(None, 32, 0, id="none-defaults"),
        pytest.param(0, 32, 1, id="zero-warns-and-defaults"),
        pytest.param(-1, 32, 1, id="negative-warns-and-defaults"),
        pytest.param(1, 1, 0, id="one"),
        pytest.param(2, 2, 0, id="two"),
    ],
)
def test_effective_batch_size_normalizes_model_batch_size(
    monkeypatch: pytest.MonkeyPatch,
    max_batch_size: int | None,
    expected: int,
    expected_warnings: int,
) -> None:
    adapter = _BatchingAdapter(_model(max_batch_size=max_batch_size))
    warnings: list[tuple[object, ...]] = []

    def record_warning(*args: object, **_kwargs: object) -> None:
        warnings.append(args)

    monkeypatch.setattr(adapter_base.logger, "warning", record_warning)

    assert adapter.effective_batch_size() == expected
    assert len(warnings) == expected_warnings


@pytest.mark.parametrize(
    ("max_batch_size", "chunk_count", "expected_batch_sizes"),
    [
        pytest.param(32, 0, [], id="empty-input"),
        pytest.param(None, 3, [3], id="none-defaults-one-batch"),
        pytest.param(1, 3, [1, 1, 1], id="one-per-batch"),
        pytest.param(2, 3, [2, 1], id="split-batch"),
        pytest.param(3, 3, [3], id="exact-full-batch"),
    ],
)
def test_chunk_chunks_uses_effective_batch_size(
    max_batch_size: int | None,
    chunk_count: int,
    expected_batch_sizes: list[int],
) -> None:
    adapter = _BatchingAdapter(_model(max_batch_size=max_batch_size))

    batches = adapter.batches(_chunks(chunk_count))

    assert [len(batch) for batch in batches] == expected_batch_sizes
