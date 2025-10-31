import abc
import math
from abc import abstractmethod

from intric.embedding_models.domain.embedding_model import EmbeddingModel
from intric.files.chunk_embedding_list import ChunkEmbeddingList
from intric.info_blobs.info_blob import InfoBlobChunk
from intric.main.logging import get_logger


logger = get_logger(__name__)


class EmbeddingModelAdapter(abc.ABC):
    def __init__(self, model: EmbeddingModel):
        self.model = model

    def _chunk_chunks(self, chunks: list["InfoBlobChunk"]):
        """
        Group chunks into batches for embedding API requests.

        Uses max_batch_size (item count limit) instead of cumulative character length.
        max_input is a per-item limit (enforced during chunking), not a batch limit.

        Args:
            chunks: List of InfoBlobChunk objects to batch

        Yields:
            Batches of chunks (up to max_batch_size items each)
        """
        configured_batch_size = getattr(self.model, "max_batch_size", None)
        batch_size = configured_batch_size if configured_batch_size else 32

        if configured_batch_size is not None and configured_batch_size < 1:
            logger.warning(
                "[EmbeddingBatch] Invalid batch size %s for model %s; falling back to 32",
                configured_batch_size,
                getattr(self.model, "name", "<unknown>"),
            )
            batch_size = 32

        total_chunks = len(chunks)
        if total_chunks == 0:
            logger.debug(
                "[EmbeddingBatch] Model %s received no chunks to process",
                getattr(self.model, "name", "<unknown>"),
            )
            return

        total_batches = math.ceil(total_chunks / batch_size)
        logger.info(
            "[EmbeddingBatch] Model %s starting batch run: chunks=%s batch_size=%s batches=%s",
            getattr(self.model, "name", "<unknown>"),
            total_chunks,
            batch_size,
            total_batches,
        )

        for index, start in enumerate(range(0, total_chunks, batch_size), start=1):
            batch = chunks[start : start + batch_size]
            logger.debug(
                "[EmbeddingBatch] Model %s batch %s/%s size=%s",
                getattr(self.model, "name", "<unknown>"),
                index,
                total_batches,
                len(batch),
            )
            yield batch

        logger.info(
            "[EmbeddingBatch] Model %s completed batch run: batches=%s",
            getattr(self.model, "name", "<unknown>"),
            total_batches,
        )

    @abstractmethod
    async def get_embedding_for_query(self, query: str):
        raise NotImplementedError

    @abstractmethod
    async def get_embeddings(self, chunks: list[InfoBlobChunk]) -> ChunkEmbeddingList:
        raise NotImplementedError
