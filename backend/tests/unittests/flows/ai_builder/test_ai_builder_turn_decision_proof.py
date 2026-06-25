"""Regression corpus for the server-owned Builder turn controller."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TypeAlias

import pytest

from intric.flows.ai_builder.ai_builder_action_policy import (
    compute_unresolved_core_slots,
)
from intric.flows.ai_builder.ai_builder_slot_classifier import (
    UNKNOWN_SLOT_VALUE,
    ClassifiedSlot,
    SlotClassificationResult,
)
from intric.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
)
from intric.flows.ai_builder.ai_builder_turn_controller import (
    AskCanonicalQuestion,
    CommitArchitecture,
    ConfirmRequirements,
    GenerateProposal,
    resolve_turn_control,
)
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    PlanningState,
    ResolvedSlot,
    SlotSource,
    StepTriple,
)
from intric.flows.ai_builder.planning_state_builder import merge_llm_resolved_slots

ExpectedDecisionType: TypeAlias = (
    type[AskCanonicalQuestion]
    | type[CommitArchitecture]
    | type[ConfirmRequirements]
    | type[GenerateProposal]
)


@dataclass(frozen=True, slots=True)
class TurnDecisionCase:
    id: str
    state: PlanningState
    expected_type: ExpectedDecisionType
    expected_slot_name: str | None = None
    selected_questions: tuple[str, ...] = ()
    requirements_confirmed: bool = False
    is_edit_mode: bool = False


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
            expected_type=AskCanonicalQuestion,
            expected_slot_name="primary_runtime_input",
        ),
        TurnDecisionCase(
            id="missing final output asks canonical terminal-output question",
            state=_state(primary_runtime_input="documents"),
            expected_type=AskCanonicalQuestion,
            expected_slot_name="terminal_output",
        ),
        TurnDecisionCase(
            id="explicit uncertainty clears weak output and asks again",
            state=_output_uncertain_state(),
            expected_type=AskCanonicalQuestion,
            expected_slot_name="terminal_output",
        ),
        TurnDecisionCase(
            id="indirect free-text answer is treated as resolved server state",
            state=_state(
                primary_runtime_input="text",
                terminal_output="structured_text",
                document_material_scope="flexible_document_case",
            ),
            expected_type=CommitArchitecture,
        ),
        TurnDecisionCase(
            id="duplicate selected questions are skipped after answer",
            state=_state(primary_runtime_input="documents"),
            selected_questions=("input_material_mode", "primary_runtime_input"),
            expected_type=AskCanonicalQuestion,
            expected_slot_name="terminal_output",
        ),
        TurnDecisionCase(
            id="off-topic message cannot bypass missing required input",
            state=PlanningState.empty(),
            expected_type=AskCanonicalQuestion,
            expected_slot_name="primary_runtime_input",
        ),
        TurnDecisionCase(
            id="requirements ready commits architecture without planner LLM",
            state=ready_for_commit,
            expected_type=CommitArchitecture,
        ),
        TurnDecisionCase(
            id="committed requirements ask for deterministic confirmation",
            state=committed,
            expected_type=ConfirmRequirements,
        ),
        TurnDecisionCase(
            id="confirmed create requirements generate proposal",
            state=committed,
            requirements_confirmed=True,
            expected_type=GenerateProposal,
        ),
        TurnDecisionCase(
            id="confirmed edit revision request generates edit proposal",
            state=committed,
            requirements_confirmed=True,
            is_edit_mode=True,
            expected_type=GenerateProposal,
        ),
    )


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case.id)
def test_turn_controller_returns_canonical_server_decisions(
    case: TurnDecisionCase,
) -> None:
    turn_control = resolve_turn_control(
        session_state=case.state,
        selected_discovery_question_ids=case.selected_questions,
        requirements_confirmed=case.requirements_confirmed,
        is_edit_mode=case.is_edit_mode,
        ui_language="en",
    )
    decision = turn_control.decision

    assert isinstance(decision, case.expected_type)
    assert (
        turn_control.unresolved_architectural_choices
        == compute_unresolved_core_slots(case.state)
    )

    if isinstance(decision, AskCanonicalQuestion):
        assert decision.slot_name == case.expected_slot_name
        assert decision.slot_name in KNOWN_REQUIREMENT_SLOT_NAMES
    if isinstance(decision, GenerateProposal):
        assert decision.is_edit_mode is case.is_edit_mode
