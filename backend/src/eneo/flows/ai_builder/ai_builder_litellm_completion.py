"""LiteLLM completion boundary for AI Builder turns."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderProviderOutcomeUnknownException,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ProposalCompletionFn,
    ProposalCompletionRequest,
)
from eneo.flows.ai_builder.ai_builder_token_usage import (
    TOKEN_USAGE_SOURCE_PROVIDER,
    CompletionTokenUsage,
    completion_token_usage_from_response,
)
from eneo.main.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CompletionMetadata:
    finish_reason: str | None
    usage: CompletionTokenUsage


@dataclass(frozen=True, slots=True)
class LLMCompletionToolCallFunction:
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class LLMCompletionToolCall:
    id: str
    function: LLMCompletionToolCallFunction


@dataclass(frozen=True, slots=True)
class LLMCompletionMessage:
    content: str | None
    tool_calls: tuple[LLMCompletionToolCall, ...]


@dataclass(frozen=True, slots=True)
class LLMCompletionChoice:
    message: LLMCompletionMessage
    finish_reason: str | None


@dataclass(frozen=True, slots=True)
class LLMCompletionResponse:
    choices: tuple[LLMCompletionChoice, ...]
    usage: CompletionTokenUsage | None


async def call_proposal_completion(
    *,
    litellm_client: Any,
    request: ProposalCompletionRequest,
    usage_tracker: ProposalTurnTelemetry | None = None,
    before_provider_call: Callable[[], Awaitable[None]] | None = None,
) -> LLMCompletionResponse:
    provider_kwargs = request.route.filter_unsupported_model_kwargs(
        ModelKwargs(temperature=request.temperature)
    )
    provider_kwargs.pop("drop_params", None)
    dropped_response_format = provider_kwargs.pop("response_format", None)
    if dropped_response_format is not None:
        logger.debug("ai_builder_proposal_completion_dropped_response_format")
    if before_provider_call is not None:
        await before_provider_call()
    try:
        raw_response = await litellm_client.acompletion(
            model=request.route.litellm_model,
            messages=request.messages,
            tools=request.tool_schemas,
            tool_choice=request.tool_choice,
            stream=False,
            drop_params=True,
            max_tokens=request.max_output_tokens,
            **provider_kwargs,
        )
    except Exception as error:
        if before_provider_call is not None:
            raise AIBuilderProviderOutcomeUnknownException() from error
        raise
    response = normalize_litellm_completion_response(raw_response)
    if usage_tracker is not None:
        completion_text, finish_reason = _first_text_and_finish_reason(response)
        metadata = _completion_metadata_from_response(
            response,
            litellm_model=request.route.litellm_model,
            messages=request.messages,
            completion_text=completion_text,
            finish_reason=finish_reason,
        )
        usage_tracker.record_response(
            finish_reason=metadata.finish_reason,
            usage=metadata.usage,
            counts_as_repair=request.counts_as_repair,
        )
    return response


def make_usage_tracked_proposal_completion(
    *,
    litellm_client: Any,
    usage_tracker: ProposalTurnTelemetry | None,
    before_provider_call: Callable[[], Awaitable[None]] | None = None,
) -> ProposalCompletionFn:
    async def _tracked_completion(
        request: ProposalCompletionRequest,
    ) -> LLMCompletionResponse:
        return await call_proposal_completion(
            litellm_client=litellm_client,
            request=request,
            usage_tracker=usage_tracker,
            before_provider_call=before_provider_call,
        )

    return _tracked_completion


def normalize_litellm_completion_response(response: Any) -> LLMCompletionResponse:
    choices: list[LLMCompletionChoice] = []
    for raw_choice in _sequence_field(response, "choices"):
        message = _object_field(raw_choice, "message")
        raw_content = _object_field(message, "content")
        choices.append(
            LLMCompletionChoice(
                message=LLMCompletionMessage(
                    content=raw_content if isinstance(raw_content, str) else None,
                    tool_calls=tuple(
                        _normalize_tool_call(raw_tool_call)
                        for raw_tool_call in _sequence_field(message, "tool_calls")
                    ),
                ),
                finish_reason=_string_or_none(
                    _object_field(raw_choice, "finish_reason")
                ),
            )
        )
    return LLMCompletionResponse(
        choices=tuple(choices),
        usage=_normalized_completion_usage(_object_field(response, "usage")),
    )


def _normalize_tool_call(raw_tool_call: Any) -> LLMCompletionToolCall:
    function = _object_field(raw_tool_call, "function")
    return LLMCompletionToolCall(
        id=_string_field(raw_tool_call, "id"),
        function=LLMCompletionToolCallFunction(
            name=_string_field(function, "name"),
            arguments=_string_field(function, "arguments"),
        ),
    )


def _first_text_and_finish_reason(
    response: LLMCompletionResponse,
) -> tuple[str, str | None]:
    if not response.choices:
        return "", None
    choice = response.choices[0]
    return choice.message.content or "", choice.finish_reason


def _completion_metadata_from_response(
    response: LLMCompletionResponse,
    *,
    litellm_model: str,
    messages: Sequence[Mapping[str, Any]],
    completion_text: str,
    finish_reason: str | None,
) -> CompletionMetadata:
    usage = completion_token_usage_from_response(
        response,
        model_name=litellm_model,
        messages=messages,
        completion_text=completion_text,
    )
    return CompletionMetadata(
        finish_reason=finish_reason,
        usage=usage,
    )


def _normalized_completion_usage(usage: Any) -> CompletionTokenUsage | None:
    if usage is None:
        return None
    prompt_tokens = _safe_int(_object_field(usage, "prompt_tokens"))
    completion_tokens = _safe_int(_object_field(usage, "completion_tokens"))
    total_tokens = _safe_int(_object_field(usage, "total_tokens"))
    if prompt_tokens is None and completion_tokens is None and total_tokens is None:
        return None
    if (
        total_tokens is None
        and prompt_tokens is not None
        and completion_tokens is not None
    ):
        total_tokens = prompt_tokens + completion_tokens
    return CompletionTokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        source=TOKEN_USAGE_SOURCE_PROVIDER,
        estimated=False,
    )


def _sequence_field(value: Any, field_name: str) -> tuple[object, ...]:
    field_value = _object_field(value, field_name)
    if isinstance(field_value, Sequence) and not isinstance(field_value, (str, bytes)):
        return tuple(cast(Sequence[object], field_value))
    return ()


def _object_field(value: Any, field_name: str) -> Any:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        return mapping.get(field_name)
    return getattr(value, field_name, None)


def _string_field(value: Any, field_name: str) -> str:
    field_value = _object_field(value, field_name)
    return field_value if isinstance(field_value, str) else ""


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _safe_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


__all__ = [
    "CompletionMetadata",
    "LLMCompletionChoice",
    "LLMCompletionMessage",
    "LLMCompletionResponse",
    "LLMCompletionToolCall",
    "LLMCompletionToolCallFunction",
    "call_proposal_completion",
    "make_usage_tracked_proposal_completion",
    "normalize_litellm_completion_response",
]
