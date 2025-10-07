from typing import Optional

from mistralai import Mistral
from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from intric.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModel,
    Context,
    FunctionCall,
    ModelKwargs,
)
from intric.completion_models.infrastructure.adapters.openai_model_adapter import (
    OpenAIModelAdapter,
)
from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException
from intric.main.logging import get_logger
from intric.settings.credential_resolver import CredentialResolver

logger = get_logger(__name__)

TOKENS_RESERVED_FOR_COMPLETION = 1000


class MistralModelAdapter(OpenAIModelAdapter):
    def __init__(
        self,
        model: CompletionModel,
        credential_resolver: Optional[CredentialResolver] = None,
    ):
        self.model = model
        self.credential_resolver = credential_resolver

    def _build_tools_from_context(self, context: Context):
        if not context.function_definitions:
            return []

        if not self.model.vision:
            return []

        return [
            {
                "type": "function",
                "function": {
                    "name": function_definition.name,
                    "description": function_definition.description,
                    "parameters": function_definition.schema,
                    "required": function_definition.schema.get("required", []),
                },
            }
            for function_definition in context.function_definitions
        ]

    def _get_api_key(self) -> str:
        """Get API key from credential resolver or fall back to global settings."""
        if self.credential_resolver is not None:
            return self.credential_resolver.get_api_key("mistral")
        return get_settings().mistral_api_key

    @retry(
        wait=wait_random_exponential(min=1, max=20),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def get_response(
        self,
        context: Context,
        model_kwargs: ModelKwargs | None = None,
    ):
        query = self.create_query_from_context(context=context)
        kwargs = self._get_kwargs(model_kwargs)

        try:
            async with Mistral(api_key=self._get_api_key()) as mistral:
                response = await mistral.chat.complete_async(
                    model=self.model.name, messages=query, **kwargs
                )

                completion_str = response.choices[0].message.content.strip()
                return Completion(text=completion_str)

        except Exception as e:
            logger.error(f"Error calling Mistral API: {e}")
            raise

    def get_response_streaming(
        self,
        context: Context,
        model_kwargs: ModelKwargs | None = None,
    ):
        query = self.create_query_from_context(context=context)
        kwargs = self._get_kwargs(model_kwargs)
        tools = self._build_tools_from_context(context=context)

        @retry(
            wait=wait_random_exponential(min=1, max=20),
            stop=stop_after_attempt(3),
            retry=retry_if_not_exception_type(BadRequestException),
            reraise=True,
        )
        async def stream_generator():
            try:
                async with Mistral(api_key=self._get_api_key()) as mistral:
                    res = await mistral.chat.stream_async(
                        model=self.model.name,
                        messages=query,
                        tools=tools,
                        **kwargs,
                    )

                    async with res as event_stream:
                        async for event in event_stream:
                            choice = event.data.choices[0]
                            delta = choice.delta

                            completion = Completion()

                            if choice.finish_reason:
                                completion.stop = True

                            if delta.tool_calls:
                                tool_call = delta.tool_calls[0]

                                completion.tool_call = FunctionCall(
                                    name=tool_call.function.name,
                                    arguments=tool_call.function.arguments,
                                )

                            elif delta.content:
                                completion.text = delta.content

                            yield completion

            except Exception as e:
                logger.error(f"Error streaming from Mistral API: {e}")
                raise

        return stream_generator()
