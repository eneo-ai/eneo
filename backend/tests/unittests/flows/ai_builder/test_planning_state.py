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

from eneo.flows.ai_builder.planning_state import (
    ARCHITECTURE_HASH_HEX_LENGTH,
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
    PLANNING_STATE_PAYLOAD_CAP_BYTES,
    ArchitectureCommit,
    FileRoleEvidence,
    OutputSchemaEvidence,
    PlanningSignal,
    PlanningState,
    ResolvedSlot,
    StepTriple,
)
from eneo.flows.enums import FlowAuthoringInputType, FlowAuthoringOutputMode

_VALID_ARCH_HASH = "a" * ARCHITECTURE_HASH_HEX_LENGTH


class TestModuleConstants:
    def test_builder_schema_version_is_six(self) -> None:
        assert BUILDER_SCHEMA_VERSION == 6

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

    def test_empty_has_no_signals_slots_or_commit(self) -> None:
        state = PlanningState.empty()
        assert state.signals == []
        assert state.resolved_slots == {}
        assert state.file_roles == []
        assert state.output_schema_evidence is None
        assert state.architecture_commit is None


class TestOutputSchemaEvidence:
    def test_accepts_template_placeholder_source(self) -> None:
        evidence = OutputSchemaEvidence(
            json_schema={
                "type": "object",
                "properties": {"kundnamn": {"type": "string"}},
            },
            source="template_placeholders",
            confidence="high",
            evidence=["file:file_id:content:template_placeholder:kundnamn"],
        )

        assert evidence.source == "template_placeholders"

    def test_old_payload_defaults_truncation_metadata(self) -> None:
        state = PlanningState.model_validate(
            {
                "fcm_version": FCM_VERSION,
                "planner_contract_version": PLANNER_CONTRACT_VERSION,
                "builder_schema_version": 5,
                "output_schema_evidence": {
                    "json_schema": {
                        "type": "object",
                        "properties": {"kundnamn": {"type": "string"}},
                    },
                    "source": "template_placeholders",
                    "confidence": "high",
                    "evidence": ["file:file_id:content:template_placeholder:kundnamn"],
                },
            }
        )

        evidence = state.output_schema_evidence
        assert evidence is not None
        assert evidence.total_count is None
        assert evidence.truncated is False
        assert state.builder_schema_version == 5


class TestRoundTrip:
    @staticmethod
    def _populated_state() -> PlanningState:
        return PlanningState(
            fcm_version=FCM_VERSION,
            planner_contract_version=PLANNER_CONTRACT_VERSION,
            builder_schema_version=BUILDER_SCHEMA_VERSION,
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
            file_roles=[
                FileRoleEvidence(
                    file_id="00000000-0000-0000-0000-000000000701",
                    filename="beslutsmall.docx",
                    file_type="document",
                    mimetype=(
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                    role="template",
                    source="heuristic",
                    confidence="medium",
                    evidence=["filename:mall"],
                    candidate_roles=["template"],
                )
            ],
            output_schema_evidence=OutputSchemaEvidence(
                json_schema={
                    "type": "object",
                    "properties": {"decision": {"type": "string"}},
                    "required": ["decision"],
                },
                source="freeform_text",
                confidence="high",
                evidence=["message:msg_schema", "fenced_json_schema"],
            ),
            architecture_commit=ArchitectureCommit(
                tuples_chain=[
                    StepTriple(
                        input_type="document",
                        output_type="text",
                        output_mode="pass_through",
                    )
                ],
                chosen_patterns=["document_to_structured_report"],
                committed_at=datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc),
                architecture_hash=_VALID_ARCH_HASH,
            ),
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


class TestAssignmentRevalidation:
    """`validate_assignment=True` re-runs validators when an attribute
    is directly reassigned, closing the most obvious drift hole for a
    mutable Pydantic model.
    """

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


class TestFileRoleEvidenceValidation:
    def test_file_role_evidence_accepts_declared_roles(self) -> None:
        evidence = FileRoleEvidence(
            file_id="00000000-0000-0000-0000-000000000701",
            filename="lagstod.pdf",
            file_type="document",
            mimetype="application/pdf",
            role="reference_material",
            source="heuristic",
            confidence="medium",
            evidence=["filename:lag"],
        )

        assert evidence.role == "reference_material"

    def test_file_role_evidence_preserves_candidate_roles(self) -> None:
        evidence = FileRoleEvidence(
            file_id="00000000-0000-0000-0000-000000000701",
            filename="lagmall.docx",
            file_type="document",
            mimetype=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml."
                "document"
            ),
            role="template",
            source="heuristic",
            confidence="medium",
            candidate_roles=["template", "reference_material"],
        )

        assert evidence.role == "template"
        assert evidence.candidate_roles == ["template", "reference_material"]

    def test_file_role_evidence_rejects_candidates_without_primary_role(self) -> None:
        with pytest.raises(ValidationError):
            FileRoleEvidence(
                file_id="00000000-0000-0000-0000-000000000701",
                filename="lagmall.docx",
                file_type="document",
                mimetype=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml."
                    "document"
                ),
                role="template",
                source="heuristic",
                confidence="medium",
                candidate_roles=["reference_material"],
            )

    def test_file_role_evidence_rejects_unknown_role(self) -> None:
        with pytest.raises(ValidationError):
            FileRoleEvidence(
                file_id="00000000-0000-0000-0000-000000000701",
                filename="lagstod.pdf",
                file_type="document",
                mimetype="application/pdf",
                role="sourceish",  # type: ignore[arg-type]
                source="heuristic",
                confidence="medium",
            )

    def test_planning_state_rejects_duplicate_file_role_ids(self) -> None:
        file_role = FileRoleEvidence(
            file_id="00000000-0000-0000-0000-000000000701",
            filename="lagstod.pdf",
            file_type="document",
            mimetype="application/pdf",
            role="reference_material",
            source="heuristic",
            confidence="medium",
        )

        with pytest.raises(ValidationError):
            PlanningState(
                fcm_version=FCM_VERSION,
                planner_contract_version=PLANNER_CONTRACT_VERSION,
                builder_schema_version=BUILDER_SCHEMA_VERSION,
                file_roles=[file_role, file_role],
            )


class TestResolvedSlotValidation:
    def test_resolved_slot_accepts_low_confidence_for_model_resolution(self) -> None:
        slot = ResolvedSlot(
            name="document_kind",
            value="case_documents",
            source="model",
            evidence=["msg_1"],
            confidence="low",
        )

        assert slot.source == "model"
        assert slot.confidence == "low"


class TestStepTripleValidation:
    def test_step_input_type_uses_canonical_flow_authoring_enum(self) -> None:
        assert (
            StepTriple.model_fields["input_type"].annotation is FlowAuthoringInputType
        )

    @pytest.mark.parametrize(
        "input_type", [item.value for item in FlowAuthoringInputType]
    )
    def test_canonical_input_type_values_load_from_jsonb_payload(
        self,
        input_type: str,
    ) -> None:
        triple = StepTriple.model_validate(
            {
                "input_type": input_type,
                "output_type": "text",
                "output_mode": "pass_through",
            }
        )

        assert triple.input_type == input_type

    def test_image_input_type_rejected_from_jsonb_payload(self) -> None:
        with pytest.raises(ValidationError):
            StepTriple.model_validate(
                {
                    "input_type": "image",
                    "output_type": "text",
                    "output_mode": "pass_through",
                }
            )

    def test_step_output_mode_uses_canonical_flow_authoring_enum(self) -> None:
        assert (
            StepTriple.model_fields["output_mode"].annotation is FlowAuthoringOutputMode
        )

    @pytest.mark.parametrize(
        "output_mode", [item.value for item in FlowAuthoringOutputMode]
    )
    def test_canonical_output_modes_load_and_serialize_as_wire_values(
        self,
        output_mode: str,
    ) -> None:
        triple = StepTriple.model_validate(
            {
                "input_type": "text",
                "output_type": "text",
                "output_mode": output_mode,
            }
        )

        assert triple.output_mode is FlowAuthoringOutputMode(output_mode)
        assert triple.model_dump(mode="json")["output_mode"] == output_mode

    def test_server_injected_http_post_output_mode_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StepTriple.model_validate(
                {
                    "input_type": "text",
                    "output_type": "text",
                    "output_mode": "http_post",
                }
            )

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
            "signals": [],
            "resolved_slots": {},
            "architecture_commit": None,
            "unexpected_field": "drift",
        }
        with pytest.raises(ValidationError):
            PlanningState.model_validate(payload)

    @pytest.mark.parametrize(
        "legacy_field",
        ["open_questions", "draft_plan_id", "validation", "phase", "evidence"],
    )
    def test_deleted_planning_state_fields_are_rejected(
        self, legacy_field: str
    ) -> None:
        payload = PlanningState.empty().model_dump(mode="json")
        payload[legacy_field] = None

        with pytest.raises(ValidationError):
            PlanningState.model_validate(payload)


class TestVersionStampContract:
    """All three first-class stamps are required and preserved verbatim.
    The Pydantic model does not auto-upgrade them; repository/planner
    policy owns any reset or stale-session behavior.
    """

    def test_older_fcm_version_round_trips_unchanged(self) -> None:
        state = PlanningState(
            fcm_version=FCM_VERSION - 100,
            planner_contract_version=PLANNER_CONTRACT_VERSION,
            builder_schema_version=BUILDER_SCHEMA_VERSION,
        )
        restored = PlanningState.model_validate_json(state.model_dump_json())
        assert restored.fcm_version == FCM_VERSION - 100

    def test_older_planner_contract_version_round_trips_unchanged(self) -> None:
        state = PlanningState(
            fcm_version=FCM_VERSION,
            planner_contract_version=PLANNER_CONTRACT_VERSION - 100,
            builder_schema_version=BUILDER_SCHEMA_VERSION,
        )
        restored = PlanningState.model_validate_json(state.model_dump_json())
        assert restored.planner_contract_version == PLANNER_CONTRACT_VERSION - 100

    def test_missing_builder_schema_version_rejected(self) -> None:
        payload = {
            "fcm_version": FCM_VERSION,
            "planner_contract_version": PLANNER_CONTRACT_VERSION,
            "signals": [],
            "resolved_slots": {},
            "architecture_commit": None,
        }
        with pytest.raises(ValidationError):
            PlanningState.model_validate(payload)

    def test_older_builder_schema_version_round_trips_unchanged(self) -> None:
        state = PlanningState(
            fcm_version=FCM_VERSION,
            planner_contract_version=PLANNER_CONTRACT_VERSION,
            builder_schema_version=BUILDER_SCHEMA_VERSION - 100,
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

    def test_rejects_deleted_chosen_pattern_id(self) -> None:
        with pytest.raises(ValidationError, match="unknown pattern ids"):
            ArchitectureCommit.model_validate(
                {
                    "tuples_chain": [],
                    "chosen_patterns": ["multi_step_quality_chain"],
                    "committed_at": "2026-04-23T12:00:00+00:00",
                    "architecture_hash": _VALID_ARCH_HASH,
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


def test_fcm_version_has_one_home() -> None:
    """The planner stamps the capability manifest's version, not a copy of it.

    A second constant drifted to 1 while the manifest reached 8, so a fresh
    session and a built one stamped different versions of the same field.
    """
    from eneo.flows.ai_builder import planning_state as planning_state_module
    from eneo.flows.flow_capability_manifest import FCM_VERSION as CANONICAL

    assert planning_state_module.FCM_VERSION is CANONICAL
    assert PlanningState.empty().fcm_version == CANONICAL


def test_payload_cap_admits_a_state_within_the_limit() -> None:
    from eneo.flows.ai_builder.planning_state import (
        enforce_planning_state_payload_cap,
    )

    payload = {"fcm_version": 8, "notes": "x" * 1000}

    assert enforce_planning_state_payload_cap(payload) is payload


def test_payload_cap_refuses_an_oversized_state_before_it_is_persisted() -> None:
    """A declared cap that nothing enforces is not a cap.

    Persisting an oversized state would produce a session that cannot be
    loaded again, so the write is refused and the last good state survives.
    """
    import pytest

    from eneo.flows.ai_builder.planning_state import (
        PLANNING_STATE_PAYLOAD_CAP_BYTES,
        PlanningStatePayloadTooLargeError,
        enforce_planning_state_payload_cap,
    )

    oversized = {"blob": "x" * (PLANNING_STATE_PAYLOAD_CAP_BYTES + 1)}

    with pytest.raises(PlanningStatePayloadTooLargeError) as excinfo:
        enforce_planning_state_payload_cap(oversized)

    assert excinfo.value.cap_bytes == PLANNING_STATE_PAYLOAD_CAP_BYTES
    assert excinfo.value.byte_size > PLANNING_STATE_PAYLOAD_CAP_BYTES
