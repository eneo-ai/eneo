import json
from typing import AsyncGenerator, Optional

import litellm
from litellm import AuthenticationError, APIError, RateLimitError

from intric.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModel,
    Context,
    ModelKwargs,
)
from intric.completion_models.infrastructure.adapters.base_adapter import (
    CompletionModelAdapter,
)
from intric.ai_models.litellm_providers.provider_registry import LiteLLMProviderRegistry
from intric.logging.logging import LoggingDetails
from intric.main.config import get_settings
from intric.main.exceptions import APIKeyNotConfiguredException, OpenAIException
from intric.main.logging import get_logger
from intric.settings.credential_resolver import CredentialResolver

logger = get_logger(__name__)

TOKENS_RESERVED_FOR_COMPLETION = 1000


class LiteLLMModelAdapter(CompletionModelAdapter):
    def _mask_sensitive_kwargs(self, kwargs: dict) -> dict:
        """Return copy of kwargs with masked API key for safe logging."""
        safe_kwargs = kwargs.copy()
        if "api_key" in safe_kwargs:
            key = safe_kwargs["api_key"]
            safe_kwargs["api_key"] = f"...{key[-4:]}" if len(key) > 4 else "***"
        return safe_kwargs

    def __init__(
        self,
        model: CompletionModel,
        credential_resolver: Optional[CredentialResolver] = None,
    ):
        super().__init__(model)
        self.credential_resolver = credential_resolver

        # Get provider configuration based on litellm_model_name
        provider_registry = LiteLLMProviderRegistry.get_provider_for_model(
            model.litellm_model_name
        )

        # Only apply custom configuration if needed
        if provider_registry.needs_custom_config():
            self.litellm_model = provider_registry.get_litellm_model(model.litellm_model_name)
            self.api_config = provider_registry.get_api_config()
            logger.info(
                f"[LiteLLM] Using custom provider config for {model.name}: {list(self.api_config.keys())}"
            )
        else:
            # Standard LiteLLM behavior for supported providers
            self.litellm_model = model.litellm_model_name
            self.api_config = {}

        # Validate credentials early if credential_resolver is provided
        # This ensures errors are raised before streaming starts
        if credential_resolver is not None:
            provider = self._detect_provider(self.litellm_model)
            try:
                # Pre-validate that credential exists
                # Don't store it yet - will get it per-request for security
                _ = credential_resolver.get_api_key(provider)
                logger.info(
                    f"[LiteLLM] Validated credential for provider {provider}",
                    extra={
                        "model": model.name,
                        "provider": provider,
                    },
                )
            except ValueError as e:
                logger.error(
                    f"[LiteLLM] Credential validation failed during initialization",
                    extra={
                        "model": model.name,
                        "provider": provider,
                        "error": str(e),
                    },
                )
                raise APIKeyNotConfiguredException(str(e))

        logger.info(
            f"[LiteLLM] Initializing adapter for model: {model.name} -> {self.litellm_model}"
        )

    def _detect_provider(self, litellm_model_name: str) -> str:
        """
        Detect provider from model name.

        Args:
            litellm_model_name: The LiteLLM model name (e.g., 'azure/gpt-4', 'anthropic/claude-3')

        Returns:
            Provider name (openai, azure, anthropic, berget, mistral, ovhcloud, vllm)
        """
        if litellm_model_name.startswith("azure/"):
            return "azure"
        elif litellm_model_name.startswith("anthropic/"):
            return "anthropic"
        elif litellm_model_name.startswith("berget/"):
            return "berget"
        elif litellm_model_name.startswith("mistral/"):
            return "mistral"
        elif litellm_model_name.startswith("ovhcloud/"):
            return "ovhcloud"
        elif litellm_model_name.startswith("vllm/"):
            return "vllm"
        else:
            # Default to OpenAI for unprefixed models
            return "openai"

    def _get_kwargs(self, kwargs: ModelKwargs | None):
        if kwargs is None:
            logger.info(f"[LiteLLM] {self.litellm_model}: No kwargs provided")
            return {}

        # Get all kwargs from the model
        all_kwargs = kwargs.model_dump(exclude_none=True)
        logger.info(
            f"[LiteLLM] {self.litellm_model}: Parameters being sent: {all_kwargs}"
        )

        # Pass all parameters directly to LiteLLM
        # Let the API handle parameter validation
        return all_kwargs

    def get_token_limit_of_model(self):
        return self.model.token_limit - TOKENS_RESERVED_FOR_COMPLETION

    def get_logging_details(self, context: Context, model_kwargs: ModelKwargs):
        query = self.create_query_from_context(context=context)
        processed_kwargs = self._get_kwargs(model_kwargs)

        logger.info(
            f"[LiteLLM] {self.litellm_model}: Logging request with {len(query)} messages and processed kwargs: {self._mask_sensitive_kwargs(processed_kwargs)}"
        )

        return LoggingDetails(
            json_body=json.dumps(query), model_kwargs=processed_kwargs
        )

    def create_query_from_context(self, context: Context):
        messages = []

        # Add system prompt if present
        if context.prompt:
            messages.append({"role": "system", "content": context.prompt})

        # Add conversation history
        for message in context.messages:
            # Add user message
            user_content = []
            user_content.append({"type": "text", "text": message.question})

            # Add images if present
            for image in message.images:
                if hasattr(image, "base64_content") and image.base64_content:
                    user_content.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image.base64_content}"
                            },
                        }
                    )

            messages.append(
                {
                    "role": "user",
                    "content": user_content
                    if len(user_content) > 1
                    else message.question,
                }
            )

            # Add assistant response
            messages.append({"role": "assistant", "content": message.answer})

        # Add current input
        current_content = []
        current_content.append({"type": "text", "text": context.input})

        # Add current images
        for image in context.images:
            if hasattr(image, "base64_content") and image.base64_content:
                current_content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image.base64_content}"
                        },
                    }
                )

        messages.append(
            {
                "role": "user",
                "content": current_content
                if len(current_content) > 1
                else context.input,
            }
        )

        return messages

    async def get_response(
        self, context: Context, model_kwargs: ModelKwargs | None = None
    ):
        messages = self.create_query_from_context(context=context)
        kwargs = self._get_kwargs(model_kwargs)

        # Add provider-specific API configuration
        if self.api_config:
            kwargs.update(self.api_config)
            logger.info(
                f"[LiteLLM] {self.litellm_model}: Adding provider config: {list(self.api_config.keys())}"
            )

        # Inject tenant-specific API key if credential_resolver is provided
        if self.credential_resolver:
            provider = self._detect_provider(self.litellm_model)
            try:
                api_key = self.credential_resolver.get_api_key(provider)
                kwargs["api_key"] = api_key
                logger.info(
                    f"[LiteLLM] {self.litellm_model}: Injecting tenant API key for {provider}"
                )
            except ValueError as e:
                logger.error(
                    f"[LiteLLM] {self.litellm_model}: Credential resolution failed: {e}"
                )
                raise APIKeyNotConfiguredException(str(e))

            # Inject api_base for VLLM and other providers with custom endpoints
            # VLLM requires endpoint - fallback to global VLLM_MODEL_URL for single-tenant deployments
            settings = get_settings()
            endpoint_fallback = settings.vllm_model_url if provider == "vllm" else None
            endpoint = self.credential_resolver.get_credential_field(
                provider=provider,
                field="endpoint",
                fallback=endpoint_fallback
            )

            if endpoint:
                kwargs["api_base"] = endpoint
                logger.info(
                    f"[LiteLLM] {self.litellm_model}: Injecting endpoint for {provider}: {endpoint}"
                )

        logger.info(
            f"[LiteLLM] {self.litellm_model}: Making completion request with {len(messages)} messages and kwargs: {self._mask_sensitive_kwargs(kwargs)}"
        )

        try:
            response = await litellm.acompletion(
                model=self.litellm_model, messages=messages, **kwargs
            )

            logger.info(
                f"[LiteLLM] {self.litellm_model}: Completion successful, response received"
            )
            content = response.choices[0].message.content or ""
            return Completion(text=content, stop=True)

        except AuthenticationError as exc:
            # Invalid API credentials
            provider = self._detect_provider(self.litellm_model)
            logger.error(
                "Authentication failed",
                extra={
                    "tenant_id": str(self.credential_resolver.tenant.id) if self.credential_resolver and self.credential_resolver.tenant else None,
                    "tenant_name": self.credential_resolver.tenant.name if self.credential_resolver and self.credential_resolver.tenant else None,
                    "provider": provider,
                    "error_type": "AuthenticationError",
                    "model": self.litellm_model,
                },
            )
            raise APIKeyNotConfiguredException(
                f"Invalid API credentials for provider '{provider}'. "
                f"Please verify your API key configuration."
            ) from exc

        except RateLimitError as exc:
            provider = self._detect_provider(self.litellm_model)
            logger.error(
                "Rate limit error",
                extra={
                    "provider": provider,
                    "model": self.litellm_model,
                },
            )
            raise OpenAIException(
                f"Rate limit exceeded for {provider}. Please try again later."
            ) from exc

        except APIError as exc:
            # API errors including Azure firewall/network issues
            error_message = str(exc)
            provider = self._detect_provider(self.litellm_model)
            logger.error(
                f"API error: {error_message}",
                extra={
                    "tenant_id": str(self.credential_resolver.tenant.id) if self.credential_resolver and self.credential_resolver.tenant else None,
                    "provider": provider,
                    "model": self.litellm_model,
                },
            )

            # Check for Azure firewall/network errors in the error message
            if "Virtual Network/Firewall" in error_message or "Firewall rules" in error_message or "Access denied" in error_message:
                raise OpenAIException(
                    "Azure access denied: Virtual Network/Firewall rules. "
                    "Please check your Azure network configuration or contact your administrator."
                ) from exc
            elif "rate limit" in error_message.lower():
                raise OpenAIException(
                    f"Rate limit exceeded for {provider}. Please try again later."
                ) from exc
            else:
                raise OpenAIException(f"API error: {error_message}") from exc

        except Exception as exc:
            logger.exception(f"[LiteLLM] {self.litellm_model}: Unexpected error")
            raise OpenAIException("Unknown error occurred") from exc

    async def prepare_streaming(self, context: Context, model_kwargs: ModelKwargs | None = None):
        """
        Phase 1: Create stream connection before EventSourceResponse.
        Can raise exceptions for authentication, firewall, rate limit errors.
        """
        messages = self.create_query_from_context(context=context)
        kwargs = self._get_kwargs(model_kwargs)

        # Add provider-specific API configuration
        if self.api_config:
            kwargs.update(self.api_config)
            logger.info(
                f"[LiteLLM] {self.litellm_model}: Adding provider config for streaming: {list(self.api_config.keys())}"
            )

        # Inject tenant-specific API key - raises APIKeyNotConfiguredException if missing
        if self.credential_resolver:
            provider = self._detect_provider(self.litellm_model)
            try:
                api_key = self.credential_resolver.get_api_key(provider)
                kwargs["api_key"] = api_key
                logger.info(
                    f"[LiteLLM] {self.litellm_model}: Injecting tenant API key for streaming {provider}"
                )
            except ValueError as e:
                logger.error(
                    f"[LiteLLM] {self.litellm_model}: Credential resolution failed for streaming: {e}"
                )
                raise APIKeyNotConfiguredException(str(e))

            # Inject api_base for streaming
            # VLLM requires endpoint - fallback to global VLLM_MODEL_URL for single-tenant deployments
            settings = get_settings()
            endpoint_fallback = settings.vllm_model_url if provider == "vllm" else None
            endpoint = self.credential_resolver.get_credential_field(
                provider=provider,
                field="endpoint",
                fallback=endpoint_fallback
            )

            if endpoint:
                kwargs["api_base"] = endpoint
                logger.info(
                    f"[LiteLLM] {self.litellm_model}: Injecting endpoint for streaming {provider}: {endpoint}"
                )

        logger.info(
            f"[LiteLLM] {self.litellm_model}: Creating streaming connection with {len(messages)} messages and kwargs: {self._mask_sensitive_kwargs(kwargs)}"
        )

        # Create stream connection - can raise exceptions
        try:
            stream = await litellm.acompletion(
                model=self.litellm_model, messages=messages, stream=True, **kwargs
            )
            logger.info(f"[LiteLLM] {self.litellm_model}: Stream connection created successfully")
            return stream

        except AuthenticationError as exc:
            provider = self._detect_provider(self.litellm_model)
            logger.error(
                "Authentication failed (streaming)",
                extra={
                    "tenant_id": str(self.credential_resolver.tenant.id) if self.credential_resolver and self.credential_resolver.tenant else None,
                    "tenant_name": self.credential_resolver.tenant.name if self.credential_resolver and self.credential_resolver.tenant else None,
                    "provider": provider,
                    "error_type": "AuthenticationError",
                    "model": self.litellm_model,
                },
            )
            raise APIKeyNotConfiguredException(
                f"Invalid API credentials for provider '{provider}'. "
                f"Please verify your API key configuration."
            ) from exc

        except RateLimitError as exc:
            provider = self._detect_provider(self.litellm_model)
            logger.error(
                "Rate limit error (streaming)",
                extra={
                    "provider": provider,
                    "model": self.litellm_model,
                },
            )
            raise OpenAIException(
                f"Rate limit exceeded for {provider}. Please try again later."
            ) from exc

        except APIError as exc:
            error_message = str(exc)
            provider = self._detect_provider(self.litellm_model)
            logger.error(
                f"API error (streaming): {error_message}",
                extra={
                    "tenant_id": str(self.credential_resolver.tenant.id) if self.credential_resolver and self.credential_resolver.tenant else None,
                    "provider": provider,
                    "model": self.litellm_model,
                },
            )

            # Check for Azure firewall/network errors in the error message
            if "Virtual Network/Firewall" in error_message or "Firewall rules" in error_message or "Access denied" in error_message:
                raise OpenAIException(
                    "Azure access denied: Virtual Network/Firewall rules. "
                    "Please check your Azure network configuration or contact your administrator."
                ) from exc
            elif "rate limit" in error_message.lower():
                raise OpenAIException(
                    f"Rate limit exceeded for {provider}. Please try again later."
                ) from exc
            else:
                raise OpenAIException(f"API error: {error_message}") from exc

        except Exception as exc:
            logger.exception(f"[LiteLLM] {self.litellm_model}: Unexpected error creating stream")
            raise OpenAIException("Unknown error occurred") from exc

    async def iterate_stream(self, stream, context: Context = None, model_kwargs: ModelKwargs | None = None):
        """
        Phase 2: Iterate pre-created stream inside EventSourceResponse.
        Yields error events for mid-stream failures.
        """
        from intric.ai_models.completion_models.completion_model import ResponseType

        try:
            logger.info(f"[LiteLLM] {self.litellm_model}: Starting stream iteration")

            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield Completion(text=delta.content)

            # Send final stop chunk
            logger.info(f"[LiteLLM] {self.litellm_model}: Stream iteration completed")
            yield Completion(stop=True)

        except Exception as exc:
            # Mid-stream errors: yield error event instead of raising
            logger.error(f"[LiteLLM] {self.litellm_model}: Error during stream iteration: {exc}")
            yield Completion(
                text="",
                error=f"Stream error: {str(exc)}",
                error_code=500,
                response_type=ResponseType.ERROR,
                stop=True
            )

    def get_response_streaming(
        self, context: Context, model_kwargs: ModelKwargs | None = None
    ):
        """
        Legacy method for backward compatibility.
        Uses two-phase pattern internally.
        """
        return self._get_response_streaming(context, model_kwargs)

    async def _get_response_streaming(
        self, context: Context, model_kwargs: ModelKwargs | None = None
    ) -> AsyncGenerator[Completion, None]:
        """
        Legacy implementation using two-phase pattern internally.
        """
        # Phase 1: Create stream (can raise exceptions)
        stream = await self.prepare_streaming(context, model_kwargs)

        # Phase 2: Iterate stream (yields error events for failures)
        async for chunk in self.iterate_stream(stream, context, model_kwargs):
            yield chunk
