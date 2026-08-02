"""Derive Flow fan-in intent from trusted AI Builder planning slots."""

from __future__ import annotations

from eneo.flows.ai_builder.planning_state import AggregationIntent, PlanningState

DOCUMENT_SCOPE_AGGREGATION_VALUES: frozenset[str] = frozenset(
    {"multiple_documents_case"}
)
SAME_RUN_DOCUMENT_COMPARISON_SCOPE_VALUES: frozenset[str] = frozenset(
    {"same_run_compare"}
)
DOCUMENT_MATERIAL_INPUT_VALUES: frozenset[str] = frozenset(
    {"document", "documents", "text_and_documents"}
)
DOCUMENT_REPORT_OUTPUT_VALUES: frozenset[str] = frozenset(
    {"pdf_document", "docx_document"}
)
MULTI_SOURCE_DOCUMENT_SCOPE_VALUES: frozenset[str] = frozenset(
    {"multiple_documents_case", "flexible_document_case"}
)


def comparison_scope_is_relevant(
    *,
    primary_runtime_input: str | None,
    unresolved_values_are_relevant: bool,
) -> bool:
    if primary_runtime_input is None:
        return unresolved_values_are_relevant
    return primary_runtime_input in DOCUMENT_MATERIAL_INPUT_VALUES


def report_disposition_is_relevant(
    *,
    primary_runtime_input: str | None,
    terminal_output: str | None,
    document_material_scope: str | None,
    docx_output_mode: str | None,
    unresolved_values_are_relevant: bool,
) -> bool:
    expected_values = (
        (primary_runtime_input, DOCUMENT_MATERIAL_INPUT_VALUES),
        (terminal_output, DOCUMENT_REPORT_OUTPUT_VALUES),
        (document_material_scope, MULTI_SOURCE_DOCUMENT_SCOPE_VALUES),
    )
    for value, allowed_values in expected_values:
        if value is None:
            if not unresolved_values_are_relevant:
                return False
            continue
        if value not in allowed_values:
            return False
    return not (
        terminal_output == "docx_document" and docx_output_mode == "template_fill_docx"
    )


def derive_aggregation_intent_from_slots(
    state: PlanningState,
    *,
    document_material_input: bool,
) -> AggregationIntent:
    comparison_scope = _commit_grade_slot_value(state, "comparison_scope")
    if (
        document_material_input
        and comparison_scope in SAME_RUN_DOCUMENT_COMPARISON_SCOPE_VALUES
    ):
        return "compare"

    document_scope = _commit_grade_slot_value(state, "document_material_scope")
    if document_material_input and document_scope in DOCUMENT_SCOPE_AGGREGATION_VALUES:
        return "aggregate"

    return "linear"


def _commit_grade_slot_value(state: PlanningState, slot_name: str) -> str | None:
    slot = state.resolved_slots.get(slot_name)
    if slot is None or not slot.is_commit_grade:
        return None
    return slot.value
