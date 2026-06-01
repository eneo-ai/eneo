"""Tests for the server-owned AI Builder planner action policy."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from intric.flows.ai_builder.ai_builder_action_policy import (
    PlannerActionPolicy,
    build_planner_action_policy,
    render_action_policy_prompt_block,
)
from intric.flows.ai_builder.ai_builder_slot_classifier import (
    UNKNOWN_SLOT_VALUE,
    ClassifiedSlot,
    SlotClassificationResult,
)
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    PlanningState,
    ResolvedSlot,
    StepTriple,
)
from intric.flows.ai_builder.planning_state_builder import merge_llm_resolved_slots


def _slot_value(slot_name: str) -> str:
    return {
        "primary_runtime_input": "documents",
        "terminal_output": "text",
        "document_material_scope": "flexible_document_case",
    }.get(slot_name, f"{slot_name}_value")


def _state_with_resolved_slots(*slot_names: str) -> PlanningState:
    state = PlanningState.empty()
    for slot_name in slot_names:
        state.resolved_slots[slot_name] = ResolvedSlot(
            name=slot_name,
            value=_slot_value(slot_name),
            source="structured_answer",
            evidence=[],
            confidence="high",
        )
    return state


def _state_with_architecture_commit() -> PlanningState:
    state = _state_with_resolved_slots("primary_runtime_input", "terminal_output")
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=[],
        committed_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        architecture_hash="a" * 64,
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


def test_policy_prompt_block_is_a_single_contract_surface() -> None:
    policy = PlannerActionPolicy(
        allowed_action_kinds=("ask_question", "confirm_requirements"),
        allowed_ask_question_targets=("terminal_output",),
        blocked_action_reasons={
            "commit_architecture": "unresolved architecture choices: terminal_output",
            "propose_plan": "architecture has not been committed",
        },
    )

    block = render_action_policy_prompt_block(policy)

    assert "Allowed Planner Actions This Turn" in block
    assert "`ask_question`" in block
    assert "`confirm_requirements`" in block
    assert "`terminal_output`" in block
    assert "`commit_architecture` is not allowed" in block
    assert "`propose_plan` is not allowed" not in block
