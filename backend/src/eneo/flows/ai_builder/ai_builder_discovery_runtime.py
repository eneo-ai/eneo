from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AIBuilderAttachmentContext,
    apply_attachment_file_roles_to_planning_state,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    SlotClassificationMetadata,
    slot_classification_metadata_from_result,
)
from eneo.flows.ai_builder.ai_builder_discovery import (
    analyze_discovery,
    build_discovery_block_message,
)
from eneo.flows.ai_builder.ai_builder_discovery_models import (
    DiscoveryAnalysis,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
    slot_names_blocked_by_explicit_uncertainty,
)
from eneo.flows.ai_builder.ai_builder_question_state import (
    last_answered_question,
)
from eneo.flows.ai_builder.ai_builder_slot_classifier import (
    SlotClassificationBias,
    SlotClassificationResult,
    classify_slots,
    slot_classification_prompt_hash,
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


@dataclass(frozen=True, slots=True)
class RuntimeDiscoveryContext:
    planning_state: PlanningState
    slot_classification_result: SlotClassificationResult | None = None
    slot_classification_metadata: SlotClassificationMetadata | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryRuntimeResult:
    discovery_block_message: str | None
    discovery_analysis: DiscoveryAnalysis
    planning_state: PlanningState
    slot_classification_metadata: SlotClassificationMetadata | None = None


async def analyze_discovery_runtime(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    litellm_client: Any | None = None,
    litellm_model: str | None = None,
    litellm_kwargs: dict[str, Any] | None = None,
    ui_language: str | None = None,
    allow_semantic_adjudication: bool = True,
    tenant_id: UUID,
    attachment_context: AIBuilderAttachmentContext | None = None,
) -> DiscoveryAnalysis:
    context = await build_runtime_discovery_context(
        conversation=conversation,
        flow=flow,
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs,
        ui_language=ui_language,
        tenant_id=tenant_id,
        allow_classification=allow_semantic_adjudication,
        attachment_context=attachment_context,
    )
    return analyze_discovery(
        conversation,
        flow=flow,
        planning_state=context.planning_state,
        slot_classification_result=context.slot_classification_result,
    )


def _targeted_classification_bias(
    conversation: list[ConversationMessage],
    allowed_slot_values: Mapping[str, Collection[str]],
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
    return SlotClassificationBias(
        target_slot_name=target_slot,
        asked_question_id=asked_question_id,
        latest_user_answer=latest_answer,
    )


async def build_runtime_discovery_context(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    litellm_client: Any | None = None,
    litellm_model: str | None = None,
    litellm_kwargs: dict[str, Any] | None = None,
    ui_language: str | None = None,
    tenant_id: UUID,
    allow_classification: bool = True,
    attachment_context: AIBuilderAttachmentContext | None = None,
) -> RuntimeDiscoveryContext:
    state = build_planning_state_from_conversation(conversation, flow=flow)
    apply_attachment_file_roles_to_planning_state(state, attachment_context)
    if not allow_classification or litellm_client is None or litellm_model is None:
        return RuntimeDiscoveryContext(planning_state=state)

    text = aggregate_freeform_user_text(conversation)
    uploaded_file_evidence = (
        attachment_context.discovery_context if attachment_context is not None else None
    )
    if not text.strip() and uploaded_file_evidence is None:
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
    bias = _targeted_classification_bias(conversation, allowed_values)
    result = await classify_slots(
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs or {},
        text=text,
        allowed_slot_values=allowed_values,
        tenant_id=tenant_id,
        ui_language=ui_language,
        bias=bias,
        uploaded_file_evidence=uploaded_file_evidence,
    )
    if result is None:
        return RuntimeDiscoveryContext(planning_state=state)

    prompt_hash = slot_classification_prompt_hash(
        text=text,
        ui_language=ui_language,
        allowed_slot_values=allowed_values,
        bias=bias,
        uploaded_file_evidence=uploaded_file_evidence,
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
        ),
    )


async def build_runtime_planning_state(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    litellm_client: Any | None = None,
    litellm_model: str | None = None,
    litellm_kwargs: dict[str, Any] | None = None,
    ui_language: str | None = None,
    tenant_id: UUID,
    allow_classification: bool = True,
    attachment_context: AIBuilderAttachmentContext | None = None,
) -> PlanningState:
    context = await build_runtime_discovery_context(
        conversation,
        flow=flow,
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs,
        ui_language=ui_language,
        tenant_id=tenant_id,
        allow_classification=allow_classification,
        attachment_context=attachment_context,
    )
    return context.planning_state


async def build_discovery_block_message_runtime(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    litellm_client: Any | None = None,
    litellm_model: str | None = None,
    litellm_kwargs: dict[str, Any] | None = None,
    ui_language: str | None = None,
    allow_semantic_adjudication: bool = True,
    tenant_id: UUID,
    attachment_context: AIBuilderAttachmentContext | None = None,
) -> tuple[str | None, DiscoveryAnalysis, PlanningState]:
    result = await build_discovery_runtime_result(
        conversation,
        flow=flow,
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs,
        ui_language=ui_language,
        allow_semantic_adjudication=allow_semantic_adjudication,
        tenant_id=tenant_id,
        attachment_context=attachment_context,
    )
    return (
        result.discovery_block_message,
        result.discovery_analysis,
        result.planning_state,
    )


async def build_discovery_runtime_result(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    litellm_client: Any | None = None,
    litellm_model: str | None = None,
    litellm_kwargs: dict[str, Any] | None = None,
    ui_language: str | None = None,
    allow_semantic_adjudication: bool = True,
    tenant_id: UUID,
    attachment_context: AIBuilderAttachmentContext | None = None,
) -> DiscoveryRuntimeResult:
    context = await build_runtime_discovery_context(
        conversation,
        flow=flow,
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs,
        ui_language=ui_language,
        tenant_id=tenant_id,
        allow_classification=allow_semantic_adjudication,
        attachment_context=attachment_context,
    )
    analysis = analyze_discovery(
        conversation,
        flow=flow,
        planning_state=context.planning_state,
        slot_classification_result=context.slot_classification_result,
    )
    discovery_block_message = build_discovery_block_message(
        conversation,
        flow=flow,
        analysis=analysis,
    )
    return DiscoveryRuntimeResult(
        discovery_block_message=discovery_block_message,
        discovery_analysis=analysis,
        planning_state=context.planning_state,
        slot_classification_metadata=context.slot_classification_metadata,
    )
