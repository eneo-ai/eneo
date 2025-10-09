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

    @retry(
        wait=wait_random_exponential(min=1, max=20),
        stop=stop_after_attempt(3),
        retry=retry_if_not_exception_type(BadRequestException),
        reraise=True,
    )
    async def prepare_streaming(self, context: Context, model_kwargs: ModelKwargs | None = None):
        """
        Phase 1: Create stream connection before EventSourceResponse.
        Can raise exceptions for authentication, connection, rate limit errors.
        """
        query = self.create_query_from_context(context=context)
        kwargs = self._get_kwargs(model_kwargs)
        tools = self._build_tools_from_context(context=context)

        try:
            # Create Mistral client and stream connection
            # Note: We need to keep the client alive, so we return both
            mistral_client = Mistral(api_key=self._get_api_key())
            res = await mistral_client.chat.stream_async(
                model=self.model.name,
                messages=query,
                tools=tools,
                **kwargs,
            )
            # Return tuple of (client, stream) so client stays alive
            return (mistral_client, res)

        except Exception as e:
            logger.error(f"Error creating Mistral stream: {e}")
            raise

    async def iterate_stream(self, stream, context: Context = None, model_kwargs: ModelKwargs | None = None):
        """
        Phase 2: Iterate pre-created stream inside EventSourceResponse.
        Yields error events for mid-stream failures.
        """
        from intric.ai_models.completion_models.completion_model import ResponseType

        # Unpack the tuple from prepare_streaming
        mistral_client, event_stream_response = stream

        try:
            async with event_stream_response as event_stream:
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

        except Exception as exc:
            # Mid-stream errors: yield error event instead of raising
            logger.error(f"Error during Mistral stream iteration: {exc}")
            yield Completion(
                text="",
                error=f"Stream error: {str(exc)}",
                error_code=500,
                response_type=ResponseType.ERROR,
                stop=True
            )
        finally:
            # Clean up the client
            await mistral_client.close()

    def get_response_streaming(
        self,
        context: Context,
        model_kwargs: ModelKwargs | None = None,
    ):
        """
        Legacy method for backward compatibility.
        Uses two-phase pattern internally.
        """
        @retry(
            wait=wait_random_exponential(min=1, max=20),
            stop=stop_after_attempt(3),
            retry=retry_if_not_exception_type(BadRequestException),
            reraise=True,
        )
        async def stream_generator():
            """Legacy implementation using two-phase pattern internally."""
            # Phase 1: Create stream (can raise exceptions)
            stream = await self.prepare_streaming(context, model_kwargs)

            # Phase 2: Iterate stream (yields error events for failures)
            async for chunk in self.iterate_stream(stream, context, model_kwargs):
                yield chunk

        return stream_generator()
