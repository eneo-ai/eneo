import pytest

from eneo.embedding_models.infrastructure.datastore import autocut
from eneo.info_blobs.info_blob import InfoBlobChunkWithEmbedding
from tests.fixtures import TEST_UUID


@pytest.mark.parametrize(["cutoff", "cut_point"], [(1, 3), (2, 5), (3, 6)])
def test_autocut1(cutoff: int, cut_point: int):
    scores = [0.1899, 0.1901, 0.191, 0.21, 0.215, 0.23]

    cut_point_real = autocut(scores, cutoff)
    assert cut_point_real == cut_point
    assert len(scores[:cut_point]) == cut_point


def test_chunk_size_calculation():
    text = "Test text"
    embedding = [1.0, 2.0, 3.0]
    chunk = InfoBlobChunkWithEmbedding(
        text=text,
        chunk_no=1,
        info_blob_id=TEST_UUID,
        tenant_id=TEST_UUID,
        embedding=embedding,
    )

    size_text = len(text.encode())
    size_embedding = len(embedding) * 4

    assert chunk.size == size_text + size_embedding
