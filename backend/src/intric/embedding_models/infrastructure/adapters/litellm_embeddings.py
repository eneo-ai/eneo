from typing import TYPE_CHECKING, Optional

import litellm
from fastapi import HTTPException
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
from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException, OpenAIException
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.embedding_models.domain.embedding_model import EmbeddingModel
    from intric.info_blobs.info_blob import InfoBlobChunk
    from intric.settings.credential_resolver import CredentialResolver


logger = get_logger(__name__)


class LiteLLMEmbeddingAdapter(EmbeddingModelAdapter):
    def _mask_sensitive_params(self, params: dict) -> dict:
        """Return copy of params with masked API key for safe logging."""
        safe_params = params.copy()
        if "api_key" in safe_params:
            key = safe_params["api_key"]
            safe_params["api_key"] = f"...{key[-4:]}" if len(key) > 4 else "***"
        return safe_params

    def __init__(
        self,
        model: "EmbeddingModel",
        credential_resolver: Optional["CredentialResolver"] = None
    ):
        super().__init__(model)
        self.credential_resolver = credential_resolver

        # Store the original model name for provider detection (before any transformation)
        # This is critical for correct credential resolution with custom providers
        self._original_model_name = model.litellm_model_name

        # Get provider configuration based on litellm_model_name
        provider = LiteLLMProviderRegistry.get_provider_for_model(model.litellm_model_name)

        # Only apply custom configuration if needed
        if provider.needs_custom_config():
            self.litellm_model = provider.get_litellm_model(model.litellm_model_name)
            self.api_config = provider.get_api_config()
            logger.debug(f"[LiteLLM] Using custom provider config for embedding {model.name}: {list(self.api_config.keys())}")
        else:
            # Standard LiteLLM behavior for supported providers
            self.litellm_model = model.litellm_model_name
            self.api_config = {}

        logger.debug(f"[LiteLLM] Initializing embedding adapter for model: {model.name} -> {self.litellm_model}")

    def _detect_provider(self, litellm_model_name: str) -> str:
        """
        Detect provider from model name.

        Args:
            litellm_model_name: The LiteLLM model name (e.g., 'azure/text-embedding-ada-002', 'vllm/e5-mistral-7b')

        Returns:
            Provider name (openai, azure, anthropic, berget, gdm, mistral, ovhcloud, vllm)
        """
        if litellm_model_name.startswith("azure/"):
            return "azure"
        elif litellm_model_name.startswith("anthropic/"):
            return "anthropic"
        elif litellm_model_name.startswith("berget/"):
            return "berget"
        elif litellm_model_name.startswith("gdm/"):
            return "gdm"
        elif litellm_model_name.startswith("mistral/"):
            return "mistral"
        elif litellm_model_name.startswith("ovhcloud/"):
            return "ovhcloud"
        elif litellm_model_name.startswith("vllm/"):
            return "vllm"
        else:
            # Default to OpenAI for unprefixed models
            return "openai"

    async def get_embeddings(self, chunks: list["InfoBlobChunk"]) -> ChunkEmbeddingList:
        chunk_embedding_list = ChunkEmbeddingList()
        batch_size = getattr(self.model, "max_batch_size", None) or 32
        total_chunks = len(chunks)
        total_batches = (total_chunks + batch_size - 1) // batch_size if total_chunks else 0
        logger.debug(
            "[LiteLLM] Model %s batching %s chunks into %s batches (size=%s)",
            self.model.name,
            total_chunks,
            total_batches,
            batch_size,
        )

        for chunked_chunks in self._chunk_chunks(chunks):
            # Add "passage:" prefix for E5 models, use text directly for others
            if self.model.family == ModelFamily.E5:
                texts_for_chunks = [f"passage: {chunk.text}" for chunk in chunked_chunks]
            else:
                texts_for_chunks = [chunk.text for chunk in chunked_chunks]

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
            # Guard against empty input - GDM API requires non-empty input
            if not texts or len(texts) == 0:
                logger.warning("[LiteLLM] Empty text list provided to embeddings, returning empty result")
                return []

            # Prepare the parameters for the embeddings
            params = {"input": texts, "model": self.litellm_model}

            # If dimensions exists on the model, add it to the parameters
            if self.model.dimensions is not None:
                params["dimensions"] = self.model.dimensions

            # Add provider-specific API configuration
            if self.api_config:
                params.update(self.api_config)
                logger.debug(f"[LiteLLM] {self.litellm_model}: Adding provider config for embeddings: {list(self.api_config.keys())}")

            # Inject tenant-specific API key if credential_resolver is provided
            if self.credential_resolver:
                provider = self._detect_provider(self._original_model_name)
                try:
                    api_key = self.credential_resolver.get_api_key(provider)
                    params['api_key'] = api_key
                    logger.debug(f"[LiteLLM] {self.litellm_model}: Injecting tenant API key for {provider}")
                except ValueError as e:
                    logger.error(f"[LiteLLM] {self.litellm_model}: Credential resolution failed: {e}")
                    raise HTTPException(
                        status_code=503,
                        detail=f"Embedding service unavailable: {str(e)}"
                    )

                # Inject endpoint for VLLM and other providers with custom endpoints
                # VLLM requires endpoint - fallback to global VLLM_MODEL_URL for single-tenant deployments
                settings = get_settings()
                endpoint_fallback = settings.vllm_model_url if provider == "vllm" else None
                endpoint = self.credential_resolver.get_credential_field(
                    provider=provider,
                    field="endpoint",
                    fallback=endpoint_fallback,
                    required=(provider in {"vllm", "azure"})  # endpoint is required for vLLM and Azure
                )

                if endpoint:
                    params['api_base'] = endpoint
                    logger.debug(f"[LiteLLM] {self.litellm_model}: Injecting endpoint for {provider}: {endpoint}")

                # Inject api_version for Azure embeddings
                if provider == "azure":
                    # In strict mode, each tenant must configure their own api_version
                    # In single-tenant mode, can fallback to global default
                    api_version = self.credential_resolver.get_credential_field(
                        "azure",
                        "api_version",
                        settings.azure_api_version,
                        required=(
                            self.credential_resolver.tenant is not None and
                            self.credential_resolver.settings.tenant_credentials_enabled
                        ),
                    )
                    if api_version:
                        params["api_version"] = api_version
                        logger.debug(f"[LiteLLM] {self.litellm_model}: Injecting api_version for Azure: {api_version}")

            safe_params = {k: v for k, v in params.items() if k != "input"}
            logger.debug(
                f"[LiteLLM] {self.litellm_model}: Making embedding request with {len(texts)} texts and params: "
                f"{self._mask_sensitive_params(safe_params)}"
            )

            # Call LiteLLM API to get the embeddings
            response = await litellm.aembedding(**params)

            logger.debug(f"[LiteLLM] {self.litellm_model}: Embedding request successful")

        except litellm.AuthenticationError:
            # Strict error handling: NO fallback if tenant credential exists but is invalid
            provider = self._detect_provider(self._original_model_name)
            tenant_id = self.credential_resolver.tenant.id if self.credential_resolver and self.credential_resolver.tenant else None
            tenant_name = self.credential_resolver.tenant.name if self.credential_resolver and self.credential_resolver.tenant else None

            logger.error(
                "Tenant API credential authentication failed",
                extra={
                    "tenant_id": str(tenant_id) if tenant_id else None,
                    "tenant_name": tenant_name,
                    "provider": provider,
                    "error_type": "AuthenticationError",
                    "model": self.litellm_model
                }
            )

            raise HTTPException(
                status_code=401,
                detail=f"Invalid API credentials for provider {provider}. "
                       f"Please verify your API key configuration."
            )
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
