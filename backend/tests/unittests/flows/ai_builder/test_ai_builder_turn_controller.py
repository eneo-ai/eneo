from __future__ import annotations

from datetime import datetime, timezone
from typing import get_args

from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_turn_controller import (
    AskCanonicalQuestion,
    CommitArchitecture,
    ConfirmRequirements,
    ReviseArchitecture,
    resolve_turn_control,
)
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    PlanningState,
    ResolvedSlot,
    SlotConfidence,
    SlotSource,
    StepTriple,
)


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
        evidence=[f"{source}:{name}"],
        confidence=confidence,
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


def _decision(
    *,
    state: PlanningState,
    ui_language: str | None,
    requirements_confirmed: bool = False,
) -> object:
    return resolve_turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        requirements_confirmed=requirements_confirmed,
        ui_language=ui_language,
    ).decision


def test_server_builds_ask_question_for_allowed_target() -> None:
    state = _state(primary_runtime_input="documents", terminal_output="text")
    decision = _decision(state=state, ui_language="en")

    assert isinstance(decision, AskCanonicalQuestion)
    assert decision.slot_name == "document_material_scope"
    assert "uploaded source material" in decision.prompt


def test_server_builds_commit_when_no_questions_remain() -> None:
    state = _state(
        primary_runtime_input="documents",
        terminal_output="text",
        document_material_scope="flexible_document_case",
    )
    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, CommitArchitecture)
    assert decision.architecture_commit.tuples_chain


def test_server_commit_for_text_docx_has_resolvable_pattern() -> None:
    state = _state(
        primary_runtime_input="text",
        terminal_output="docx_document",
    )
    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, CommitArchitecture)
    assert decision.architecture_commit.chosen_patterns == ["text_to_artifact_report"]


def test_server_builds_confirm_requirements_checkpoint_after_commit() -> None:
    state = _state(
        primary_runtime_input="documents",
        terminal_output="docx_document",
        document_material_scope="flexible_document_case",
        docx_output_mode="generated_docx",
        runtime_metadata_fields="no_extra_metadata",
    )
    state.architecture_commit = _finalized_commit_for_state(state)
    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, ConfirmRequirements)
    payload = decision.payload
    assert (
        payload.summary
        == "Flödet ska ta emot Dokument vid körning och leverera DOCX-dokument."
    )
    assert payload.input_description == "Primär indata vid körning: Dokument."
    assert payload.output_description == "Huvudsakligt slutresultat: DOCX-dokument."
    assert {decision.topic for decision in payload.key_decisions} >= {
        "DOCX-resultat",
        "Indata vid körning",
        "Planerad bearbetning",
        "Slutresultat",
    }
    assert {decision.decision for decision in payload.key_decisions} >= {
        "Genererad DOCX utan mall",
        "Ibland ett, ibland flera dokument",
        "Inga extra fält",
        "Skapa DOCX",
    }
    assert "Docx Output Mode" not in {
        decision.topic for decision in payload.key_decisions
    }


def test_server_confirmation_summarizes_processing_goal() -> None:
    state = _state(
        primary_runtime_input="audio",
        terminal_output="docx_document",
        docx_output_mode="generated_docx",
        post_processing_goal="action_followup",
        runtime_metadata_fields="no_extra_metadata",
    )
    state.architecture_commit = _finalized_commit_for_state(state)
    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, ConfirmRequirements)
    payload = decision.payload
    assert "Resultatet ska hjälpa till med: Beslut, nästa steg" in payload.summary
    assert {decision.topic for decision in payload.key_decisions} >= {
        "Syfte med bearbetningen",
    }
    assert {decision.decision for decision in payload.key_decisions} >= {
        "Beslut, nästa steg och uppföljning",
    }


def test_server_confirmation_names_json_to_json_architecture() -> None:
    state = _state(
        primary_runtime_input="json",
        terminal_output="structured_json",
        post_processing_goal="extract_key_information",
        runtime_metadata_fields="no_extra_metadata",
    )
    state.architecture_commit = _finalized_commit_for_state(state)
    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, ConfirmRequirements)
    decisions = {
        decision.topic: decision.decision for decision in decision.payload.key_decisions
    }
    assert decisions["Planerad bearbetning"] == "JSON till JSON"


def test_server_revises_architecture_for_commit_grade_terminal_output_change() -> None:
    state = _state(primary_runtime_input="text", terminal_output="pdf_document")
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            ),
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=[],
        committed_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        architecture_hash="f" * 64,
    )

    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, ReviseArchitecture)
    assert decision.architecture_commit.tuples_chain[0].output_type == "pdf"
    assert decision.architecture_commit.chosen_patterns == ["text_to_artifact_report"]


def test_server_reasks_when_pinned_commit_conflicts_with_weak_output_slot() -> None:
    state = _state(primary_runtime_input="text")
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
        source="model",
        confidence="medium",
    )
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            ),
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=[],
        committed_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        architecture_hash="a" * 64,
    )

    decision = _decision(
        state=state,
        ui_language="sv",
        requirements_confirmed=True,
    )

    assert isinstance(decision, AskCanonicalQuestion)
    assert decision.slot_name == "terminal_output"


def test_server_confirmation_separates_decisions_from_assumptions() -> None:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "audio"),
        "terminal_output": _slot(
            "terminal_output",
            "structured_text",
            source="model",
            confidence="medium",
        ),
        "runtime_metadata_fields": _slot(
            "runtime_metadata_fields",
            "no_extra_metadata",
            source="policy_default",
            confidence="medium",
        ),
        "post_processing_goal": _slot(
            "post_processing_goal",
            "summarize_or_overview",
            source="heuristic",
        ),
        "docx_output_mode": _slot(
            "docx_output_mode",
            "generated_docx",
            source="flow_default",
        ),
    }
    state.architecture_commit = _finalized_commit_for_state(state)

    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, ConfirmRequirements)
    decisions = {
        decision.topic: decision.decision for decision in decision.payload.key_decisions
    }
    assert "Indata vid körning" in decisions
    assert "DOCX-resultat" in decisions
    assert "Planerad bearbetning" in decisions
    assert "Slutresultat" not in decisions
    assert "Metadata vid körning" not in decisions
    assert "Syfte med bearbetningen" not in decisions
    assert "Slutresultat: Strukturerat textresultat" in decision.payload.assumptions
    assert "Metadata vid körning: Inga extra fält" in decision.payload.assumptions
    assert "Syfte med bearbetningen: Sammanfatta eller ge överblick" in (
        decision.payload.assumptions
    )


def test_slot_sources_land_in_exactly_one_summary_bucket() -> None:
    source_to_slot = {
        "structured_answer": ("primary_runtime_input", "audio"),
        "requirements_summary": ("terminal_output", "structured_text"),
        "flow_default": ("docx_output_mode", "generated_docx"),
        "policy_default": ("runtime_metadata_fields", "no_extra_metadata"),
        "heuristic": ("post_processing_goal", "summarize_or_overview"),
        "model": ("document_material_scope", "single_uploaded_document"),
    }
    state = PlanningState.empty()
    state.resolved_slots = {
        slot_name: _slot(slot_name, value, source=source)
        for source, (slot_name, value) in source_to_slot.items()
    }
    state.architecture_commit = _finalized_commit_for_state(state)

    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, ConfirmRequirements)
    assert set(source_to_slot) == set(get_args(SlotSource))
    decision_topics = {
        key_decision.topic for key_decision in decision.payload.key_decisions
    } - {"Planerad bearbetning"}
    assumption_topics = {
        assumption.split(":", 1)[0]
        for assumption in decision.payload.assumptions
        if ":" in assumption
    }
    assert decision_topics == {
        "Indata vid körning",
        "Slutresultat",
        "DOCX-resultat",
    }
    assert assumption_topics == {
        "Dokumentunderlag",
        "Metadata vid körning",
        "Syfte med bearbetningen",
    }
    assert decision_topics.isdisjoint(assumption_topics)
