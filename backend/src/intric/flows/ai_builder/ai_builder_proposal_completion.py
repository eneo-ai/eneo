from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ProposalCompletionFn,
    ProposalCompletionRequest,
    ProposalCompletionResponse,
    ProposalCompletionToolCall,
    ProposalCompletionUsage,
)
from intric.main.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class _ProposalCompletionMessageView:
    content: str | None
    tool_calls: Sequence[ProposalCompletionToolCall]


@dataclass(frozen=True)
class _ProposalCompletionChoiceView:
    message: _ProposalCompletionMessageView
    finish_reason: str | None


@dataclass(frozen=True)
class _ProposalCompletionResponseView:
    choices: Sequence[_ProposalCompletionChoiceView]
    usage: ProposalCompletionUsage | None


@dataclass(frozen=True)
class _ProposalCompletionToolCallFunctionView:
    name: str
    arguments: str


@dataclass(frozen=True)
class _ProposalCompletionToolCallView:
    id: str
    function: _ProposalCompletionToolCallFunctionView


def _normalized_completion_response(response: Any) -> ProposalCompletionResponse:
    choices: list[_ProposalCompletionChoiceView] = []
    for choice in getattr(response, "choices", ()) or ():
        message = getattr(choice, "message", None)
        raw_content = getattr(message, "content", None)
        raw_tool_calls = getattr(message, "tool_calls", None)
        raw_finish_reason = getattr(choice, "finish_reason", None)
        choices.append(
            _ProposalCompletionChoiceView(
                message=_ProposalCompletionMessageView(
                    content=raw_content if isinstance(raw_content, str) else None,
                    tool_calls=tuple(
                        _normalized_completion_tool_call(raw_tool_call)
                        for raw_tool_call in raw_tool_calls or ()
                    ),
                ),
                finish_reason=(
                    raw_finish_reason if isinstance(raw_finish_reason, str) else None
                ),
            )
        )
    return _ProposalCompletionResponseView(
        choices=tuple(choices),
        usage=_normalized_completion_usage(getattr(response, "usage", None)),
    )


def _normalized_completion_tool_call(raw_tool_call: Any) -> ProposalCompletionToolCall:
    function = _object_field(raw_tool_call, "function")
    return _ProposalCompletionToolCallView(
        id=_string_field(raw_tool_call, "id"),
        function=_ProposalCompletionToolCallFunctionView(
            name=_string_field(function, "name"),
            arguments=_string_field(function, "arguments"),
        ),
    )


def _normalized_completion_usage(usage: Any) -> ProposalCompletionUsage | None:
    if usage is None:
        return None
    if all(
        isinstance(getattr(usage, field_name, None), int)
        for field_name in ("prompt_tokens", "completion_tokens", "total_tokens")
    ):
        return cast(ProposalCompletionUsage, usage)
    return None


def _object_field(value: Any, field_name: str) -> Any:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        return mapping.get(field_name)
    return getattr(value, field_name, None)


def _string_field(value: Any, field_name: str) -> str:
    field_value = _object_field(value, field_name)
    return field_value if isinstance(field_value, str) else ""


async def call_proposal_completion(
    *,
    litellm_client: Any,
    request: ProposalCompletionRequest,
    usage_tracker: ProposalTurnTelemetry | None = None,
) -> ProposalCompletionResponse:
    provider_kwargs = dict(request.litellm_kwargs)
    provider_kwargs.pop("drop_params", None)
    dropped_response_format = provider_kwargs.pop("response_format", None)
    if dropped_response_format is not None:
        logger.debug("ai_builder_proposal_completion_dropped_response_format")

    raw_response = await litellm_client.acompletion(
        model=request.litellm_model,
        messages=request.messages,
        tools=request.tool_schemas,
        tool_choice=request.tool_choice,
        stream=False,
        drop_params=True,
        max_tokens=request.max_output_tokens,
        temperature=request.temperature,
        **provider_kwargs,
    )
    response = _normalized_completion_response(raw_response)
    if usage_tracker is not None:
        usage_tracker.record_response(
            response,
            messages=request.messages,
            counts_as_repair=request.counts_as_repair,
        )
    return response


def make_usage_tracked_proposal_completion(
    *,
    litellm_client: Any,
    usage_tracker: ProposalTurnTelemetry | None,
) -> ProposalCompletionFn:
    async def _tracked_completion(
        request: ProposalCompletionRequest,
    ) -> ProposalCompletionResponse:
        return await call_proposal_completion(
            litellm_client=litellm_client,
            request=request,
            usage_tracker=usage_tracker,
        )

    return _tracked_completion
