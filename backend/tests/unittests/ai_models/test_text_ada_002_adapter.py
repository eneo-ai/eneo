import pytest
from uuid import uuid4

from intric.ai_models.embedding_models.embedding_model import (
    EmbeddingModelFamily,
    EmbeddingModelLegacy,
    ModelHostingLocation,
    ModelStability,
)
from intric.embedding_models.infrastructure.adapters.openai_embeddings import (
    OpenAIEmbeddingAdapter,
)
from intric.info_blobs.info_blob import InfoBlobChunk
from tests.fixtures import TEST_UUID


@pytest.fixture(autouse=True)
def mock_openai_key(monkeypatch):
    """Mock OPENAI_API_KEY for adapter instantiation.

    These tests only test chunking logic and don't make real API calls.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-test-key-for-chunking")


def _get_adapter_with_max_limit(max_limit: int, max_batch_size: int | None = None):
    model = EmbeddingModelLegacy(
        id=uuid4(),
        name="multilingual-e5-large",
        family=EmbeddingModelFamily.E5,
        open_source=True,
        max_input=max_limit,
        stability=ModelStability.STABLE,
        hosting=ModelHostingLocation.USA,
        is_deprecated=False,
        max_batch_size=max_batch_size,
    )

    adapter = OpenAIEmbeddingAdapter(model=model)

    return adapter


def _get_chunks(texts: list[str]):
    return [
        InfoBlobChunk(
            user_id=0,
            chunk_no=i,
            text=text,
            info_blob_id=TEST_UUID,
            group_id=0,
            tenant_id=TEST_UUID,
        )
        for i, text in enumerate(texts)
    ]


def test_chunking_is_one_chunk_if_sum_is_less_than_limit():
    # Test that with max_batch_size=32, all 9 chunks fit in 1 batch
    adapter = _get_adapter_with_max_limit(8191, max_batch_size=32)

    texts = ["c" * i for i in range(1, 10)]
    chunks = _get_chunks(texts)

    assert len(list(adapter._chunk_chunks(chunks))) == 1


def test_chunking_is_two_chunks_if_sum_is_slightly_larger_than_limit():
    # Test that with max_batch_size=1, each chunk goes in its own batch
    adapter = _get_adapter_with_max_limit(8, max_batch_size=1)

    texts = ["c" * 5, "c" * 5]
    chunks = _get_chunks(texts)

    assert len(list(adapter._chunk_chunks(chunks))) == 2


def test_chunking_with_three_chunks():
    # Test that with max_batch_size=2, 4 chunks are split into 2 batches
    adapter = _get_adapter_with_max_limit(8, max_batch_size=2)

    texts = ["c" * 7, "c" * 5, "c" * 3, "c" * 6]
    chunks = _get_chunks(texts)

    assert len(list(adapter._chunk_chunks(chunks))) == 2
