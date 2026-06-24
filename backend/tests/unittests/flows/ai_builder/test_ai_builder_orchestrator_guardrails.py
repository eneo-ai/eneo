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

from intric.flows.ai_builder.ai_builder_action_policy import PlannerActionPolicy
from intric.flows.ai_builder.ai_builder_orchestrator import (
    OrchestrationContext,
    RejectionCode,
    RejectionReason,
    evaluate_planner_output,
    parse_planner_output,
)
from intric.flows.ai_builder.ai_builder_question_state import AskedQuestionState
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    PlanningState,
    ResolvedSlot,
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
    chosen_patterns: list[str] | None = None,
) -> dict:
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
                "chosen_patterns": (
                    chosen_patterns
                    if chosen_patterns is not None
                    else ["summarize_text"]
                ),
                "required_capabilities": required_capabilities or [],
            },
        },
        "planner_action": {
            "kind": "commit_architecture",
            "payload": {"note": ""},
        },
    }


def _confirm_requirements(*, base_version: int = 0) -> dict:
    return {
        "planning_state_delta": _empty_delta_dict(base_version=base_version),
        "planner_action": {
            "kind": "confirm_requirements",
            "payload": {
                "summary": "Resolved requirements.",
                "key_decisions": [],
                "input_description": "",
                "output_description": "",
                "assumptions": [],
                "manual_setup_notes": [],
            },
        },
    }


def _empty_session_state() -> PlanningState:
    return PlanningState.empty()


def _resolved_core_slots() -> dict[str, ResolvedSlot]:
    return {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="text",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="text",
            source="structured_answer",
            confidence="high",
        ),
    }


def _session_state_with_core_slots_resolved() -> PlanningState:
    state = PlanningState.empty()
    state.resolved_slots = _resolved_core_slots()
    return state


def _session_state_with_commit(*, step_count: int = 1) -> PlanningState:
    state = PlanningState.empty()
    state.resolved_slots = _resolved_core_slots()
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            )
            for _ in range(step_count)
        ],
        chosen_patterns=["summarize_text"],
        committed_at=datetime(2026, 4, 23, tzinfo=timezone.utc),
        architecture_hash="b" * 64,
    )
    return state


def _asked_question_state(
    *,
    asked_question_ids: frozenset[str] = frozenset(),
    question_ids_with_new_evidence: frozenset[str] = frozenset(),
    has_new_evidence: bool = False,
    question_id_counts: dict[str, int] | None = None,
) -> AskedQuestionState:
    return AskedQuestionState(
        asked_question_ids=asked_question_ids,
        question_ids_with_new_evidence=question_ids_with_new_evidence,
        has_new_evidence=has_new_evidence,
        question_id_counts=question_id_counts or {},
    )


def _ctx(
    *,
    session_state: PlanningState | None = None,
    current_version: int = 0,
    asked_question_ids: frozenset[str] = frozenset(),
    has_new_evidence: bool = False,
    question_ids_with_new_evidence: frozenset[str] = frozenset(),
    unresolved_architectural_choices: frozenset[str] = frozenset(),
    required_slot_names: frozenset[str] = frozenset(),
    action_policy: PlannerActionPolicy | None = None,
) -> OrchestrationContext:
    return OrchestrationContext(
        current_version=current_version,
        session_state=session_state or _empty_session_state(),
        asked_question_ids=asked_question_ids,
        has_new_evidence=has_new_evidence,
        question_ids_with_new_evidence=question_ids_with_new_evidence,
        unresolved_architectural_choices=unresolved_architectural_choices,
        required_slot_names=required_slot_names,
        action_policy=action_policy,
    )


# ---------------------------------------------------------------------------
# Context construction
# ---------------------------------------------------------------------------


class TestOrchestrationContextConstruction:
    def test_for_turn_derives_required_slots_and_question_evidence(self) -> None:
        state = PlanningState.empty()
        state.resolved_slots = {
            "terminal_output": ResolvedSlot(
                name="terminal_output",
                value="text",
                source="structured_answer",
                confidence="high",
            )
        }
        asked_state = _asked_question_state(
            asked_question_ids=frozenset({"final_output_mode"}),
            question_ids_with_new_evidence=frozenset({"final_output_mode"}),
            has_new_evidence=True,
        )

        context = OrchestrationContext.for_turn(
            current_version=7,
            session_state=state,
            action_policy=PlannerActionPolicy(
                allowed_action_kinds=("ask_question",),
                allowed_ask_question_targets=(
                    "document_material_scope",
                    "primary_runtime_input",
                    "terminal_output",
                ),
            ),
            asked_question_state=asked_state,
            unresolved_architectural_choices=frozenset({"primary_runtime_input"}),
        )

        assert context.current_version == 7
        assert context.session_state is state
        assert context.unresolved_architectural_choices == frozenset(
            {"primary_runtime_input"}
        )
        assert context.required_slot_names == frozenset({"document_material_scope"})
        assert context.asked_question_ids == frozenset({"final_output_mode"})
        assert context.question_ids_with_new_evidence == frozenset(
            {"final_output_mode"}
        )
        assert context.has_new_evidence is True

    def test_for_turn_defensively_excludes_resolved_slots_from_required_surface(
        self,
    ) -> None:
        state = PlanningState.empty()
        state.resolved_slots = {
            "terminal_output": ResolvedSlot(
                name="terminal_output",
                value="text",
                source="structured_answer",
                confidence="high",
            )
        }

        context = OrchestrationContext.for_turn(
            current_version=1,
            session_state=state,
            action_policy=PlannerActionPolicy(
                allowed_action_kinds=("ask_question",),
                allowed_ask_question_targets=("terminal_output",),
            ),
            asked_question_state=_asked_question_state(),
            unresolved_architectural_choices=frozenset(),
        )

        assert context.required_slot_names == frozenset()


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
# Guardrail 7 — server-owned action policy
# ---------------------------------------------------------------------------


class TestActionPolicyGuardrail:
    def test_rejects_action_not_allowed_by_server_policy(self) -> None:
        output = parse_planner_output(_commit_architecture())
        context = _ctx(
            session_state=_session_state_with_core_slots_resolved(),
            action_policy=PlannerActionPolicy(
                allowed_action_kinds=("confirm_requirements",),
                blocked_action_reasons={"commit_architecture": "already committed"},
            ),
        )

        rejection = evaluate_planner_output(output, context)

        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "action_not_allowed"
        assert "already committed" in rejection.detail

    def test_accepts_action_allowed_by_server_policy(self) -> None:
        output = parse_planner_output(_confirm_requirements())
        context = _ctx(
            session_state=_session_state_with_commit(),
            action_policy=PlannerActionPolicy(
                allowed_action_kinds=("confirm_requirements",),
            ),
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

    def test_rejects_repeat_question_after_slot_is_already_resolved(self) -> None:
        state = PlanningState.empty()
        state.resolved_slots["document_material_scope"] = ResolvedSlot(
            name="document_material_scope",
            value="flexible_document_case",
            source="heuristic",
            confidence="medium",
        )
        output = parse_planner_output(
            _ask_question(
                question_id="document_material_scope",
                slot_name="document_material_scope",
            )
        )
        context = _ctx(
            session_state=state,
            asked_question_ids=frozenset({"document_material_scope"}),
            has_new_evidence=True,
            question_ids_with_new_evidence=frozenset({"document_material_scope"}),
            required_slot_names=frozenset({"document_material_scope"}),
        )

        rejection = evaluate_planner_output(output, context)

        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "duplicate_question"
        assert "already resolved" in rejection.detail

    def test_rejects_repeat_question_when_evidence_belongs_to_different_question(
        self,
    ) -> None:
        output = parse_planner_output(_ask_question(question_id="final_output_mode"))
        context = _ctx(
            asked_question_ids=frozenset(
                {"final_output_mode", "runtime_metadata_fields"}
            ),
            has_new_evidence=True,
            question_ids_with_new_evidence=frozenset({"runtime_metadata_fields"}),
            required_slot_names=frozenset({"final_output_mode"}),
        )

        rejection = evaluate_planner_output(output, context)

        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "duplicate_question"

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

    def test_off_topic_rejection_names_allowed_targets_for_repair(self) -> None:
        output = parse_planner_output(
            _ask_question(question_id="case_type_scope", slot_name="case_type_scope")
        )
        context = _ctx(required_slot_names=frozenset({"runtime_metadata_fields"}))

        rejection = evaluate_planner_output(output, context)

        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "off_topic_question"
        assert "runtime_metadata_fields" in rejection.detail
        assert "Allowed ask_question targets" in rejection.detail

    def test_accepts_question_resolving_required_slot(self) -> None:
        output = parse_planner_output(
            _ask_question(question_id="document_kind", slot_name="document_kind")
        )
        context = _ctx(required_slot_names=frozenset({"document_kind"}))

        assert evaluate_planner_output(output, context) is None

    def test_accepts_question_resolving_architectural_choice(
        self,
    ) -> None:
        output = parse_planner_output(
            _ask_question(question_id="terminal_output", slot_name="terminal_output")
        )
        context = _ctx(
            unresolved_architectural_choices=frozenset({"terminal_output"}),
            required_slot_names=frozenset(),
        )

        assert evaluate_planner_output(output, context) is None

    def test_rejects_mismatched_question_id_and_slot_name(self) -> None:
        output = parse_planner_output(
            _ask_question(question_id="terminal_output", slot_name="document_kind")
        )
        context = _ctx(
            unresolved_architectural_choices=frozenset({"terminal_output"}),
            required_slot_names=frozenset({"document_kind"}),
        )

        rejection = evaluate_planner_output(output, context)

        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "off_topic_question"


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

    def test_rejects_commit_action_missing_architecture_commit_delta(self) -> None:
        payload = _commit_architecture()
        payload["planning_state_delta"]["architecture_commit"] = None
        output = parse_planner_output(payload)
        context = _ctx()

        rejection = evaluate_planner_output(output, context)

        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "architecture_commit_missing_delta"
        assert "architecture_commit delta" in rejection.detail

    def test_accepts_commit_with_legal_tuple_and_no_unresolved_choices(self) -> None:
        output = parse_planner_output(_commit_architecture())
        context = _ctx(session_state=_session_state_with_core_slots_resolved())

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
        context = _ctx(session_state=_session_state_with_core_slots_resolved())

        assert evaluate_planner_output(output, context) is None

    def test_accepts_commit_with_empty_required_capabilities(self) -> None:
        output = parse_planner_output(_commit_architecture(required_capabilities=[]))
        context = _ctx(session_state=_session_state_with_core_slots_resolved())

        assert evaluate_planner_output(output, context) is None


class TestCommitArchitectureUnresolvablePatternGuardrail:
    """Mirrors the capability-unresolvable guardrail for `chosen_patterns`.

    Without this check an unknown pattern id passes the orchestrator
    and is then silently dropped downstream by the capability-projection
    module's drift-tolerant filter. Validating here fails loud at the
    earliest boundary so the planner retry loop can react.
    """

    def test_rejects_commit_with_pattern_not_in_pattern_registry(self) -> None:
        output = parse_planner_output(
            _commit_architecture(chosen_patterns=["definitely_not_a_real_pattern"])
        )
        context = _ctx()

        rejection = evaluate_planner_output(output, context)

        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "architecture_commit_unresolvable_pattern"
        assert "definitely_not_a_real_pattern" in rejection.detail

    def test_accepts_commit_with_patterns_present_in_pattern_registry(self) -> None:
        output = parse_planner_output(
            _commit_architecture(chosen_patterns=["summarize_text"])
        )
        context = _ctx(session_state=_session_state_with_core_slots_resolved())

        assert evaluate_planner_output(output, context) is None

    def test_rejects_commit_with_empty_chosen_patterns(self) -> None:
        """Empty chosen_patterns evades pattern-specific slot enforcement.

        Without this guard, a commit that declares no patterns skips the
        pattern-required-slot check that otherwise catches a planner
        committing before required slots resolve. The committed delta also
        leaves the capability-projection module with nothing to narrow to
        post-commit.
        """
        output = parse_planner_output(_commit_architecture(chosen_patterns=[]))
        context = _ctx(session_state=_session_state_with_core_slots_resolved())

        rejection = evaluate_planner_output(output, context)

        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "architecture_commit_unresolvable_pattern"

    def test_rejects_commit_when_pattern_required_slot_is_unresolved(self) -> None:
        """Pattern-specific slot enforcement.

        `summarize_text` requires `primary_runtime_input` and
        `terminal_output` — a commit against an otherwise-empty session
        should be rejected with the premature-choices code so the planner
        retry loop knows which slot to resolve next, not dropped by the
        downstream bridge after an expensive LLM turn.
        """
        output = parse_planner_output(
            _commit_architecture(chosen_patterns=["summarize_text"])
        )
        context = _ctx()

        rejection = evaluate_planner_output(output, context)

        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "architecture_commit_premature_unresolved_choices"
        assert "primary_runtime_input" in rejection.detail
        assert "terminal_output" in rejection.detail


# ---------------------------------------------------------------------------
# Commit-preservation: a pinned commit is the canonical contract and
# cannot be re-emitted, replaced, or drifted by any later turn.
# ---------------------------------------------------------------------------


class TestCommitPreservationGuardrail:
    """Once a commit lands, every later turn must either preserve it
    byte-identically in its delta or omit the ``architecture_commit``
    field entirely. A second ``commit_architecture`` action rejects even
    when it replays the pinned body, because the atomic dispatch path
    would create a second audit turn and signal planner confusion.
    """

    def test_rejects_second_commit_architecture_when_session_has_pinned_commit(
        self,
    ) -> None:
        output = parse_planner_output(
            _commit_architecture(chosen_patterns=["summarize_text"])
        )
        context = _ctx(session_state=_session_state_with_commit(step_count=1))

        rejection = evaluate_planner_output(output, context)

        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "architecture_commit_drift_from_pinned"

    def test_rejects_ask_question_when_delta_carries_drifted_architecture_commit(
        self,
    ) -> None:
        drifted_raw = _ask_question(
            question_id="final_output_mode", slot_name="final_output_mode"
        )
        drifted_raw["planning_state_delta"]["architecture_commit"] = {
            "tuples_chain": [
                {
                    "input_type": "text",
                    "output_type": "text",
                    "output_mode": "pass_through",
                },
                {
                    "input_type": "text",
                    "output_type": "text",
                    "output_mode": "pass_through",
                },
            ],
            "chosen_patterns": ["summarize_text"],
            "required_capabilities": [],
        }
        output = parse_planner_output(drifted_raw)
        context = _ctx(
            session_state=_session_state_with_commit(step_count=1),
            required_slot_names=frozenset({"final_output_mode"}),
        )

        rejection = evaluate_planner_output(output, context)

        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "architecture_commit_drift_from_pinned"

    def test_accepts_ask_question_without_delta_commit_when_session_is_pinned(
        self,
    ) -> None:
        output = parse_planner_output(
            _ask_question(
                question_id="final_output_mode", slot_name="final_output_mode"
            )
        )
        context = _ctx(
            session_state=_session_state_with_commit(step_count=1),
            required_slot_names=frozenset({"final_output_mode"}),
        )

        assert evaluate_planner_output(output, context) is None


# ---------------------------------------------------------------------------
# Negative-polarity patterns are anti-patterns — they must never be
# committed even though they live in PATTERN_REGISTRY alongside positive
# archetypes for knowledge-pack teaching purposes.
# ---------------------------------------------------------------------------


class TestNegativePolarityPatternGuardrail:
    def test_rejects_commit_with_negative_polarity_pattern(self) -> None:
        output = parse_planner_output(
            _commit_architecture(chosen_patterns=["template_fill_non_docx"])
        )
        context = _ctx(session_state=_session_state_with_core_slots_resolved())

        rejection = evaluate_planner_output(output, context)

        assert isinstance(rejection, RejectionReason)
        assert rejection.code == "architecture_commit_unresolvable_pattern"
        assert "negative" in rejection.detail
        assert "template_fill_non_docx" in rejection.detail

    def test_accepts_commit_with_only_positive_polarity_patterns(self) -> None:
        output = parse_planner_output(
            _commit_architecture(chosen_patterns=["summarize_text"])
        )
        context = _ctx(session_state=_session_state_with_core_slots_resolved())

        assert evaluate_planner_output(output, context) is None


# ---------------------------------------------------------------------------
# RejectionCode is the single source of truth for rejection branches.
# If a new guardrail adds a code, the Literal must grow with it.
# ---------------------------------------------------------------------------


class TestRejectionCodeExhaustiveness:
    _expected_codes = frozenset(
        {
            "version_mismatch",
            "action_not_allowed",
            "duplicate_question",
            "off_topic_question",
            "architecture_commit_premature_unresolved_choices",
            "architecture_commit_missing_delta",
            "architecture_commit_illegal_tuple",
            "architecture_commit_unresolvable_capability",
            "architecture_commit_unresolvable_pattern",
            "architecture_commit_drift_from_pinned",
        }
    )

    def test_rejection_code_literal_matches_expected_set(self) -> None:
        literal_args = frozenset(typing.get_args(RejectionCode))
        assert literal_args == self._expected_codes
