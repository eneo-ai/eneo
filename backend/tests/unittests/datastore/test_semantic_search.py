from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from intric.embedding_models.infrastructure.datastore import Datastore
from intric.files.chunk_embedding_list import ChunkEmbeddingList
from intric.info_blobs.info_blob import InfoBlobInDB
from tests.fixtures import TEST_COLLECTION


@pytest.fixture(name="datastore")
def datastore_with_mocks():
    return Datastore(
        tenant_id=uuid4(),
        info_blob_chunk_repo=AsyncMock(),
        create_embeddings_service=AsyncMock(),
    )


async def test_semantic_search(datastore: Datastore):
    with patch(
        "intric.embedding_models.infrastructure.datastore.autocut",
    ) as autocut_mock:
        await datastore.semantic_search(
            search_string="giraffe",
            collections=[TEST_COLLECTION],
            embedding_model=TEST_COLLECTION.embedding_model,
        )
        autocut_mock.assert_not_called()

        await datastore.semantic_search(
            search_string="giraffe",
            collections=[TEST_COLLECTION],
            autocut_cutoff=1,
            embedding_model=TEST_COLLECTION.embedding_model,
        )
        autocut_mock.assert_called_once()


async def test_add_stamps_chunks_with_datastore_tenant_id():
    tenant_id = uuid4()
    info_blob = InfoBlobInDB(
        id=uuid4(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
        url=None,
        title="Tenant scoped text",
        embedding_model_id=TEST_COLLECTION.embedding_model.id,
        user_id=uuid4(),
        # The blob tenant deliberately differs; chunks must use Datastore scope.
        tenant_id=uuid4(),
        size=0,
        group_id=TEST_COLLECTION.id,
        website_id=None,
        integration_knowledge_id=None,
        sharepoint_item_id=None,
        group=None,
        website=None,
        text="One paragraph.\n\nSecond paragraph.",
    )
    chunk_repo = AsyncMock()
    create_embeddings_service = AsyncMock()

    async def _get_embeddings(*, chunks, **_kwargs):
        chunk_embedding_list = ChunkEmbeddingList()
        chunk_embedding_list.add(
            chunks,
            [[0.1, 0.2] for _chunk in chunks],
        )
        return chunk_embedding_list

    create_embeddings_service.get_embeddings.side_effect = _get_embeddings
    datastore = Datastore(
        tenant_id=tenant_id,
        info_blob_chunk_repo=chunk_repo,
        create_embeddings_service=create_embeddings_service,
    )

    await datastore.add(
        info_blob=info_blob, embedding_model=TEST_COLLECTION.embedding_model
    )

    added_chunks = chunk_repo.add.await_args.args[0]
    chunk_repo.add.assert_awaited_once()
    assert added_chunks
    assert {chunk.tenant_id for chunk in added_chunks} == {tenant_id}
