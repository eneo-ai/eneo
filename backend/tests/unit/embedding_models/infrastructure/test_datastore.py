"""Unit tests for Datastore's search-scope handling."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from eneo.embedding_models.infrastructure.datastore import Datastore


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
