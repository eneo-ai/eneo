import anthropic
from anthropic import AsyncAnthropic
from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from intric.ai_models.completion_models.completion_model import Completion, FunctionCall
from intric.main.exceptions import BadRequestException, ClaudeException
from intric.main.logging import get_logger

logger = get_logger(__name__)


@retry(
    wait=wait_random_exponential(min=1, max=20),
    stop=stop_after_attempt(3),
    retry=retry_if_not_exception_type(BadRequestException),
    reraise=True,
)
async def get_response(
    client: AsyncAnthropic,
    model_name: str,
    prompt: str,
    messages: list,
    model_kwargs: dict,
    max_tokens: int,
):
    try:
        message = await client.messages.create(
            max_tokens=max_tokens,
            system=prompt,
            messages=messages,
            model=model_name,
            **model_kwargs,
        )
        completion = Completion(text=message.content[0].text)
        return completion
    except anthropic.APIConnectionError as exc:
        logger.exception("Connection error:")
        raise ClaudeException("The server could not be reached") from exc
    except anthropic.BadRequestError as exc:
        raise BadRequestException("Invalid model kwargs") from exc
    except anthropic.RateLimitError as exc:
        logger.exception("Rate limit error:")
        raise ClaudeException("Rate limit exceeded") from exc
    except Exception as exc:
        logger.exception("Unknown error:")
        raise ClaudeException("Unknown Claude AI exception") from exc


@retry(
    wait=wait_random_exponential(min=1, max=20),
    stop=stop_after_attempt(3),
    retry=retry_if_not_exception_type(BadRequestException),
    reraise=True,
)
async def prepare_stream(
    client: AsyncAnthropic,
    model_name: str,
    prompt: str,
    messages: list,
    model_kwargs: dict,
    max_tokens: int,
    tools: dict,
):
    """
    Phase 1 (Pre-flight): Creates streaming connection.
    Raises exceptions for authentication, connection, rate limit errors.
    """
    tools = tools or anthropic.NOT_GIVEN
    try:
        stream = await client.messages.create(
            max_tokens=max_tokens,
            system=prompt,
            messages=messages,
            model=model_name,
            stream=True,
            tools=tools,
            **model_kwargs,
        )
        return stream
    except anthropic.APIConnectionError as exc:
        logger.exception("Connection error:")
        raise ClaudeException("The server could not be reached") from exc
    except anthropic.BadRequestError as exc:
        raise BadRequestException("Invalid model kwargs") from exc
    except anthropic.RateLimitError as exc:
        logger.exception("Rate limit error:")
        raise ClaudeException("Rate limit exceeded") from exc
    except Exception as exc:
        logger.exception("Unknown error:")
        raise ClaudeException("Unknown Claude AI exception") from exc


async def iterate_stream(stream):
    """
    Phase 2 (Iteration): Yields chunks from pre-created stream.
    Yields error events (not raises) for mid-stream failures.
    """
    try:
        async for event in stream:
            if event.type == "content_block_delta":
                if event.delta.type == "text_delta":
                    yield Completion(text=event.delta.text)

                elif event.delta.type == "input_json_delta":
                    yield Completion(
                        tool_call=FunctionCall(arguments=event.delta.partial_json)
                    )

            if event.type == "content_block_start":
                if event.content_block.type == "tool_use":
                    yield Completion(
                        tool_call=FunctionCall(name=event.content_block.name)
                    )

            if event.type == "message_stop":
                yield Completion(stop=True)

    except Exception as exc:
        # Mid-stream errors: yield error event instead of raising
        from intric.ai_models.completion_models.completion_model import ResponseType
        logger.error(f"Error during stream iteration: {exc}")
        yield Completion(
            text="",
            error=f"Stream error: {str(exc)}",
            error_code=500,
            response_type=ResponseType.ERROR,
            stop=True
        )


@retry(
    wait=wait_random_exponential(min=1, max=20),
    stop=stop_after_attempt(3),
    retry=retry_if_not_exception_type(BadRequestException),
    reraise=True,
)
async def get_response_streaming(
    client: AsyncAnthropic,
    model_name: str,
    prompt: str,
    messages: list,
    model_kwargs: dict,
    max_tokens: int,
    tools: dict,
):
    """
    Legacy streaming method for backward compatibility.
    Uses the two-phase pattern internally.
    """
    # Phase 1: Create stream (can raise exceptions)
    stream = await prepare_stream(
        client=client,
        model_name=model_name,
        prompt=prompt,
        messages=messages,
        model_kwargs=model_kwargs,
        max_tokens=max_tokens,
        tools=tools,
    )

    # Phase 2: Iterate stream (yields error events for failures)
    async for chunk in iterate_stream(stream):
        yield chunk
