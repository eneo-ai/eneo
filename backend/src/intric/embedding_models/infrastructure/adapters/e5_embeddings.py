from typing import TYPE_CHECKING, Optional

from tenacity import retry, stop_after_attempt, wait_random_exponential

from intric.embedding_models.infrastructure.adapters.base import (
    EmbeddingModelAdapter,
)
from intric.files.chunk_embedding_list import ChunkEmbeddingList
from intric.info_blobs.info_blob import InfoBlobChunk
from intric.main.aiohttp_client import aiohttp_client
from intric.main.config import get_settings
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.settings.credential_resolver import CredentialResolver

logger = get_logger(__name__)


class E5Adapter(EmbeddingModelAdapter):
    def __init__(
        self,
        model,
        credential_resolver: Optional["CredentialResolver"] = None,
    ):
        super().__init__(model)
        # E5 is a local model (Infinity), doesn't need credentials
        # credential_resolver accepted for interface consistency

    async def get_embedding_for_query(self, query: str):
        truncated_query = query[: self.model.max_input]
        query_prepended = [f"query: {truncated_query}"]

        embeddings = await self._get_embeddings(query_prepended)
        return embeddings[0]

    async def get_embeddings(self, chunks: list[InfoBlobChunk]):
        chunk_embedding_list = ChunkEmbeddingList()
        for chunked_chunks in self._chunk_chunks(chunks):
            texts_prepended = [f"passage: {chunk.text}" for chunk in chunked_chunks]

            logger.debug(f"Embedding a chunk of {len(chunked_chunks)} chunks")

            embeddings_for_chunks = await self._get_embeddings(texts_prepended)
            chunk_embedding_list.add(chunked_chunks, embeddings_for_chunks)

        return chunk_embedding_list

    @retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(3))
    async def _get_embeddings(self, texts: list[str]) -> list[list[float]]:
        payload = {"input": texts, "model": self.model.name}

        url = f"{get_settings().infinity_url}/embeddings"
        async with aiohttp_client().post(url, json=payload) as resp:
            data = await resp.json()

        return [embedding["embedding"] for embedding in data["data"]]
