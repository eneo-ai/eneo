"""Parse-time tests for the AI Builder orchestrator JSON contract.

The orchestrator's public contract is a single structured JSON product
per planner turn:

```json
{
  "planning_state_delta": {
    "base_planning_state_version": int,
    "signals_added": [...],
    "slots_resolved": [...],
    "architecture_commit": null | { "tuples_chain": [...], ... }
  },
  "planner_action": {
    "kind": "ask_question" | "commit_architecture"
          | "confirm_requirements",
    "payload": {...}
  }
}
```

These tests pin the shape at parse time. Monotonicity-guardrail and
architecture-commit-semantics tests live alongside in
`test_ai_builder_orchestrator_guardrails.py`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from intric.flows.ai_builder.ai_builder_orchestrator import (
    AskQuestionAction,
    AskQuestionPayload,
    CommitArchitectureAction,
    CommitArchitecturePayload,
    ConfirmRequirementsAction,
    ConfirmRequirementsPayload,
    PlannerOutput,
    PlanningStateDelta,
    parse_planner_output,
)
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommitDraft,
    PlanningSignal,
    ResolvedSlot,
    StepTriple,
)

# ---------------------------------------------------------------------------
# Fixtures — minimal valid planner outputs, one per action kind.
# ---------------------------------------------------------------------------


def _empty_delta_dict(base_version: int = 0) -> dict:
    return {
        "base_planning_state_version": base_version,
        "signals_added": [],
        "slots_resolved": [],
        "architecture_commit": None,
    }


def _ask_question_output() -> dict:
    return {
        "planning_state_delta": _empty_delta_dict(),
        "planner_action": {
            "kind": "ask_question",
            "payload": {
                "question_id": "final_output_mode",
                "slot_name": "final_output_mode",
                "prompt": "Vilket format vill du ha som slutresultat?",
            },
        },
    }


def _commit_architecture_output() -> dict:
    return {
        "planning_state_delta": {
            **_empty_delta_dict(base_version=2),
            "architecture_commit": {
                "tuples_chain": [
                    {
                        "input_type": "text",
                        "output_type": "text",
                        "output_mode": "pass_through",
                    }
                ],
                "chosen_patterns": ["text_summary_basic"],
                "required_capabilities": [],
            },
        },
        "planner_action": {
            "kind": "commit_architecture",
            "payload": {
                "note": "All required slots resolved; committing tuple chain.",
            },
        },
    }


def _confirm_requirements_output() -> dict:
    return {
        "planning_state_delta": _empty_delta_dict(base_version=3),
        "planner_action": {
            "kind": "confirm_requirements",
            "payload": {
                "summary": "Du vill sammanfatta inlämnad text till en kort rapport.",
            },
        },
    }


# ---------------------------------------------------------------------------
# Happy-path parsing per action kind.
# ---------------------------------------------------------------------------


class TestPlannerOutputParsesEveryActionKind:
    def test_ask_question_output_parses_with_structured_payload(self) -> None:
        output = parse_planner_output(_ask_question_output())

        assert isinstance(output, PlannerOutput)
        assert isinstance(output.planner_action, AskQuestionAction)
        assert output.planner_action.kind == "ask_question"
        assert isinstance(output.planner_action.payload, AskQuestionPayload)
        assert output.planner_action.payload.question_id == "final_output_mode"
        assert output.planner_action.payload.slot_name == "final_output_mode"

    def test_commit_architecture_output_parses_architecture_commit_into_state_delta(
        self,
    ) -> None:
        output = parse_planner_output(_commit_architecture_output())

        assert isinstance(output.planner_action, CommitArchitectureAction)
        assert output.planner_action.kind == "commit_architecture"
        assert isinstance(output.planner_action.payload, CommitArchitecturePayload)
        assert isinstance(
            output.planning_state_delta.architecture_commit, ArchitectureCommitDraft
        )
        assert output.planning_state_delta.architecture_commit.chosen_patterns == [
            "text_summary_basic"
        ]

    def test_confirm_requirements_output_parses_summary(self) -> None:
        output = parse_planner_output(_confirm_requirements_output())

        assert isinstance(output.planner_action, ConfirmRequirementsAction)
        assert output.planner_action.kind == "confirm_requirements"
        assert isinstance(output.planner_action.payload, ConfirmRequirementsPayload)
        assert output.planner_action.payload.summary.startswith("Du vill")


class TestPlannerOutputIngestsSignalsAndSlotsIntoDelta:
    def test_signals_added_and_slots_resolved_round_trip_typed_models(self) -> None:
        raw = {
            "planning_state_delta": {
                "base_planning_state_version": 5,
                "signals_added": [
                    {
                        "question_id": "final_output_mode",
                        "value": "text",
                        "confidence": "high",
                        "source": "structured_answer",
                        "provenance": ["turn:7"],
                    }
                ],
                "slots_resolved": [
                    {
                        "name": "final_output_mode",
                        "value": "text",
                        "source": "structured_answer",
                        "evidence": ["turn:7"],
                        "confidence": "high",
                    }
                ],
                "architecture_commit": None,
            },
            "planner_action": {
                "kind": "ask_question",
                "payload": {
                    "question_id": "document_kind",
                    "slot_name": "document_kind",
                    "prompt": "Vilken typ av dokument arbetar du med?",
                },
            },
        }

        output = parse_planner_output(raw)
        delta = output.planning_state_delta

        assert isinstance(delta, PlanningStateDelta)
        assert len(delta.signals_added) == 1
        assert isinstance(delta.signals_added[0], PlanningSignal)
        assert delta.signals_added[0].question_id == "final_output_mode"
        assert isinstance(delta.slots_resolved[0], ResolvedSlot)

    def test_tuple_chain_round_trips_as_step_triples(self) -> None:
        output = parse_planner_output(_commit_architecture_output())

        commit = output.planning_state_delta.architecture_commit
        assert commit is not None
        assert isinstance(commit.tuples_chain[0], StepTriple)
        assert commit.tuples_chain[0].input_type == "text"


# ---------------------------------------------------------------------------
# Hard-stop validation — unknown keys, unknown kinds, missing fields.
# ---------------------------------------------------------------------------


class TestPlannerOutputRejectsMalformedShapes:
    def test_unknown_top_level_key_rejected(self) -> None:
        raw = _ask_question_output()
        raw["extra_goo"] = True

        with pytest.raises(ValidationError):
            parse_planner_output(raw)

    def test_unknown_planner_action_kind_rejected(self) -> None:
        raw = _ask_question_output()
        raw["planner_action"]["kind"] = "take_over_the_flow"

        with pytest.raises(ValidationError):
            parse_planner_output(raw)

    def test_missing_base_planning_state_version_rejected(self) -> None:
        raw = _ask_question_output()
        del raw["planning_state_delta"]["base_planning_state_version"]

        with pytest.raises(ValidationError):
            parse_planner_output(raw)

    def test_wrong_payload_shape_for_kind_rejected(self) -> None:
        # ask_question requires question_id + slot_name; pass an unrelated
        # payload instead.
        raw = _ask_question_output()
        raw["planner_action"]["payload"] = {"plan_reference": "latest"}

        with pytest.raises(ValidationError):
            parse_planner_output(raw)

    def test_negative_base_version_rejected(self) -> None:
        raw = _ask_question_output()
        raw["planning_state_delta"]["base_planning_state_version"] = -1

        with pytest.raises(ValidationError):
            parse_planner_output(raw)

    def test_extra_fields_in_delta_rejected(self) -> None:
        raw = _ask_question_output()
        raw["planning_state_delta"]["ghost_field"] = "boo"

        with pytest.raises(ValidationError):
            parse_planner_output(raw)

    def test_parse_planner_output_accepts_json_string(self) -> None:
        import json

        output = parse_planner_output(json.dumps(_ask_question_output()))
        assert output.planner_action.kind == "ask_question"

    def test_architecture_commit_rejects_server_owned_fields(self) -> None:
        raw = _commit_architecture_output()
        raw["planning_state_delta"]["architecture_commit"]["architecture_hash"] = (
            "a" * 64
        )
        raw["planning_state_delta"]["architecture_commit"]["committed_at"] = (
            "2026-04-24T18:35:00Z"
        )

        with pytest.raises(ValidationError) as exc_info:
            parse_planner_output(raw)

        locs = {
            ".".join(str(part) for part in error.get("loc", ()))
            for error in exc_info.value.errors()
            if error.get("type") == "extra_forbidden"
        }
        assert any(loc.endswith("architecture_hash") for loc in locs)
        assert any(loc.endswith("committed_at") for loc in locs)
