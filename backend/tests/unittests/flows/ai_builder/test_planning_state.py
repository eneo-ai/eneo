"""Typed PlanningState Pydantic model contract.

PlanningState is the persisted blob that lives in
`builder_sessions.planning_state_jsonb`. Business logic always goes
through the typed Pydantic model — never through partial JSONB
operators — so the JSONB schema stays coherent across turns.

This file pins the shape, version stamps, round-trip behavior, and
validation boundaries the rest of the builder depends on.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from eneo.flows.ai_builder.ai_builder_proposal_intent import FlowInputFieldIntent
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    SCHEMA_MAX_JSON_BYTES,
    build_schema_evidence,
    canonical_schema_bytes,
)
from eneo.flows.ai_builder.planning_state import (
    ARCHITECTURE_HASH_HEX_LENGTH,
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
    PLANNING_STATE_PAYLOAD_CAP_BYTES,
    ArchitectureCommit,
    AttachmentCoverage,
    CheckpointIntent,
    ConfirmedRuntimeMetadataField,
    ExactNamedResultPlacement,
    ExampleOutputCitation,
    ExampleOutputConstraintEvidence,
    ExampleOutputSourceCoverage,
    FileRoleEvidence,
    NamedResultEvidence,
    PlanningSignal,
    PlanningState,
    ResolvedSlot,
    StepTriple,
    UnplacedNamedResultPlacement,
    enforce_planning_state_payload_cap,
)
from eneo.flows.enums import FlowAuthoringInputType, FlowAuthoringOutputMode

_VALID_ARCH_HASH = "a" * ARCHITECTURE_HASH_HEX_LENGTH


class TestModuleConstants:
    def test_builder_schema_version_is_twenty_two(self) -> None:
        # v22: focused classifier attempts persist once per catalog slot.
        assert BUILDER_SCHEMA_VERSION == 22

    def test_payload_cap_is_512_kibibytes(self) -> None:
        assert PLANNING_STATE_PAYLOAD_CAP_BYTES == 512 * 1024

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
        assert state.focused_classification_attempted_slots == []
        assert state.file_roles == []
        assert state.input_schema_evidence is None
        assert state.output_schema_evidence is None
        assert state.architecture_commit is None


class TestConfirmedRuntimeMetadataFields:
    def test_state_round_trips_value_purpose_and_structured_answer_message(
        self,
    ) -> None:
        state = PlanningState.empty()
        state.input_fields = [
            ConfirmedRuntimeMetadataField(
                value=FlowInputFieldIntent(
                    name="case_id",
                    label="Case id",
                    provenance="user_confirmed",
                ),
                purpose="interpret_input",
                structured_answer_message_id="answer-2",
            )
        ]

        restored = PlanningState.model_validate_json(state.model_dump_json())

        assert restored.input_fields[0].value.variable_name == "case_id"
        assert restored.input_fields[0].purpose == "interpret_input"
        assert restored.input_fields[0].structured_answer_message_id == "answer-2"

    def test_state_rejects_non_confirmed_runtime_metadata_value(self) -> None:
        with pytest.raises(ValidationError):
            ConfirmedRuntimeMetadataField(
                value=FlowInputFieldIntent(name="case_id", label="Case id"),
                purpose="interpret_input",
                structured_answer_message_id="answer-2",
            )


class TestSchemaEvidence:
    def test_two_distinct_near_limit_schemas_round_trip_below_state_cap(
        self,
    ) -> None:
        schemas = tuple(
            {
                "type": "object",
                "description": fill * (SCHEMA_MAX_JSON_BYTES - 2_048),
                "properties": {field: {"type": "string"}},
            }
            for fill, field in (("x", "case_id"), ("y", "decision"))
        )
        input_evidence, output_evidence = (
            build_schema_evidence(
                json_schema=schema,
                source="declared_schema",
                confidence="high",
                evidence=(f"message:{index}", "fenced_json_schema"),
            )
            for index, schema in enumerate(schemas)
        )
        state = PlanningState.empty()
        state.replace_schema_resolution(
            input_evidence=input_evidence,
            output_evidence=output_evidence,
            example_inference=None,
        )

        payload = enforce_planning_state_payload_cap(state.model_dump(mode="json"))
        restored = PlanningState.model_validate(payload)

        assert all(
            len(canonical_schema_bytes(schema)) > SCHEMA_MAX_JSON_BYTES * 0.95
            for schema in schemas
        )
        assert len(payload["schema_resolution"]["schemas"]) == 2
        assert restored.input_schema_evidence == input_evidence
        assert restored.output_schema_evidence == output_evidence

    def test_shared_near_limit_schema_is_stored_once_and_fits_state_cap(self) -> None:
        schema = {
            "type": "object",
            "description": "x" * 70_000,
            "properties": {"case_id": {"type": "string"}},
        }
        evidence = build_schema_evidence(
            json_schema=schema,
            source="declared_schema",
            confidence="high",
            evidence=("message:msg_schema", "fenced_json_schema"),
        )
        state = PlanningState.empty()
        state.replace_schema_resolution(
            input_evidence=evidence,
            output_evidence=evidence,
            example_inference=None,
        )

        payload = state.model_dump(mode="json")

        assert len(str(schema).encode("utf-8")) < SCHEMA_MAX_JSON_BYTES
        assert "input_schema_evidence" not in payload
        assert "output_schema_evidence" not in payload
        assert len(payload["schema_resolution"]["schemas"]) == 1
        assert payload["schema_resolution"]["input"]["fingerprint"] == (
            evidence.fingerprint
        )
        assert payload["schema_resolution"]["output"]["fingerprint"] == (
            evidence.fingerprint
        )
        enforce_planning_state_payload_cap(payload)

    @pytest.mark.parametrize(
        ("input_selected", "output_selected"),
        [(True, False), (False, True), (True, True)],
    )
    def test_declared_schema_round_trips_for_each_selected_boundary(
        self,
        input_selected: bool,
        output_selected: bool,
    ) -> None:
        evidence = build_schema_evidence(
            json_schema={
                "type": "object",
                "properties": {"case_id": {"type": "string"}},
            },
            source="declared_schema",
            confidence="high",
            evidence=("message:msg_schema", "fenced_json_schema"),
        )
        state = PlanningState.empty()
        state.replace_schema_resolution(
            input_evidence=evidence if input_selected else None,
            output_evidence=evidence if output_selected else None,
            example_inference=None,
        )

        restored = PlanningState.model_validate_json(state.model_dump_json())

        assert restored.input_schema_evidence == (evidence if input_selected else None)
        assert restored.output_schema_evidence == (
            evidence if output_selected else None
        )
        if input_selected and output_selected:
            assert (
                restored.input_schema_evidence.fingerprint
                == restored.output_schema_evidence.fingerprint
            )

    def test_accepts_template_placeholder_source(self) -> None:
        evidence = build_schema_evidence(
            json_schema={
                "type": "object",
                "properties": {"kundnamn": {"type": "string"}},
            },
            source="template_placeholders",
            source_file_ids=("00000000-0000-0000-0000-000000000001",),
            confidence="high",
            evidence=["file:file_id:content:template_placeholder:kundnamn"],
        )

        assert evidence.source == "template_placeholders"

    def test_incomplete_schema_evidence_payload_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlanningState.model_validate(
                {
                    "fcm_version": FCM_VERSION,
                    "planner_contract_version": PLANNER_CONTRACT_VERSION,
                    "builder_schema_version": BUILDER_SCHEMA_VERSION,
                    "output_schema_evidence": {
                        "json_schema": {
                            "type": "object",
                            "properties": {"kundnamn": {"type": "string"}},
                        },
                        "source": "template_placeholders",
                        "confidence": "high",
                        "evidence": [
                            "file:file_id:content:template_placeholder:kundnamn"
                        ],
                    },
                }
            )


class TestExampleOutputConstraints:
    def test_coverage_must_match_current_file_role_evidence(self) -> None:
        file_id = "00000000-0000-0000-0000-000000000709"
        with pytest.raises(
            ValidationError,
            match="coverage must match file role evidence",
        ):
            PlanningState(
                fcm_version=FCM_VERSION,
                planner_contract_version=PLANNER_CONTRACT_VERSION,
                builder_schema_version=BUILDER_SCHEMA_VERSION,
                file_roles=[
                    FileRoleEvidence(
                        file_id=file_id,
                        filename="example.pdf",
                        file_type="document",
                        mimetype="application/pdf",
                        has_readable_text=True,
                        coverage="excerpt_truncated",
                        role="example_output",
                        source="model",
                        confidence="medium",
                    )
                ],
                example_output_constraints=ExampleOutputConstraintEvidence(
                    source_file_ids=[file_id],
                    source_coverage=[
                        ExampleOutputSourceCoverage(
                            file_id=file_id,
                            coverage="fully_seen",
                        )
                    ],
                    headings=["Summary"],
                    confidence="medium",
                    citations=[
                        ExampleOutputCitation(
                            source_id=f"uploaded_file:{file_id}",
                            file_id=file_id,
                            quote="# Summary",
                        )
                    ],
                ),
            )


class TestRoundTrip:
    @staticmethod
    def _populated_state() -> PlanningState:
        state = PlanningState(
            fcm_version=FCM_VERSION,
            planner_contract_version=PLANNER_CONTRACT_VERSION,
            builder_schema_version=BUILDER_SCHEMA_VERSION,
            signals=[
                PlanningSignal(
                    question_id="runtime_metadata_fields",
                    value="basic_runtime_metadata",
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
                "runtime_metadata_fields": ResolvedSlot(
                    name="runtime_metadata_fields",
                    value="basic_runtime_metadata",
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
                    has_readable_text=True,
                    coverage="fully_seen",
                    role="template",
                    source="heuristic",
                    confidence="medium",
                    evidence=["filename:mall"],
                    candidate_roles=["template"],
                )
            ],
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
        state.replace_schema_resolution(
            input_evidence=None,
            output_evidence=build_schema_evidence(
                json_schema={
                    "type": "object",
                    "properties": {"decision": {"type": "string"}},
                    "required": ["decision"],
                },
                source="declared_schema",
                confidence="high",
                evidence=["message:msg_schema", "fenced_json_schema"],
            ),
            example_inference=None,
        )
        return state

    def test_model_dump_json_survives_round_trip(self) -> None:
        original = self._populated_state()
        dumped = original.model_dump_json()
        restored = PlanningState.model_validate_json(dumped)
        assert restored == original


class TestFileRoleEvidenceValidation:
    @pytest.mark.parametrize(
        "coverage",
        ["fully_seen", "excerpt_truncated", "inventory_only"],
    )
    def test_readable_file_role_evidence_accepts_every_coverage_state(
        self,
        coverage: AttachmentCoverage,
    ) -> None:
        evidence = FileRoleEvidence(
            file_id="00000000-0000-0000-0000-000000000701",
            filename="lagstod.pdf",
            file_type="document",
            mimetype="application/pdf",
            has_readable_text=True,
            coverage=coverage,
            role="reference_material",
            source="heuristic",
            confidence="medium",
        )

        assert evidence.has_readable_text is True
        assert evidence.coverage == coverage

    def test_non_readable_file_role_evidence_requires_inventory_only(self) -> None:
        with pytest.raises(ValidationError):
            FileRoleEvidence(
                file_id="00000000-0000-0000-0000-000000000701",
                filename="lagstod.pdf",
                file_type="document",
                mimetype="application/pdf",
                has_readable_text=False,
                coverage="fully_seen",
                role="reference_material",
                source="heuristic",
                confidence="medium",
            )

    def test_file_role_evidence_accepts_declared_roles(self) -> None:
        evidence = FileRoleEvidence(
            file_id="00000000-0000-0000-0000-000000000701",
            filename="lagstod.pdf",
            file_type="document",
            mimetype="application/pdf",
            has_readable_text=True,
            coverage="fully_seen",
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
            has_readable_text=True,
            coverage="fully_seen",
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
                has_readable_text=True,
                coverage="fully_seen",
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
                has_readable_text=True,
                coverage="fully_seen",
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
            has_readable_text=True,
            coverage="fully_seen",
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

    def test_checkpoint_intent_round_trips_with_closed_producer_and_mode(self) -> None:
        intent = CheckpointIntent(
            producer_kind="transcript",
            operation="set",
            mode="edit",
            confidence="high",
            evidence=["quote:user_message:user-1:edit the transcript before analysis"],
            evidence_level="explicit",
        )
        state = PlanningState.empty()
        state.checkpoint_intents = [intent]

        restored = PlanningState.model_validate_json(state.model_dump_json())

        assert restored.checkpoint_intents == [intent]
        assert restored.checkpoint_intents[0].mode.value == "edit"

    def test_checkpoint_set_requires_mode_and_clear_forbids_it(self) -> None:
        with pytest.raises(ValidationError, match="requires a review mode"):
            CheckpointIntent(
                producer_kind="transcript",
                operation="set",
                mode=None,
                confidence="high",
                evidence=["quote:user_message:user-1:edit the transcript"],
                evidence_level="explicit",
            )
        with pytest.raises(ValidationError, match="must not carry a review mode"):
            CheckpointIntent(
                producer_kind="transcript",
                operation="clear",
                mode="edit",
                confidence="high",
                evidence=["quote:user_message:user-1:remove the review"],
                evidence_level="explicit",
            )

    def test_checkpoint_intent_requires_evidence_that_states_the_change(self) -> None:
        for operation, mode in (("set", "edit"), ("clear", None)):
            with pytest.raises(
                ValidationError, match="explicitly stated checkpoint change"
            ):
                CheckpointIntent(
                    producer_kind="transcript",
                    operation=operation,
                    mode=mode,
                    confidence="high",
                    evidence=["quote:user_message:user-1:transcribe the audio"],
                    evidence_level="inferred",
                )

    def test_persisted_checkpoint_intent_is_rechecked_on_load(self) -> None:
        payload = json.loads(
            PlanningState(
                fcm_version=FCM_VERSION,
                planner_contract_version=PLANNER_CONTRACT_VERSION,
                builder_schema_version=BUILDER_SCHEMA_VERSION,
                checkpoint_intents=[
                    CheckpointIntent(
                        producer_kind="transcript",
                        operation="set",
                        mode="edit",
                        confidence="high",
                        evidence=[
                            "quote:user_message:user-1:let me edit the transcript first"
                        ],
                        evidence_level="explicit",
                    )
                ],
            ).model_dump_json()
        )
        payload["checkpoint_intents"][0]["evidence_level"] = "inferred"

        with pytest.raises(
            ValidationError, match="explicitly stated checkpoint change"
        ):
            PlanningState.model_validate(payload)

    def test_checkpoint_clear_tombstone_round_trips(self) -> None:
        intent = CheckpointIntent(
            producer_kind="structured_result",
            operation="clear",
            mode=None,
            confidence="high",
            evidence=["quote:user_message:user-1:remove the JSON approval"],
            evidence_level="explicit",
        )
        state = PlanningState.empty()
        state.checkpoint_intents = [intent]

        restored = PlanningState.model_validate_json(state.model_dump_json())

        assert restored.checkpoint_intents == [intent]
        assert restored.checkpoint_intents[0].operation == "clear"
        assert restored.checkpoint_intents[0].mode is None

    def test_planning_state_rejects_duplicate_checkpoint_producer(self) -> None:
        intent = CheckpointIntent(
            producer_kind="report_text",
            operation="set",
            mode="view",
            confidence="medium",
            evidence=["quote:user_message:user-1:approve the report"],
            evidence_level="explicit",
        )

        with pytest.raises(
            ValidationError,
            match="checkpoint_intents must contain unique producer_kind values",
        ):
            PlanningState(
                fcm_version=FCM_VERSION,
                planner_contract_version=PLANNER_CONTRACT_VERSION,
                builder_schema_version=BUILDER_SCHEMA_VERSION,
                checkpoint_intents=[intent, intent],
            )


class TestResolvedSlotValidation:
    def test_model_evidence_level_round_trips_with_the_resolved_slot(self) -> None:
        slot = ResolvedSlot(
            name="terminal_output",
            value="structured_json",
            source="model",
            evidence=["quote:user_message:test:JSON"],
            confidence="medium",
            evidence_level="explicit",
        )

        restored = ResolvedSlot.model_validate_json(slot.model_dump_json())

        assert restored == slot
        assert restored.is_commit_grade is True

    @pytest.mark.parametrize(
        ("source", "evidence", "confidence", "evidence_level"),
        [
            ("model", ["quote:user_message:test:JSON"], "medium", None),
            ("model", ["model:terminal_output:hash"], "medium", "explicit"),
            ("model", ["quote:user_message:test:JSON"], "low", "explicit"),
            ("heuristic", ["heuristic:terminal_output"], "medium", "explicit"),
        ],
    )
    def test_resolved_slot_rejects_incoherent_model_provenance(
        self,
        source: str,
        evidence: list[str],
        confidence: str,
        evidence_level: str | None,
    ) -> None:
        with pytest.raises(ValidationError):
            ResolvedSlot.model_validate(
                {
                    "name": "terminal_output",
                    "value": "structured_json",
                    "source": source,
                    "evidence": evidence,
                    "confidence": confidence,
                    "evidence_level": evidence_level,
                }
            )


class TestNamedResultEvidenceValidation:
    def test_placement_union_round_trips_exact_root_nested_and_unplaced(self) -> None:
        placements = (
            ExactNamedResultPlacement(),
            ExactNamedResultPlacement(segments=("documents", "passages")),
            UnplacedNamedResultPlacement(),
        )

        restored = tuple(
            NamedResultEvidence.model_validate_json(
                NamedResultEvidence(
                    name="page_or_section",
                    placement=placement,
                    evidence=["quote:user_message:user-1:page_or_section"],
                    confidence="high",
                ).model_dump_json()
            ).placement
            for placement in placements
        )

        assert restored == placements
        assert ExactNamedResultPlacement().segments == ()

    @pytest.mark.parametrize(
        ("segments", "error"),
        [
            (
                ("one", "two", "three", "four"),
                "named result placement exceeds structured field depth",
            ),
            (
                ("valid", "123"),
                "named result placement segments must be compilable identifiers",
            ),
        ],
    )
    def test_exact_placement_rejects_depth_and_identifier_violations(
        self,
        segments: tuple[str, ...],
        error: str,
    ) -> None:
        with pytest.raises(ValidationError, match=error):
            NamedResultEvidence(
                name="leaf",
                placement=ExactNamedResultPlacement(segments=segments),
                evidence=["quote:user_message:user-1:leaf"],
                confidence="high",
            )

    def test_named_result_rejects_a_leaf_that_cannot_compile(self) -> None:
        with pytest.raises(
            ValidationError,
            match="named result evidence name must be non-empty",
        ):
            NamedResultEvidence(
                name="2024_summary",
                evidence=["quote:user_message:user-1:2024_summary"],
                confidence="high",
            )

    def test_state_accepts_same_leaf_at_two_exact_locations(self) -> None:
        state = PlanningState.empty()
        state.named_result_evidence = [
            NamedResultEvidence(
                name="events",
                placement=ExactNamedResultPlacement(),
                declared_shape="array",
                evidence=["quote:user_message:user-1:events[]"],
                confidence="high",
            ),
            NamedResultEvidence(
                name="alerts",
                placement=ExactNamedResultPlacement(),
                declared_shape="array",
                evidence=["quote:user_message:user-1:alerts[]"],
                confidence="high",
            ),
            NamedResultEvidence(
                name="timestamp",
                placement=ExactNamedResultPlacement(segments=("events",)),
                evidence=["quote:user_message:user-1:events[].timestamp"],
                confidence="high",
            ),
            NamedResultEvidence(
                name="timestamp",
                placement=ExactNamedResultPlacement(segments=("alerts",)),
                evidence=["quote:user_message:user-1:alerts[].timestamp"],
                confidence="high",
            ),
        ]

        assert PlanningState.model_validate(
            state.model_dump()
        ).named_result_evidence == (state.named_result_evidence)

    def test_state_rejects_unplaced_leaf_that_also_has_exact_placement(self) -> None:
        with pytest.raises(ValidationError, match="unplaced named result.*timestamp"):
            PlanningState.model_validate(
                {
                    **PlanningState.empty().model_dump(),
                    "named_result_evidence": [
                        {
                            "name": "timestamp",
                            "placement": {"kind": "unplaced"},
                            "evidence": ["quote:user_message:user-1:timestamp"],
                            "confidence": "high",
                        },
                        {
                            "name": "timestamp",
                            "placement": {
                                "kind": "exact",
                                "segments": ["events"],
                            },
                            "evidence": [
                                "quote:user_message:user-1:events[].timestamp"
                            ],
                            "confidence": "high",
                        },
                    ],
                }
            )

    def test_state_rejects_exact_orphan_with_the_full_path(self) -> None:
        with pytest.raises(ValidationError, match=r"documents\.passages\.page"):
            PlanningState.model_validate(
                {
                    **PlanningState.empty().model_dump(),
                    "named_result_evidence": [
                        {
                            "name": "documents",
                            "placement": {"kind": "exact", "segments": []},
                            "declared_shape": "array",
                            "evidence": ["quote:user_message:user-1:documents[]"],
                            "confidence": "high",
                        },
                        {
                            "name": "page",
                            "placement": {
                                "kind": "exact",
                                "segments": ["documents", "passages"],
                            },
                            "evidence": [
                                "quote:user_message:user-1:documents[].passages[].page"
                            ],
                            "confidence": "high",
                        },
                    ],
                }
            )

    @pytest.mark.parametrize(
        ("confidence", "expected"),
        [("high", True), ("medium", True), ("low", False)],
    )
    def test_commit_grade_named_evidence_needs_supported_confidence(
        self,
        confidence: str,
        expected: bool,
    ) -> None:
        # Admission already proved the name is explicit: it was cited
        # literally in the current user-owned message. Confidence is the only
        # remaining question.
        evidence = NamedResultEvidence.model_validate(
            {
                "name": "bids",
                "evidence": ["quote:user_message:user-1:bids[]"],
                "confidence": confidence,
                "declared_shape": "array",
            }
        )

        assert evidence.is_commit_grade is expected

    def test_declared_shape_round_trips_with_the_persisted_evidence(self) -> None:
        evidence = NamedResultEvidence(
            name="bids",
            evidence=["quote:user_message:user-1:bids[]"],
            confidence="high",
            declared_shape="array",
        )

        restored = NamedResultEvidence.model_validate_json(evidence.model_dump_json())

        assert restored == evidence
        assert restored.declared_shape == "array"

    def test_declared_shape_defaults_to_no_declaration(self) -> None:
        evidence = NamedResultEvidence(
            name="bids",
            evidence=["quote:user_message:user-1:bids"],
            confidence="high",
        )

        assert evidence.declared_shape is None

    def test_declared_shape_rejects_a_shape_outside_the_contract(self) -> None:
        with pytest.raises(ValidationError):
            NamedResultEvidence.model_validate(
                {
                    "name": "bids",
                    "evidence": ["quote:user_message:user-1:bids"],
                    "confidence": "high",
                    "declared_shape": "list",
                }
            )


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
                question_id="runtime_metadata_fields",
                value="basic_runtime_metadata",
                confidence="high",
                source="structured_answer",
            )
        )
        assert len(state.signals) == 1

    def test_resolved_slots_can_be_added(self) -> None:
        state = PlanningState.empty()
        state.resolved_slots["runtime_metadata_fields"] = ResolvedSlot(
            name="runtime_metadata_fields",
            value="basic_runtime_metadata",
            source="structured_answer",
            evidence=["msg_1"],
            confidence="high",
        )
        assert "runtime_metadata_fields" in state.resolved_slots

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
