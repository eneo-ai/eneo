from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    SlotClassificationMetadata,
    metadata_has_question_answer,
    slot_classification_metadata_from_result,
)
from intric.flows.ai_builder.ai_builder_discovery import (
    analyze_discovery,
    build_discovery_block_message,
    build_discovery_followup,
)
from intric.flows.ai_builder.ai_builder_discovery_models import DiscoveryAnalysis
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
)
from intric.flows.ai_builder.ai_builder_slot_classifier import (
    SlotClassificationResult,
    classify_slots,
    slot_classification_prompt_hash,
)
from intric.flows.ai_builder.planning_state import PlanningState
from intric.flows.ai_builder.planning_state_builder import (
    apply_policy_defaults_from_resolved_slots,
    build_planning_state_from_conversation,
    llm_resolvable_slot_values_for_state,
    merge_llm_resolved_slots,
)
from intric.flows.domain.flow import Flow


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
    should_emit_forced_followup: bool = False


def _narrow_structured_analysis_need_from_classifier(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None,
    planning_state: PlanningState,
    allowed_values: dict[str, frozenset[str]],
) -> dict[str, frozenset[str]]:
    if "structured_analysis_need" not in allowed_values:
        return allowed_values

    pre_classifier_analysis = analyze_discovery(
        conversation,
        flow=flow,
        planning_state=planning_state,
    )
    if "structured_analysis_need" not in pre_classifier_analysis.selected_question_ids:
        return allowed_values

    narrowed_values = dict(allowed_values)
    narrowed_values.pop("structured_analysis_need", None)
    return narrowed_values


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
    )
    return analyze_discovery(
        conversation,
        flow=flow,
        planning_state=context.planning_state,
        slot_classification_result=context.slot_classification_result,
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
) -> RuntimeDiscoveryContext:
    state = build_planning_state_from_conversation(conversation, flow=flow)
    if not allow_classification or litellm_client is None or litellm_model is None:
        return RuntimeDiscoveryContext(planning_state=state)

    text = aggregate_freeform_user_text(conversation)
    if not text.strip():
        return RuntimeDiscoveryContext(planning_state=state)

    allowed_values = llm_resolvable_slot_values_for_state(state)
    if not allowed_values:
        return RuntimeDiscoveryContext(planning_state=state)
    allowed_values = _narrow_structured_analysis_need_from_classifier(
        conversation,
        flow=flow,
        planning_state=state,
        allowed_values=allowed_values,
    )
    if not allowed_values:
        return RuntimeDiscoveryContext(planning_state=state)

    result = await classify_slots(
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs or {},
        text=text,
        allowed_slot_values=allowed_values,
        tenant_id=tenant_id,
        ui_language=ui_language,
    )
    if result is None:
        return RuntimeDiscoveryContext(planning_state=state)

    prompt_hash = slot_classification_prompt_hash(
        text=text,
        ui_language=ui_language,
        slot_names=allowed_values.keys(),
    )
    merge_llm_resolved_slots(state, result, prompt_hash=prompt_hash)
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
    requirements_confirmed: bool = False,
    is_requirements_confirmation: bool = False,
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
        should_emit_forced_followup=_should_emit_forced_followup(
            conversation,
            requirements_confirmed=requirements_confirmed,
            is_requirements_confirmation=is_requirements_confirmation,
            discovery_block_message=discovery_block_message,
            discovery_analysis=analysis,
            flow=flow,
        ),
        discovery_analysis=analysis,
        planning_state=context.planning_state,
        slot_classification_metadata=context.slot_classification_metadata,
    )


async def build_discovery_followup_runtime(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
    litellm_client: Any | None = None,
    litellm_model: str | None = None,
    litellm_kwargs: dict[str, Any] | None = None,
    ui_language: str | None = None,
    allow_semantic_adjudication: bool = True,
    tenant_id: UUID,
):
    context = await build_runtime_discovery_context(
        conversation,
        flow=flow,
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs,
        ui_language=ui_language,
        tenant_id=tenant_id,
        allow_classification=allow_semantic_adjudication,
    )
    analysis = analyze_discovery(
        conversation,
        flow=flow,
        planning_state=context.planning_state,
        slot_classification_result=context.slot_classification_result,
    )
    return (
        build_discovery_followup(
            conversation,
            flow=flow,
            analysis=analysis,
        ),
        analysis,
        context.planning_state,
    )


def _should_emit_forced_followup(
    conversation: list[ConversationMessage],
    *,
    requirements_confirmed: bool,
    is_requirements_confirmation: bool,
    discovery_block_message: str | None,
    discovery_analysis: DiscoveryAnalysis,
    flow: Flow | None,
) -> bool:
    # Two unanswered discovery turns are enough evidence of a stalled freeform loop.
    is_free_discovery = (
        not requirements_confirmed
        and not is_requirements_confirmation
        and not discovery_analysis.mvs_met
        and discovery_block_message is None
    )
    if not is_free_discovery:
        return False
    if _count_free_discovery_turns(conversation) < 2:
        return False
    return _get_mvs_forced_followup(conversation, flow=flow) is not None


def _count_free_discovery_turns(conversation: list[ConversationMessage]) -> int:
    count = 0
    for msg in reversed(conversation):
        if msg.role == "assistant" and msg.content and not msg.tool_calls:
            count += 1
        elif msg.role == "user" and metadata_has_question_answer(msg.metadata):
            break
    return count


def _get_mvs_forced_followup(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
) -> str | None:
    followup = build_discovery_followup(conversation, flow=flow)
    if followup is not None:
        return followup[2]
    return None
