import openai
from openai import AsyncOpenAI
from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from intric.ai_models.completion_models.completion_model import Completion, FunctionCall
from intric.main.exceptions import BadRequestException, OpenAIException
from intric.main.logging import get_logger

logger = get_logger(__name__)


@retry(
    wait=wait_random_exponential(min=1, max=20),
    stop=stop_after_attempt(3),
    retry=retry_if_not_exception_type(BadRequestException),
    reraise=True,
)
async def get_response(
    client: AsyncOpenAI,
    model_name: str,
    messages: list,
    model_kwargs: dict,
    extra_headers: dict = None,
):
    extra_headers = extra_headers or openai.NOT_GIVEN
    try:
        response = await client.chat.completions.create(
            model=model_name,
            messages=messages,
            extra_headers=extra_headers,
            **model_kwargs,
        )
        choices = response.choices  # type: ignore

        completion_str = choices[0].message.content.strip()

        try:
            reasoning_tokens = response.usage.completion_tokens_details.reasoning_tokens
        except AttributeError:
            reasoning_tokens = 0

        completion = Completion(
            reasoning_token_count=reasoning_tokens,
            text=completion_str,
        )

        return completion
    except openai.BadRequestError as exc:
        raise BadRequestException("Invalid model kwargs") from exc
    except openai.AuthenticationError as exc:
        logger.exception("Authentication error:")
        raise OpenAIException("Invalid API credentials. Please check your API key.") from exc
    except openai.PermissionDeniedError as exc:
        # Azure firewall/network errors
        error_detail = str(exc)
        logger.error(f"Permission denied error: {error_detail}")

        if "Virtual Network/Firewall" in error_detail or "Firewall rules" in error_detail:
            raise OpenAIException(
                "Azure access denied: Virtual Network/Firewall rules. "
                "Please check your Azure network configuration or contact your administrator."
            ) from exc
        else:
            raise OpenAIException(f"Access denied: {error_detail}") from exc
    except openai.RateLimitError as exc:
        logger.exception("Rate limit error:")
        raise OpenAIException("Rate limit exceeded. Please try again later.") from exc
    except openai.APIError as exc:
        logger.error(f"API error: {exc}")
        raise OpenAIException(f"API error: {str(exc)}") from exc
    except Exception as exc:
        logger.exception("Unknown error:")
        raise OpenAIException("Unknown error occurred") from exc


@retry(
    wait=wait_random_exponential(min=1, max=20),
    stop=stop_after_attempt(3),
    retry=retry_if_not_exception_type(BadRequestException),
    reraise=True,
)
async def prepare_stream(
    client: AsyncOpenAI,
    model_name: str,
    messages: list,
    model_kwargs: dict,
    tools: list[dict] = None,
    extra_headers: dict = None,
):
    """
    Phase 1 (Pre-flight): Creates streaming connection.
    Raises exceptions for authentication, firewall, rate limit errors.
    """
    tools = tools or openai.NOT_GIVEN
    extra_headers = extra_headers or openai.NOT_GIVEN

    try:
        stream = await client.chat.completions.create(
            model=model_name,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            tools=tools,
            extra_headers=extra_headers,
            **model_kwargs,
        )
        return stream
    except openai.BadRequestError as exc:
        raise BadRequestException("Invalid model kwargs") from exc
    except openai.AuthenticationError as exc:
        logger.exception("Authentication error:")
        raise OpenAIException("Invalid API credentials. Please check your API key.") from exc
    except openai.PermissionDeniedError as exc:
        error_detail = str(exc)
        logger.error(f"Permission denied error: {error_detail}")

        if "Virtual Network/Firewall" in error_detail or "Firewall rules" in error_detail:
            raise OpenAIException(
                "Azure access denied: Virtual Network/Firewall rules. "
                "Please check your Azure network configuration or contact your administrator."
            ) from exc
        else:
            raise OpenAIException(f"Access denied: {error_detail}") from exc
    except openai.RateLimitError as exc:
        logger.exception("Rate limit error:")
        raise OpenAIException("Rate limit exceeded. Please try again later.") from exc
    except openai.APIError as exc:
        logger.error(f"API error: {exc}")
        raise OpenAIException(f"API error: {str(exc)}") from exc
    except Exception as exc:
        logger.exception("Unknown error:")
        raise OpenAIException("Unknown error occurred") from exc


async def iterate_stream(stream):
    """
    Phase 2 (Iteration): Yields chunks from pre-created stream.
    Yields error events (not raises) for mid-stream failures.
    """
    try:
        async for chunk in stream:
            if len(chunk.choices) > 0:
                delta = chunk.choices[0].delta

                if delta.tool_calls:
                    _tool_call = delta.tool_calls[0]
                    tool_call = FunctionCall(
                        name=_tool_call.function.name,
                        arguments=_tool_call.function.arguments,
                    )
                else:
                    tool_call = None

                yield Completion(text=delta.content, tool_call=tool_call)
            elif chunk.usage:
                try:
                    yield Completion(
                        reasoning_token_count=chunk.usage.completion_tokens_details.reasoning_tokens,
                    )
                except AttributeError as attr_err:
                    logger.warning(f"Attribution error while processing chunk: {attr_err}")

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
    client: AsyncOpenAI,
    model_name: str,
    messages: list,
    model_kwargs: dict,
    tools: list[dict] = None,
    extra_headers: dict = None,
):
    """
    Legacy streaming method for backward compatibility.
    Uses the two-phase pattern internally.
    """
    # Phase 1: Create stream (can raise exceptions)
    stream = await prepare_stream(
        client=client,
        model_name=model_name,
        messages=messages,
        model_kwargs=model_kwargs,
        tools=tools,
        extra_headers=extra_headers,
    )

    # Phase 2: Iterate stream (yields error events for failures)
    async for chunk in iterate_stream(stream):
        yield chunk
