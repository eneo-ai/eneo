from typing import Optional

from openai import AsyncAzureOpenAI

from intric.ai_models.completion_models.completion_model import (
    CompletionModel,
    Context,
    ModelKwargs,
)
from intric.completion_models.infrastructure import get_response_open_ai
from intric.completion_models.infrastructure.adapters.openai_model_adapter import (
    OpenAIModelAdapter,
)
from intric.main.config import get_settings
from intric.main.exceptions import APIKeyNotConfiguredException
from intric.main.logging import get_logger
from intric.settings.credential_resolver import CredentialResolver

logger = get_logger(__name__)


class AzureOpenAIModelAdapter(OpenAIModelAdapter):
    def __init__(
        self,
        model: CompletionModel,
        credential_resolver: Optional[CredentialResolver] = None,
    ):
        self.model = model
        settings = get_settings()

        # If credential_resolver is provided, resolve tenant-specific credentials
        # This will raise ValueError (converted to APIKeyNotConfiguredException) if key is missing
        if credential_resolver is not None:
            try:
                # Get API key (required)
                api_key = credential_resolver.get_api_key("azure")

                # Get endpoint - tenant-specific or global
                azure_endpoint = credential_resolver.get_credential_field(
                    "azure", "endpoint", settings.azure_endpoint
                )

                # Get API version - tenant-specific or global
                api_version = credential_resolver.get_credential_field(
                    "azure", "api_version", settings.azure_api_version
                )

                # Get deployment_name - tenant-specific or model default
                deployment_name = credential_resolver.get_credential_field(
                    "azure", "deployment_name", model.deployment_name
                )
                self._deployment_name = deployment_name or model.deployment_name

            except ValueError as e:
                logger.error(
                    "Azure credential resolution failed",
                    extra={
                        "model": model.name,
                        "error": str(e),
                    },
                )
                raise APIKeyNotConfiguredException(str(e))

            # Create client with tenant-specific or global configuration
            self.client: AsyncAzureOpenAI = AsyncAzureOpenAI(
                api_key=api_key,
                azure_endpoint=azure_endpoint,
                api_version=api_version,
            )
        # Fall back to global settings
        else:
            if not settings.azure_api_key:
                raise APIKeyNotConfiguredException(
                    "No API key configured for provider 'azure'. "
                    "Please contact your administrator to configure credentials for this provider."
                )
            self.client: AsyncAzureOpenAI = AsyncAzureOpenAI(
                api_key=settings.azure_api_key,
                azure_endpoint=settings.azure_endpoint,
                api_version=settings.azure_api_version,
            )
            # Use model's deployment_name when using global settings
            self._deployment_name = model.deployment_name

    def _get_kwargs(self, kwargs):
        kwargs = super()._get_kwargs(kwargs)

        # For reasoning models hosted by Azure max_completion_tokens has to be provided.
        # https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/reasoning?tabs=python-secure#api--feature-support
        if self.model.reasoning:
            kwargs["max_completion_tokens"] = 5000

        return kwargs

    async def get_response(
        self,
        context: Context,
        model_kwargs: ModelKwargs | None = None,
    ):
        query = self.create_query_from_context(context=context)
        # All error handling is in get_response_open_ai.get_response
        # which properly handles AuthenticationError, PermissionDeniedError, etc.
        return await get_response_open_ai.get_response(
            client=self.client,
            model_name=self._deployment_name,
            messages=query,
            model_kwargs=self._get_kwargs(model_kwargs),
        )

    async def prepare_streaming(self, context: Context, model_kwargs: ModelKwargs | None = None):
        """
        Phase 1: Create stream connection before EventSourceResponse.
        Can raise exceptions for authentication, Azure firewall, rate limit errors.
        """
        query = self.create_query_from_context(context=context)

        # This can raise exceptions - that's what we want for pre-flight
        return await get_response_open_ai.prepare_stream(
            client=self.client,
            model_name=self._deployment_name,
            messages=query,
            model_kwargs=self._get_kwargs(model_kwargs),
        )

    async def iterate_stream(self, stream, context: Context = None, model_kwargs: ModelKwargs | None = None):
        """
        Phase 2: Iterate pre-created stream inside EventSourceResponse.
        Yields error events for mid-stream failures.
        """
        # Delegate to shared utility
        async for chunk in get_response_open_ai.iterate_stream(stream):
            yield chunk

    def get_response_streaming(
        self,
        context: Context,
        model_kwargs: ModelKwargs | None = None,
    ):
        """
        Legacy method for backward compatibility.
        Uses two-phase pattern internally via get_response_open_ai.get_response_streaming.
        """
        query = self.create_query_from_context(context=context)
        # All error handling is in get_response_open_ai.get_response_streaming
        # which properly raises exceptions for errors before streaming
        # and yields error events for errors during streaming (unavoidable)
        return get_response_open_ai.get_response_streaming(
            client=self.client,
            model_name=self._deployment_name,
            messages=query,
            model_kwargs=self._get_kwargs(model_kwargs),
        )
