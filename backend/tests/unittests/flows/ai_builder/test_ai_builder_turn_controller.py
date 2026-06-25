from __future__ import annotations

from datetime import datetime, timezone

from intric.flows.ai_builder.ai_builder_orchestrator import (
    OrchestrationContext,
    PlannerOutput,
    evaluate_planner_output,
)
from intric.flows.ai_builder.ai_builder_turn_controller import (
    BuilderTurnControl,
    planner_output_for_turn_decision,
    resolve_turn_control,
)
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    PlanningState,
    ResolvedSlot,
    StepTriple,
)


def _slot(name: str, value: str) -> ResolvedSlot:
    return ResolvedSlot(
        name=name,
        value=value,
        source="structured_answer",
        evidence=[],
        confidence="high",
    )


def _state(**slots: str) -> PlanningState:
    state = PlanningState.empty()
    state.resolved_slots = {name: _slot(name, value) for name, value in slots.items()}
    return state


def _turn_output(
    *,
    state: PlanningState,
    base_planning_state_version: int,
    ui_language: str | None,
    requirements_confirmed: bool = False,
) -> tuple[PlannerOutput | None, BuilderTurnControl]:
    turn_control = resolve_turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        requirements_confirmed=requirements_confirmed,
        is_edit_mode=False,
        ui_language=ui_language,
    )
    return (
        planner_output_for_turn_decision(
            decision=turn_control.decision,
            base_planning_state_version=base_planning_state_version,
        ),
        turn_control,
    )


def test_server_builds_ask_question_for_allowed_target() -> None:
    state = _state(primary_runtime_input="documents", terminal_output="text")
    output, _ = _turn_output(
        state=state,
        base_planning_state_version=7,
        ui_language="en",
    )

    assert output is not None
    assert output.planning_state_delta.base_planning_state_version == 7
    assert output.planner_action.kind == "ask_question"
    assert output.planner_action.payload.question_id == "document_material_scope"
    assert output.planner_action.payload.slot_name == "document_material_scope"
    assert "uploaded source material" in output.planner_action.payload.prompt


def test_server_builds_commit_when_no_questions_remain() -> None:
    state = _state(
        primary_runtime_input="documents",
        terminal_output="text",
        document_material_scope="flexible_document_case",
    )
    output, _ = _turn_output(
        state=state,
        base_planning_state_version=8,
        ui_language="sv",
    )

    assert output is not None
    assert output.planning_state_delta.base_planning_state_version == 8
    assert output.planner_action.kind == "commit_architecture"
    assert output.planning_state_delta.architecture_commit is not None


def test_server_commit_for_text_docx_has_resolvable_pattern() -> None:
    state = _state(
        primary_runtime_input="text",
        terminal_output="docx_document",
    )
    output, turn_control = _turn_output(
        state=state,
        base_planning_state_version=8,
        ui_language="sv",
    )

    assert output is not None
    commit = output.planning_state_delta.architecture_commit
    assert commit is not None
    assert commit.chosen_patterns == ["text_to_artifact_report"]
    assert (
        evaluate_planner_output(
            output,
            OrchestrationContext(
                current_version=8,
                session_state=state,
                action_policy=turn_control.action_policy,
                unresolved_architectural_choices=(
                    turn_control.unresolved_architectural_choices
                ),
            ),
        )
        is None
    )


def test_server_builds_confirm_requirements_checkpoint_after_commit() -> None:
    state = _state(
        primary_runtime_input="documents",
        terminal_output="docx_document",
        document_material_scope="flexible_document_case",
        docx_output_mode="generated_docx",
        runtime_metadata_fields="no_extra_metadata",
    )
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="document",
                output_type="text",
                output_mode="pass_through",
            ),
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=[],
        committed_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        architecture_hash="a" * 64,
    )
    output, _ = _turn_output(
        state=state,
        base_planning_state_version=9,
        ui_language="sv",
    )

    assert output is not None
    assert output.planning_state_delta.base_planning_state_version == 9
    assert output.planner_action.kind == "confirm_requirements"
    assert output.planning_state_delta.architecture_commit is None
    payload = output.planner_action.payload
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
        "dokument till text",
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
        structured_analysis_need="use_structured_analysis",
        runtime_metadata_fields="no_extra_metadata",
    )
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="audio",
                output_type="docx",
                output_mode="pass_through",
            ),
        ],
        chosen_patterns=["audio_to_artifact_report"],
        required_capabilities=[],
        committed_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        architecture_hash="b" * 64,
    )
    output, _ = _turn_output(
        state=state,
        base_planning_state_version=10,
        ui_language="sv",
    )

    assert output is not None
    assert output.planner_action.kind == "confirm_requirements"
    payload = output.planner_action.payload
    assert "Resultatet ska hjälpa till med: Beslut, nästa steg" in payload.summary
    assert {decision.topic for decision in payload.key_decisions} >= {
        "Syfte med bearbetningen",
        "Strukturerad analys",
    }
    assert {decision.decision for decision in payload.key_decisions} >= {
        "Beslut, nästa steg och uppföljning",
        "Ja, använd strukturerad analys där det förbättrar kvaliteten",
    }


def test_server_confirmation_names_json_to_json_architecture() -> None:
    state = _state(
        primary_runtime_input="json",
        terminal_output="structured_json",
        post_processing_goal="extract_key_information",
        structured_analysis_need="use_structured_analysis",
        runtime_metadata_fields="no_extra_metadata",
    )
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="json",
                output_type="json",
                output_mode="pass_through",
            ),
        ],
        chosen_patterns=["json_to_structured_payload"],
        required_capabilities=[],
        committed_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        architecture_hash="c" * 64,
    )
    output, _ = _turn_output(
        state=state,
        base_planning_state_version=11,
        ui_language="sv",
    )

    assert output is not None
    assert output.planner_action.kind == "confirm_requirements"
    payload = output.planner_action.payload
    decisions = {
        decision.topic: decision.decision for decision in payload.key_decisions
    }
    assert decisions["Planerad bearbetning"] == "JSON till JSON"
