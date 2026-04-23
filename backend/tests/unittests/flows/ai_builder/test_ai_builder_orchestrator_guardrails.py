"""Tests for AI Builder orchestrator monotonicity guardrails.

The orchestrator rejects planner output when any of the monotonicity
guardrails fires. Rejection produces a structured `RejectionReason`
the planner retry loop can react to; acceptance returns ``None``.

Each guardrail has a firing test and a silence test so regressions land
loudly: a loosened guardrail stops catching bad planner output, a
tightened guardrail starts rejecting legal output.
"""

from __future__ import annotations

import typing
from datetime import datetime, timezone

from intric.flows.ai_builder.ai_builder_orchestrator import (
    OrchestrationContext,
    RejectionCode,
    RejectionReason,
    evaluate_planner_output,
    parse_planner_output,
)
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    PlanningState,
    StepTriple,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _empty_delta_dict(base_version: int = 0) -> dict:
    return {
        "base_planning_state_version": base_version,
        "signals_added": [],
        "slots_resolved": [],
        "architecture_commit": None,
        "draft_plan": None,
    }


def _ask_question(
    *,
    question_id: str = "final_output_mode",
    slot_name: str = "final_output_mode",
    base_version: int = 0,
) -> dict:
    return {
        "planning_state_delta": _empty_delta_dict(base_version=base_version),
        "planner_action": {
            "kind": "ask_question",
            "payload": {
                "question_id": question_id,
                "slot_name": slot_name,
                "prompt": "dummy",
            },
        },
    }


def _commit_architecture(
    *,
    base_version: int = 0,
    tuples_chain: list[dict] | None = None,
    required_capabilities: list[str] | None = None,
) -> dict:
    hash_hex = "a" * 64
    chain = (
        tuples_chain
        if tuples_chain is not None
        else [
            {
                "input_type": "text",
                "output_type": "text",
                "output_mode": "pass_through",
            }
        ]
    )
    return {
        "planning_state_delta": {
            **_empty_delta_dict(base_version=base_version),
            "architecture_commit": {
                "tuples_chain": chain,
                "chosen_patterns": ["summarize_text"],
                "required_capabilities": required_capabilities or [],
                "committed_at": datetime(2026, 4, 23, tzinfo=timezone.utc).isoformat(),
                "architecture_hash": hash_hex,
            },
        },
        "planner_action": {
            "kind": "commit_architecture",
            "payload": {"note": ""},
        },
    }


def _propose_plan(*, base_version: int = 0) -> dict:
    return {
        "planning_state_delta": {
            **_empty_delta_dict(base_version=base_version),
            "draft_plan": {"steps": []},
        },
        "planner_action": {
            "kind": "propose_plan",
            "payload": {"plan_reference": "latest"},
        },
    }


def _empty_session_state() -> PlanningState:
    return PlanningState.empty()


def _session_state_with_commit() -> PlanningState:
    state = PlanningState.empty()
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=["summarize_text"],
        committed_at=datetime(2026, 4, 23, tzinfo=timezone.utc),
        architecture_hash="b" * 64,
    )
    return state


def _ctx(
    *,
    session_state: PlanningState | None = None,
    current_version: int = 0,
    asked_question_ids: frozenset[str] = frozenset(),
    has_new_evidence: bool = False,
    unresolved_architectural_choices: frozenset[str] = frozenset(),
    required_slot_names: frozenset[str] = frozenset(),
) -> OrchestrationContext:
    return OrchestrationContext(
        current_version=current_version,
        session_state=session_state or _empty_session_state(),
        asked_question_ids=asked_question_ids,
        has_new_evidence=has_new_evidence,
        unresolved_architectural_choices=unresolved_architectural_choices,
        required_slot_names=required_slot_names,
    )


# ---------------------------------------------------------------------------
# Guardrail 6 — optimistic concurrency (version mismatch)
# ---------------------------------------------------------------------------


class TestVersionMismatchGuardrail:
    def test_rejects_stale_delta(self) -> None:
        output = parse_planner_output(_ask_question(base_version=0))
        context = _ctx(
            current_version=3, required_slot_names=frozenset({"final_output_mode"})
        )

        rejection = evaluate_planner_output(output, context)

        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "version_mismatch"
        assert rejection.current_version == 3

    def test_accepts_matching_version(self) -> None:
        output = parse_planner_output(_ask_question(base_version=3))
        context = _ctx(
            current_version=3, required_slot_names=frozenset({"final_output_mode"})
        )

        assert evaluate_planner_output(output, context) is None


# ---------------------------------------------------------------------------
# Guardrail 1 — duplicate ask_question with no new evidence
# ---------------------------------------------------------------------------


class TestDuplicateQuestionGuardrail:
    def test_rejects_repeat_question_without_new_evidence(self) -> None:
        output = parse_planner_output(_ask_question(question_id="final_output_mode"))
        context = _ctx(
            asked_question_ids=frozenset({"final_output_mode"}),
            has_new_evidence=False,
            required_slot_names=frozenset({"final_output_mode"}),
        )

        rejection = evaluate_planner_output(output, context)

        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "duplicate_question"

    def test_accepts_repeat_question_when_new_evidence_arrived(self) -> None:
        output = parse_planner_output(_ask_question(question_id="final_output_mode"))
        context = _ctx(
            asked_question_ids=frozenset({"final_output_mode"}),
            has_new_evidence=True,
            required_slot_names=frozenset({"final_output_mode"}),
        )

        assert evaluate_planner_output(output, context) is None

    def test_accepts_new_question_id(self) -> None:
        output = parse_planner_output(
            _ask_question(question_id="document_kind", slot_name="document_kind")
        )
        context = _ctx(
            asked_question_ids=frozenset({"final_output_mode"}),
            has_new_evidence=False,
            required_slot_names=frozenset({"document_kind"}),
        )

        assert evaluate_planner_output(output, context) is None


# ---------------------------------------------------------------------------
# Guardrail 2 — off-topic ask_question
# ---------------------------------------------------------------------------


class TestOffTopicQuestionGuardrail:
    def test_rejects_question_that_resolves_nothing(self) -> None:
        output = parse_planner_output(_ask_question(slot_name="favourite_colour"))
        context = _ctx(
            required_slot_names=frozenset({"final_output_mode", "document_kind"}),
            unresolved_architectural_choices=frozenset({"terminal_output"}),
        )

        rejection = evaluate_planner_output(output, context)

        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "off_topic_question"

    def test_accepts_question_resolving_required_slot(self) -> None:
        output = parse_planner_output(_ask_question(slot_name="document_kind"))
        context = _ctx(required_slot_names=frozenset({"document_kind"}))

        assert evaluate_planner_output(output, context) is None

    def test_accepts_question_resolving_architectural_choice_by_question_id(
        self,
    ) -> None:
        output = parse_planner_output(
            _ask_question(question_id="terminal_output", slot_name="__irrelevant__")
        )
        context = _ctx(
            unresolved_architectural_choices=frozenset({"terminal_output"}),
            required_slot_names=frozenset(),
        )

        assert evaluate_planner_output(output, context) is None


# ---------------------------------------------------------------------------
# Guardrail 3 — premature commit_architecture
# ---------------------------------------------------------------------------


class TestCommitArchitecturePrematureGuardrail:
    def test_rejects_commit_with_unresolved_architectural_choices(self) -> None:
        output = parse_planner_output(_commit_architecture())
        context = _ctx(
            unresolved_architectural_choices=frozenset({"terminal_output"}),
        )

        rejection = evaluate_planner_output(output, context)

        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "architecture_commit_premature_unresolved_choices"

    def test_rejects_commit_with_illegal_tuple(self) -> None:
        # TEMPLATE_FILL is legal ONLY for DOCX output per FCM; text output is illegal.
        output = parse_planner_output(
            _commit_architecture(
                tuples_chain=[
                    {
                        "input_type": "text",
                        "output_type": "text",
                        "output_mode": "template_fill",
                    }
                ]
            )
        )
        context = _ctx()

        rejection = evaluate_planner_output(output, context)

        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "architecture_commit_illegal_tuple"

    def test_accepts_commit_with_legal_tuple_and_no_unresolved_choices(self) -> None:
        output = parse_planner_output(_commit_architecture())
        context = _ctx()

        assert evaluate_planner_output(output, context) is None


# ---------------------------------------------------------------------------
# Guardrail 4 — propose_plan without ArchitectureCommit
# ---------------------------------------------------------------------------


class TestProposePlanRequiresArchitectureCommitGuardrail:
    def test_rejects_propose_plan_when_session_has_no_architecture_commit(
        self,
    ) -> None:
        output = parse_planner_output(_propose_plan())
        context = _ctx(session_state=_empty_session_state())

        rejection = evaluate_planner_output(output, context)

        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "propose_plan_without_architecture_commit"

    def test_accepts_propose_plan_when_session_has_architecture_commit(self) -> None:
        output = parse_planner_output(_propose_plan())
        context = _ctx(session_state=_session_state_with_commit())

        assert evaluate_planner_output(output, context) is None


# ---------------------------------------------------------------------------
# Structural rejection contract — machine-readable code + optional detail
# ---------------------------------------------------------------------------


class TestRejectionReasonSurface:
    def test_rejection_serialises_with_code_and_detail(self) -> None:
        output = parse_planner_output(_ask_question(base_version=0))
        context = _ctx(current_version=9)

        rejection = evaluate_planner_output(output, context)
        assert isinstance(rejection, RejectionReason)

        dumped = rejection.model_dump()
        assert dumped["code"] == "version_mismatch"
        assert "9" in dumped["detail"]
        assert dumped["current_version"] == 9

    def test_first_failing_guardrail_wins(self) -> None:
        # Version mismatch + duplicate question + off-topic — version check fires
        # first because it invalidates everything downstream.
        output = parse_planner_output(_ask_question(base_version=0, question_id="x"))
        context = _ctx(
            current_version=5,
            asked_question_ids=frozenset({"x"}),
            has_new_evidence=False,
            required_slot_names=frozenset({"irrelevant"}),
        )

        rejection = evaluate_planner_output(output, context)
        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "version_mismatch"


# ---------------------------------------------------------------------------
# Guardrail 3 (capability branch) — unresolvable required_capabilities
# ---------------------------------------------------------------------------


class TestCommitArchitectureUnresolvableCapabilityGuardrail:
    def test_rejects_commit_with_capability_not_in_fcm_registry(self) -> None:
        output = parse_planner_output(
            _commit_architecture(required_capabilities=["not_a_real_capability"])
        )
        context = _ctx()

        rejection = evaluate_planner_output(output, context)

        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "architecture_commit_unresolvable_capability"
        assert "not_a_real_capability" in rejection.detail

    def test_accepts_commit_with_capabilities_present_in_fcm_registry(self) -> None:
        output = parse_planner_output(
            _commit_architecture(
                required_capabilities=["input_text", "output_mode_pass_through"]
            )
        )
        context = _ctx()

        assert evaluate_planner_output(output, context) is None

    def test_accepts_commit_with_empty_required_capabilities(self) -> None:
        output = parse_planner_output(_commit_architecture(required_capabilities=[]))
        context = _ctx()

        assert evaluate_planner_output(output, context) is None


# ---------------------------------------------------------------------------
# RejectionCode is the single source of truth for rejection branches.
# If a new guardrail adds a code, the Literal must grow with it.
# ---------------------------------------------------------------------------


class TestRejectionCodeExhaustiveness:
    _expected_codes = frozenset(
        {
            "version_mismatch",
            "duplicate_question",
            "off_topic_question",
            "architecture_commit_premature_unresolved_choices",
            "architecture_commit_illegal_tuple",
            "architecture_commit_unresolvable_capability",
            "propose_plan_without_architecture_commit",
        }
    )

    def test_rejection_code_literal_matches_expected_set(self) -> None:
        literal_args = frozenset(typing.get_args(RejectionCode))
        assert literal_args == self._expected_codes
