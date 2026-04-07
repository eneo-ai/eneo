import tempfile
from collections.abc import Iterator
from typing import IO

import numpy as np

from intric.info_blobs.info_blob import InfoBlobChunk
from intric.main.exceptions import ChunkEmbeddingMisMatchException


class ChunkEmbeddingList:
    _file: IO[bytes]
    _chunks: list[InfoBlobChunk]

    def __init__(self) -> None:
        super().__init__()
        self._file = tempfile.TemporaryFile()
        self._chunks = []

    def add(self, chunks: list[InfoBlobChunk], embeddings: list[list[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ChunkEmbeddingMisMatchException(
                f"Number of chunks: {len(chunks)}, Number of embeddings: {len(embeddings)}"
            )

        self._chunks.extend(chunks)

        for embedding in embeddings:
            np.save(self._file, embedding)

    def __iter__(self) -> Iterator[tuple[InfoBlobChunk, list[float]]]:
        self._file.seek(0)
        for chunk in self._chunks:
            embedding: list[float] = np.load(self._file).tolist()

            yield chunk, embedding

        self._file.close()
