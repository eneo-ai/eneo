import pytest

from eneo.files.chunk_embedding_list import ChunkEmbeddingList
from eneo.main.exceptions import ChunkEmbeddingMisMatchException


def test_add_one_at_a_time():
    chunk_embedding_list = ChunkEmbeddingList()

    chunks_list = ["hello", "there", "I", "am", "Henry"]
    embeddings = [[i, 2, 3, 4] for i in range(len(chunks_list))]

    for chunk, embedding in zip(chunks_list, embeddings):
        chunk_embedding_list.add([chunk], [embedding])

    for (chunk, embedding), (expected_chunk, expected_embedding) in zip(
        chunk_embedding_list, zip(chunks_list, embeddings)
    ):
        assert chunk == expected_chunk
        assert list(embedding) == expected_embedding


def test_add_in_chunks():
    chunk_embedding_list = ChunkEmbeddingList()

    chunks_list = ["hello", "there", "I", "am", "Henry"]
    embeddings = [[i, 2, 3, 4] for i in range(len(chunks_list))]

    chunk_embedding_list.add(chunks_list[:3], embeddings[:3])
    chunk_embedding_list.add(chunks_list[3:], embeddings[3:])

    for (chunk, embedding), (expected_chunk, expected_embedding) in zip(
        chunk_embedding_list, zip(chunks_list, embeddings)
    ):
        assert chunk == expected_chunk
        assert list(embedding) == expected_embedding


def test_fails_when_the_lengths_dont_match():
    chunk_embedding_list = ChunkEmbeddingList()

    try:
        with pytest.raises(ChunkEmbeddingMisMatchException):
            chunk_embedding_list.add([1, 2], [[1]])
    finally:
        chunk_embedding_list._file.close()
