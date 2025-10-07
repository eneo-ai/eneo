from typing import Optional

from openai import AsyncOpenAI

from intric.ai_models.completion_models.completion_model import CompletionModel
from intric.completion_models.infrastructure.adapters.openai_model_adapter import (
    OpenAIModelAdapter,
)
from intric.main.config import SETTINGS
from intric.settings.credential_resolver import CredentialResolver


class OVHCloudModelAdapter(OpenAIModelAdapter):
    def __init__(
        self,
        model: CompletionModel,
        credential_resolver: Optional[CredentialResolver] = None,
    ):
        self.model = model

        # Resolve API key from credential resolver or fall back to global settings
        if credential_resolver is not None:
            ovhcloud_api_key = credential_resolver.get_setting("ovhcloud_api_key")
        else:
            ovhcloud_api_key = SETTINGS.ovhcloud_api_key

        self.client = AsyncOpenAI(
            api_key=ovhcloud_api_key, base_url=model.base_url
        )
        self.extra_headers = None
