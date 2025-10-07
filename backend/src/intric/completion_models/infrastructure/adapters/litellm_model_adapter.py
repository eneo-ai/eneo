import json
from typing import AsyncGenerator, Optional

import litellm
from litellm import AuthenticationError
from fastapi import HTTPException

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
        provider = LiteLLMProviderRegistry.get_provider_for_model(
            model.litellm_model_name
        )

        # Only apply custom configuration if needed
        if provider.needs_custom_config():
            self.litellm_model = provider.get_litellm_model(model.litellm_model_name)
            self.api_config = provider.get_api_config()
            logger.info(
                f"[LiteLLM] Using custom provider config for {model.name}: {list(self.api_config.keys())}"
            )
        else:
            # Standard LiteLLM behavior for supported providers
            self.litellm_model = model.litellm_model_name
            self.api_config = {}

        logger.info(
            f"[LiteLLM] Initializing adapter for model: {model.name} -> {self.litellm_model}"
        )

        # LiteLLM will automatically detect and use environment variables:
        # - AZURE_API_KEY
        # - AZURE_API_BASE
        # - AZURE_API_VERSION
        # when the model name starts with 'azure/'

    def _detect_provider(self, litellm_model_name: str) -> str:
        """
        Detect provider from model name.

        Args:
            litellm_model_name: The LiteLLM model name (e.g., 'azure/gpt-4', 'anthropic/claude-3')

        Returns:
            Provider name (openai, azure, anthropic, berget, mistral, ovhcloud)
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
                raise HTTPException(
                    status_code=503, detail=f"LLM service unavailable: {str(e)}"
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

        except AuthenticationError:
            # Strict error handling: NO fallback if tenant credential exists but is invalid
            provider = self._detect_provider(self.litellm_model)
            tenant_id = (
                self.credential_resolver.tenant.id
                if self.credential_resolver and self.credential_resolver.tenant
                else None
            )
            tenant_name = (
                self.credential_resolver.tenant.name
                if self.credential_resolver and self.credential_resolver.tenant
                else None
            )

            logger.error(
                "Tenant API credential authentication failed",
                extra={
                    "tenant_id": str(tenant_id) if tenant_id else None,
                    "tenant_name": tenant_name,
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

        except Exception as e:
            logger.error(
                f"[LiteLLM] {self.litellm_model}: Completion failed with error: {e}"
            )
            logger.error(
                f"[LiteLLM] {self.litellm_model}: Failed request had kwargs: {self._mask_sensitive_kwargs(kwargs)}"
            )
            raise

    def get_response_streaming(
        self, context: Context, model_kwargs: ModelKwargs | None = None
    ):
        return self._get_response_streaming(context, model_kwargs)

    async def _get_response_streaming(
        self, context: Context, model_kwargs: ModelKwargs | None = None
    ) -> AsyncGenerator[Completion, None]:
        messages = self.create_query_from_context(context=context)
        kwargs = self._get_kwargs(model_kwargs)

        # Add provider-specific API configuration
        if self.api_config:
            kwargs.update(self.api_config)
            logger.info(
                f"[LiteLLM] {self.litellm_model}: Adding provider config for streaming: {list(self.api_config.keys())}"
            )

        # Inject tenant-specific API key if credential_resolver is provided
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
                raise HTTPException(
                    status_code=503, detail=f"LLM service unavailable: {str(e)}"
                )

        logger.info(
            f"[LiteLLM] {self.litellm_model}: Making streaming completion request with {len(messages)} messages and kwargs: {self._mask_sensitive_kwargs(kwargs)}"
        )

        try:
            response = await litellm.acompletion(
                model=self.litellm_model, messages=messages, stream=True, **kwargs
            )

            logger.info(f"[LiteLLM] {self.litellm_model}: Streaming completion started")

            async for chunk in response:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield Completion(text=delta.content)

            # Send final stop chunk
            logger.info(
                f"[LiteLLM] {self.litellm_model}: Streaming completion finished"
            )
            yield Completion(stop=True)

        except AuthenticationError:
            # Strict error handling: NO fallback if tenant credential exists but is invalid
            provider = self._detect_provider(self.litellm_model)
            tenant_id = (
                self.credential_resolver.tenant.id
                if self.credential_resolver and self.credential_resolver.tenant
                else None
            )
            tenant_name = (
                self.credential_resolver.tenant.name
                if self.credential_resolver and self.credential_resolver.tenant
                else None
            )

            logger.error(
                "Tenant API credential authentication failed (streaming)",
                extra={
                    "tenant_id": str(tenant_id) if tenant_id else None,
                    "tenant_name": tenant_name,
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

        except Exception as e:
            logger.error(
                f"[LiteLLM] {self.litellm_model}: Streaming completion failed with error: {e}"
            )
            logger.error(
                f"[LiteLLM] {self.litellm_model}: Failed streaming request had kwargs: {self._mask_sensitive_kwargs(kwargs)}"
            )
            raise
