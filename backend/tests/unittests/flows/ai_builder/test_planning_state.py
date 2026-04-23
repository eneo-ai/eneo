"""Typed PlanningState Pydantic model contract.

PlanningState is the persisted blob that lives in
`builder_sessions.planning_state_jsonb`. Business logic always goes
through the typed Pydantic model — never through partial JSONB
operators — so the JSONB schema stays coherent across turns.

This file pins the shape, version stamps, round-trip behavior, and
validation boundaries the rest of the builder depends on.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from intric.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
    PLANNING_STATE_PAYLOAD_CAP_BYTES,
    ArchitectureCommit,
    EvidenceRef,
    InvariantEvaluation,
    OpenQuestion,
    PlanningPhase,
    PlanningSignal,
    PlanningState,
    ResolvedSlot,
)


class TestModuleConstants:
    def test_builder_schema_version_is_one(self) -> None:
        assert BUILDER_SCHEMA_VERSION == 1

    def test_payload_cap_is_128_kilobytes(self) -> None:
        assert PLANNING_STATE_PAYLOAD_CAP_BYTES == 128 * 1024

    def test_fcm_version_is_positive_int(self) -> None:
        assert isinstance(FCM_VERSION, int)
        assert FCM_VERSION >= 1

    def test_planner_contract_version_is_positive_int(self) -> None:
        assert isinstance(PLANNER_CONTRACT_VERSION, int)
        assert PLANNER_CONTRACT_VERSION >= 1


class TestEmptyConstruction:
    def test_empty_factory_stamps_current_versions(self) -> None:
        state = PlanningState.empty()
        assert state.fcm_version == FCM_VERSION
        assert state.planner_contract_version == PLANNER_CONTRACT_VERSION
        assert state.builder_schema_version == BUILDER_SCHEMA_VERSION

    def test_empty_starts_in_awaiting_input(self) -> None:
        state = PlanningState.empty()
        assert state.phase == "awaiting_input"

    def test_empty_has_no_signals_slots_or_questions(self) -> None:
        state = PlanningState.empty()
        assert state.signals == []
        assert state.resolved_slots == {}
        assert state.open_questions == []
        assert state.validation == []
        assert state.architecture_commit is None
        assert state.draft_plan_id is None

    def test_empty_evidence_has_empty_lists_and_hash(self) -> None:
        state = PlanningState.empty()
        assert state.evidence.conversation_message_ids == []
        assert state.evidence.attachment_digest_hashes == []
        assert state.evidence.raw_prompt_hash == ""


class TestRoundTrip:
    @staticmethod
    def _populated_state() -> PlanningState:
        return PlanningState(
            fcm_version=FCM_VERSION,
            planner_contract_version=PLANNER_CONTRACT_VERSION,
            builder_schema_version=BUILDER_SCHEMA_VERSION,
            phase="discovering",
            evidence=EvidenceRef(
                conversation_message_ids=["msg_1", "msg_2"],
                attachment_digest_hashes=["sha256:abcd"],
                raw_prompt_hash="sha256:rawprompt",
            ),
            signals=[
                PlanningSignal(
                    question_id="document_kind",
                    value="case_documents",
                    confidence="high",
                    source="structured_answer",
                    provenance=["msg_1"],
                ),
                PlanningSignal(
                    question_id="processing_scope",
                    value="single_case",
                    confidence="medium",
                    source="freeform_text",
                    provenance=["msg_2"],
                ),
            ],
            resolved_slots={
                "document_kind": ResolvedSlot(
                    name="document_kind",
                    value="case_documents",
                    source="structured_answer",
                    evidence=["msg_1"],
                    confidence="high",
                ),
            },
            architecture_commit=ArchitectureCommit(
                tuples_chain=[["document", "structured_text", "generated_text"]],
                chosen_patterns=["case_to_memo"],
                committed_at=datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc),
                architecture_hash="sha256:arch",
            ),
            open_questions=[
                OpenQuestion(
                    question_id="output_reader",
                    slot_name="output_reader",
                    priority=1,
                    reason="Reader unspecified",
                ),
            ],
            draft_plan_id=42,
            validation=[
                InvariantEvaluation(
                    invariant_id="form_fields.reference_resolves",
                    result="pass",
                    detail="",
                ),
            ],
        )

    def test_model_dump_json_survives_round_trip(self) -> None:
        original = self._populated_state()
        dumped = original.model_dump_json()
        restored = PlanningState.model_validate_json(dumped)
        assert restored == original

    def test_model_dump_dict_survives_round_trip(self) -> None:
        original = self._populated_state()
        dumped = original.model_dump(mode="json")
        restored = PlanningState.model_validate(dumped)
        assert restored == original

    def test_empty_state_round_trip(self) -> None:
        original = PlanningState.empty()
        restored = PlanningState.model_validate_json(original.model_dump_json())
        assert restored == original


class TestPhaseValidation:
    @pytest.mark.parametrize(
        "phase",
        ["awaiting_input", "discovering", "ready_to_commit", "plan_proposed"],
    )
    def test_valid_phase_accepted(self, phase: PlanningPhase) -> None:
        state = PlanningState(
            fcm_version=FCM_VERSION,
            planner_contract_version=PLANNER_CONTRACT_VERSION,
            phase=phase,
            evidence=EvidenceRef(),
        )
        assert state.phase == phase

    def test_unknown_phase_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlanningState(
                fcm_version=FCM_VERSION,
                planner_contract_version=PLANNER_CONTRACT_VERSION,
                phase="not_a_real_phase",  # type: ignore[arg-type]
                evidence=EvidenceRef(),
            )


class TestSignalValidation:
    def test_invalid_confidence_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlanningSignal(
                question_id="document_kind",
                value="case_documents",
                confidence="absolute",  # type: ignore[arg-type]
                source="structured_answer",
            )

    def test_invalid_source_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlanningSignal(
                question_id="document_kind",
                value="case_documents",
                confidence="high",
                source="invented_source",  # type: ignore[arg-type]
            )


class TestResolvedSlotValidation:
    def test_resolved_slot_low_confidence_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ResolvedSlot(
                name="document_kind",
                value="case_documents",
                source="structured_answer",
                evidence=["msg_1"],
                confidence="low",  # type: ignore[arg-type]
            )


class TestStrictExtraRejection:
    def test_unknown_field_on_planning_state_rejected(self) -> None:
        payload = {
            "fcm_version": FCM_VERSION,
            "planner_contract_version": PLANNER_CONTRACT_VERSION,
            "builder_schema_version": BUILDER_SCHEMA_VERSION,
            "phase": "awaiting_input",
            "evidence": {
                "conversation_message_ids": [],
                "attachment_digest_hashes": [],
                "raw_prompt_hash": "",
            },
            "signals": [],
            "resolved_slots": {},
            "architecture_commit": None,
            "open_questions": [],
            "draft_plan_id": None,
            "validation": [],
            "unexpected_field": "drift",
        }
        with pytest.raises(ValidationError):
            PlanningState.model_validate(payload)

    def test_unknown_field_on_evidence_ref_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceRef.model_validate({"mystery": 1})


class TestVersionStampsArePreservedVerbatim:
    """Stale version stamps must round-trip unchanged — the stale-session
    policy compares them against current module constants at load time,
    but the Pydantic model does not auto-upgrade them.
    """

    def test_older_fcm_version_round_trips_unchanged(self) -> None:
        state = PlanningState(
            fcm_version=FCM_VERSION - 100,
            planner_contract_version=PLANNER_CONTRACT_VERSION,
            phase="awaiting_input",
            evidence=EvidenceRef(),
        )
        restored = PlanningState.model_validate_json(state.model_dump_json())
        assert restored.fcm_version == FCM_VERSION - 100

    def test_older_planner_contract_version_round_trips_unchanged(self) -> None:
        state = PlanningState(
            fcm_version=FCM_VERSION,
            planner_contract_version=PLANNER_CONTRACT_VERSION - 100,
            phase="awaiting_input",
            evidence=EvidenceRef(),
        )
        restored = PlanningState.model_validate_json(state.model_dump_json())
        assert restored.planner_contract_version == PLANNER_CONTRACT_VERSION - 100


class TestArchitectureCommitDoesNotStampRegistryVersion:
    """Round 4 refinement: ArchitectureCommit records chosen_patterns by
    id but does NOT stamp pattern_registry_version. The registry's own
    version counter is module-internal hygiene, not an artifact of the
    commit."""

    def test_architecture_commit_rejects_pattern_registry_version(self) -> None:
        with pytest.raises(ValidationError):
            ArchitectureCommit.model_validate(
                {
                    "tuples_chain": [],
                    "chosen_patterns": [],
                    "committed_at": "2026-04-23T12:00:00+00:00",
                    "architecture_hash": "sha256:x",
                    "pattern_registry_version": 1,
                }
            )


class TestMutabilityForFullSnapshotDiscipline:
    """Business logic mutates the typed model in Python, then the save
    path serializes and writes the full validated snapshot. The model
    therefore must be mutable.
    """

    def test_signals_list_can_be_appended(self) -> None:
        state = PlanningState.empty()
        state.signals.append(
            PlanningSignal(
                question_id="document_kind",
                value="case_documents",
                confidence="high",
                source="structured_answer",
            )
        )
        assert len(state.signals) == 1

    def test_phase_can_be_reassigned(self) -> None:
        state = PlanningState.empty()
        state.phase = "discovering"
        assert state.phase == "discovering"

    def test_resolved_slots_can_be_added(self) -> None:
        state = PlanningState.empty()
        state.resolved_slots["document_kind"] = ResolvedSlot(
            name="document_kind",
            value="case_documents",
            source="structured_answer",
            evidence=["msg_1"],
            confidence="high",
        )
        assert "document_kind" in state.resolved_slots
