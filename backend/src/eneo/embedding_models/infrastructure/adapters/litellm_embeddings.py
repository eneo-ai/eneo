import asyncio
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Optional

from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)
from typing_extensions import override

from eneo.embedding_models.infrastructure.adapters.base import (
    EmbeddingModelAdapter,
    PartialEmbeddingBatchError,
)
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


class _EmbeddingRequestDeadlineExceeded(TimeoutError):
    """The crawler-owned request deadline expired after dispatch."""


class LiteLLMEmbeddingAdapter(EmbeddingModelAdapter):
    def __init__(
        self,
        model: "EmbeddingModelLike",
        credential_resolver: Optional[TenantModelCredentialResolver] = None,
        litellm_model_name: Optional[str] = None,
        request_semaphore: asyncio.Semaphore | None = None,
        request_timeout_seconds: float | None = None,
    ) -> None:
        super().__init__(model)
        self.credential_resolver = credential_resolver
        self.request_semaphore = request_semaphore
        self.request_timeout_seconds = request_timeout_seconds
        self._provider_kwargs: dict[str, object] | None = None

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
        completed_count = 0

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

            try:
                embeddings_for_chunks: list[list[float]] = await self._get_embeddings(
                    texts=texts_for_chunks
                )
                chunk_embedding_list.add(chunked_chunks, embeddings_for_chunks)
            except Exception as error:
                raise PartialEmbeddingBatchError(
                    completed=chunk_embedding_list,
                    completed_count=completed_count,
                    cause=error,
                ) from error
            completed_count += len(chunked_chunks)

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
            (
                *litellm_transport.NON_RETRYABLE_PROVIDER_ERRORS,
                _EmbeddingRequestDeadlineExceeded,
            )
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
                if self._provider_kwargs is None:
                    provider = self.credential_resolver.provider_type
                    provider_kwargs = build_litellm_provider_kwargs(
                        self.credential_resolver
                    )

                    # Inject endpoint for providers with custom endpoints.
                    settings = get_settings()
                    endpoint_fallback = (
                        settings.infinity_url if provider == "infinity" else None
                    )
                    endpoint = provider_kwargs.get("api_base") or endpoint_fallback
                    if endpoint:
                        provider_kwargs["api_base"] = endpoint
                        logger.debug(
                            f"[LiteLLM] {self.litellm_model}: Injecting endpoint for {provider}: {endpoint}"
                        )
                    self._provider_kwargs = provider_kwargs

                params.update(self._provider_kwargs)

            safe_params = {
                key: value
                for key, value in params.items()
                if key not in {"api_key", "input"}
            }
            logger.debug(
                f"[LiteLLM] {self.litellm_model}: Making embedding request with {len(texts)} texts and params: "
                f"{safe_params}"
            )

            # Queueing for a global slot must not consume the provider timeout.
            request_deadline: asyncio.Timeout | None = None
            try:
                async with AsyncExitStack() as request_stack:
                    if self.request_semaphore is not None:
                        await request_stack.enter_async_context(self.request_semaphore)
                    if self.request_timeout_seconds is not None:
                        request_deadline = asyncio.timeout(self.request_timeout_seconds)
                        await request_stack.enter_async_context(request_deadline)
                    response = await litellm_transport.aembedding(**params)
            except TimeoutError as error:
                if request_deadline is None or not request_deadline.expired():
                    raise
                raise _EmbeddingRequestDeadlineExceeded(
                    "Embedding request deadline exceeded"
                ) from error

            logger.debug(
                f"[LiteLLM] {self.litellm_model}: Embedding request successful"
            )

        except _EmbeddingRequestDeadlineExceeded:
            raise
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
