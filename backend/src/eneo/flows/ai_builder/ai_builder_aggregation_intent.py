"""Derive Flow fan-in intent from trusted AI Builder planning slots."""

from __future__ import annotations

from eneo.flows.ai_builder.planning_state import AggregationIntent, PlanningState

DOCUMENT_SCOPE_AGGREGATION_VALUES: frozenset[str] = frozenset(
    {
        "multiple_documents_case",
        "multiple_pdfs_same_run",
        "same_run_multiple_documents",
    }
)
SAME_RUN_DOCUMENT_COMPARISON_SCOPE_VALUES: frozenset[str] = frozenset(
    {
        "same_run_multiple_documents",
        "multiple_documents_case",
    }
)


def derive_aggregation_intent_from_slots(
    state: PlanningState,
    *,
    document_material_input: bool,
) -> AggregationIntent:
    comparison_scope = _commit_grade_slot_value(state, "comparison_scope")
    if comparison_scope == "same_run_compare":
        return "compare"
    if (
        document_material_input
        and comparison_scope in SAME_RUN_DOCUMENT_COMPARISON_SCOPE_VALUES
    ):
        return "compare"

    document_scope = _resolved_slot_value(state, "document_material_scope")
    if document_material_input and document_scope in DOCUMENT_SCOPE_AGGREGATION_VALUES:
        return "aggregate"

    return "linear"


def _commit_grade_slot_value(state: PlanningState, slot_name: str) -> str | None:
    slot = state.resolved_slots.get(slot_name)
    if slot is None or not slot.is_commit_grade:
        return None
    return slot.value


def _resolved_slot_value(state: PlanningState, slot_name: str) -> str | None:
    slot = state.resolved_slots.get(slot_name)
    return slot.value if slot is not None else None
