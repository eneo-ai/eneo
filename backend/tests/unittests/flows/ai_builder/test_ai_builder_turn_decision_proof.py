"""Proof corpus for collapsing Builder turn control.

The production control plane still uses planner actions. This file keeps the
candidate `BuilderTurnDecision` shape test-local until the corpus proves the
old action protocol can be replaced without a second production path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TypeAlias

import pytest

from intric.flows.ai_builder.ai_builder_action_policy import (
    build_planner_action_policy,
)
from intric.flows.ai_builder.ai_builder_server_actions import (
    build_server_planner_output,
)
from intric.flows.ai_builder.ai_builder_slot_classifier import (
    UNKNOWN_SLOT_VALUE,
    ClassifiedSlot,
    SlotClassificationResult,
)
from intric.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
)
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    PlanningState,
    ResolvedSlot,
    SlotSource,
    StepTriple,
)
from intric.flows.ai_builder.planning_state_builder import merge_llm_resolved_slots


@dataclass(frozen=True, slots=True)
class AskCanonicalQuestion:
    slot_name: str


@dataclass(frozen=True, slots=True)
class CommitArchitecture:
    pass


@dataclass(frozen=True, slots=True)
class ConfirmRequirements:
    pass


@dataclass(frozen=True, slots=True)
class GenerateProposal:
    is_edit_mode: bool


BuilderTurnDecision: TypeAlias = (
    AskCanonicalQuestion | CommitArchitecture | ConfirmRequirements | GenerateProposal
)


@dataclass(frozen=True, slots=True)
class TurnDecisionCase:
    id: str
    state: PlanningState
    expected_decision: BuilderTurnDecision
    selected_questions: tuple[str, ...] = ()
    requirements_confirmed: bool = False
    is_edit_mode: bool = False


@dataclass(frozen=True, slots=True)
class TurnDecisionProof:
    decision: BuilderTurnDecision
    requires_planner_llm: bool


def _slot(
    name: str,
    value: str,
    *,
    source: SlotSource = "structured_answer",
) -> ResolvedSlot:
    return ResolvedSlot(
        name=name,
        value=value,
        source=source,
        evidence=[f"{source}:{name}"],
        confidence="high",
    )


def _state(**slots: str) -> PlanningState:
    state = PlanningState.empty()
    state.resolved_slots = {name: _slot(name, value) for name, value in slots.items()}
    return state


def _committed_state(**slots: str) -> PlanningState:
    state = _state(**slots)
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="document",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=[],
        committed_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        architecture_hash="d" * 64,
    )
    return state


def _candidate_decision(
    *,
    state: PlanningState,
    selected_questions: tuple[str, ...] = (),
    requirements_confirmed: bool = False,
    is_edit_mode: bool = False,
) -> TurnDecisionProof:
    policy = build_planner_action_policy(
        session_state=state,
        unresolved_architectural_choices=frozenset(),
        selected_discovery_question_ids=selected_questions,
        requirements_confirmed=requirements_confirmed,
    )
    server_output = build_server_planner_output(
        action_policy=policy,
        session_state=state,
        base_planning_state_version=1,
        ui_language="en",
    )
    if server_output is not None:
        action = server_output.planner_action
        if action.kind == "ask_question":
            return TurnDecisionProof(
                AskCanonicalQuestion(action.payload.slot_name),
                requires_planner_llm=False,
            )
        if action.kind == "commit_architecture":
            return TurnDecisionProof(CommitArchitecture(), requires_planner_llm=False)
        if action.kind == "confirm_requirements":
            return TurnDecisionProof(ConfirmRequirements(), requires_planner_llm=False)

    if policy.allowed_action_kinds == ("propose_plan",):
        return TurnDecisionProof(
            GenerateProposal(is_edit_mode=is_edit_mode),
            requires_planner_llm=True,
        )

    raise AssertionError(
        f"Unsupported turn decision proof case: {policy.allowed_action_kinds!r}"
    )


def _output_uncertain_state() -> PlanningState:
    state = _state(primary_runtime_input="audio", terminal_output="structured_text")
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_text",
        source="model",
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
        prompt_hash="e" * 64,
        freeform_text="not sure what the final output should be",
    )
    return state


def _cases() -> tuple[TurnDecisionCase, ...]:
    ready_for_commit = _state(
        primary_runtime_input="documents",
        terminal_output="structured_text",
        document_material_scope="flexible_document_case",
    )
    committed = _committed_state(
        primary_runtime_input="documents",
        terminal_output="structured_text",
        document_material_scope="flexible_document_case",
    )
    return (
        TurnDecisionCase(
            id="missing input type asks canonical runtime-input question",
            state=PlanningState.empty(),
            expected_decision=AskCanonicalQuestion("primary_runtime_input"),
        ),
        TurnDecisionCase(
            id="missing final output asks canonical terminal-output question",
            state=_state(primary_runtime_input="documents"),
            expected_decision=AskCanonicalQuestion("terminal_output"),
        ),
        TurnDecisionCase(
            id="explicit uncertainty clears weak output and asks again",
            state=_output_uncertain_state(),
            expected_decision=AskCanonicalQuestion("terminal_output"),
        ),
        TurnDecisionCase(
            id="indirect free-text answer is treated as resolved server state",
            state=_state(
                primary_runtime_input="text",
                terminal_output="structured_text",
                document_material_scope="flexible_document_case",
            ),
            expected_decision=CommitArchitecture(),
        ),
        TurnDecisionCase(
            id="duplicate selected questions are skipped after answer",
            state=_state(primary_runtime_input="documents"),
            selected_questions=("input_material_mode", "primary_runtime_input"),
            expected_decision=AskCanonicalQuestion("terminal_output"),
        ),
        TurnDecisionCase(
            id="off-topic message cannot bypass missing required input",
            state=PlanningState.empty(),
            selected_questions=(),
            expected_decision=AskCanonicalQuestion("primary_runtime_input"),
        ),
        TurnDecisionCase(
            id="requirements ready commits architecture without planner LLM",
            state=ready_for_commit,
            expected_decision=CommitArchitecture(),
        ),
        TurnDecisionCase(
            id="committed requirements ask for deterministic confirmation",
            state=committed,
            expected_decision=ConfirmRequirements(),
        ),
        TurnDecisionCase(
            id="confirmed create requirements generate proposal",
            state=committed,
            requirements_confirmed=True,
            expected_decision=GenerateProposal(is_edit_mode=False),
        ),
        TurnDecisionCase(
            id="confirmed edit revision request generates edit proposal",
            state=committed,
            requirements_confirmed=True,
            is_edit_mode=True,
            expected_decision=GenerateProposal(is_edit_mode=True),
        ),
    )


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case.id)
def test_current_pipeline_projects_to_candidate_turn_decision(
    case: TurnDecisionCase,
) -> None:
    proof = _candidate_decision(
        state=case.state,
        selected_questions=case.selected_questions,
        requirements_confirmed=case.requirements_confirmed,
        is_edit_mode=case.is_edit_mode,
    )

    assert proof == TurnDecisionProof(
        case.expected_decision,
        requires_planner_llm=isinstance(case.expected_decision, GenerateProposal),
    )
    if isinstance(proof.decision, AskCanonicalQuestion):
        assert proof.decision.slot_name in KNOWN_REQUIREMENT_SLOT_NAMES
