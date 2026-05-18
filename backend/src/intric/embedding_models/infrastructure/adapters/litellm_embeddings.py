from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Protocol, TypeGuard, cast

import litellm
from fastapi import HTTPException
from litellm.exceptions import AuthenticationError, BadRequestError, RateLimitError
from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)
from typing_extensions import override

from intric.embedding_models.domain.embedding_batch import (
    EmbeddingBatchResult,
    EmbeddingUsage,
)
from intric.embedding_models.infrastructure.adapters.base import EmbeddingModelAdapter
from intric.files.chunk_embedding_list import ChunkEmbeddingList
from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException, OpenAIException
from intric.main.logging import get_logger
from intric.model_providers.infrastructure.tenant_model_credential_resolver import (
    TenantModelCredentialResolver,
)

if TYPE_CHECKING:
    from intric.embedding_models.infrastructure.create_embeddings_service import (
        EmbeddingModelLike,
    )
    from intric.files.chunk_embedding_list import InfoBlobChunk


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _LiteLLMEmbeddingBatch:
    embeddings: list[list[float]]
    usage: EmbeddingUsage


class _LiteLLMEmbeddingResponse(Protocol):
    data: object
    usage: object | None


_LiteLLMEmbeddingCallable = Callable[..., Awaitable[object]]


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

        self.litellm_model = litellm_model_name or model.litellm_model_name

        logger.debug(
            f"[LiteLLM] Initializing embedding adapter for model: {model.name} -> {self.litellm_model}"
        )

    @override
    async def get_embeddings(
        self, chunks: list["InfoBlobChunk"]
    ) -> EmbeddingBatchResult:
        chunk_embedding_list = ChunkEmbeddingList()
        total_tokens = 0
        prompt_tokens = 0
        saw_provider_usage = False

        for chunked_chunks in self._chunk_chunks(chunks):
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

            batch = await self._get_embeddings(texts=texts_for_chunks)
            chunk_embedding_list.add(chunked_chunks, batch.embeddings)
            if batch.usage.source == "provider_reported":
                saw_provider_usage = True
                total_tokens += batch.usage.total_tokens or 0
                prompt_tokens += batch.usage.prompt_tokens or 0

        usage = (
            EmbeddingUsage(
                prompt_tokens=prompt_tokens,
                total_tokens=total_tokens,
                source="provider_reported",
            )
            if saw_provider_usage
            else EmbeddingUsage(
                prompt_tokens=None,
                total_tokens=None,
                source="missing",
            )
        )
        return EmbeddingBatchResult(embeddings=chunk_embedding_list, usage=usage)

    @override
    async def get_embedding_for_query(self, query: str) -> list[float]:
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

        batch = await self._get_embeddings([truncated_query])
        return batch.embeddings[0]

    @retry(
        wait=wait_random_exponential(min=1, max=20),
        stop=stop_after_attempt(3),
        retry=retry_if_not_exception_type(BadRequestException),
        reraise=True,
    )
    async def _get_embeddings(self, texts: list[str]) -> _LiteLLMEmbeddingBatch:
        try:
            if not texts or len(texts) == 0:
                logger.warning(
                    "[LiteLLM] Empty text list provided to embeddings, returning empty result"
                )
                return _LiteLLMEmbeddingBatch(
                    embeddings=[],
                    usage=EmbeddingUsage(
                        prompt_tokens=None,
                        total_tokens=None,
                        source="missing",
                    ),
                )

            params: dict[str, object] = {
                "input": texts,
                "model": self.litellm_model,
            }

            if self.model.dimensions is not None:
                params["dimensions"] = self.model.dimensions

            if self.credential_resolver:
                provider = self.credential_resolver.provider_type

                try:
                    api_key = self.credential_resolver.get_api_key()
                    logger.debug(
                        f"[LiteLLM] {self.litellm_model}: Injecting tenant model API key for {provider}"
                    )
                    params["api_key"] = api_key
                except ValueError as e:
                    logger.error(
                        f"[LiteLLM] {self.litellm_model}: Credential resolution failed: {e}"
                    )
                    raise HTTPException(
                        status_code=503,
                        detail=f"Embedding service unavailable: {str(e)}",
                    )

                settings = get_settings()
                if provider == "infinity":
                    endpoint_fallback = settings.infinity_url
                else:
                    endpoint_fallback = None

                endpoint = self.credential_resolver.get_credential_field(
                    field="endpoint",
                    fallback=endpoint_fallback,
                    required=(provider in {"infinity", "azure"}),
                )

                if endpoint:
                    params["api_base"] = endpoint
                    logger.debug(
                        f"[LiteLLM] {self.litellm_model}: Injecting endpoint for {provider}: {endpoint}"
                    )

                if provider == "azure":
                    api_version = self.credential_resolver.get_credential_field(
                        field="api_version",
                        fallback=None,
                        required=True,
                    )

                    if api_version:
                        params["api_version"] = api_version
                        logger.debug(
                            f"[LiteLLM] {self.litellm_model}: Injecting api_version for Azure: {api_version}"
                        )

            safe_params = {k: v for k, v in params.items() if k != "input"}
            logger.debug(
                f"[LiteLLM] {self.litellm_model}: Making embedding request with {len(texts)} texts and params: "
                f"{self._mask_sensitive_params(safe_params)}"
            )

            response = await _call_litellm_embedding(params)

            logger.debug(
                f"[LiteLLM] {self.litellm_model}: Embedding request successful"
            )

        except AuthenticationError:
            provider = (
                self.credential_resolver.provider_type
                if self.credential_resolver
                else "unknown"
            )
            provider_id = (
                self.credential_resolver.provider_id
                if self.credential_resolver
                else None
            )

            logger.error(
                "Tenant API credential authentication failed",
                extra={
                    "provider_id": str(provider_id) if provider_id else None,
                    "provider": provider,
                    "error_type": "AuthenticationError",
                    "model": self.litellm_model,
                },
            )

            raise HTTPException(
                status_code=401,
                detail=f"Invalid API credentials for provider {provider}. "
                f"Please verify your API key configuration.",
            )
        except BadRequestError as e:
            logger.exception(f"[LiteLLM] {self.litellm_model}: Bad request error:")
            raise BadRequestException("Invalid input") from e
        except RateLimitError as e:
            logger.exception(f"[LiteLLM] {self.litellm_model}: Rate limit error:")
            raise OpenAIException("LiteLLM Rate limit exception") from e
        except Exception as e:
            logger.exception(
                f"[LiteLLM] {self.litellm_model}: Unknown LiteLLM exception:"
            )
            raise OpenAIException("Unknown LiteLLM exception") from e

        embeddings = _embedding_vectors_from_response(response)
        usage = _embedding_usage_from_response(response)
        return _LiteLLMEmbeddingBatch(embeddings=embeddings, usage=usage)


def _embedding_vectors_from_response(
    response: _LiteLLMEmbeddingResponse,
) -> list[list[float]]:
    data = response.data
    if not _is_non_string_sequence(data):
        raise OpenAIException("LiteLLM embedding response did not include data")

    return [_embedding_vector_from_item(item) for item in data]


def _embedding_vector_from_item(item: object) -> list[float]:
    if not isinstance(item, Mapping):
        raise OpenAIException("LiteLLM embedding response item was not an object")

    mapping = cast(Mapping[object, object], item)
    embedding = mapping.get("embedding")
    if not _is_non_string_sequence(embedding):
        raise OpenAIException("LiteLLM embedding response item lacked embedding")

    vector: list[float] = []
    for value in embedding:
        if not _is_embedding_number(value):
            raise OpenAIException("LiteLLM embedding vector contained a non-number")
        vector.append(float(value))
    return vector


def _is_non_string_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _is_embedding_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


async def _call_litellm_embedding(
    params: dict[str, object],
) -> _LiteLLMEmbeddingResponse:
    aembedding = cast(_LiteLLMEmbeddingCallable, getattr(litellm, "aembedding"))
    return cast(_LiteLLMEmbeddingResponse, await aembedding(**params))


def _embedding_usage_from_response(
    response: _LiteLLMEmbeddingResponse,
) -> EmbeddingUsage:
    usage = response.usage
    total_tokens = getattr(usage, "total_tokens", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None)

    if isinstance(total_tokens, int):
        return EmbeddingUsage(
            prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
            total_tokens=total_tokens,
            source="provider_reported",
        )

    return EmbeddingUsage(
        prompt_tokens=None,
        total_tokens=None,
        source="missing",
    )
