"""Regression corpus for the server-owned Builder turn controller."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TypeAlias

import pytest

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
from eneo.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
)
from eneo.flows.ai_builder.ai_builder_turn_controller import (
    AskCanonicalQuestion,
    CommitArchitecture,
    ConfirmRequirements,
    GenerateProposal,
    ReviseArchitecture,
    resolve_turn_control,
)
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    PlanningState,
    ResolvedSlot,
    SlotConfidence,
    SlotSource,
)
from eneo.flows.ai_builder.planning_state_builder import merge_llm_resolved_slots

ExpectedDecisionType: TypeAlias = (
    type[AskCanonicalQuestion]
    | type[CommitArchitecture]
    | type[ConfirmRequirements]
    | type[GenerateProposal]
    | type[ReviseArchitecture]
)


@dataclass(frozen=True, slots=True)
class TurnDecisionCase:
    id: str
    state: PlanningState
    expected_type: ExpectedDecisionType
    expected_slot_name: str | None = None
    selected_questions: tuple[str, ...] = ()
    requirements_confirmed: bool = False


def _slot(
    name: str,
    value: str,
    *,
    source: SlotSource = "structured_answer",
    confidence: SlotConfidence = "high",
) -> ResolvedSlot:
    return ResolvedSlot(
        name=name,
        value=value,
        source=source,
        evidence=[
            f"quote:user_message:test:{name}"
            if source == "model"
            else f"{source}:{name}"
        ],
        confidence=confidence,
        evidence_level="inferred" if source == "model" else None,
    )


def _state(**slots: str) -> PlanningState:
    state = PlanningState.empty()
    state.resolved_slots = {name: _slot(name, value) for name, value in slots.items()}
    return state


def _finalized_commit_for_state(state: PlanningState) -> ArchitectureCommit:
    draft = derive_architecture_commit_draft(state)
    assert draft is not None
    return finalize_architecture_commit(
        draft,
        now=lambda: datetime(2026, 4, 24, tzinfo=timezone.utc),
    )


def _committed_state(**slots: str) -> PlanningState:
    state = _state(**slots)
    state.architecture_commit = _finalized_commit_for_state(state)
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
                    evidence=("not sure what the final output should be",),
                ),
            )
        ),
        prompt_hash="e" * 64,
        freeform_text="not sure what the final output should be",
    )
    return state


def _model_medium_output_state() -> PlanningState:
    state = _state(primary_runtime_input="audio")
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_text",
        source="model",
        confidence="medium",
    )
    return state


def _committed_state_with_commit_grade_output_drift() -> PlanningState:
    state = _committed_state(
        primary_runtime_input="documents",
        terminal_output="structured_text",
        document_material_scope="flexible_document_case",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
    )
    state.resolved_slots["pdf_generation_mode"] = _slot(
        "pdf_generation_mode",
        "generated_pdf",
    )
    return state


def _committed_state_with_weak_output_drift() -> PlanningState:
    state = _committed_state(
        primary_runtime_input="documents",
        terminal_output="structured_text",
        document_material_scope="flexible_document_case",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
        source="model",
        confidence="medium",
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
            id="medium model output is known but still asks before commit",
            state=_model_medium_output_state(),
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
            id="commit-grade document drift asks report disposition before revision",
            state=_committed_state_with_commit_grade_output_drift(),
            expected_type=AskCanonicalQuestion,
            expected_slot_name="report_disposition",
        ),
        TurnDecisionCase(
            id="weak architecture drift reopens canonical output question",
            state=_committed_state_with_weak_output_drift(),
            expected_type=AskCanonicalQuestion,
            expected_slot_name="terminal_output",
            requirements_confirmed=True,
        ),
        TurnDecisionCase(
            id="confirmed create requirements generate proposal",
            state=committed,
            requirements_confirmed=True,
            expected_type=GenerateProposal,
        ),
    )


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case.id)
def test_turn_controller_returns_canonical_server_decisions(
    case: TurnDecisionCase,
) -> None:
    confirmed_attachment_evidence_fingerprint: str | None = None
    if case.requirements_confirmed:
        unconfirmed = resolve_turn_control(
            session_state=case.state,
            selected_discovery_question_ids=case.selected_questions,
            confirmed_attachment_evidence_fingerprint=None,
            ui_language="en",
        ).decision
        if isinstance(unconfirmed, ConfirmRequirements):
            confirmed_attachment_evidence_fingerprint = (
                unconfirmed.attachment_evidence_fingerprint
            )
    turn_control = resolve_turn_control(
        session_state=case.state,
        selected_discovery_question_ids=case.selected_questions,
        confirmed_attachment_evidence_fingerprint=(
            confirmed_attachment_evidence_fingerprint
        ),
        ui_language="en",
    )
    decision = turn_control.decision

    assert isinstance(decision, case.expected_type)

    if isinstance(decision, AskCanonicalQuestion):
        assert decision.slot_name == case.expected_slot_name
        assert decision.slot_name in KNOWN_REQUIREMENT_SLOT_NAMES
