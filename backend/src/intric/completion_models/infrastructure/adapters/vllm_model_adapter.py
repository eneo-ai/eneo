import json
from typing import Optional

import jinja2
from openai import AsyncOpenAI

from intric.ai_models.completion_models.completion_model import (
    CompletionModel,
    Context,
    ModelKwargs,
)
from intric.completion_models.infrastructure.adapters.openai_model_adapter import (
    OpenAIModelAdapter,
)
from intric.logging.logging import LoggingDetails
from intric.logging.logging_templates import LLAMA_TEMPLATE
from intric.main.config import SETTINGS
from intric.settings.credential_resolver import CredentialResolver

JINJA_TEMPLATE = jinja2.Environment().from_string(LLAMA_TEMPLATE)


class VLMMModelAdapter(OpenAIModelAdapter):
    def __init__(
        self,
        model: CompletionModel,
        credential_resolver: Optional[CredentialResolver] = None,
    ):
        self.model = model

        # Resolve API key from credential resolver or fall back to global settings
        if credential_resolver is not None:
            vllm_api_key = credential_resolver.get_setting("vllm_api_key")
            vllm_model_url = credential_resolver.get_setting("vllm_model_url")
        else:
            vllm_api_key = SETTINGS.vllm_api_key
            vllm_model_url = SETTINGS.vllm_model_url

        self.client = AsyncOpenAI(
            api_key="EMPTY", base_url=model.base_url or vllm_model_url
        )
        self.extra_headers = {"X-API-Key": vllm_api_key}

    def get_token_limit_of_model(self):
        return self.model.token_limit

    def get_logging_details(
        self,
        context: Context,
        model_kwargs: ModelKwargs | None = None,
    ):
        query = self.create_query_from_context(context=context)
        messages = {"messages": query}
        context = JINJA_TEMPLATE.render(messages)

        return LoggingDetails(
            context=context,
            model_kwargs=self._get_kwargs(model_kwargs),
            json_body=json.dumps(query),
        )

    def create_query_from_context(self, context: Context):
        system_message = (
            [{"role": "system", "content": context.prompt}] if context.prompt else []
        )

        previous_messages = [
            message
            for question in context.messages
            for message in [
                {"role": "user", "content": question.question},
                {"role": "assistant", "content": question.answer},
            ]
        ]
        question = [{"role": "user", "content": context.input}]

        return system_message + previous_messages + question
