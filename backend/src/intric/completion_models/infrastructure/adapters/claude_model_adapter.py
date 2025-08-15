import base64

from anthropic import AsyncAnthropic

from intric.ai_models.completion_models.completion_model import (
    CompletionModel,
    Context,
    ModelKwargs,
)
from intric.completion_models.infrastructure import get_response_claude
from intric.completion_models.infrastructure.adapters.base_adapter import (
    CompletionModelAdapter,
)
from intric.files.file_models import File
from intric.main.config import get_settings
from intric.main.logging import get_logger

logger = get_logger(__name__)

MAX_TOKENS = 4096


class ClaudeModelAdapter(CompletionModelAdapter):
    def __init__(
        self,
        model: CompletionModel,
        async_client: AsyncAnthropic = AsyncAnthropic(api_key=get_settings().anthropic_api_key),
    ):
        self.model = model
        self.async_client = async_client

    def _get_kwargs(self, kwargs: ModelKwargs | None):
        if kwargs is None:
            return {}

        # We allow input from (0, 2), however claude only takes (0, 1)
        if kwargs.temperature is not None:
            kwargs.temperature /= 2

        base_kwargs = kwargs.model_dump(exclude_none=True)
        
        # Remove Intric-specific parameters not supported by Claude API
        # These are our internal abstractions that need provider-specific handling
        base_kwargs.pop("thinking_budget", None)   # Legacy Gemini parameter
        base_kwargs.pop("reasoning_level", None)   # Unified abstraction
        
        return base_kwargs

    def get_token_limit_of_model(self):
        return self.model.token_limit

    def _build_image_input(self, file: File):
        image_data = base64.b64encode(file.blob).decode("utf-8")

        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": file.mimetype,
                "data": image_data,
            },
        }

    def _build_content(
        self,
        input: str,
        images: list[File],
    ):
        content = (
            [
                {
                    "type": "text",
                    "text": input,
                }
            ]
            if input
            else []
        )

        for image in images:
            content.append(self._build_image_input(image))

        return content

    def _build_tools_from_context(self, context: Context):
        if not context.function_definitions:
            return []

        if not self.model.vision:
            return []

        return [
            {
                "name": function_definition.name,
                "description": function_definition.description,
                "input_schema": function_definition.schema,
            }
            for function_definition in context.function_definitions
        ]

    def create_query_from_context(self, context: Context):
        previous_messages = [
            message
            for question in context.messages
            for message in [
                {
                    "role": "user",
                    "content": self._build_content(
                        input=question.question,
                        images=question.images + question.generated_images,
                    ),
                },
                {
                    "role": "assistant",
                    "content": question.answer or "[image generated]",
                },
            ]
        ]
        question = [
            {
                "role": "user",
                "content": self._build_content(
                    input=context.input,
                    images=context.images,
                ),
            }
        ]
        return previous_messages + question

    async def get_response(
        self,
        context: Context,
        model_kwargs: ModelKwargs | None = None,
    ):
        query = self.create_query_from_context(context=context)
        return await get_response_claude.get_response(
            client=self.async_client,
            max_tokens=MAX_TOKENS,
            model_name=self.model.name,
            prompt=context.prompt,
            messages=query,
            model_kwargs=self._get_kwargs(model_kwargs),
        )

    def get_response_streaming(
        self,
        context: Context,
        model_kwargs: ModelKwargs | None = None,
    ):
        query = self.create_query_from_context(context=context)
        tools = self._build_tools_from_context(context=context)
        return get_response_claude.get_response_streaming(
            client=self.async_client,
            max_tokens=MAX_TOKENS,
            model_name=self.model.name,
            prompt=context.prompt,
            messages=query,
            model_kwargs=self._get_kwargs(model_kwargs),
            tools=tools,
        )
