"""The one decision about each requirement slot: ask, assume, accept, commit."""

from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_slot_interaction_policy import (
    POLICY_COVERED_SLOT_NAMES,
    SLOT_INTERACTION_POLICIES,
    effective_slot_impact,
    evaluate_slot_interaction,
    slot_interaction_order,
    slot_is_relevant,
)
from eneo.flows.ai_builder.planning_state import (
    MappedFileLimit,
    PlanningState,
    ResolvedSlot,
    SlotConfidence,
    SlotSource,
    SlotUncertainty,
)


def _slot(
    slot_name: str,
    value: str,
    *,
    source: SlotSource = "structured_answer",
    confidence: SlotConfidence = "high",
) -> ResolvedSlot:
    return ResolvedSlot(
        name=slot_name,
        value=value,
        source=source,
        evidence=[f"{source}:{slot_name}"],
        confidence=confidence,
    )


def _document_report_state() -> PlanningState:
    """One document-material flow that produces a PDF report."""

    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input", "documents"
    )
    state.resolved_slots["terminal_output"] = _slot("terminal_output", "pdf_document")
    return state


def test_every_slot_the_builder_can_hold_a_requirement_for_has_a_policy() -> None:
    assert set(SLOT_INTERACTION_POLICIES) == POLICY_COVERED_SLOT_NAMES


def test_a_slot_that_assumes_carries_the_value_it_assumes() -> None:
    for policy in SLOT_INTERACTION_POLICIES.values():
        if policy.when_unknown == "assume":
            assert policy.default_value is not None, policy.slot_name


def test_questions_are_ordered_by_the_table_and_nothing_else() -> None:
    orders = [policy.order for policy in SLOT_INTERACTION_POLICIES.values()]
    assert len(set(orders)) == len(orders)
    # A gate that is not a slot places itself; it never borrows a slot's order.
    assert slot_interaction_order("comparison_scope_conflict") == 999
    assert slot_interaction_order("primary_runtime_input") < slot_interaction_order(
        "terminal_output"
    )


def test_an_unresolved_architecture_slot_is_asked() -> None:
    state = PlanningState.empty()

    assert (
        evaluate_slot_interaction(
            SLOT_INTERACTION_POLICIES["primary_runtime_input"], state
        )
        == "ask"
    )


def test_an_unresolved_quality_slot_takes_its_default_silently() -> None:
    state = _document_report_state()

    assert (
        evaluate_slot_interaction(
            SLOT_INTERACTION_POLICIES["runtime_metadata_fields"], state
        )
        == "assume"
    )


def test_a_quality_slot_the_table_always_asks_about_is_asked() -> None:
    state = PlanningState.empty()

    assert (
        evaluate_slot_interaction(
            SLOT_INTERACTION_POLICIES["post_processing_goal"], state
        )
        == "ask"
    )


def test_a_slot_resolved_with_strong_evidence_commits() -> None:
    state = _document_report_state()

    assert (
        evaluate_slot_interaction(SLOT_INTERACTION_POLICIES["terminal_output"], state)
        == "commit"
    )


def test_a_weakly_resolved_quality_slot_stays_an_assumption_row() -> None:
    state = _document_report_state()
    state.resolved_slots["runtime_metadata_fields"] = _slot(
        "runtime_metadata_fields",
        "no_extra_metadata",
        source="policy_default",
        confidence="medium",
    )

    assert (
        evaluate_slot_interaction(
            SLOT_INTERACTION_POLICIES["runtime_metadata_fields"], state
        )
        == "accept"
    )


def test_a_weakly_resolved_architecture_slot_is_asked_rather_than_accepted() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "documents",
        source="heuristic",
        confidence="medium",
    )
    assert not state.resolved_slots["primary_runtime_input"].is_commit_grade

    assert (
        evaluate_slot_interaction(
            SLOT_INTERACTION_POLICIES["primary_runtime_input"], state
        )
        == "ask"
    )


def test_the_model_saying_it_does_not_know_turns_an_assumption_into_a_question() -> (
    None
):
    state = _document_report_state()
    state.slot_uncertainties["runtime_metadata_fields"] = SlotUncertainty(
        slot="runtime_metadata_fields",
        kind="explicitly_uncertain",
    )

    assert (
        evaluate_slot_interaction(
            SLOT_INTERACTION_POLICIES["runtime_metadata_fields"], state
        )
        == "ask"
    )


def test_a_slot_the_shape_has_no_place_for_is_neither_asked_nor_assumed() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input", "audio"
    )

    assert not slot_is_relevant(slot_name="comparison_scope", state=state)
    assert (
        evaluate_slot_interaction(SLOT_INTERACTION_POLICIES["comparison_scope"], state)
        == "not_relevant"
    )


def test_a_quality_slot_the_architecture_needs_is_architectural_here() -> None:
    """The derivation, not the table, decides whether a missing answer blocks."""

    state = _document_report_state()
    state.resolved_slots["document_material_scope"] = _slot(
        "document_material_scope", "multiple_documents_case"
    )
    policy = SLOT_INTERACTION_POLICIES["report_disposition"]
    assert policy.impact == "quality"

    assert effective_slot_impact(policy, state) == "architecture"


def test_the_mapped_ceiling_is_a_question_only_once_it_has_been_proposed() -> None:
    state = _document_report_state()
    state.resolved_slots["document_material_scope"] = _slot(
        "document_material_scope", "flexible_document_case"
    )
    policy = SLOT_INTERACTION_POLICIES["mapped_file_limit"]

    # No proposal from the organization's policy yet: nothing to confirm.
    assert evaluate_slot_interaction(policy, state) in {"not_relevant"}

    state.mapped_file_limit = MappedFileLimit(proposed_value=20)
    assert evaluate_slot_interaction(policy, state) == "ask"

    state.mapped_file_limit = MappedFileLimit(
        proposed_value=20,
        accepted_value=10,
        provenance="authored",
    )
    assert evaluate_slot_interaction(policy, state) == "commit"


def test_an_empty_brief_asks_the_architecture_questions_in_order() -> None:
    state = PlanningState.empty()
    asked = [
        policy.slot_name
        for policy in sorted(
            SLOT_INTERACTION_POLICIES.values(), key=lambda item: item.order
        )
        if evaluate_slot_interaction(policy, state) == "ask"
    ]

    assert asked[:3] == [
        "post_processing_goal",
        "primary_runtime_input",
        "terminal_output",
    ]
    assert asked == sorted(asked, key=slot_interaction_order)


def test_a_brief_that_asks_for_comparison_is_asked_how() -> None:
    state = _document_report_state()
    policy = SLOT_INTERACTION_POLICIES["comparison_scope"]

    assert evaluate_slot_interaction(policy, state) == "assume"
    assert (
        evaluate_slot_interaction(
            policy, state, freeform_text="Jämför dokumenten mot vår policy."
        )
        == "ask"
    )
    state.resolved_slots["post_processing_goal"] = _slot(
        "post_processing_goal", "compare_or_validate"
    )
    assert evaluate_slot_interaction(policy, state) == "ask"


def test_weak_architectural_evidence_is_asked_not_accepted() -> None:
    """The architecture readers commit nothing below commit grade.

    Accepting a confident text rule here would disclose a same-run comparison
    or a template DOCX while the derivation committed a linear flow or a
    generated DOCX. The question keeps the card and the build in agreement.
    """

    state = _document_report_state()
    state.resolved_slots["comparison_scope"] = _slot(
        "comparison_scope", "same_run_compare", source="heuristic", confidence="high"
    )
    assert (
        evaluate_slot_interaction(SLOT_INTERACTION_POLICIES["comparison_scope"], state)
        == "ask"
    )

    state.resolved_slots["terminal_output"] = _slot("terminal_output", "docx_document")
    state.resolved_slots["docx_output_mode"] = _slot(
        "docx_output_mode", "template_fill_docx", source="heuristic", confidence="high"
    )
    assert (
        evaluate_slot_interaction(SLOT_INTERACTION_POLICIES["docx_output_mode"], state)
        == "ask"
    )
