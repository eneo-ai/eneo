"""Derive `PlanningState` from a conversation + optional `Flow`.

This is the bridge between the legacy per-turn reconstruction path
(`build_resolved_requirements_state`) and the persisted typed
PlanningState that eventually replaces it. Today it delegates to the
legacy resolver and translates the resulting `RequirementSlot` tuple
into `ResolvedSlot` entries on a freshly-stamped `PlanningState`, so
callers can start flowing through the new model before the legacy
machinery is deleted.

Parity with the legacy path is verified test-side; any divergence
between the two derivations is a regression.
"""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_resolved_requirements import (
    RequirementSlot,
    build_resolved_requirements_state,
)
from intric.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
    EvidenceRef,
    PlanningState,
    ResolvedSlot,
)
from intric.flows.domain.flow import Flow


def build_planning_state_from_conversation(
    conversation: list[ConversationMessage],
    *,
    flow: Flow | None = None,
) -> PlanningState:
    """Derive a `PlanningState` from the same inputs the legacy resolver uses.

    Phase is set to `discovering` once any slot is resolved; otherwise the
    state stays in `awaiting_input`. Evidence captures the stable
    conversation message ids so the snapshot survives conversation
    compaction. No signals, architecture commit, or open questions are
    populated yet — those layers land in subsequent slices.
    """
    legacy_state = build_resolved_requirements_state(conversation, flow=flow)
    resolved_slots = {slot.name: _to_resolved_slot(slot) for slot in legacy_state.slots}
    phase = "discovering" if resolved_slots else "awaiting_input"
    return PlanningState(
        fcm_version=FCM_VERSION,
        planner_contract_version=PLANNER_CONTRACT_VERSION,
        builder_schema_version=BUILDER_SCHEMA_VERSION,
        phase=phase,
        evidence=EvidenceRef(
            conversation_message_ids=[message.message_id for message in conversation],
        ),
        resolved_slots=resolved_slots,
    )


def _to_resolved_slot(slot: RequirementSlot) -> ResolvedSlot:
    return ResolvedSlot(
        name=slot.name,
        value=slot.value,
        source=slot.source,
        evidence=list(slot.evidence),
        confidence=slot.confidence,
    )
