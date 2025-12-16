from typing import TYPE_CHECKING, Optional

import openai
from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from intric.embedding_models.infrastructure.adapters.base import EmbeddingModelAdapter
from intric.files.chunk_embedding_list import ChunkEmbeddingList
from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException, OpenAIException
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.embedding_models.infrastructure.create_embeddings_service import (
        EmbeddingModelLike,
    )
    from intric.info_blobs.info_blob import InfoBlobChunk
    from intric.settings.credential_resolver import CredentialResolver


logger = get_logger(__name__)


class OpenAIEmbeddingAdapter(EmbeddingModelAdapter):
    def __init__(
        self,
        model: "EmbeddingModelLike",
        credential_resolver: Optional["CredentialResolver"] = None,
    ):
        super().__init__(model)

        # Use tenant credentials if available, otherwise fall back to global settings
        if credential_resolver:
            api_key = credential_resolver.get_api_key("openai")
        else:
            api_key = get_settings().openai_api_key

        self.client = openai.AsyncOpenAI(api_key=api_key)

    async def get_embeddings(self, chunks: list["InfoBlobChunk"]) -> ChunkEmbeddingList:
        chunk_embedding_list = ChunkEmbeddingList()
        batch_size = getattr(self.model, "max_batch_size", None) or 32
        total_chunks = len(chunks)
        total_batches = (total_chunks + batch_size - 1) // batch_size if total_chunks else 0
        logger.debug(
            "Embedding model %s batching %s chunks into %s batches (size=%s)",
            self.model.name,
            total_chunks,
            total_batches,
            batch_size,
        )

        for chunked_chunks in self._chunk_chunks(chunks):
            texts_for_chunks = [chunk.text for chunk in chunked_chunks]

            embeddings_for_chunks = await self._get_embeddings(texts=texts_for_chunks)
            chunk_embedding_list.add(chunked_chunks, embeddings_for_chunks)

        return chunk_embedding_list

    async def get_embedding_for_query(self, query: str):
        truncated_query = query[: self.model.max_input]
        embeddings = await self._get_embeddings([truncated_query])
        return embeddings[0]

    @retry(
        wait=wait_random_exponential(min=1, max=20),
        stop=stop_after_attempt(3),
        retry=retry_if_not_exception_type(BadRequestException),
        reraise=True,
    )
    async def _get_embeddings(self, texts: list[str]):
        try:
            # Prepare the parameters for the embeddings.create method
            params = {"input": texts, "model": self.model.name}

            # If dimensions exists on the model, add it to the parameters
            if self.model.dimensions is not None:
                params["dimensions"] = self.model.dimensions

            # Call the OpenAI API to get the embeddings
            response = await self.client.embeddings.create(**params)

        except openai.BadRequestError as e:
            logger.exception("Bad request error:")
            raise BadRequestException("Invalid input") from e
        except openai.RateLimitError as e:
            logger.exception("Rate limit error:")
            raise OpenAIException("OpenAI Ratelimit exception") from e
        except Exception as e:
            logger.exception("Unknown OpenAI exception:")
            raise OpenAIException("Unknown OpenAI exception") from e

        return [embedding.embedding for embedding in response.data]
