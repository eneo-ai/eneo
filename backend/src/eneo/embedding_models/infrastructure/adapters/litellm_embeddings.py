from typing import TYPE_CHECKING, Optional

from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)
from typing_extensions import override

from eneo.embedding_models.infrastructure.adapters.base import EmbeddingModelAdapter
from eneo.files.chunk_embedding_list import ChunkEmbeddingList
from eneo.main.config import get_settings
from eneo.main.logging import get_logger
from eneo.model_providers.infrastructure import litellm_transport
from eneo.model_providers.infrastructure.litellm_provider import (
    build_litellm_provider_kwargs,
)
from eneo.model_providers.infrastructure.tenant_model_credential_resolver import (
    TenantModelCredentialResolver,
)

if TYPE_CHECKING:
    from eneo.embedding_models.infrastructure.create_embeddings_service import (
        EmbeddingModelLike,
    )
    from eneo.files.chunk_embedding_list import InfoBlobChunk


logger = get_logger(__name__)


class LiteLLMEmbeddingAdapter(EmbeddingModelAdapter):
    def _mask_sensitive_params(self, params: dict[str, object]) -> dict[str, object]:
        """Return copy of params with masked API key for safe logging."""
        safe_params = dict(params)
        if "api_key" in safe_params:
            key = safe_params["api_key"]
            if isinstance(key, str):
                safe_params["api_key"] = f"...{key[-4:]}" if len(key) > 4 else "***"
        return safe_params

    def __init__(
        self,
        model: "EmbeddingModelLike",
        credential_resolver: Optional[TenantModelCredentialResolver] = None,
        litellm_model_name: Optional[str] = None,
    ) -> None:
        super().__init__(model)
        self.credential_resolver = credential_resolver

        # Use explicit litellm_model_name if provided (supports frozen dataclasses
        # like EmbeddingModelSpec where the name is constructed from provider info).
        # Falls back to model.litellm_model_name for mutable ORM objects.
        self.litellm_model = litellm_model_name or model.litellm_model_name

        logger.debug(
            f"[LiteLLM] Initializing embedding adapter for model: {model.name} -> {self.litellm_model}"
        )

    @override
    async def get_embeddings(self, chunks: list["InfoBlobChunk"]) -> ChunkEmbeddingList:
        chunk_embedding_list = ChunkEmbeddingList()
        batch_size = getattr(self.model, "max_batch_size", None) or 32
        total_chunks = len(chunks)
        total_batches = (
            (total_chunks + batch_size - 1) // batch_size if total_chunks else 0
        )
        logger.debug(
            "[LiteLLM] Model %s (family=%s) batching %s chunks into %s batches (size=%s)",
            self.model.name,
            self.model.family,
            total_chunks,
            total_batches,
            batch_size,
        )

        for chunked_chunks in self._chunk_chunks(chunks):
            # Add "passage:" prefix for E5 models, use text directly for others
            if self.model.family == "e5":
                texts_for_chunks = [
                    f"passage: {chunk.text}" for chunk in chunked_chunks
                ]
                logger.debug(
                    "[LiteLLM] %s: Using 'passage:' prefix (family=%s)",
                    self.model.name,
                    self.model.family,
                )
            else:
                texts_for_chunks = [chunk.text for chunk in chunked_chunks]
                logger.debug(
                    "[LiteLLM] %s: No prefix applied (family=%s)",
                    self.model.name,
                    self.model.family,
                )

            embeddings_for_chunks: list[list[float]] = await self._get_embeddings(
                texts=texts_for_chunks
            )
            chunk_embedding_list.add(chunked_chunks, embeddings_for_chunks)

        return chunk_embedding_list

    @override
    async def get_embedding_for_query(self, query: str) -> list[float]:
        # Add "query:" prefix for E5 models, use query directly for others
        max_input = self.model.max_input  # may be None → slice[:None] keeps full string
        if self.model.family == "e5":
            truncated_query = f"query: {query[:max_input]}"
            logger.debug(
                "[LiteLLM] %s: Using 'query:' prefix (family=%s)",
                self.model.name,
                self.model.family,
            )
        else:
            truncated_query = query[:max_input]
            logger.debug(
                "[LiteLLM] %s: No query prefix applied (family=%s)",
                self.model.name,
                self.model.family,
            )

        embeddings: list[list[float]] = await self._get_embeddings([truncated_query])
        return embeddings[0]

    @retry(
        wait=wait_random_exponential(min=1, max=20),
        stop=stop_after_attempt(3),
        retry=retry_if_not_exception_type(
            litellm_transport.NON_RETRYABLE_PROVIDER_ERRORS
        ),
        reraise=True,
    )
    async def _get_embeddings(self, texts: list[str]) -> list[list[float]]:
        try:
            # Guard against empty input - some APIs require non-empty input
            if not texts or len(texts) == 0:
                logger.warning(
                    "[LiteLLM] Empty text list provided to embeddings, returning empty result"
                )
                return []

            # Prepare the parameters for the embeddings.
            # Set encoding_format explicitly: LiteLLM otherwise defaults it to
            # null for OpenAI-compatible providers, which strict APIs (e.g.
            # Berget.ai) reject with "Expected 'float' | 'base64', received
            # null". "float" is the universal default and matches our expected
            # list-of-floats output.
            params: dict[str, object] = {
                "input": texts,
                "model": self.litellm_model,
                "encoding_format": "float",
            }

            # If dimensions exists on the model, add it to the parameters
            if self.model.dimensions is not None:
                params["dimensions"] = self.model.dimensions

            # Inject tenant-specific credentials if credential_resolver is provided
            if self.credential_resolver:
                provider = self.credential_resolver.provider_type

                params.update(build_litellm_provider_kwargs(self.credential_resolver))

                # Inject endpoint for providers with custom endpoints
                settings = get_settings()
                if provider == "infinity":
                    endpoint_fallback = settings.infinity_url
                else:
                    endpoint_fallback = None

                endpoint = params.get("api_base") or endpoint_fallback

                if endpoint:
                    params["api_base"] = endpoint
                    logger.debug(
                        f"[LiteLLM] {self.litellm_model}: Injecting endpoint for {provider}: {endpoint}"
                    )

            safe_params = {k: v for k, v in params.items() if k != "input"}
            logger.debug(
                f"[LiteLLM] {self.litellm_model}: Making embedding request with {len(texts)} texts and params: "
                f"{self._mask_sensitive_params(safe_params)}"
            )

            # Call LiteLLM API to get the embeddings
            response = await litellm_transport.aembedding(**params)

            logger.debug(
                f"[LiteLLM] {self.litellm_model}: Embedding request successful"
            )

        except Exception as e:
            logger.exception(
                f"[LiteLLM] {self.litellm_model}: Unknown LiteLLM exception:"
            )
            provider_type = (
                self.credential_resolver.provider_type
                if self.credential_resolver
                else "unknown"
            )
            litellm_transport.raise_public_litellm_error(
                e,
                provider_type=provider_type,
                is_unavailable=litellm_transport.is_provider_unavailable_error,
                raise_unavailable=litellm_transport.raise_provider_unavailable,
            )

        return [
            embedding["embedding"]  # pyright: ignore[reportUnknownVariableType,reportUnknownMemberType,reportUnknownArgumentType] – litellm EmbeddingResponse.data items lack full stubs
            for embedding in response.data  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType] – litellm lacks complete stubs
        ]
