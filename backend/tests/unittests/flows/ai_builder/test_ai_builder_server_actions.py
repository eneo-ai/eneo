from __future__ import annotations

from datetime import datetime, timezone

from intric.flows.ai_builder.ai_builder_action_policy import (
    build_planner_action_policy,
)
from intric.flows.ai_builder.ai_builder_server_actions import (
    build_server_planner_output,
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


def test_server_builds_ask_question_for_allowed_target() -> None:
    state = _state(primary_runtime_input="documents", terminal_output="text")
    policy = build_planner_action_policy(
        session_state=state,
        unresolved_architectural_choices=frozenset(),
        selected_discovery_question_ids=frozenset(),
    )

    output = build_server_planner_output(
        action_policy=policy,
        session_state=state,
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
    policy = build_planner_action_policy(
        session_state=state,
        unresolved_architectural_choices=frozenset(),
        selected_discovery_question_ids=frozenset(),
    )

    output = build_server_planner_output(
        action_policy=policy,
        session_state=state,
        base_planning_state_version=8,
        ui_language="sv",
    )

    assert output is not None
    assert output.planning_state_delta.base_planning_state_version == 8
    assert output.planner_action.kind == "commit_architecture"
    assert output.planning_state_delta.architecture_commit is not None


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
    policy = build_planner_action_policy(
        session_state=state,
        unresolved_architectural_choices=frozenset(),
        selected_discovery_question_ids=frozenset(),
    )

    output = build_server_planner_output(
        action_policy=policy,
        session_state=state,
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
        "Slutresultat",
    }
    assert {decision.decision for decision in payload.key_decisions} >= {
        "Genererad DOCX utan mall",
        "Ibland ett, ibland flera dokument",
        "Inga extra fält",
    }
    assert "Docx Output Mode" not in {
        decision.topic for decision in payload.key_decisions
    }
