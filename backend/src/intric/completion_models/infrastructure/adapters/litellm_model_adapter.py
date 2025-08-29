import base64
import json
from typing import AsyncGenerator

from litellm import acompletion

from intric.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModel,
    Context,
    FunctionCall,
    ModelKwargs,
)
from intric.completion_models.infrastructure.adapters.base_adapter import (
    CompletionModelAdapter,
)
from intric.files.file_models import File
from intric.logging.logging import LoggingDetails
from intric.main.logging import get_logger

logger = get_logger(__name__)

TOKENS_RESERVED_FOR_COMPLETION = 1000


class LiteLLMAdapter(CompletionModelAdapter):
    def __init__(self, model: CompletionModel):
        self.model = model

    def _get_kwargs(self, kwargs: ModelKwargs | None):
        if kwargs is None:
            return {}

        return kwargs.model_dump(exclude_none=True)

    def get_token_limit_of_model(self):
        return self.model.token_limit - TOKENS_RESERVED_FOR_COMPLETION

    def get_logging_details(self, context: Context, model_kwargs: ModelKwargs):
        query = self.create_query_from_context(context=context)
        return LoggingDetails(
            json_body=json.dumps(query), model_kwargs=self._get_kwargs(model_kwargs)
        )

    def _build_image(self, file: File):
        image_data = base64.b64encode(file.blob).decode("utf-8")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{file.mimetype};base64,{image_data}"},
        }

    def _build_content(self, input: str, images: list[File]):
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
            content.append(self._build_image(image))

        return content

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
                    "strict": True,
                },
            }
            for function_definition in context.function_definitions
        ]

    def create_query_from_context(self, context: Context):
        system_message = []
        if context.prompt and context.prompt.strip():
            system_message = [{"role": "system", "content": context.prompt}]

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
                    "content": question.answer,
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

        return system_message + previous_messages + question

    async def get_response(
        self,
        context: Context,
        model_kwargs: ModelKwargs | None = None,
    ):
        query = self.create_query_from_context(context=context)

        try:
            response = await acompletion(
                model=self.model.litellm_model_name,
                messages=query,
                **self._get_kwargs(model_kwargs),
            )

            # Extract completion text from LiteLLM response
            completion_text = response.choices[0].message.content

            return {
                "completion": completion_text,
                "usage": {
                    "total_tokens": response.usage.total_tokens,
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                },
            }
        except Exception as e:
            logger.error(f"LiteLLM completion error: {e}")
            raise

    async def get_response_streaming(
        self,
        context: Context,
        model_kwargs: ModelKwargs | None = None,
    ) -> AsyncGenerator[Completion, None]:
        query = self.create_query_from_context(context=context)
        tools = self._build_tools_from_context(context=context)

        try:
            response_stream = await acompletion(
                model=self.model.litellm_model_name,
                messages=query,
                stream=True,
                tools=tools if tools else None,
                **self._get_kwargs(model_kwargs),
            )

            async for chunk in response_stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta

                    completion = Completion()

                    # Handle content
                    if hasattr(delta, 'content') and delta.content:
                        completion.text = delta.content

                    # Handle tool calls
                    if hasattr(delta, 'tool_calls') and delta.tool_calls:
                        for tool_call in delta.tool_calls:
                            if hasattr(tool_call, 'function'):
                                completion.tool_call = FunctionCall(
                                    name=tool_call.function.name if hasattr(tool_call.function, 'name') else None,
                                    arguments=tool_call.function.arguments if hasattr(tool_call.function, 'arguments') else None
                                )

                    # Handle reasoning tokens (Claude 3.7 specific)
                    if hasattr(chunk, 'usage') and chunk.usage:
                        completion.reasoning_token_count = getattr(chunk.usage, 'reasoning_tokens', 0)

                    yield completion

        except Exception as e:
            logger.error(f"LiteLLM streaming error: {e}")
            raise
