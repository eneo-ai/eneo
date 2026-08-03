"""Tests for the server-owned AI Builder planner action policy."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from eneo.flows.ai_builder.ai_builder_action_policy import (
    build_planner_action_policy,
)
from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_slot_classifier import (
    UNKNOWN_SLOT_VALUE,
    ClassifiedSlot,
    SlotClassificationResult,
)
from eneo.flows.ai_builder.planning_state import (
    PlanningState,
    ResolvedSlot,
    SlotConfidence,
    SlotSource,
)
from eneo.flows.ai_builder.planning_state_builder import merge_llm_resolved_slots


def _slot_value(slot_name: str) -> str:
    return {
        "primary_runtime_input": "documents",
        "terminal_output": "text",
        "document_material_scope": "flexible_document_case",
    }.get(slot_name, f"{slot_name}_value")


def _slot(
    slot_name: str,
    value: str | None = None,
    *,
    source: SlotSource = "structured_answer",
    confidence: SlotConfidence = "high",
    evidence: list[str] | None = None,
) -> ResolvedSlot:
    return ResolvedSlot(
        name=slot_name,
        value=value or _slot_value(slot_name),
        source=source,
        evidence=(
            [
                (
                    f"quote:user_message:test:{slot_name}"
                    if source == "model"
                    else f"{source}:{slot_name}"
                )
            ]
            if evidence is None
            else evidence
        ),
        confidence=confidence,
    )


def _state_with_resolved_slots(*slot_names: str) -> PlanningState:
    state = PlanningState.empty()
    for slot_name in slot_names:
        state.resolved_slots[slot_name] = _slot(slot_name)
    return state


def _state_with_architecture_commit() -> PlanningState:
    state = _state_with_resolved_slots(
        "primary_runtime_input",
        "terminal_output",
        "document_material_scope",
    )
    draft = derive_architecture_commit_draft(state)
    assert draft is not None
    state.architecture_commit = finalize_architecture_commit(
        draft,
        now=lambda: datetime(2026, 4, 24, tzinfo=timezone.utc),
    )
    return state


def test_policy_blocks_commit_and_plan_until_core_architecture_is_resolved() -> None:
    policy = build_planner_action_policy(
        session_state=PlanningState.empty(),
        selected_discovery_question_ids=("document_material_scope",),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == (
        "primary_runtime_input",
        "terminal_output",
        "document_material_scope",
    )


def test_policy_asks_for_model_medium_core_slot_before_commit() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "audio",
        source="heuristic",
        confidence="high",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_text",
        source="model",
        confidence="medium",
    )
    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == (
        "primary_runtime_input",
        "terminal_output",
    )


def test_policy_asks_weak_pattern_slot_only_when_discovery_selects_it() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "documents",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_text",
    )
    state.resolved_slots["document_material_scope"] = _slot(
        "document_material_scope",
        "flexible_document_case",
        source="model",
        confidence="medium",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=("document_material_scope",),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == ("document_material_scope",)


@pytest.mark.parametrize(
    ("slot", "expected"),
    [
        (_slot("terminal_output", "structured_text", source="model"), True),
        (
            _slot(
                "terminal_output",
                "structured_text",
                source="model",
                evidence=[],
            ),
            False,
        ),
        (
            _slot(
                "terminal_output",
                "structured_text",
                source="model",
                confidence="medium",
            ),
            False,
        ),
        (
            _slot(
                "terminal_output",
                "structured_text",
                source="model",
                confidence="low",
            ),
            False,
        ),
        (
            _slot(
                "terminal_output",
                "structured_text",
                source="heuristic",
                confidence="medium",
            ),
            False,
        ),
        (
            _slot(
                "terminal_output",
                "structured_text",
                source="heuristic",
                confidence="low",
            ),
            False,
        ),
        (
            _slot(
                "terminal_output",
                "structured_text",
                source="requirements_summary",
                confidence="medium",
            ),
            True,
        ),
        (
            _slot(
                "primary_runtime_input",
                "audio",
                source="heuristic",
                confidence="high",
            ),
            False,
        ),
        (
            _slot(
                "runtime_metadata_fields",
                "no_extra_metadata",
                source="policy_default",
                confidence="medium",
            ),
            False,
        ),
        (_slot("terminal_output", "docx_document", source="flow_default"), True),
    ],
)
def test_commit_grade_truth_table(slot: ResolvedSlot, expected: bool) -> None:
    assert slot.is_commit_grade is expected


def test_policy_prioritizes_missing_core_slots_before_discovery_targets() -> None:
    policy = build_planner_action_policy(
        session_state=PlanningState.empty(),
        selected_discovery_question_ids=("document_material_scope",),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == (
        "primary_runtime_input",
        "terminal_output",
        "document_material_scope",
    )


def test_policy_does_not_force_inferred_metadata_default_into_questions() -> None:
    state = _state_with_resolved_slots(
        "primary_runtime_input",
        "terminal_output",
        "document_material_scope",
    )
    state.resolved_slots["runtime_metadata_fields"] = _slot(
        "runtime_metadata_fields",
        "no_extra_metadata",
        source="model",
        confidence="medium",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_does_not_force_heuristic_comparison_scope_into_questions() -> None:
    state = _state_with_resolved_slots(
        "primary_runtime_input",
        "terminal_output",
        "document_material_scope",
    )
    state.resolved_slots["comparison_scope"] = _slot(
        "comparison_scope",
        "same_run_compare",
        source="heuristic",
        confidence="high",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_keeps_selected_comparison_question_askable() -> None:
    state = _state_with_resolved_slots(
        "primary_runtime_input",
        "terminal_output",
        "document_material_scope",
    )
    state.resolved_slots["comparison_scope"] = _slot(
        "comparison_scope",
        "same_run_compare",
        source="heuristic",
        confidence="high",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=("comparison_scope",),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == ("comparison_scope",)


def test_policy_prioritizes_missing_core_without_reordering_discovery() -> None:
    policy = build_planner_action_policy(
        session_state=PlanningState.empty(),
        selected_discovery_question_ids=(
            "runtime_metadata_fields",
            "post_processing_goal",
        ),
    )

    assert policy.allowed_ask_question_targets == (
        "primary_runtime_input",
        "terminal_output",
        "runtime_metadata_fields",
        "post_processing_goal",
    )


@pytest.mark.parametrize("primary_runtime_input", ["audio", "text", "json"])
def test_policy_ignores_weak_comparison_for_non_document_input(
    primary_runtime_input: str,
) -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        primary_runtime_input,
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_text",
    )
    state.resolved_slots["comparison_scope"] = _slot(
        "comparison_scope",
        "same_run_compare",
        source="heuristic",
        confidence="high",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()


@pytest.mark.parametrize("primary_runtime_input", ["audio", "text", "json"])
def test_policy_ignores_weak_report_disposition_for_non_document_input(
    primary_runtime_input: str,
) -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        primary_runtime_input,
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_text",
    )
    state.resolved_slots["report_disposition"] = _slot(
        "report_disposition",
        "both",
        source="model",
        confidence="medium",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_does_not_force_policy_default_docx_mode_into_questions() -> None:
    state = _state_with_resolved_slots(
        "primary_runtime_input",
        "document_material_scope",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "docx_document",
    )
    state.resolved_slots["docx_output_mode"] = _slot(
        "docx_output_mode",
        "generated_docx",
        source="policy_default",
        confidence="medium",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_allows_commit_after_core_slots_and_selected_questions_resolve() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_resolved_slots(
            "primary_runtime_input",
            "terminal_output",
            "document_material_scope",
        ),
        selected_discovery_question_ids=("document_material_scope",),
    )

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_does_not_use_pattern_metadata_as_question_selection() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_resolved_slots(
            "primary_runtime_input",
            "terminal_output",
        ),
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_asks_selected_report_disposition_for_multi_source_pdf_report() -> None:
    state = _state_with_resolved_slots("primary_runtime_input")
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
    )
    state.resolved_slots["pdf_generation_mode"] = _slot(
        "pdf_generation_mode",
        "generated_pdf",
    )
    state.resolved_slots["document_material_scope"] = _slot(
        "document_material_scope",
        "multiple_documents_case",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=("report_disposition",),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == ("report_disposition",)


def test_policy_accepts_classifier_inferred_report_disposition() -> None:
    state = _state_with_resolved_slots("primary_runtime_input")
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
    )
    state.resolved_slots["pdf_generation_mode"] = _slot(
        "pdf_generation_mode",
        "generated_pdf",
    )
    state.resolved_slots["document_material_scope"] = _slot(
        "document_material_scope",
        "multiple_documents_case",
    )
    state.resolved_slots["report_disposition"] = _slot(
        "report_disposition",
        "per_source_sections",
        source="model",
        confidence="high",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_does_not_ask_report_disposition_for_docx_template_fill() -> None:
    state = _state_with_resolved_slots("primary_runtime_input")
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "docx_document",
    )
    state.resolved_slots["docx_output_mode"] = _slot(
        "docx_output_mode",
        "template_fill_docx",
    )
    state.resolved_slots["document_material_scope"] = _slot(
        "document_material_scope",
        "multiple_documents_case",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_never_exposes_resolved_slots_as_question_targets() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_resolved_slots("primary_runtime_input"),
        selected_discovery_question_ids=("primary_runtime_input",),
    )

    assert policy.allowed_ask_question_targets == ("terminal_output",)
    assert policy.allowed_action_kinds == ("ask_question",)


def test_policy_filters_commit_grade_terminal_output_discovery_target() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_resolved_slots(
            "primary_runtime_input",
            "terminal_output",
        ),
        selected_discovery_question_ids=("final_output_mode",),
    )

    assert "terminal_output" not in policy.allowed_ask_question_targets


def test_policy_can_ask_output_after_classifier_uncertainty_clears_guess() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = ResolvedSlot(
        name="primary_runtime_input",
        value="audio",
        source="heuristic",
        evidence=["heuristic:role-aware freeform analysis"],
        confidence="high",
    )
    state.resolved_slots["terminal_output"] = ResolvedSlot(
        name="terminal_output",
        value="structured_text",
        source="model",
        evidence=["model:terminal_output:" + "a" * 64],
        confidence="medium",
    )

    merge_llm_resolved_slots(
        state,
        SlotClassificationResult(
            slots=(
                ClassifiedSlot(
                    slot_name="terminal_output",
                    value=UNKNOWN_SLOT_VALUE,
                    confidence="high",
                    reason="user_explicit_uncertain",
                    evidence=("not sure what the final output should be",),
                ),
            )
        ),
        prompt_hash="b" * 64,
        freeform_text="",
    )
    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert "terminal_output" not in state.resolved_slots
    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == (
        "primary_runtime_input",
        "terminal_output",
    )


@pytest.mark.parametrize("source", ["structured_answer", "flow_default"])
def test_classifier_uncertainty_keeps_protected_output_sources_resolved(
    source: str,
) -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = ResolvedSlot(
        name="primary_runtime_input",
        value="audio",
        source="heuristic",
        evidence=["heuristic:role-aware freeform analysis"],
        confidence="high",
    )
    state.resolved_slots["terminal_output"] = ResolvedSlot(
        name="terminal_output",
        value="docx_document",
        source=source,
        evidence=[f"{source}:final_output_mode"],
        confidence="high",
    )

    merge_llm_resolved_slots(
        state,
        SlotClassificationResult(
            slots=(
                ClassifiedSlot(
                    slot_name="terminal_output",
                    value=UNKNOWN_SLOT_VALUE,
                    confidence="high",
                    reason="user_explicit_uncertain",
                    evidence=("not sure what the final output should be",),
                ),
            )
        ),
        prompt_hash="c" * 64,
        freeform_text="",
    )
    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert state.resolved_slots["terminal_output"].value == "docx_document"
    assert state.resolved_slots["terminal_output"].source == source
    assert "terminal_output" not in policy.allowed_ask_question_targets


def test_policy_asks_missing_core_slots_even_without_discovery_selection() -> None:
    policy = build_planner_action_policy(
        session_state=PlanningState.empty(),
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == (
        "primary_runtime_input",
        "terminal_output",
    )


def test_policy_normalizes_legacy_discovery_question_ids_to_slot_targets() -> None:
    policy = build_planner_action_policy(
        session_state=PlanningState.empty(),
        selected_discovery_question_ids=("final_output_mode",),
    )

    assert policy.allowed_ask_question_targets == (
        "primary_runtime_input",
        "terminal_output",
    )


def test_policy_allows_requirements_confirmation_after_architecture_commit() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_architecture_commit(),
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("confirm_requirements",)


def test_policy_keeps_discovery_selected_question_after_architecture_commit() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_architecture_commit(),
        selected_discovery_question_ids=("runtime_metadata_fields",),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == ("runtime_metadata_fields",)


def test_policy_keeps_renderable_non_slot_discovery_question() -> None:
    state = _state_with_resolved_slots(
        "primary_runtime_input",
        "terminal_output",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=("flow_input_architecture",),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == ("flow_input_architecture",)


def test_policy_revises_committed_architecture_when_commit_grade_slots_drift() -> None:
    state = _state_with_architecture_commit()
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
    )
    state.resolved_slots["pdf_generation_mode"] = _slot(
        "pdf_generation_mode",
        "generated_pdf",
    )
    state.resolved_slots["document_material_scope"] = _slot(
        "document_material_scope",
        "flexible_document_case",
    )
    state.resolved_slots["report_disposition"] = _slot(
        "report_disposition",
        "both",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("revise_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_revises_commit_when_report_disposition_changes() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "documents",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
    )
    state.resolved_slots["pdf_generation_mode"] = _slot(
        "pdf_generation_mode",
        "generated_pdf",
    )
    state.resolved_slots["document_material_scope"] = _slot(
        "document_material_scope",
        "multiple_documents_case",
    )
    state.resolved_slots["report_disposition"] = _slot(
        "report_disposition",
        "per_source_sections",
    )
    draft = derive_architecture_commit_draft(state)
    assert draft is not None
    state.architecture_commit = finalize_architecture_commit(draft)
    state.resolved_slots["report_disposition"] = _slot(
        "report_disposition",
        "both",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("revise_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_keeps_pinned_commit_when_only_weak_slot_conflicts() -> None:
    state = _state_with_architecture_commit()
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
        source="model",
        confidence="medium",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
        requirements_confirmed=True,
    )

    assert policy.allowed_action_kinds == ("propose_plan",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_ignores_stale_weak_report_disposition_after_commit() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "text",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_text",
    )
    draft = derive_architecture_commit_draft(state)
    assert draft is not None
    state.architecture_commit = finalize_architecture_commit(draft)
    state.resolved_slots["report_disposition"] = _slot(
        "report_disposition",
        "both",
        source="heuristic",
        confidence="high",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("confirm_requirements",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_allows_plan_after_architecture_and_requirements_confirmation() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_architecture_commit(),
        selected_discovery_question_ids=(),
        requirements_confirmed=True,
    )

    assert policy.allowed_action_kinds == ("propose_plan",)
