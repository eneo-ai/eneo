import tempfile
from collections.abc import Iterator
from typing import Tuple

import numpy as np

from eneo.info_blobs.info_blob import InfoBlobChunk
from eneo.main.exceptions import ChunkEmbeddingMisMatchException


class ChunkEmbeddingList:
    def __init__(self):
        self._file = tempfile.TemporaryFile()
        self._chunks = []

    def add(self, chunks: list[InfoBlobChunk], embeddings: list[list[float]]):
        if len(chunks) != len(embeddings):
            raise ChunkEmbeddingMisMatchException(
                f"Number of chunks: {len(chunks)}, Number of embeddings: {len(embeddings)}"
            )

        self._chunks.extend(chunks)

        for embedding in embeddings:
            np.save(self._file, embedding)

    def __iter__(self) -> Iterator[Tuple[InfoBlobChunk, list[float]]]:
        self._file.seek(0)
        for chunk in self._chunks:
            embedding = np.load(self._file)

            yield chunk, embedding

        self._file.close()
