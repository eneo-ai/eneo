"""LiteLLM completion boundary for AI Builder turns."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.completion_models.infrastructure.completion_service import (
    CompletionEvidenceField,
    CompletionEvidenceFieldDomain,
    completion_evidence_field_domain,
    completion_evidence_json_type,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderProviderRequestEvidence,
    classify_ai_builder_provider_failure,
    prepare_ai_builder_provider_kwargs,
    provider_call_stopped_error,
    record_ai_builder_provider_failure,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalCallKind,
    ProposalTurnTelemetry,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ProposalCallBudgetExhausted,
    ProposalCompletionFn,
    ProposalCompletionRequest,
    fit_proposal_request_budget,
    flatten_proposal_message_groups,
    outbound_proposal_tool_schemas,
)
from eneo.flows.ai_builder.ai_builder_provider_call import (
    ObservedTiming,
    ProviderCallStopped,
    ProviderCallTiming,
    ProviderRequestNotAdmitted,
    ProviderWorkGate,
    complete_with_silence_deadline,
)
from eneo.flows.ai_builder.ai_builder_token_usage import (
    CompletionTokenUsage,
    completion_token_usage_from_response,
    provider_token_usage,
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
    call_kind: ProposalCallKind | None = None,
    provider_gate: ProviderWorkGate | None = None,
) -> LLMCompletionResponse:
    tool_schemas = _outbound_proposal_tool_schemas(request)
    fitted_message_groups, request_budget = fit_proposal_request_budget(
        budget=request.request_budget,
        message_groups=request.message_groups,
        tool_schemas=tool_schemas,
        model_name=request.route.litellm_model,
        replan=request.counts_as_repair,
    )
    messages = flatten_proposal_message_groups(fitted_message_groups)
    provider_kwargs = prepare_ai_builder_provider_kwargs(
        request.route,
        ModelKwargs(temperature=request.temperature),
        stage="proposal_completion",
        request_id=usage_tracker.request_id if usage_tracker is not None else None,
    )
    if not request.call_budget.try_start_call():
        raise ProposalCallBudgetExhausted
    provider_kwargs.pop("drop_params", None)
    provider_kwargs.pop("timeout", None)
    # Keep both LiteLLM and provider SDK retries inside the turn's call budget.
    provider_kwargs.update(num_retries=0, max_retries=0)
    dropped_response_format = provider_kwargs.pop("response_format", None)
    if dropped_response_format is not None:
        logger.debug("ai_builder_proposal_completion_dropped_response_format")
    incident_evidence: AIBuilderProviderRequestEvidence | None = None
    if usage_tracker is not None:
        usage_tracker.start_attempt(
            counts_as_repair=request.counts_as_repair,
            call_kind=call_kind,
            request_budget=request_budget,
        )
    timing = ObservedTiming()

    def observe_sdk_input(sdk_input: Mapping[str, Any]) -> None:
        nonlocal incident_evidence
        incident_evidence = _proposal_request_evidence(
            request=request, sdk_input=sdk_input
        )

    def admit_request_without_refused_control(
        _control: str, error: Exception, refused_timing: ProviderCallTiming
    ) -> bool:
        # One more request costs one call of the turn's budget and is its own
        # call record; the refused one is recorded as failed, with its own timing.
        if not request.call_budget.try_start_call():
            return False
        if usage_tracker is not None:
            usage_tracker.retry_call(
                failure=classify_ai_builder_provider_failure(
                    error,
                    stage="proposal_completion",
                    request_id=usage_tracker.request_id,
                ),
                timing=refused_timing,
            )
        return True

    try:
        raw_response = await complete_with_silence_deadline(
            litellm_client,
            silence_deadline_seconds=request_budget.timeout_seconds,
            ceiling_seconds=request_budget.ceiling_seconds,
            request={
                "model": request.route.litellm_model,
                "messages": messages,
                "tools": tool_schemas,
                "tool_choice": request.tool_choice,
                "parallel_tool_calls": False,
                "drop_params": True,
                "max_tokens": request_budget.provider_output_cap_tokens,
                **provider_kwargs,
            },
            retry_without_refused_control=admit_request_without_refused_control,
            observe_sdk_input=observe_sdk_input,
            observe_timing=timing,
            gate=provider_gate,
        )
    except ProviderRequestNotAdmitted as not_admitted:
        raise not_admitted.error
    except ProviderCallStopped as stopped:
        assert provider_gate is not None
        raise provider_call_stopped_error(
            provider_gate,
            call_kind=call_kind or "proposal",
            model=request.route.litellm_model,
            timing=timing.value,
        ) from stopped
    except Exception as error:
        failure = record_ai_builder_provider_failure(
            error,
            stage="proposal_completion",
            usage_tracker=usage_tracker,
            request_id=usage_tracker.request_id if usage_tracker is not None else None,
            incident_evidence=incident_evidence,
            request_budget=request_budget,
            timing=timing.value,
        )
        raise failure.as_exception() from error
    response = normalize_litellm_completion_response(raw_response)
    if usage_tracker is not None:
        _, finish_reason = _first_text_and_finish_reason(response)
        metadata = _completion_metadata_from_response(
            response,
            litellm_model=request.route.litellm_model,
            messages=messages,
            completion_messages=completion_messages_for_usage(response),
            finish_reason=finish_reason,
        )
        usage_tracker.record_response(
            finish_reason=metadata.finish_reason,
            usage=metadata.usage,
            counts_as_repair=request.counts_as_repair,
            timing=timing.value,
        )
    return response


def _outbound_proposal_tool_schemas(
    request: ProposalCompletionRequest,
) -> list[dict[str, Any]]:
    return outbound_proposal_tool_schemas(
        request.tool_schemas, strict=request.route.supports_strict_tool_schema
    )


def _proposal_request_evidence(
    *,
    request: ProposalCompletionRequest,
    sdk_input: Mapping[str, Any],
) -> AIBuilderProviderRequestEvidence:
    domains: dict[str, CompletionEvidenceFieldDomain] = {
        "model": "route",
        "messages": "conversation",
        "tools": "tool_contract",
        "tool_choice": "tool_selection",
        "parallel_tool_calls": "transport_control",
        "stream": "transport_control",
        "stream_options": "transport_control",
        "max_tokens": "output_limit",
        "timeout": "transport_control",
    }
    sdk_input_fields: list[CompletionEvidenceField] = []
    unclassified_sdk_input_field_count = 0
    for name, value in sdk_input.items():
        domain = domains.get(name) or completion_evidence_field_domain(name)
        if domain is None:
            unclassified_sdk_input_field_count += 1
            continue
        sdk_input_fields.append(
            CompletionEvidenceField(
                name=name,
                json_type=completion_evidence_json_type(value),
                domain=domain,
            )
        )
    return AIBuilderProviderRequestEvidence(
        route=request.route.incident_evidence(),
        sdk_input_fields=tuple(sorted(sdk_input_fields, key=lambda field: field.name)),
        unclassified_sdk_input_field_count=unclassified_sdk_input_field_count,
    )


def make_usage_tracked_proposal_completion(
    *,
    litellm_client: Any,
    usage_tracker: ProposalTurnTelemetry | None,
    call_kind: ProposalCallKind | None = None,
    provider_gate: ProviderWorkGate | None = None,
) -> ProposalCompletionFn:
    async def _tracked_completion(
        request: ProposalCompletionRequest,
    ) -> LLMCompletionResponse:
        return await call_proposal_completion(
            litellm_client=litellm_client,
            request=request,
            usage_tracker=usage_tracker,
            call_kind=call_kind,
            provider_gate=provider_gate,
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
        usage=provider_token_usage(_object_field(response, "usage")),
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
    completion_messages: Sequence[Mapping[str, Any]],
    finish_reason: str | None,
) -> CompletionMetadata:
    usage = completion_token_usage_from_response(
        response,
        model_name=litellm_model,
        messages=messages,
        completion_messages=completion_messages,
    )
    return CompletionMetadata(
        finish_reason=finish_reason,
        usage=usage,
    )


def completion_messages_for_usage(
    response: LLMCompletionResponse,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for choice in response.choices:
        message: dict[str, Any] = {
            "role": "assistant",
            "content": choice.message.content,
        }
        if choice.message.tool_calls:
            message["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
                for tool_call in choice.message.tool_calls
            ]
        messages.append(message)
    return messages


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


__all__ = [
    "CompletionMetadata",
    "LLMCompletionChoice",
    "LLMCompletionMessage",
    "LLMCompletionResponse",
    "LLMCompletionToolCall",
    "LLMCompletionToolCallFunction",
    "call_proposal_completion",
    "completion_messages_for_usage",
    "make_usage_tracked_proposal_completion",
    "normalize_litellm_completion_response",
]
