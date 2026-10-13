"""Unit tests for Datastore's search-scope handling."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.embedding_models.infrastructure.adapters.base import (
    PartialEmbeddingBatchError,
)
from eneo.embedding_models.infrastructure.datastore import Datastore
from eneo.files.chunk_embedding_list import ChunkEmbeddingList
from eneo.info_blobs.info_blob import InfoBlobChunk
from eneo.main.exceptions import OpenAIException


def _datastore():
    return Datastore(
        user=MagicMock(),
        info_blob_chunk_repo=MagicMock(),
        create_embeddings_service=MagicMock(),
    )


class TestSemanticSearchScopeGuard:
    """Scope buckets are OR-ed in SQL, so mixing them widens instead of narrows."""

    async def test_document_scope_cannot_be_combined_with_a_collection(self):
        with pytest.raises(ValueError, match="cannot be combined"):
            await _datastore().semantic_search(
                "waste",
                embedding_model=MagicMock(),
                collections=[SimpleNamespace(id=uuid4())],
                info_blob_ids=[uuid4()],
            )

    async def test_document_scope_cannot_be_combined_with_a_website(self):
        with pytest.raises(ValueError, match="cannot be combined"):
            await _datastore().semantic_search(
                "waste",
                embedding_model=MagicMock(),
                websites=[SimpleNamespace(id=uuid4())],
                info_blob_ids=[uuid4()],
            )

    async def test_document_scope_cannot_be_combined_with_an_integration(self):
        with pytest.raises(ValueError, match="cannot be combined"):
            await _datastore().semantic_search(
                "waste",
                embedding_model=MagicMock(),
                integration_knowledge_list=[SimpleNamespace(id=uuid4())],
                info_blob_ids=[uuid4()],
            )


async def test_add_surfaces_the_original_provider_error(monkeypatch):
    chunk = InfoBlobChunk(
        text="knowledge",
        chunk_no=0,
        info_blob_id=uuid4(),
        tenant_id=uuid4(),
    )
    monkeypatch.setattr(Datastore, "_chunk_text", lambda _self, _blob, _model: [chunk])
    provider_error = OpenAIException("provider unavailable")
    completed = ChunkEmbeddingList()
    embeddings = MagicMock()
    embeddings.get_embeddings = AsyncMock(
        side_effect=PartialEmbeddingBatchError(
            completed=completed,
            completed_count=0,
            cause=provider_error,
        )
    )
    chunk_repo = MagicMock()
    chunk_repo.add = AsyncMock()
    datastore = Datastore(
        user=MagicMock(),
        info_blob_chunk_repo=chunk_repo,
        create_embeddings_service=embeddings,
    )

    with pytest.raises(OpenAIException) as exc_info:
        await datastore.add(MagicMock(source_metadata=None), MagicMock())

    assert exc_info.value is provider_error
    assert completed._file.closed
    chunk_repo.add.assert_not_awaited()


def test_chunk_text_clamps_to_the_embedding_models_limit(monkeypatch):
    from types import SimpleNamespace

    from eneo.embedding_models.domain import chunking
    from eneo.tokens.token_utils import count_tokens

    monkeypatch.setattr(chunking.settings, "chunk_size", 200)
    monkeypatch.setattr(chunking.settings, "chunk_overlap", 40)
    datastore = Datastore(
        user=MagicMock(tenant_id=uuid4()),
        info_blob_chunk_repo=MagicMock(),
        create_embeddings_service=MagicMock(),
    )
    info_blob = SimpleNamespace(
        id=uuid4(), text=" ".join(f"w{i}" for i in range(300)), source_metadata=None
    )
    small_model = SimpleNamespace(name="small", family=None, max_input=30)

    chunks = datastore._chunk_text(info_blob, small_model)  # type: ignore[arg-type]

    assert len(chunks) > 1
    assert max(count_tokens(chunk.text) for chunk in chunks) <= 30
