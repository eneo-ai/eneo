import abc
from abc import abstractmethod

from intric.embedding_models.domain.embedding_model import EmbeddingModel
from intric.files.chunk_embedding_list import ChunkEmbeddingList
from intric.info_blobs.info_blob import InfoBlobChunk


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
        # Default to 32 items per batch if not specified
        # This balances API efficiency with request size limits
        batch_size = getattr(self.model, "max_batch_size", 32)

        for i in range(0, len(chunks), batch_size):
            yield chunks[i : i + batch_size]

    @abstractmethod
    async def get_embedding_for_query(self, query: str):
        raise NotImplementedError

    @abstractmethod
    async def get_embeddings(self, chunks: list[InfoBlobChunk]) -> ChunkEmbeddingList:
        raise NotImplementedError
