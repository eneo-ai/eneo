from openai import AsyncOpenAI

from intric.ai_models.completion_models.completion_model import CompletionModel
from intric.completion_models.infrastructure.adapters.openai_model_adapter import (
    OpenAIModelAdapter,
)
from intric.main.config import get_settings


class OVHCloudModelAdapter(OpenAIModelAdapter):
    def __init__(self, model: CompletionModel):
        self.model = model
        self.client = AsyncOpenAI(
            api_key=get_settings().ovhcloud_api_key, base_url=model.base_url
        )
        self.extra_headers = None
