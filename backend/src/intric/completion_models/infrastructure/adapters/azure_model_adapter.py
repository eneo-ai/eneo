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
from intric.settings.credential_resolver import CredentialResolver


class AzureOpenAIModelAdapter(OpenAIModelAdapter):
    def __init__(
        self,
        model: CompletionModel,
        credential_resolver: Optional[CredentialResolver] = None,
    ):
        self.model = model

        # If credential_resolver is provided, resolve tenant-specific API key
        if credential_resolver is not None:
            api_key = credential_resolver.get_api_key("azure")
            azure_endpoint = credential_resolver.get_setting("azure_endpoint")
            azure_api_version = credential_resolver.get_setting("azure_api_version")
            self.client: AsyncAzureOpenAI = AsyncAzureOpenAI(
                api_key=api_key,
                azure_endpoint=azure_endpoint,
                api_version=azure_api_version,
            )
        # Fall back to global settings
        else:
            self.client: AsyncAzureOpenAI = AsyncAzureOpenAI(
                api_key=get_settings().azure_api_key,
                azure_endpoint=get_settings().azure_endpoint,
                api_version=get_settings().azure_api_version,
            )

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
        return await get_response_open_ai.get_response(
            client=self.client,
            model_name=self.model.deployment_name,
            messages=query,
            model_kwargs=self._get_kwargs(model_kwargs),
        )

    def get_response_streaming(
        self,
        context: Context,
        model_kwargs: ModelKwargs | None = None,
    ):
        query = self.create_query_from_context(context=context)
        return get_response_open_ai.get_response_streaming(
            client=self.client,
            model_name=self.model.deployment_name,
            messages=query,
            model_kwargs=self._get_kwargs(model_kwargs),
        )
