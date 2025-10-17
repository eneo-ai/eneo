from typing import TYPE_CHECKING

import litellm
from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from intric.ai_models.litellm_providers.provider_registry import LiteLLMProviderRegistry
from intric.ai_models.model_enums import ModelFamily
from intric.embedding_models.infrastructure.adapters.base import EmbeddingModelAdapter
from intric.files.chunk_embedding_list import ChunkEmbeddingList
from intric.main.exceptions import BadRequestException, OpenAIException
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.embedding_models.domain.embedding_model import EmbeddingModel
    from intric.info_blobs.info_blob import InfoBlobChunk


logger = get_logger(__name__)


class LiteLLMEmbeddingAdapter(EmbeddingModelAdapter):
    def __init__(self, model: "EmbeddingModel"):
        super().__init__(model)

        # Get provider configuration based on litellm_model_name
        provider = LiteLLMProviderRegistry.get_provider_for_model(model.litellm_model_name)

        # Only apply custom configuration if needed
        if provider.needs_custom_config():
            self.litellm_model = provider.get_litellm_model(model.litellm_model_name)
            self.api_config = provider.get_api_config()
            logger.info(f"[LiteLLM] Using custom provider config for embedding {model.name}: {list(self.api_config.keys())}")
        else:
            # Standard LiteLLM behavior for supported providers
            self.litellm_model = model.litellm_model_name
            self.api_config = {}

        logger.info(f"[LiteLLM] Initializing embedding adapter for model: {model.name} -> {self.litellm_model}")

    async def get_embeddings(self, chunks: list["InfoBlobChunk"]) -> ChunkEmbeddingList:
        chunk_embedding_list = ChunkEmbeddingList()
        for chunked_chunks in self._chunk_chunks(chunks):
            # Add "passage:" prefix for E5 models, use text directly for others
            if self.model.family == ModelFamily.E5:
                texts_for_chunks = [f"passage: {chunk.text}" for chunk in chunked_chunks]
            else:
                texts_for_chunks = [chunk.text for chunk in chunked_chunks]

            logger.debug(f"[LiteLLM] Embedding a chunk of {len(chunked_chunks)} chunks")

            embeddings_for_chunks = await self._get_embeddings(texts=texts_for_chunks)
            chunk_embedding_list.add(chunked_chunks, embeddings_for_chunks)

        return chunk_embedding_list

    async def get_embedding_for_query(self, query: str):
        # Add "query:" prefix for E5 models, use query directly for others
        if self.model.family == ModelFamily.E5:
            truncated_query = f"query: {query[: self.model.max_input]}"
        else:
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
            # Prepare the parameters for the embeddings
            params = {"input": texts, "model": self.litellm_model}

            # If dimensions exists on the model, add it to the parameters
            if self.model.dimensions is not None:
                params["dimensions"] = self.model.dimensions

            # Add provider-specific API configuration
            if self.api_config:
                params.update(self.api_config)
                logger.info(f"[LiteLLM] {self.litellm_model}: Adding provider config for embeddings: {list(self.api_config.keys())}")

            logger.info(f"[LiteLLM] {self.litellm_model}: Making embedding request with {len(texts)} texts")

            # Call LiteLLM API to get the embeddings
            response = await litellm.aembedding(**params)

            logger.info(f"[LiteLLM] {self.litellm_model}: Embedding request successful")

        except litellm.BadRequestError as e:
            logger.exception(f"[LiteLLM] {self.litellm_model}: Bad request error:")
            raise BadRequestException("Invalid input") from e
        except litellm.RateLimitError as e:
            logger.exception(f"[LiteLLM] {self.litellm_model}: Rate limit error:")
            raise OpenAIException("LiteLLM Rate limit exception") from e
        except Exception as e:
            logger.exception(f"[LiteLLM] {self.litellm_model}: Unknown LiteLLM exception:")
            raise OpenAIException("Unknown LiteLLM exception") from e

        return [embedding['embedding'] for embedding in response.data]
