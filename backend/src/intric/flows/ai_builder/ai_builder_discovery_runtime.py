from __future__ import annotations

from typing import Any
from uuid import UUID

from intric.flows.ai_builder.ai_builder_discovery import (
    analyze_discovery,
    build_discovery_block_message,
    build_discovery_followup,
)
from intric.flows.ai_builder.ai_builder_discovery_models import DiscoveryAnalysis
from intric.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_semantic_adjudication import (
    adjudicate_discovery_semantics,
    should_run_semantic_adjudication,
)
from intric.flows.ai_builder.ai_builder_slot_classifier import (
    classify_slots,
    slot_classification_prompt_hash,
)
from intric.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
    NON_LLM_RESOLVABLE_SLOT_NAMES,
)
from intric.flows.ai_builder.planning_state import PlanningState
from intric.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
    merge_llm_resolved_slots,
)
from intric.flows.ai_builder.question_catalog import legal_slot_values
from intric.flows.domain.flow import Flow


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
    analysis = analyze_discovery(conversation, flow=flow)
    if (
        not allow_semantic_adjudication
        or litellm_client is None
        or litellm_model is None
        or not should_run_semantic_adjudication(analysis)
    ):
        return analysis

    classification_result = await adjudicate_discovery_semantics(
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs or {},
        conversation=conversation,
        analysis=analysis,
        tenant_id=tenant_id,
        ui_language=ui_language,
    )
    if classification_result is None:
        return analysis
    return analyze_discovery(
        conversation,
        flow=flow,
        slot_classification_result=classification_result,
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
    state = build_planning_state_from_conversation(conversation, flow=flow)
    if not allow_classification or litellm_client is None or litellm_model is None:
        return state

    text = aggregate_freeform_user_text(conversation)
    if not text.strip():
        return state

    allowed_values = _llm_candidate_slot_values(state)
    if not allowed_values:
        return state

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
        return state

    prompt_hash = slot_classification_prompt_hash(
        text=text,
        ui_language=ui_language,
        slot_names=allowed_values.keys(),
    )
    merge_llm_resolved_slots(state, result, prompt_hash=prompt_hash)
    return state


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
) -> tuple[str | None, DiscoveryAnalysis]:
    analysis = await analyze_discovery_runtime(
        conversation,
        flow=flow,
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs,
        ui_language=ui_language,
        allow_semantic_adjudication=allow_semantic_adjudication,
        tenant_id=tenant_id,
    )
    return build_discovery_block_message(
        conversation,
        flow=flow,
        analysis=analysis,
    ), analysis


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
    analysis = await analyze_discovery_runtime(
        conversation,
        flow=flow,
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs,
        ui_language=ui_language,
        allow_semantic_adjudication=allow_semantic_adjudication,
        tenant_id=tenant_id,
    )
    return build_discovery_followup(
        conversation,
        flow=flow,
        analysis=analysis,
    ), analysis


def _llm_candidate_slot_values(
    state: PlanningState,
) -> dict[str, frozenset[str]]:
    resolvable_slots = KNOWN_REQUIREMENT_SLOT_NAMES - NON_LLM_RESOLVABLE_SLOT_NAMES
    candidate_slots = {
        slot_name
        for slot_name in resolvable_slots
        if (
            slot_name not in state.resolved_slots
            or state.resolved_slots[slot_name].source in {"heuristic", "policy_default"}
        )
    }
    return {
        slot_name: legal_slot_values(slot_name) for slot_name in sorted(candidate_slots)
    }
