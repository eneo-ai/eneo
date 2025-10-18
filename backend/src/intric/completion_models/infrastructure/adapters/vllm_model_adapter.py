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
from intric.main.config import get_settings
from intric.settings.credential_resolver import CredentialResolver

JINJA_TEMPLATE = jinja2.Environment().from_string(LLAMA_TEMPLATE)


class VLMMModelAdapter(OpenAIModelAdapter):
    def __init__(
        self,
        model: CompletionModel,
        credential_resolver: Optional[CredentialResolver] = None,
    ):
        self.model = model
        settings = get_settings()

        api_key: Optional[str] = None
        tenant_endpoint: Optional[str] = None

        if credential_resolver is not None:
            try:
                api_key = credential_resolver.get_api_key("vllm")
            except ValueError as _exc:
                # In strict tenant mode we must surface the error immediately
                if settings.tenant_credentials_enabled and credential_resolver.tenant:
                    raise
                # Otherwise fall back to global credentials

            try:
                tenant_endpoint = credential_resolver.get_credential_field(
                    provider="vllm",
                    field="endpoint",
                    fallback=None,
                )
            except ValueError as _exc:
                if settings.tenant_credentials_enabled and credential_resolver.tenant:
                    raise

        if (
            tenant_endpoint is None
            and settings.tenant_credentials_enabled
            and credential_resolver.tenant
        ):
            # In strict multi-tenant mode we require both api_key and endpoint so that
            # traffic never leaks onto the shared VLLM infrastructure.
            raise ValueError(
                "No VLLM endpoint configured for tenant. Configure via "
                "PUT /api/v1/sysadmin/tenants/{tenant_id}/credentials/vllm."
            )

        if api_key is None:
            api_key = settings.vllm_api_key

        base_url_candidates = [tenant_endpoint, model.base_url, settings.vllm_model_url]
        base_url = next((url for url in base_url_candidates if url), None)

        if not api_key:
            raise ValueError(
                "No VLLM API key configured. Provide VLLM_API_KEY or tenant credential."
            )

        if not base_url:
            raise ValueError(
                "No VLLM endpoint configured. Provide VLLM_MODEL_URL, model.base_url, or tenant credential endpoint."
            )

        self.client = AsyncOpenAI(api_key="EMPTY", base_url=base_url)
        self.extra_headers = {"X-API-Key": api_key}

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
