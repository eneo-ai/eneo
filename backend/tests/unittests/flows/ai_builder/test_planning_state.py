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
from uuid import uuid4

import pytest
from pydantic import ValidationError

from intric.flows.ai_builder.planning_state import (
    ARCHITECTURE_HASH_HEX_LENGTH,
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
    StepTriple,
)

_VALID_ARCH_HASH = "a" * ARCHITECTURE_HASH_HEX_LENGTH


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

    def test_architecture_hash_is_64_hex_chars(self) -> None:
        assert ARCHITECTURE_HASH_HEX_LENGTH == 64


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
                attachment_digest_hashes=["f" * 64],
                raw_prompt_hash="b" * 64,
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
                tuples_chain=[
                    StepTriple(
                        input_type="document",
                        output_type="text",
                        output_mode="pass_through",
                    )
                ],
                chosen_patterns=["case_to_memo"],
                committed_at=datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc),
                architecture_hash=_VALID_ARCH_HASH,
            ),
            open_questions=[
                OpenQuestion(
                    question_id="output_reader",
                    slot_name="output_reader",
                    priority=1,
                    reason="Reader unspecified",
                ),
            ],
            draft_plan_id=uuid4(),
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
            builder_schema_version=BUILDER_SCHEMA_VERSION,
            phase=phase,
            evidence=EvidenceRef(),
        )
        assert state.phase == phase

    def test_unknown_phase_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlanningState(
                fcm_version=FCM_VERSION,
                planner_contract_version=PLANNER_CONTRACT_VERSION,
                builder_schema_version=BUILDER_SCHEMA_VERSION,
                phase="not_a_real_phase",  # type: ignore[arg-type]
                evidence=EvidenceRef(),
            )


class TestAssignmentRevalidation:
    """`validate_assignment=True` re-runs validators when an attribute
    is directly reassigned, closing the most obvious drift hole for a
    mutable Pydantic model.
    """

    def test_invalid_phase_assignment_raises(self) -> None:
        state = PlanningState.empty()
        with pytest.raises(ValidationError):
            state.phase = "bogus"  # type: ignore[assignment]

    def test_invalid_draft_plan_id_assignment_raises(self) -> None:
        state = PlanningState.empty()
        with pytest.raises(ValidationError):
            state.draft_plan_id = "not-a-uuid"  # type: ignore[assignment]

    def test_invalid_signal_confidence_assignment_raises(self) -> None:
        signal = PlanningSignal(
            question_id="q",
            value="v",
            confidence="high",
            source="structured_answer",
        )
        with pytest.raises(ValidationError):
            signal.confidence = "absolute"  # type: ignore[assignment]


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


class TestStepTripleValidation:
    def test_unknown_input_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StepTriple(
                input_type="spreadsheet",  # type: ignore[arg-type]
                output_type="text",
                output_mode="pass_through",
            )

    def test_unknown_output_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StepTriple(
                input_type="text",
                output_type="xml",  # type: ignore[arg-type]
                output_mode="pass_through",
            )

    def test_unknown_output_mode_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="freestyle",  # type: ignore[arg-type]
            )

    def test_extra_field_on_step_triple_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StepTriple.model_validate(
                {
                    "input_type": "text",
                    "output_type": "text",
                    "output_mode": "pass_through",
                    "role": "step_1",
                }
            )


class TestArchitectureHashContract:
    def _minimal_commit(self, arch_hash: str) -> ArchitectureCommit:
        return ArchitectureCommit(
            tuples_chain=[],
            chosen_patterns=[],
            committed_at=datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc),
            architecture_hash=arch_hash,
        )

    def test_valid_64_hex_hash_accepted(self) -> None:
        commit = self._minimal_commit(_VALID_ARCH_HASH)
        assert commit.architecture_hash == _VALID_ARCH_HASH

    def test_prefixed_hash_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._minimal_commit(f"sha256:{_VALID_ARCH_HASH}")

    def test_short_hash_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._minimal_commit("a" * 63)

    def test_uppercase_hash_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._minimal_commit("A" * ARCHITECTURE_HASH_HEX_LENGTH)

    def test_hash_fits_into_database_column_width(self) -> None:
        assert len(_VALID_ARCH_HASH) <= 64


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


class TestVersionStampContract:
    """All three first-class stamps are required and preserved verbatim.
    The stale-session policy compares them against current module
    constants at load time, but the Pydantic model does not auto-upgrade
    them.
    """

    def test_older_fcm_version_round_trips_unchanged(self) -> None:
        state = PlanningState(
            fcm_version=FCM_VERSION - 100,
            planner_contract_version=PLANNER_CONTRACT_VERSION,
            builder_schema_version=BUILDER_SCHEMA_VERSION,
            phase="awaiting_input",
            evidence=EvidenceRef(),
        )
        restored = PlanningState.model_validate_json(state.model_dump_json())
        assert restored.fcm_version == FCM_VERSION - 100

    def test_older_planner_contract_version_round_trips_unchanged(self) -> None:
        state = PlanningState(
            fcm_version=FCM_VERSION,
            planner_contract_version=PLANNER_CONTRACT_VERSION - 100,
            builder_schema_version=BUILDER_SCHEMA_VERSION,
            phase="awaiting_input",
            evidence=EvidenceRef(),
        )
        restored = PlanningState.model_validate_json(state.model_dump_json())
        assert restored.planner_contract_version == PLANNER_CONTRACT_VERSION - 100

    def test_missing_builder_schema_version_rejected(self) -> None:
        payload = {
            "fcm_version": FCM_VERSION,
            "planner_contract_version": PLANNER_CONTRACT_VERSION,
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
        }
        with pytest.raises(ValidationError):
            PlanningState.model_validate(payload)

    def test_older_builder_schema_version_round_trips_unchanged(self) -> None:
        state = PlanningState(
            fcm_version=FCM_VERSION,
            planner_contract_version=PLANNER_CONTRACT_VERSION,
            builder_schema_version=BUILDER_SCHEMA_VERSION - 100,
            phase="awaiting_input",
            evidence=EvidenceRef(),
        )
        restored = PlanningState.model_validate_json(state.model_dump_json())
        assert restored.builder_schema_version == BUILDER_SCHEMA_VERSION - 100


class TestArchitectureCommitStrictStamps:
    """The commit records `chosen_patterns` by id; it does not stamp
    module-internal version counters."""

    def test_rejects_pattern_registry_version(self) -> None:
        with pytest.raises(ValidationError):
            ArchitectureCommit.model_validate(
                {
                    "tuples_chain": [],
                    "chosen_patterns": [],
                    "committed_at": "2026-04-23T12:00:00+00:00",
                    "architecture_hash": _VALID_ARCH_HASH,
                    "pattern_registry_version": 1,
                }
            )

    def test_rejects_question_catalog_version(self) -> None:
        with pytest.raises(ValidationError):
            ArchitectureCommit.model_validate(
                {
                    "tuples_chain": [],
                    "chosen_patterns": [],
                    "committed_at": "2026-04-23T12:00:00+00:00",
                    "architecture_hash": _VALID_ARCH_HASH,
                    "question_catalog_version": 1,
                }
            )


class TestContainerMutationDiscipline:
    """Direct reassignment is revalidated; list/dict mutations are not.
    `validated_snapshot()` is the save-path defense that re-runs the
    full model validator before writing.
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

    def test_validated_snapshot_roundtrips_clean_state(self) -> None:
        state = PlanningState.empty()
        snapshot = state.validated_snapshot()
        assert snapshot == state
        assert snapshot is not state

    def test_validated_snapshot_rejects_post_mutation_drift(self) -> None:
        state = PlanningState.empty()
        state.signals.append("not a signal")  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            state.validated_snapshot()
