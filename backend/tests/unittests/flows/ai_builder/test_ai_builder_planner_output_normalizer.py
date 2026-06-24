from __future__ import annotations

import json
from datetime import datetime, timezone

from intric.flows.ai_builder.ai_builder_action_policy import (
    build_planner_action_policy,
)
from intric.flows.ai_builder.ai_builder_orchestrator import (
    OrchestrationContext,
    parse_planner_output,
)
from intric.flows.ai_builder.ai_builder_planner_output_normalizer import (
    normalize_planner_output,
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
        confidence="high",
    )


def _state_with_slots(**slots: str) -> PlanningState:
    state = PlanningState.empty()
    state.resolved_slots = {name: _slot(name, value) for name, value in slots.items()}
    return state


def _pinned_commit() -> ArchitectureCommit:
    return ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=["input_text", "output_mode_pass_through"],
        committed_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
        architecture_hash="a" * 64,
    )


def _commit_output(*, architecture_commit: object) -> dict[str, object]:
    return {
        "planning_state_delta": {
            "base_planning_state_version": 0,
            "signals_added": [],
            "slots_resolved": [],
            "architecture_commit": architecture_commit,
        },
        "planner_action": {
            "kind": "commit_architecture",
            "payload": {"note": ""},
        },
    }


def _ask_question_output(*, question_id: str, slot_name: str) -> dict[str, object]:
    return {
        "planning_state_delta": {
            "base_planning_state_version": 0,
            "signals_added": [],
            "slots_resolved": [],
            "architecture_commit": None,
        },
        "planner_action": {
            "kind": "ask_question",
            "payload": {
                "question_id": question_id,
                "slot_name": slot_name,
                "prompt": "More details?",
            },
        },
    }


def test_populates_missing_commit_delta_from_server_state() -> None:
    output = parse_planner_output(_commit_output(architecture_commit=None))
    context = OrchestrationContext(
        current_version=0,
        session_state=_state_with_slots(
            primary_runtime_input="text",
            terminal_output="structured_text",
        ),
    )

    normalized = normalize_planner_output(output, context)

    commit = normalized.planning_state_delta.architecture_commit
    assert commit is not None
    assert [triple.model_dump() for triple in commit.tuples_chain] == [
        {
            "input_type": "text",
            "output_type": "text",
            "output_mode": "pass_through",
        }
    ]
    assert commit.chosen_patterns == ["summarize_text"]


def test_replaces_llm_freehand_commit_delta_with_server_derived_draft() -> None:
    llm_commit = {
        "tuples_chain": [
            {
                "input_type": "text",
                "output_type": "text",
                "output_mode": "template_fill",
            }
        ],
        "chosen_patterns": ["document_to_docx_template"],
        "required_capabilities": ["input_text", "output_mode_template_fill"],
    }
    output = parse_planner_output(_commit_output(architecture_commit=llm_commit))
    context = OrchestrationContext(
        current_version=0,
        session_state=_state_with_slots(
            primary_runtime_input="text",
            terminal_output="structured_text",
        ),
    )

    normalized = normalize_planner_output(output, context)

    assert json.loads(normalized.model_dump_json())["planning_state_delta"][
        "architecture_commit"
    ] == {
        "tuples_chain": [
            {
                "input_type": "text",
                "output_type": "text",
                "output_mode": "pass_through",
            }
        ],
        "chosen_patterns": ["summarize_text"],
        "required_capabilities": ["input_text", "output_mode_pass_through"],
        "aggregation_intent": "linear",
    }


def test_preserves_commit_delta_when_architecture_is_already_pinned() -> None:
    llm_commit = {
        "tuples_chain": [
            {
                "input_type": "text",
                "output_type": "json",
                "output_mode": "pass_through",
            }
        ],
        "chosen_patterns": ["extract_structured_data"],
        "required_capabilities": ["input_text", "output_structured_json"],
    }
    output = parse_planner_output(_commit_output(architecture_commit=llm_commit))
    state = _state_with_slots(
        primary_runtime_input="text",
        terminal_output="structured_text",
    )
    state.architecture_commit = _pinned_commit()
    context = OrchestrationContext(current_version=0, session_state=state)

    normalized = normalize_planner_output(output, context)

    assert json.loads(normalized.model_dump_json())["planning_state_delta"][
        "architecture_commit"
    ] == {
        **llm_commit,
        "aggregation_intent": "linear",
    }


def test_pivots_disallowed_question_to_server_derived_commit() -> None:
    state = _state_with_slots(
        primary_runtime_input="text",
        terminal_output="structured_text",
    )
    output = parse_planner_output(
        _ask_question_output(
            question_id="document_material_scope",
            slot_name="document_material_scope",
        )
    )
    context = OrchestrationContext(
        current_version=0,
        session_state=state,
        action_policy=build_planner_action_policy(
            session_state=state,
            unresolved_architectural_choices=frozenset(),
            selected_discovery_question_ids=(),
        ),
    )

    normalized = normalize_planner_output(output, context)

    assert normalized.planner_action.kind == "commit_architecture"
    assert normalized.planning_state_delta.architecture_commit is not None
