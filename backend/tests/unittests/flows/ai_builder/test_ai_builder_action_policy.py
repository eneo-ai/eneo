"""Tests for the server-owned AI Builder planner action policy."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from eneo.flows.ai_builder.ai_builder_action_policy import (
    build_planner_action_policy,
    compute_unresolved_core_slots,
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
) -> ResolvedSlot:
    return ResolvedSlot(
        name=slot_name,
        value=value or _slot_value(slot_name),
        source=source,
        evidence=[f"{source}:{slot_name}"],
        confidence=confidence,
    )


def _state_with_resolved_slots(*slot_names: str) -> PlanningState:
    state = PlanningState.empty()
    for slot_name in slot_names:
        state.resolved_slots[slot_name] = _slot(slot_name)
    return state


def _state_with_architecture_commit() -> PlanningState:
    state = _state_with_resolved_slots("primary_runtime_input", "terminal_output")
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
        unresolved_architectural_choices=frozenset({"terminal_output"}),
        selected_discovery_question_ids=("document_material_scope",),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == (
        "document_material_scope",
        "primary_runtime_input",
        "terminal_output",
    )
    assert policy.blocked_action_reasons["commit_architecture"].startswith(
        "unresolved architecture choices"
    )
    assert policy.blocked_action_reasons["propose_plan"].startswith(
        "architecture has not been committed"
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
    unresolved = compute_unresolved_core_slots(state)

    policy = build_planner_action_policy(
        session_state=state,
        unresolved_architectural_choices=unresolved,
        selected_discovery_question_ids=(),
    )

    assert unresolved == frozenset({"terminal_output"})
    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == ("terminal_output",)
    assert "terminal_output" in policy.blocked_action_reasons["commit_architecture"]


def test_policy_blocks_model_medium_pattern_required_slot() -> None:
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
        unresolved_architectural_choices=compute_unresolved_core_slots(state),
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == ("document_material_scope",)
    assert (
        "document_material_scope"
        in policy.blocked_action_reasons["commit_architecture"]
    )


@pytest.mark.parametrize(
    ("slot", "expected"),
    [
        (_slot("terminal_output", "structured_text", source="model"), True),
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
            True,
        ),
        (
            _slot(
                "runtime_metadata_fields",
                "no_extra_metadata",
                source="policy_default",
                confidence="medium",
            ),
            True,
        ),
        (_slot("terminal_output", "docx_document", source="flow_default"), True),
    ],
)
def test_commit_grade_truth_table(slot: ResolvedSlot, expected: bool) -> None:
    assert slot.is_commit_grade is expected


def test_policy_preserves_selected_discovery_question_priority() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_resolved_slots(
            "primary_runtime_input",
            "terminal_output",
        ),
        unresolved_architectural_choices=frozenset(),
        selected_discovery_question_ids=(
            "structured_analysis_need",
            "document_material_scope",
        ),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == (
        "structured_analysis_need",
        "document_material_scope",
    )


def test_policy_appends_missing_core_slots_after_selected_discovery_targets() -> None:
    policy = build_planner_action_policy(
        session_state=PlanningState.empty(),
        unresolved_architectural_choices=frozenset(),
        selected_discovery_question_ids=("document_material_scope",),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == (
        "document_material_scope",
        "primary_runtime_input",
        "terminal_output",
    )


def test_policy_allows_commit_after_core_slots_and_selected_questions_resolve() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_resolved_slots(
            "primary_runtime_input",
            "terminal_output",
            "document_material_scope",
        ),
        unresolved_architectural_choices=frozenset(),
        selected_discovery_question_ids=("document_material_scope",),
    )

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()
    assert "commit_architecture" not in policy.blocked_action_reasons
    assert "propose_plan" in policy.blocked_action_reasons


def test_policy_blocks_commit_when_derived_pattern_requires_unresolved_slot() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_resolved_slots(
            "primary_runtime_input",
            "terminal_output",
        ),
        unresolved_architectural_choices=frozenset(),
        selected_discovery_question_ids=(),
    )

    assert "commit_architecture" not in policy.allowed_action_kinds
    assert policy.allowed_ask_question_targets == ("document_material_scope",)
    assert (
        "document_material_scope"
        in policy.blocked_action_reasons["commit_architecture"]
    )


def test_policy_never_exposes_resolved_slots_as_question_targets() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_resolved_slots("primary_runtime_input"),
        unresolved_architectural_choices=frozenset(),
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
        unresolved_architectural_choices=frozenset(),
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
                ),
            )
        ),
        prompt_hash="b" * 64,
        freeform_text="",
    )
    policy = build_planner_action_policy(
        session_state=state,
        unresolved_architectural_choices=frozenset(),
        selected_discovery_question_ids=(),
    )

    assert "terminal_output" not in state.resolved_slots
    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == ("terminal_output",)


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
                ),
            )
        ),
        prompt_hash="c" * 64,
        freeform_text="",
    )
    policy = build_planner_action_policy(
        session_state=state,
        unresolved_architectural_choices=frozenset(),
        selected_discovery_question_ids=(),
    )

    assert state.resolved_slots["terminal_output"].value == "docx_document"
    assert state.resolved_slots["terminal_output"].source == source
    assert "terminal_output" not in policy.allowed_ask_question_targets


def test_policy_asks_missing_core_slots_even_without_discovery_selection() -> None:
    policy = build_planner_action_policy(
        session_state=PlanningState.empty(),
        unresolved_architectural_choices=frozenset(),
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == (
        "primary_runtime_input",
        "terminal_output",
    )
    assert policy.blocked_action_reasons["commit_architecture"] == (
        "architecture cannot be derived from resolved state"
    )


def test_policy_normalizes_legacy_discovery_question_ids_to_slot_targets() -> None:
    policy = build_planner_action_policy(
        session_state=PlanningState.empty(),
        unresolved_architectural_choices=frozenset(),
        selected_discovery_question_ids=("final_output_mode",),
    )

    assert policy.allowed_ask_question_targets == (
        "terminal_output",
        "primary_runtime_input",
    )


def test_policy_allows_requirements_confirmation_after_architecture_commit() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_architecture_commit(),
        unresolved_architectural_choices=frozenset(),
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("confirm_requirements",)
    assert "commit_architecture" in policy.blocked_action_reasons
    assert "propose_plan" in policy.blocked_action_reasons


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

    policy = build_planner_action_policy(
        session_state=state,
        unresolved_architectural_choices=compute_unresolved_core_slots(state),
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("revise_architecture",)
    assert policy.allowed_ask_question_targets == ()
    assert "confirm_requirements" in policy.blocked_action_reasons
    assert "propose_plan" in policy.blocked_action_reasons


def test_policy_reopens_question_when_pinned_commit_conflicts_with_weak_slot() -> None:
    state = _state_with_architecture_commit()
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
        source="model",
        confidence="medium",
    )

    policy = build_planner_action_policy(
        session_state=state,
        unresolved_architectural_choices=compute_unresolved_core_slots(state),
        selected_discovery_question_ids=(),
        requirements_confirmed=True,
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == ("terminal_output",)
    assert "revise_architecture" in policy.blocked_action_reasons
    assert "propose_plan" in policy.blocked_action_reasons


def test_policy_allows_plan_after_architecture_and_requirements_confirmation() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_architecture_commit(),
        unresolved_architectural_choices=frozenset(),
        selected_discovery_question_ids=(),
        requirements_confirmed=True,
    )

    assert policy.allowed_action_kinds == ("propose_plan",)
    assert policy.blocked_action_reasons["confirm_requirements"] == (
        "requirements are already confirmed"
    )
    assert "propose_plan" not in policy.blocked_action_reasons
