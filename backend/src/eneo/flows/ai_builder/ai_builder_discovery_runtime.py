from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any
from uuid import UUID

from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AI_BUILDER_ATTACHMENT_LIMIT_MESSAGE,
    AI_BUILDER_MAX_ATTACHMENTS,
    AIBuilderAttachmentContext,
    apply_attachment_file_roles_to_planning_state,
    render_ai_builder_attachment_evidence,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    SlotClassificationMetadata,
    StructuredQuestionAnswerMetadata,
    question_answer_from_metadata,
    question_answer_values,
    slot_classification_metadata_from_result,
)
from eneo.flows.ai_builder.ai_builder_discovery import analyze_discovery
from eneo.flows.ai_builder.ai_builder_discovery_models import (
    DiscoveryAnalysis,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
    slot_names_blocked_by_explicit_uncertainty,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import ProposalTurnTelemetry
from eneo.flows.ai_builder.ai_builder_question_state import (
    assistant_question_id,
    last_answered_question,
)
from eneo.flows.ai_builder.ai_builder_slot_classifier import (
    SlotClassificationBias,
    SlotClassificationInput,
    SlotClassificationResult,
    SlotClassificationSource,
    classify_slots,
    slot_classification_prompt_hash,
    slot_classification_provider_identity,
)
from eneo.flows.ai_builder.planning_state import PlanningState
from eneo.flows.ai_builder.planning_state_builder import (
    apply_model_blocked_slots,
    apply_policy_defaults_from_resolved_slots,
    build_planning_state_from_conversation,
    llm_resolvable_slot_values_for_state,
    merge_llm_resolved_slots,
)
from eneo.flows.domain.flow import Flow
from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy

if TYPE_CHECKING:
    from eneo.completion_models.infrastructure.completion_service import (
        ResolvedCompletionModelRoute,
    )

_MAX_CLASSIFICATION_TRANSCRIPT_CHARS = 12_000
_MAX_CLASSIFICATION_TRANSCRIPT_SOURCES = 120
_MAX_CLASSIFICATION_STRUCTURED_VALUE_CHARS = 500


@dataclass(frozen=True, slots=True)
class RuntimeDiscoveryContext:
    planning_state: PlanningState
    slot_classification_result: SlotClassificationResult | None = None
    slot_classification_metadata: SlotClassificationMetadata | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryRuntimeResult:
    discovery_analysis: DiscoveryAnalysis
    planning_state: PlanningState
    slot_classification_metadata: SlotClassificationMetadata | None = None


def _targeted_classification_bias(
    conversation: list[ConversationMessage],
    allowed_slot_values: Mapping[str, Collection[str]],
    classification_input: SlotClassificationInput,
) -> SlotClassificationBias | None:
    """Bias classification toward the slot the user just answered, when unresolved.

    Only fires when the user replied with free text to the last asked question
    and that slot is still being classified, so a previous aggregate result is
    not reused for a targeted reply.
    """
    answered = last_answered_question(conversation)
    if answered is None:
        return None
    asked_question_id, latest_answer = answered
    target_slot = asked_question_id
    if target_slot not in allowed_slot_values:
        return None
    answer_message_id = next(
        (
            message.message_id
            for message in reversed(conversation)
            if message.role == "user"
            and isinstance(message.content, str)
            and message.content.strip() == latest_answer
        ),
        None,
    )
    if answer_message_id is None:
        return None
    answer_source = next(
        (
            source
            for source in reversed(classification_input.sources)
            if source.message_id == answer_message_id
            and (
                (
                    source.kind == "structured_answer"
                    and source.question_id == asked_question_id
                )
                or source.kind == "user_message"
            )
        ),
        None,
    )
    if answer_source is None:
        return None
    return SlotClassificationBias(
        target_slot_name=target_slot,
        asked_question_id=asked_question_id,
        answer_source_id=answer_source.source_id,
    )


def build_slot_classification_input(
    conversation: list[ConversationMessage],
    attachment_context: AIBuilderAttachmentContext | None,
) -> SlotClassificationInput:
    if (
        attachment_context is not None
        and len(attachment_context.evidence) > AI_BUILDER_MAX_ATTACHMENTS
    ):
        raise AIBuilderBadRequestException(
            AI_BUILDER_ATTACHMENT_LIMIT_MESSAGE,
            code=AIBuilderErrorCode.BAD_REQUEST,
        )

    transcript_sources: list[SlotClassificationSource] = []
    pending_question_id: str | None = None
    for message in conversation:
        question_id = assistant_question_id(message)
        if question_id is not None:
            pending_question_id = question_id
            continue
        if message.role != "user":
            continue
        answer = question_answer_from_metadata(message.metadata)
        if isinstance(message.content, str) and message.content.strip():
            if answer is None or not _is_structured_answer_echo(
                message.content, answer
            ):
                transcript_sources.append(
                    SlotClassificationSource(
                        source_id=f"user_message:{message.message_id}",
                        kind="user_message",
                        text=message.content.strip(),
                        message_id=message.message_id,
                        question_id=pending_question_id,
                    )
                )
        if answer is None or answer.question_id is None:
            pending_question_id = None
            continue
        for index, selected_value in enumerate(_structured_answer_values(answer)):
            transcript_sources.append(
                SlotClassificationSource(
                    source_id=f"structured_answer:{message.message_id}:{index}",
                    kind="structured_answer",
                    text=selected_value,
                    message_id=message.message_id,
                    question_id=answer.question_id,
                    selected_value=selected_value,
                )
            )
        pending_question_id = None

    sources = list(_bound_classification_transcript(transcript_sources))
    if attachment_context is not None:
        for item in sorted(
            attachment_context.evidence,
            key=lambda candidate: str(candidate.file_id),
        ):
            sources.append(
                SlotClassificationSource(
                    source_id=f"uploaded_file:{item.file_id}",
                    kind="uploaded_file",
                    text=render_ai_builder_attachment_evidence(item),
                    file_id=item.file_id,
                    coverage=item.coverage,
                    truncated=item.coverage != "fully_seen",
                )
            )
    return SlotClassificationInput(sources=tuple(sources))


def _bound_classification_transcript(
    sources: list[SlotClassificationSource],
) -> tuple[SlotClassificationSource, ...]:
    if not sources:
        return ()
    bounded_sources = [
        replace(
            source,
            text=source.text[:_MAX_CLASSIFICATION_STRUCTURED_VALUE_CHARS],
            selected_value=source.text[:_MAX_CLASSIFICATION_STRUCTURED_VALUE_CHARS],
            truncated=len(source.text) > _MAX_CLASSIFICATION_STRUCTURED_VALUE_CHARS,
        )
        if source.kind == "structured_answer"
        else source
        for source in sources
    ]
    retained = bounded_sources[-_MAX_CLASSIFICATION_TRANSCRIPT_SOURCES:]
    fair_share = _MAX_CLASSIFICATION_TRANSCRIPT_CHARS // len(retained)
    included_lengths = [min(len(source.text), fair_share) for source in retained]
    remaining = _MAX_CLASSIFICATION_TRANSCRIPT_CHARS - sum(included_lengths)
    for index in range(len(retained) - 1, -1, -1):
        if remaining <= 0:
            break
        available = len(retained[index].text) - included_lengths[index]
        added = min(available, remaining)
        included_lengths[index] += added
        remaining -= added

    return tuple(
        replace(
            source,
            text=source.text[:included_length],
            truncated=source.truncated or included_length < len(source.text),
            selected_value=source.text[:included_length]
            if source.kind == "structured_answer"
            else source.selected_value,
        )
        for source, included_length in zip(retained, included_lengths, strict=True)
    )


def _structured_answer_values(
    answer: StructuredQuestionAnswerMetadata,
) -> tuple[str, ...]:
    values: list[str] = []
    raw_values: list[str | int | float | bool | None] = []
    if answer.selected_values is not None:
        raw_values.extend(answer.selected_values)
    raw_values.extend(
        [
            answer.selected_value,
            answer.answer,
            answer.custom_value,
        ]
    )
    for item in raw_values:
        if item is None:
            continue
        value = item.strip() if isinstance(item, str) else json.dumps(item)
        if value and value not in values:
            values.append(value)
    if not values:
        option_ids = [*(answer.selected_option_ids or [])]
        if answer.selected_option_id is not None:
            option_ids.append(answer.selected_option_id)
        values.extend(value for value in option_ids if value)
    return tuple(values)


def _is_structured_answer_echo(
    content: str,
    answer: StructuredQuestionAnswerMetadata,
) -> bool:
    normalized = content.casefold().strip().rstrip(" .?!")
    if not normalized:
        return True
    return normalized in {
        value.casefold().strip().rstrip(" .?!")
        for value in question_answer_values(answer)
    }


async def build_runtime_discovery_context(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    litellm_client: Any | None = None,
    completion_model_route: ResolvedCompletionModelRoute | None = None,
    ui_language: str | None = None,
    tenant_id: UUID,
    allow_classification: bool = True,
    attachment_context: AIBuilderAttachmentContext | None = None,
    usage_tracker: ProposalTurnTelemetry | None = None,
    before_provider_call: Callable[[], Awaitable[None]] | None = None,
    mapped_execution_policy: FlowMappedExecutionPolicy | None = None,
) -> RuntimeDiscoveryContext:
    state = build_planning_state_from_conversation(
        conversation,
        flow=flow,
        attachment_output_schema_evidence=(
            attachment_context.output_schema_evidence
            if attachment_context is not None
            else None
        ),
        mapped_execution_policy=mapped_execution_policy,
    )
    apply_attachment_file_roles_to_planning_state(state, attachment_context)
    if (
        not allow_classification
        or litellm_client is None
        or completion_model_route is None
    ):
        return RuntimeDiscoveryContext(planning_state=state)

    text = aggregate_freeform_user_text(conversation)
    classification_input = build_slot_classification_input(
        conversation,
        attachment_context,
    )
    if not classification_input.sources:
        return RuntimeDiscoveryContext(planning_state=state)

    allowed_values = llm_resolvable_slot_values_for_state(state)
    model_blocked_slots = slot_names_blocked_by_explicit_uncertainty(
        conversation,
        flow=flow,
    )
    apply_model_blocked_slots(state, model_blocked_slots=model_blocked_slots)
    if model_blocked_slots:
        allowed_values = {
            slot_name: values
            for slot_name, values in allowed_values.items()
            if slot_name not in model_blocked_slots
        }
    if not allowed_values:
        return RuntimeDiscoveryContext(planning_state=state)
    bias = _targeted_classification_bias(
        conversation,
        allowed_values,
        classification_input,
    )
    result = await classify_slots(
        litellm_client=litellm_client,
        completion_model_route=completion_model_route,
        classification_input=classification_input,
        allowed_slot_values=allowed_values,
        tenant_id=tenant_id,
        ui_language=ui_language,
        bias=bias,
        usage_tracker=usage_tracker,
        before_provider_call=before_provider_call,
    )
    if result is None:
        return RuntimeDiscoveryContext(planning_state=state)

    provider = slot_classification_provider_identity(
        litellm_model=completion_model_route.litellm_model,
        litellm_kwargs=completion_model_route.litellm_kwargs,
    )
    prompt_hash = slot_classification_prompt_hash(
        classification_input=classification_input,
        ui_language=ui_language,
        allowed_slot_values=allowed_values,
        litellm_model=completion_model_route.litellm_model,
        provider=provider,
        supported_model_kwargs=completion_model_route.supported_model_kwargs,
        bias=bias,
    )
    merge_llm_resolved_slots(
        state,
        result,
        prompt_hash=prompt_hash,
        freeform_text=text,
        model_blocked_slots=model_blocked_slots,
    )
    apply_policy_defaults_from_resolved_slots(state, freeform_text=text)
    return RuntimeDiscoveryContext(
        planning_state=state,
        slot_classification_result=result,
        slot_classification_metadata=slot_classification_metadata_from_result(
            result,
            prompt_hash=prompt_hash,
            classification_input=classification_input,
            model=completion_model_route.litellm_model,
            provider=provider,
        ),
    )


async def build_discovery_runtime_result(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    litellm_client: Any | None = None,
    completion_model_route: ResolvedCompletionModelRoute | None = None,
    ui_language: str | None = None,
    allow_classification: bool = True,
    tenant_id: UUID,
    attachment_context: AIBuilderAttachmentContext | None = None,
    usage_tracker: ProposalTurnTelemetry | None = None,
    before_provider_call: Callable[[], Awaitable[None]] | None = None,
    mapped_execution_policy: FlowMappedExecutionPolicy | None = None,
) -> DiscoveryRuntimeResult:
    context = await build_runtime_discovery_context(
        conversation,
        flow=flow,
        litellm_client=litellm_client,
        completion_model_route=completion_model_route,
        ui_language=ui_language,
        tenant_id=tenant_id,
        allow_classification=allow_classification,
        attachment_context=attachment_context,
        usage_tracker=usage_tracker,
        before_provider_call=before_provider_call,
        mapped_execution_policy=mapped_execution_policy,
    )
    analysis = analyze_discovery(
        conversation,
        flow=flow,
        planning_state=context.planning_state,
        slot_classification_result=context.slot_classification_result,
    )
    return DiscoveryRuntimeResult(
        discovery_analysis=analysis,
        planning_state=context.planning_state,
        slot_classification_metadata=context.slot_classification_metadata,
    )
