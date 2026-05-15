import abc
import math
from abc import abstractmethod
from collections.abc import Iterator
from typing import TYPE_CHECKING

from intric.files.chunk_embedding_list import ChunkEmbeddingList
from intric.info_blobs.info_blob import InfoBlobChunk
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.embedding_models.infrastructure.create_embeddings_service import (
        EmbeddingModelLike,
    )


logger = get_logger(__name__)


class EmbeddingModelAdapter(abc.ABC):
    """Base class for embedding model adapters.

    Adapters accept any object satisfying EmbeddingModelLike protocol,
    including both ORM EmbeddingModel and frozen EmbeddingModelSpec DTO.
    """

    def __init__(self, model: "EmbeddingModelLike") -> None:
        super().__init__()
        self.model = model

    def _effective_batch_size(self) -> int:
        configured_batch_size = self.model.max_batch_size

        if configured_batch_size is not None and configured_batch_size < 1:
            logger.warning(
                "[EmbeddingBatch] Invalid batch size %s for model %s; falling back to 32",
                configured_batch_size,
                self.model.name,
            )
            return 32

        return configured_batch_size or 32

    def _chunk_chunks(
        self, chunks: list["InfoBlobChunk"]
    ) -> Iterator[list["InfoBlobChunk"]]:
        """Yield non-empty batches no larger than the effective batch size."""
        batch_size = self._effective_batch_size()

        total_chunks = len(chunks)
        if total_chunks == 0:
            logger.debug(
                "[EmbeddingBatch] Model %s received no chunks to process",
                self.model.name,
            )
            return

        total_batches = math.ceil(total_chunks / batch_size)
        logger.info(
            "[EmbeddingBatch] Model %s starting batch run: chunks=%s batch_size=%s batches=%s",
            self.model.name,
            total_chunks,
            batch_size,
            total_batches,
        )

        for index, start in enumerate(range(0, total_chunks, batch_size), start=1):
            batch = chunks[start : start + batch_size]
            logger.debug(
                "[EmbeddingBatch] Model %s batch %s/%s size=%s",
                self.model.name,
                index,
                total_batches,
                len(batch),
            )
            yield batch

        logger.info(
            "[EmbeddingBatch] Model %s completed batch run: batches=%s",
            self.model.name,
            total_batches,
        )

    @abstractmethod
    async def get_embedding_for_query(self, query: str) -> list[float]:
        raise NotImplementedError

    @abstractmethod
    async def get_embeddings(self, chunks: list[InfoBlobChunk]) -> ChunkEmbeddingList:
        raise NotImplementedError
