from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eneo.embedding_models.infrastructure.datastore import Datastore
from tests.fixtures import TEST_COLLECTION


@pytest.fixture(name="datastore")
def datastore_with_mocks():
    return Datastore(
        user=MagicMock(),
        info_blob_chunk_repo=AsyncMock(),
        create_embeddings_service=AsyncMock(),
    )


async def test_semantic_search(datastore: Datastore):
    with patch(
        "eneo.embedding_models.infrastructure.datastore.autocut",
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
