"""Unit tests for `planning_state_builder.carry_forward_persisted_planner_state`.

The helper is the single place the save path merges planner-owned
architecture_commit from the previously persisted state onto a freshly
rebuilt one. Integration tests pin the savepoint wiring; these unit tests
pin the merge semantics in isolation so regressions show up at the merge
layer, not two containers deep.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from eneo.flows.ai_builder.ai_builder_action_policy import (
    build_planner_action_policy,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    metadata_with_slot_classification,
    slot_classification_metadata_from_result,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    question_is_already_resolved,
)
from eneo.flows.ai_builder.ai_builder_output_schema_evidence import (
    build_output_schema_evidence,
)
from eneo.flows.ai_builder.ai_builder_slot_classifier import (
    ClassifiedEvidence,
    ClassifiedFileRole,
    ClassifiedFormIntake,
    ClassifiedSlot,
    SlotClassificationConfidence,
    SlotClassificationInput,
    SlotClassificationResult,
    SlotClassificationSource,
)
from eneo.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
    ArchitectureCommit,
    AttachmentCoverage,
    ExampleOutputCitation,
    ExampleOutputConstraintEvidence,
    ExampleOutputSchemaInferenceOutcome,
    ExampleOutputSourceCoverage,
    ExampleOutputStyleConstraint,
    FileRole,
    FileRoleEvidence,
    MappedFileLimit,
    OutputSchemaEvidence,
    PlanningState,
    ResolvedSlot,
    SlotConfidence,
    SlotSource,
    StepTriple,
)
from eneo.flows.ai_builder.planning_state_builder import (
    apply_policy_defaults_from_resolved_slots,
    build_planning_state_from_conversation,
    carry_forward_persisted_planner_state,
    llm_resolvable_slot_values_for_state,
    merge_llm_resolved_slots,
)
from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy


def _state(
    *,
    architecture_commit: ArchitectureCommit | None = None,
) -> PlanningState:
    return PlanningState(
        fcm_version=FCM_VERSION,
        planner_contract_version=PLANNER_CONTRACT_VERSION,
        builder_schema_version=BUILDER_SCHEMA_VERSION,
        architecture_commit=architecture_commit,
    )


def _output_schema_evidence() -> OutputSchemaEvidence:
    return build_output_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {"decision": {"type": "string"}},
            "required": ["decision"],
            "additionalProperties": False,
        },
        source="freeform_text",
        confidence="high",
        evidence=["message:msg_schema", "fenced_json_schema"],
    )


def _example_output_constraints(
    file_id: UUID,
    *,
    heading: str,
) -> ExampleOutputConstraintEvidence:
    return ExampleOutputConstraintEvidence(
        source_file_ids=[file_id],
        source_coverage=[
            ExampleOutputSourceCoverage(
                file_id=file_id,
                coverage="fully_seen",
            )
        ],
        headings=[heading],
        confidence="medium",
        citations=[
            ExampleOutputCitation(
                source_id=f"uploaded_file:{file_id}",
                file_id=file_id,
                quote=heading,
            )
        ],
    )


def _example_output_file_role(file_id: UUID) -> FileRoleEvidence:
    return FileRoleEvidence(
        file_id=file_id,
        filename=f"{file_id}.json",
        file_type="text",
        mimetype="application/json",
        has_readable_text=True,
        coverage="fully_seen",
        role="example_output",
        source="model",
        confidence="medium",
        evidence=["model:file_role"],
        candidate_roles=["example_output"],
    )


def _apply_inferred_example_schema(
    state: PlanningState,
    *,
    file_id: UUID,
) -> None:
    state.replace_output_schema_resolution(
        evidence=build_output_schema_evidence(
            json_schema={
                "type": "object",
                "properties": {"decision": {"type": "string"}},
            },
            source="inferred_example",
            source_file_ids=(file_id,),
            confidence="medium",
            evidence=(f"file:{file_id}:inferred_example_shape",),
        ),
        example_inference=ExampleOutputSchemaInferenceOutcome(
            status="inferred",
            source_file_ids=[file_id],
        ),
    )


def _commit(hash_char: str = "a") -> ArchitectureCommit:
    return ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=["summarize_text"],
        committed_at=datetime(2026, 4, 23, tzinfo=timezone.utc),
        architecture_hash=hash_char * 64,
    )


def _slot(
    *,
    name: str,
    value: str,
    source: SlotSource,
    confidence: SlotConfidence | None = None,
) -> ResolvedSlot:
    resolved_confidence: SlotConfidence = confidence or (
        "medium" if source == "policy_default" else "high"
    )
    return ResolvedSlot(
        name=name,
        value=value,
        source=source,
        evidence=[f"{source}:{name}"],
        confidence=resolved_confidence,
    )


def _classified(
    slot_name: str,
    value: str,
    confidence: SlotClassificationConfidence,
    *,
    evidence: tuple[str, ...] | None = None,
) -> ClassifiedSlot:
    return ClassifiedSlot(
        slot_name=slot_name,
        value=value,
        confidence=confidence,
        reason=f"{slot_name} classified",
        evidence=_model_evidence(*(evidence or (f"{slot_name} evidence",))),
    )


def _model_evidence(*quotes: str) -> tuple[ClassifiedEvidence, ...]:
    return tuple(
        ClassifiedEvidence(source_id="user_message:test-source", quote=quote)
        for quote in quotes
    )


def _slot_classification_metadata(
    *slots: ClassifiedSlot,
    prompt_hash: str = "a" * 64,
    form_intake: ClassifiedFormIntake | None = None,
) -> dict[str, object]:
    evidence_quotes = [item.quote for slot in slots for item in slot.evidence]
    if form_intake is not None:
        evidence_quotes.extend(item.quote for item in form_intake.evidence)
    metadata = slot_classification_metadata_from_result(
        SlotClassificationResult(slots=slots, form_intake=form_intake),
        prompt_hash=prompt_hash,
        classification_input=SlotClassificationInput(
            sources=(
                SlotClassificationSource(
                    source_id="user_message:test-source",
                    kind="user_message",
                    text="\n".join(evidence_quotes),
                    message_id="test-source",
                ),
            )
        ),
        model="openai/gpt-test",
        provider="openai",
    )
    assert metadata is not None
    result = metadata_with_slot_classification(None, metadata)
    assert result is not None
    return result


def test_conversation_replay_overlays_live_attachment_role_evidence() -> None:
    file_id = UUID("00000000-0000-0000-0000-000000000701")
    classification_input = SlotClassificationInput(
        sources=(
            SlotClassificationSource(
                source_id="user_message:file-role",
                kind="user_message",
                text="This attachment is the example output.",
                message_id="file-role",
            ),
            SlotClassificationSource(
                source_id=f"uploaded_file:{file_id}",
                kind="uploaded_file",
                text="filename: example.pdf",
                file_id=file_id,
                coverage="fully_seen",
            ),
        )
    )
    metadata = slot_classification_metadata_from_result(
        SlotClassificationResult(
            file_roles=(
                ClassifiedFileRole(
                    file_id=file_id,
                    role="example_output",
                    confidence="high",
                    reason="The user identified the example output.",
                    evidence=(
                        ClassifiedEvidence(
                            source_id="user_message:file-role",
                            quote="This attachment is the example output.",
                        ),
                    ),
                ),
            )
        ),
        prompt_hash="a" * 64,
        classification_input=classification_input,
        model="openai/gpt-test",
        provider="openai",
    )
    assert metadata is not None
    conversation_metadata = metadata_with_slot_classification(None, metadata)
    assert conversation_metadata is not None

    state = build_planning_state_from_conversation(
        [
            ConversationMessage(
                message_id="file-role",
                role="user",
                content="This attachment is the example output.",
                metadata=conversation_metadata,
            )
        ],
        attachment_file_roles=[
            FileRoleEvidence(
                file_id=file_id,
                filename="example.pdf",
                file_type="document",
                mimetype="application/pdf",
                has_readable_text=True,
                coverage="excerpt_truncated",
                role="context_only",
                source="heuristic",
                confidence="low",
                evidence=["fallback:unclassified_file"],
                candidate_roles=["context_only"],
            )
        ],
    )

    assert len(state.file_roles) == 1
    role = state.file_roles[0]
    assert role.role == "example_output"
    assert role.source == "model"
    assert role.has_readable_text is True
    assert role.coverage == "excerpt_truncated"


class TestPersistedNone:
    def test_is_noop_when_persisted_is_none(self) -> None:
        rebuilt = _state()

        carry_forward_persisted_planner_state(rebuilt, None, attached_file_ids=set())

        assert rebuilt.architecture_commit is None


class TestArchitectureCommitPreservation:
    def test_carries_forward_when_rebuilt_has_none(self) -> None:
        persisted_commit = _commit()
        rebuilt = _state()
        persisted = _state(architecture_commit=persisted_commit)

        carry_forward_persisted_planner_state(
            rebuilt, persisted, attached_file_ids=set()
        )

        assert rebuilt.architecture_commit is persisted_commit

    def test_does_not_overwrite_explicit_set_on_rebuilt(self) -> None:
        explicit = _commit(hash_char="b")
        persisted_commit = _commit(hash_char="a")
        rebuilt = _state(architecture_commit=explicit)
        persisted = _state(architecture_commit=persisted_commit)

        carry_forward_persisted_planner_state(
            rebuilt, persisted, attached_file_ids=set()
        )

        assert rebuilt.architecture_commit is explicit

    def test_leaves_none_when_neither_side_has_commit(self) -> None:
        rebuilt = _state()
        persisted = _state()

        carry_forward_persisted_planner_state(
            rebuilt, persisted, attached_file_ids=set()
        )

        assert rebuilt.architecture_commit is None


class TestMappedFileLimitPreservation:
    def test_carries_forward_accepted_value_within_current_policy(self) -> None:
        rebuilt = _state()
        rebuilt.mapped_file_limit = MappedFileLimit(
            proposed_value=5,
            diagnostic="confirmation_required",
        )
        persisted = _state()
        persisted.mapped_file_limit = MappedFileLimit(
            proposed_value=8,
            accepted_value=4,
            provenance="authored",
        )

        carry_forward_persisted_planner_state(
            rebuilt, persisted, attached_file_ids=set()
        )

        assert rebuilt.mapped_file_limit == MappedFileLimit(
            proposed_value=5,
            accepted_value=4,
            provenance="authored",
        )

    def test_drops_accepted_value_above_current_policy(self) -> None:
        rebuilt = _state()
        rebuilt.mapped_file_limit = MappedFileLimit(
            proposed_value=5,
            diagnostic="confirmation_required",
        )
        persisted = _state()
        persisted.mapped_file_limit = MappedFileLimit(
            proposed_value=8,
            accepted_value=6,
            provenance="authored",
        )

        carry_forward_persisted_planner_state(
            rebuilt, persisted, attached_file_ids=set()
        )

        assert rebuilt.mapped_file_limit == MappedFileLimit(
            proposed_value=5,
            diagnostic="confirmation_required",
        )


class TestFileRoleEvidencePreservation:
    def test_carries_forward_persisted_file_roles(self) -> None:
        persisted_role = FileRoleEvidence(
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
        rebuilt = _state()
        persisted = _state()
        persisted.file_roles = [persisted_role]

        carry_forward_persisted_planner_state(
            rebuilt,
            persisted,
            attached_file_ids={persisted_role.file_id},
        )

        assert rebuilt.file_roles == [persisted_role]

    def test_current_turn_file_role_wins_over_persisted_same_file(self) -> None:
        file_id = "00000000-0000-0000-0000-000000000701"
        current_role = FileRoleEvidence(
            file_id=file_id,
            filename="avtalsmall.docx",
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
        )
        stale_role = FileRoleEvidence(
            file_id=file_id,
            filename="avtalsmall.docx",
            file_type="document",
            mimetype=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml."
                "document"
            ),
            has_readable_text=True,
            coverage="fully_seen",
            role="context_only",
            source="heuristic",
            confidence="low",
        )
        rebuilt = _state()
        rebuilt.file_roles = [current_role]
        persisted = _state()
        persisted.file_roles = [stale_role]

        carry_forward_persisted_planner_state(
            rebuilt,
            persisted,
            attached_file_ids={current_role.file_id},
        )

        assert rebuilt.file_roles == [current_role]

    def test_drops_persisted_file_role_for_detached_file(self) -> None:
        persisted_role = FileRoleEvidence(
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
        rebuilt = _state()
        persisted = _state()
        persisted.file_roles = [persisted_role]

        carry_forward_persisted_planner_state(
            rebuilt,
            persisted,
            attached_file_ids=set(),
        )

        assert rebuilt.file_roles == []


class TestOutputSchemaEvidencePreservation:
    def test_carries_forward_persisted_output_schema_evidence(self) -> None:
        persisted_evidence = _output_schema_evidence()
        rebuilt = _state()
        persisted = _state()
        persisted.output_schema_evidence = persisted_evidence

        carry_forward_persisted_planner_state(
            rebuilt, persisted, attached_file_ids=set()
        )

        assert rebuilt.output_schema_evidence is persisted_evidence

    def test_current_turn_output_schema_evidence_wins(self) -> None:
        current = _output_schema_evidence()
        stale = build_output_schema_evidence(
            json_schema={
                "type": "object",
                "properties": {"old": {"type": "string"}},
            },
            source="freeform_text",
            confidence="high",
            evidence=["message:old", "fenced_json_schema"],
        )
        rebuilt = _state()
        rebuilt.output_schema_evidence = current
        persisted = _state()
        persisted.output_schema_evidence = stale

        carry_forward_persisted_planner_state(
            rebuilt,
            persisted,
            attached_file_ids=set(),
        )

        assert rebuilt.output_schema_evidence is current

    def test_filters_template_output_schema_evidence_to_attached_files(self) -> None:
        active_file_id = UUID("00000000-0000-0000-0000-000000000701")
        detached_file_id = UUID("00000000-0000-0000-0000-000000000702")
        persisted = _state()
        persisted.output_schema_evidence = build_output_schema_evidence(
            json_schema={
                "type": "object",
                "properties": {
                    "kundnamn": {"type": "string"},
                    "arkivnummer": {"type": "string"},
                },
                "required": ["kundnamn", "arkivnummer"],
                "additionalProperties": False,
            },
            source="template_placeholders",
            source_file_ids=(active_file_id, detached_file_id),
            confidence="high",
            evidence=[
                f"file:{active_file_id}:content:template_placeholder:kundnamn",
                f"file:{detached_file_id}:content:template_placeholder:arkivnummer",
            ],
        )
        rebuilt = _state()

        carry_forward_persisted_planner_state(
            rebuilt,
            persisted,
            attached_file_ids={active_file_id},
        )

        evidence = rebuilt.output_schema_evidence
        assert evidence is not None
        assert evidence.evidence == [
            f"file:{active_file_id}:content:template_placeholder:kundnamn"
        ]
        assert evidence.json_schema == {
            "type": "object",
            "properties": {"kundnamn": {"type": "string"}},
            "required": ["kundnamn"],
            "additionalProperties": False,
        }

    def test_duplicate_placeholder_survives_when_one_source_file_is_detached(
        self,
    ) -> None:
        active_file_id = UUID("00000000-0000-0000-0000-000000000701")
        detached_file_id = UUID("00000000-0000-0000-0000-000000000702")
        persisted = _state()
        persisted.output_schema_evidence = build_output_schema_evidence(
            json_schema={
                "type": "object",
                "properties": {"shared": {"type": "string"}},
            },
            source="template_placeholders",
            source_file_ids=(active_file_id, detached_file_id),
            confidence="high",
            evidence=[
                f"file:{detached_file_id}:content:template_placeholder:shared",
                f"file:{active_file_id}:content:template_placeholder:shared",
            ],
            total_count=1,
            truncated=False,
        )
        rebuilt = _state()

        carry_forward_persisted_planner_state(
            rebuilt,
            persisted,
            attached_file_ids={active_file_id},
        )

        evidence = rebuilt.output_schema_evidence
        assert evidence is not None
        assert evidence.json_schema["properties"] == {"shared": {"type": "string"}}
        assert evidence.total_count == 1

    def test_non_truncated_placeholder_total_recounts_after_detach(self) -> None:
        active_file_id = UUID("00000000-0000-0000-0000-000000000701")
        detached_file_id = UUID("00000000-0000-0000-0000-000000000702")
        persisted = _state()
        persisted.output_schema_evidence = build_output_schema_evidence(
            json_schema={
                "type": "object",
                "properties": {
                    "kept": {"type": "string"},
                    "removed": {"type": "string"},
                },
            },
            source="template_placeholders",
            source_file_ids=(active_file_id, detached_file_id),
            confidence="high",
            evidence=[
                f"file:{active_file_id}:content:template_placeholder:kept",
                f"file:{detached_file_id}:content:template_placeholder:removed",
            ],
            total_count=2,
            truncated=False,
        )
        rebuilt = _state()

        carry_forward_persisted_planner_state(
            rebuilt,
            persisted,
            attached_file_ids={active_file_id},
        )

        evidence = rebuilt.output_schema_evidence
        assert evidence is not None
        assert evidence.json_schema["properties"] == {"kept": {"type": "string"}}
        assert evidence.total_count == 1

    def test_drops_truncated_template_evidence_when_a_source_file_is_detached(
        self,
    ) -> None:
        active_file_id = UUID("00000000-0000-0000-0000-000000000701")
        detached_file_id = UUID("00000000-0000-0000-0000-000000000702")
        persisted = _state()
        persisted.output_schema_evidence = build_output_schema_evidence(
            json_schema={
                "type": "object",
                "properties": {
                    f"field_{index}": {"type": "string"} for index in range(8)
                },
            },
            source="template_placeholders",
            source_file_ids=(active_file_id, detached_file_id),
            confidence="medium",
            evidence=[
                f"file:{active_file_id}:template_placeholder_source",
                f"file:{detached_file_id}:template_placeholder_source",
                *[
                    f"file:{active_file_id}:content:template_placeholder:field_{index}"
                    for index in range(8)
                ],
            ],
            total_count=12,
            truncated=True,
        )
        rebuilt = _state()

        carry_forward_persisted_planner_state(
            rebuilt,
            persisted,
            attached_file_ids={active_file_id},
        )

        assert rebuilt.output_schema_evidence is None

    def test_drops_attached_json_schema_evidence_after_detach(self) -> None:
        file_id = UUID("00000000-0000-0000-0000-000000000701")
        persisted = _state()
        persisted.output_schema_evidence = build_output_schema_evidence(
            json_schema={
                "type": "object",
                "properties": {"decision": {"type": "string"}},
            },
            source="attachment_json_schema",
            source_file_ids=(file_id,),
            confidence="high",
            evidence=[f"file:{file_id}:json_schema_attachment"],
        )
        rebuilt = _state()

        carry_forward_persisted_planner_state(
            rebuilt,
            persisted,
            attached_file_ids=set(),
        )

        assert rebuilt.output_schema_evidence is None

    def test_drops_template_output_schema_evidence_for_detached_file(self) -> None:
        file_id = UUID("00000000-0000-0000-0000-000000000701")
        persisted = _state()
        persisted.output_schema_evidence = build_output_schema_evidence(
            json_schema={
                "type": "object",
                "properties": {"kundnamn": {"type": "string"}},
            },
            source="template_placeholders",
            source_file_ids=(file_id,),
            confidence="high",
            evidence=[f"file:{file_id}:content:template_placeholder:kundnamn"],
        )
        rebuilt = _state()

        carry_forward_persisted_planner_state(
            rebuilt,
            persisted,
            attached_file_ids=set(),
        )

        assert rebuilt.output_schema_evidence is None

    def test_keeps_freeform_output_schema_evidence_without_attached_file(self) -> None:
        persisted_evidence = _output_schema_evidence()
        persisted = _state()
        persisted.output_schema_evidence = persisted_evidence
        rebuilt = _state()

        carry_forward_persisted_planner_state(
            rebuilt,
            persisted,
            attached_file_ids=set(),
        )

        assert rebuilt.output_schema_evidence is persisted_evidence

    def test_carries_inferred_example_schema_and_outcome_as_one_resolution(
        self,
    ) -> None:
        file_id = UUID("00000000-0000-0000-0000-000000000715")
        file_role = FileRoleEvidence(
            file_id=file_id,
            filename="expected.json",
            file_type="text",
            mimetype="application/json",
            has_readable_text=True,
            coverage="fully_seen",
            role="example_output",
            source="model",
            confidence="medium",
        )
        constraints = ExampleOutputConstraintEvidence(
            source_file_ids=[file_id],
            source_coverage=[
                ExampleOutputSourceCoverage(
                    file_id=file_id,
                    coverage="fully_seen",
                )
            ],
            headings=["Decision"],
            confidence="medium",
            citations=[
                ExampleOutputCitation(
                    source_id=f"uploaded_file:{file_id}",
                    file_id=file_id,
                    quote='"decision": "approved"',
                )
            ],
        )
        evidence = build_output_schema_evidence(
            json_schema={
                "type": "object",
                "properties": {"decision": {"type": "string"}},
            },
            source="inferred_example",
            source_file_ids=(file_id,),
            confidence="medium",
            evidence=(f"file:{file_id}:inferred_example_shape",),
        )
        outcome = ExampleOutputSchemaInferenceOutcome(
            status="inferred",
            source_file_ids=[file_id],
        )
        persisted = PlanningState.model_validate(
            {
                **dict(_state()),
                "file_roles": [file_role],
                "example_output_constraints": constraints,
                "output_schema_evidence": evidence,
                "example_output_schema_inference": outcome,
            }
        )
        rebuilt = _state()
        rebuilt.file_roles = [file_role]
        rebuilt.example_output_constraints = constraints

        carry_forward_persisted_planner_state(
            rebuilt,
            persisted,
            attached_file_ids={file_id},
        )

        assert rebuilt.output_schema_evidence == evidence
        assert rebuilt.example_output_schema_inference == outcome
        rebuilt.validated_snapshot()

    def test_detach_drops_inferred_example_schema_and_outcome(self) -> None:
        file_id = UUID("00000000-0000-0000-0000-000000000716")
        file_role = FileRoleEvidence(
            file_id=file_id,
            filename="expected.json",
            file_type="text",
            mimetype="application/json",
            has_readable_text=True,
            coverage="fully_seen",
            role="example_output",
            source="model",
            confidence="medium",
        )
        constraints = ExampleOutputConstraintEvidence(
            source_file_ids=[file_id],
            source_coverage=[
                ExampleOutputSourceCoverage(
                    file_id=file_id,
                    coverage="fully_seen",
                )
            ],
            headings=["Decision"],
            confidence="medium",
            citations=[
                ExampleOutputCitation(
                    source_id=f"uploaded_file:{file_id}",
                    file_id=file_id,
                    quote='"decision": "approved"',
                )
            ],
        )
        persisted = PlanningState.model_validate(
            {
                **dict(_state()),
                "file_roles": [file_role],
                "example_output_constraints": constraints,
                "output_schema_evidence": build_output_schema_evidence(
                    json_schema={
                        "type": "object",
                        "properties": {"decision": {"type": "string"}},
                    },
                    source="inferred_example",
                    source_file_ids=(file_id,),
                    confidence="medium",
                    evidence=(f"file:{file_id}:inferred_example_shape",),
                ),
                "example_output_schema_inference": (
                    ExampleOutputSchemaInferenceOutcome(
                        status="inferred",
                        source_file_ids=[file_id],
                    )
                ),
            }
        )
        rebuilt = _state()

        carry_forward_persisted_planner_state(
            rebuilt,
            persisted,
            attached_file_ids=set(),
        )

        assert rebuilt.output_schema_evidence is None
        assert rebuilt.example_output_schema_inference is None


class TestOutputSchemaEvidenceDerivation:
    def test_captures_explicit_output_json_schema_from_user_fence(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    message_id="msg_schema",
                    role="user",
                    content=(
                        "Flödet ska returnera detta output JSON schema:\n"
                        "```json\n"
                        "{\n"
                        '  "type": "object",\n'
                        '  "properties": {\n'
                        '    "decision": {"type": "string"},\n'
                        '    "deadline": {"type": "string"}\n'
                        "  },\n"
                        '  "required": ["decision"],\n'
                        '  "additionalProperties": false\n'
                        "}\n"
                        "```"
                    ),
                )
            ]
        )

        evidence = state.output_schema_evidence
        assert evidence is not None
        assert evidence.json_schema["type"] == "object"
        properties = evidence.json_schema["properties"]
        assert isinstance(properties, dict)
        assert "decision" in properties
        assert evidence.source == "freeform_text"
        assert evidence.confidence == "high"
        assert evidence.evidence == ["message:msg_schema", "fenced_json_schema"]

    def test_ignores_fenced_json_example_instance(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    message_id="msg_example",
                    role="user",
                    content=(
                        "Exempel på output:\n"
                        "```json\n"
                        '{"decision": "bevilja", "deadline": "2026-07-04"}\n'
                        "```"
                    ),
                )
            ]
        )

        assert state.output_schema_evidence is None

    def test_ignores_json_instance_even_near_output_schema_label(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    message_id="msg_instance",
                    role="user",
                    content=(
                        "Det här är output JSON schema:\n"
                        "```json\n"
                        '{"decision": "bevilja", "deadline": "2026-07-04"}\n'
                        "```"
                    ),
                )
            ]
        )

        assert state.output_schema_evidence is None

    def test_ignores_invalid_output_schema(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    message_id="msg_invalid_schema",
                    role="user",
                    content=(
                        "Output JSON schema:\n"
                        "```json\n"
                        "{\n"
                        '  "type": "object",\n'
                        '  "properties": {"decision": {"type": 3}}\n'
                        "}\n"
                        "```"
                    ),
                )
            ]
        )

        assert state.output_schema_evidence is None

    def test_ignores_top_level_array_output_schema_for_field_evidence(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    message_id="msg_array_schema",
                    role="user",
                    content=(
                        "Output JSON schema:\n"
                        "```json\n"
                        "{\n"
                        '  "type": "array",\n'
                        '  "items": {\n'
                        '    "type": "object",\n'
                        '    "properties": {"decision": {"type": "string"}}\n'
                        "  }\n"
                        "}\n"
                        "```"
                    ),
                )
            ]
        )

        assert state.output_schema_evidence is None

    def test_latest_valid_output_schema_evidence_wins(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    message_id="msg_old_schema",
                    role="user",
                    content=(
                        "Output JSON schema:\n"
                        "```json\n"
                        "{\n"
                        '  "type": "object",\n'
                        '  "properties": {"old_field": {"type": "string"}}\n'
                        "}\n"
                        "```"
                    ),
                ),
                ConversationMessage(
                    message_id="msg_new_schema",
                    role="user",
                    content=(
                        "Uppdaterat output JSON schema:\n"
                        "```json\n"
                        "{\n"
                        '  "type": "object",\n'
                        '  "properties": {"new_field": {"type": "string"}}\n'
                        "}\n"
                        "```"
                    ),
                ),
            ]
        )

        evidence = state.output_schema_evidence
        assert evidence is not None
        properties = evidence.json_schema["properties"]
        assert isinstance(properties, dict)
        assert list(properties) == ["new_field"]
        assert evidence.evidence == ["message:msg_new_schema", "fenced_json_schema"]

    def test_output_schema_evidence_promotes_implicit_text_output_to_json(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    message_id="msg_schema",
                    role="user",
                    content=(
                        "Skapa ett flöde som tar emot text och skriver en "
                        "strukturerad rapport.\n"
                        "Output JSON schema:\n"
                        "```json\n"
                        "{\n"
                        '  "type": "object",\n'
                        '  "properties": {"summary": {"type": "string"}},\n'
                        '  "required": ["summary"]\n'
                        "}\n"
                        "```"
                    ),
                )
            ]
        )

        slot = state.resolved_slots["terminal_output"]
        assert state.output_schema_evidence is not None
        assert slot.value == "structured_json"
        assert slot.source == "heuristic"
        assert slot.confidence == "high"
        assert "output_schema_evidence:fenced_json_schema" in slot.evidence

    def test_output_schema_evidence_reopens_older_structured_text_answer(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    message_id="msg_text_answer",
                    role="user",
                    content="Ta emot text och ge ett strukturerat textresultat.",
                    metadata={
                        "question_answer": {
                            "question_id": "final_output_mode",
                            "selected_option_id": "structured_text",
                            "selected_value": "structured_text",
                        }
                    },
                ),
                ConversationMessage(
                    message_id="msg_schema",
                    role="user",
                    content=(
                        "Använd detta output JSON schema:\n"
                        "```json\n"
                        "{\n"
                        '  "type": "object",\n'
                        '  "properties": {"decision": {"type": "string"}},\n'
                        '  "required": ["decision"]\n'
                        "}\n"
                        "```"
                    ),
                ),
            ]
        )

        assert state.output_schema_evidence is not None
        assert "terminal_output" not in state.resolved_slots

    def test_later_structured_text_answer_declines_output_schema_contract(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    message_id="msg_schema",
                    role="user",
                    content=(
                        "Använd detta output JSON schema:\n"
                        "```json\n"
                        "{\n"
                        '  "type": "object",\n'
                        '  "properties": {"decision": {"type": "string"}},\n'
                        '  "required": ["decision"]\n'
                        "}\n"
                        "```"
                    ),
                ),
                ConversationMessage(
                    message_id="msg_text_answer",
                    role="user",
                    content="Jag vill ändå ha ett strukturerat textresultat.",
                    metadata={
                        "question_answer": {
                            "question_id": "final_output_mode",
                            "selected_option_id": "structured_text",
                            "selected_value": "structured_text",
                        }
                    },
                ),
            ]
        )

        slot = state.resolved_slots["terminal_output"]
        assert state.output_schema_evidence is None
        assert slot.value == "structured_text"
        assert slot.source == "structured_answer"


class TestReturnValue:
    def test_returns_none_and_mutates_in_place(self) -> None:
        rebuilt = _state()
        persisted = _state(architecture_commit=_commit())

        result = carry_forward_persisted_planner_state(
            rebuilt, persisted, attached_file_ids=set()
        )

        assert result is None
        assert rebuilt.architecture_commit is not None


class TestPolicyDefaults:
    def test_text_runtime_input_is_inferred_from_generic_receive_text_phrase(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Skapa ett enkelt flöde som tar emot en kort text från "
                        "användaren och sammanfattar den i tre tydliga punkter."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["primary_runtime_input"]
        assert slot.value == "text"
        output_slot = state.resolved_slots["terminal_output"]
        assert output_slot.value == "structured_text"

    def test_json_in_json_out_treats_input_as_structured_json_not_text(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag vill bygga ett flöde som tar emot JSON och "
                        "returnerar JSON."
                    ),
                )
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "json"
        assert state.resolved_slots["terminal_output"].value == "structured_json"

    def test_json_with_explicit_schema_preserves_input_semantics(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Bygg ett flöde som tar emot en JSON payload och "
                        "returnerar strikt JSON enligt schemat "
                        "{name: string, amount: number, deadline: string}."
                    ),
                )
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "json"
        assert state.resolved_slots["terminal_output"].value == "structured_json"

    def test_document_to_json_extraction_keeps_document_input(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Användaren laddar upp ett PDF-avtal. Flödet ska "
                        "extrahera kundnamn, datum och riskflaggor som "
                        "strukturerad JSON och returnera strukturerad JSON "
                        "som slutresultat."
                    ),
                )
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "documents"
        assert state.resolved_slots["terminal_output"].value == "structured_json"

    def test_document_input_defaults_to_flexible_document_scope(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Build a document analysis flow that accepts uploaded "
                        "documents and produces a written report."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["document_material_scope"]
        assert slot.value == "flexible_document_case"
        assert slot.source == "policy_default"

    def test_multi_source_contradiction_prompt_resolves_compare_slots(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Användaren laddar upp 2-5 underlagsfiler. Flödet ska "
                        "extrahera nyckelfakta som strukturerad JSON från varje fil "
                        "eller från varje dokumentdel, sedan identifiera motsägelser "
                        "mellan källorna i ett separat analyssteg."
                    ),
                )
            ]
        )

        assert state.resolved_slots["document_material_scope"].value == (
            "multiple_documents_case"
        )
        assert state.resolved_slots["comparison_scope"].value == "same_run_compare"

    def test_single_document_compare_prompt_does_not_resolve_same_run_compare(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Bygg ett flöde som jämför ett avtal mot interna riktlinjer "
                        "och skriver en kort rapport."
                    ),
                )
            ]
        )

        assert "comparison_scope" not in state.resolved_slots

    def test_non_comparison_multi_file_prompt_resolves_aggregate_scope_only(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Låt användaren ladda upp flera underlagsfiler och "
                        "sammanfatta dem i en strukturerad rapport."
                    ),
                )
            ]
        )

        assert state.resolved_slots["document_material_scope"].value == (
            "multiple_documents_case"
        )
        assert "comparison_scope" not in state.resolved_slots

    def test_multi_source_comparison_leaves_report_disposition_to_classifier(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag vill ladda upp ett eller flera PDF-dokument, jämföra "
                        "dem och skapa en DOCX-rapport."
                    ),
                )
            ]
        )

        assert "report_disposition" not in state.resolved_slots

    def test_multi_source_sections_and_overview_leave_report_disposition_to_classifier(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Skapa en PDF-rapport med avsnitt per källa och en samlad "
                        "översikt i slutet från flera uppladdade dokument."
                    ),
                )
            ]
        )

        assert "report_disposition" not in state.resolved_slots

    def test_plain_multi_source_report_leaves_report_disposition_open(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content="Skapa en PDF-rapport från flera uppladdade dokument.",
                )
            ]
        )

        assert "report_disposition" not in state.resolved_slots

    def test_localized_structured_answer_resolves_report_disposition(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Skapa en PDF-rapport från flera uppladdade dokument.",
            ),
            ConversationMessage(
                role="user",
                content="Både avsnitt och översikt",
                metadata={
                    "question_answer": {
                        "question_id": "report_disposition",
                        "selected_option_ids": ["both"],
                        "selected_values": ["both"],
                    }
                },
            ),
        ]

        state = build_planning_state_from_conversation(conversation)

        slot = state.resolved_slots["report_disposition"]
        assert slot.value == "both"
        assert slot.source == "structured_answer"
        assert slot.confidence == "high"
        assert slot.evidence == ["question_answer:report_disposition"]
        assert question_is_already_resolved("report_disposition", conversation)

    def test_document_input_does_not_default_runtime_metadata(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Build a document analysis flow that accepts uploaded "
                        "documents and produces a written report."
                    ),
                )
            ]
        )

        assert "runtime_metadata_fields" not in state.resolved_slots

    def test_audio_input_does_not_default_runtime_metadata(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag vill bygga ett flöde som tar emot en ljudfil, "
                        "transkriberar samtalet och skapar ett Word-dokument."
                    ),
                )
            ]
        )

        assert "runtime_metadata_fields" not in state.resolved_slots

    def test_text_input_does_not_default_runtime_metadata(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Skapa ett flöde som tar emot text från användaren, "
                        "klassificerar ärendet och skriver ett svar."
                    ),
                )
            ]
        )

        assert "runtime_metadata_fields" not in state.resolved_slots

    def test_explicit_runtime_input_fields_resolve_heuristically(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Create a document review flow that accepts PDFs, uses "
                        "input fields for audience and detail level at runtime, "
                        "and produces a DOCX report."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "detailed_case_metadata"
        assert slot.source == "heuristic"
        assert slot.confidence == "high"

    def test_optional_checklist_or_rule_runtime_fields_are_commit_grade(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag vill bygga ett flöde för bygglovshandläggning. "
                        "Vid körning laddar jag upp en ansökan och kan också "
                        "ange vilken checklista eller regel som ska användas. "
                        "Flödet ska läsa ansökan, jämföra mot checklistan och "
                        "skapa en tydlig rapport i text."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "detailed_case_metadata"
        assert slot.source == "heuristic"
        assert slot.confidence == "high"
        assert slot.is_commit_grade

        policy = build_planner_action_policy(
            session_state=state,
            selected_discovery_question_ids=("runtime_metadata_fields",),
        )
        assert "runtime_metadata_fields" not in policy.allowed_ask_question_targets

    def test_user_supplies_prompt_resolves_detailed_runtime_metadata(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Create a flow where the user supplies customer name, "
                        "analysis request, and optional uploaded files, then "
                        "the flow produces a structured answer."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "detailed_case_metadata"
        assert slot.source == "heuristic"

    def test_swedish_audio_prompt_with_terminal_word_file_resolves_core_slots(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag vill bygga ett flöde där jag ska skicka in en ljudfil "
                        "som ska transkriberas. Jag vill ha en Word-fil i slutet."
                    ),
                )
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "audio"
        assert state.resolved_slots["terminal_output"].value == "docx_document"
        assert state.resolved_slots["docx_output_mode"].value == "generated_docx"
        assert "runtime_metadata_fields" not in state.resolved_slots

    def test_swedish_audio_docx_prompt_with_no_input_fields_keeps_metadata_absent(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag vill bygga ett flöde där användaren skickar in "
                        "mötesljud, flödet transkriberar ljudet och skapar en "
                        "Word-rapport med rubriker. Inmatningsfält behövs inte."
                    ),
                )
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "audio"
        assert state.resolved_slots["terminal_output"].value == "docx_document"
        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "no_extra_metadata"
        assert slot.source == "heuristic"

    def test_swedish_audio_recording_prompt_with_terminal_word_file_resolves_core_slots(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag vill kunna skicka in en ljudinspelning och få ett "
                        "bra Word-dokument tillbaka."
                    ),
                )
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "audio"
        assert state.resolved_slots["terminal_output"].value == "docx_document"
        assert state.resolved_slots["docx_output_mode"].value == "generated_docx"
        assert "runtime_metadata_fields" not in state.resolved_slots

    def test_explicit_audio_meeting_docx_prompt_resolves_audio_with_high_confidence(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Bygg ett flöde där användaren laddar upp en ljudfil vid "
                        "körning. Ljudfilen är en inspelning från ett "
                        "kommunfullmäktigemöte. Flödet ska först transkribera "
                        "ljudfilen till svensk text. Rubrikerna ska inte vara "
                        "inmatningsfält för användaren, utan ska skapas och fyllas "
                        "i utifrån transkriptionen. Slutresultatet ska vara ett "
                        "Word-dokument. Användaren ska bara behöva lämna in "
                        "ljudfilen vid körning."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["primary_runtime_input"]
        assert slot.value == "audio"
        assert slot.source == "heuristic"
        assert slot.confidence == "high"
        assert state.resolved_slots["terminal_output"].value == "docx_document"

    def test_explicitly_uncertain_output_format_keeps_terminal_output_unresolved(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag har en svensk ljudinspelning från ett möte och vill "
                        "göra ett flöde av den. Flödet ska ta ljudfilen, förstå "
                        "vad som sades och skapa något användbart som jag kan dela "
                        "vidare efteråt. Jag vet inte exakt vilket format "
                        "slutresultatet ska vara ännu, men det ska kännas "
                        "professionellt och lätt att läsa."
                    ),
                )
            ]
        )

        assert "terminal_output" not in state.resolved_slots

    def test_meeting_followup_goal_resolves_without_structured_analysis_default(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag har en svensk ljudinspelning från ett möte. Flödet "
                        "ska transkribera ljudet och ta fram beslut, nästa steg, "
                        "ansvariga, deadlines och öppna frågor."
                    ),
                )
            ]
        )

        goal = state.resolved_slots["post_processing_goal"]
        assert goal.value == "action_followup"
        assert goal.source == "heuristic"
        assert goal.confidence == "high"
        assert "structured_analysis_need" not in state.resolved_slots

    def test_medium_model_goal_does_not_create_structured_analysis_default(
        self,
    ) -> None:
        state = PlanningState.empty()
        state.resolved_slots = {
            "primary_runtime_input": _slot(
                name="primary_runtime_input",
                value="documents",
                source="structured_answer",
            ),
            "terminal_output": _slot(
                name="terminal_output",
                value="structured_text",
                source="structured_answer",
            ),
            "document_material_scope": _slot(
                name="document_material_scope",
                value="flexible_document_case",
                source="policy_default",
            ),
            "post_processing_goal": _slot(
                name="post_processing_goal",
                value="decision_support",
                source="model",
                confidence="medium",
            ),
        }

        apply_policy_defaults_from_resolved_slots(state, freeform_text="")

        assert "structured_analysis_need" not in state.resolved_slots

        policy = build_planner_action_policy(
            session_state=state,
            selected_discovery_question_ids=(),
        )

        assert policy.allowed_action_kinds == ("commit_architecture",)
        assert policy.allowed_ask_question_targets == ()

    def test_transcript_only_goal_does_not_derive_structured_analysis(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Transkribera ljudfilen ordagrant och skapa en PDF med "
                        "bara transkriptionen. Ingen sammanfattning eller analys."
                    ),
                )
            ]
        )

        assert state.resolved_slots["post_processing_goal"].value == (
            "stop_after_primary_operation"
        )
        assert "structured_analysis_need" not in state.resolved_slots

    def test_bare_transcription_goal_stays_unresolved(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content="Jag vill ha ett transkriberingsflöde.",
                )
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "audio"
        assert "post_processing_goal" not in state.resolved_slots
        assert "structured_analysis_need" not in state.resolved_slots

    def test_later_freeform_output_choice_overrides_earlier_uncertainty(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag har en svensk ljudinspelning. Jag vet inte exakt "
                        "vilket format slutresultatet ska vara ännu."
                    ),
                ),
                ConversationMessage(
                    role="user",
                    content="Slutresultatet ska vara ett DOCX-dokument.",
                ),
            ]
        )

        assert state.resolved_slots["terminal_output"].value == "docx_document"
        assert state.resolved_slots["docx_output_mode"].value == "generated_docx"


class TestRuntimeMetadataClassificationBoundaries:
    def test_explicit_uncertainty_block_clears_runtime_metadata_guess(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Bygg ett transkriptionsflöde där användaren laddar upp "
                        "ljud vid körning. Användaren ska inte fylla i extra "
                        "formulärfält, metadatafält eller inmatningsfält vid "
                        "körning. Rapportfält som datum, språk i ljudet, namn, "
                        "kontaktuppgifter, risker och osäkerheter ska hämtas "
                        "från ljudet och transkriberingen."
                    ),
                )
            ]
        )

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "runtime_metadata_fields",
                        "detailed_case_metadata",
                        "high",
                    ),
                )
            ),
            prompt_hash="f" * 64,
            freeform_text="",
            model_blocked_slots=frozenset({"runtime_metadata_fields"}),
        )

        assert "runtime_metadata_fields" not in state.resolved_slots

    def test_classifier_runtime_metadata_uses_typed_evidence_not_raw_text_recheck(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Bygg ett flöde där användaren laddar upp en ljudfil, "
                        "flödet transkriberar ljudet och skapar en DOCX-rapport. "
                        "Alla rapportfält ska hämtas från ljudet/transkriberingen: "
                        "datum, källa, språk i ljudet, ljudkvalitet, namn, "
                        "kontaktuppgifter, risker och osäkerheter. Om något "
                        "saknas ska rapporten skriva Ej nämnt i underlaget."
                    ),
                )
            ]
        )

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "runtime_metadata_fields",
                        "detailed_case_metadata",
                        "high",
                    ),
                )
            ),
            prompt_hash="a" * 64,
            freeform_text="",
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "detailed_case_metadata"
        assert slot.source == "model"

    def test_classifier_runtime_metadata_acceptance_does_not_require_phrase_duplication(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Skapa ett flöde som ska få ett worddokument uppladdat "
                        "som input. Varje rubrik och text skall skrivas utifrån "
                        "det ursprungliga dokumentet som helhet varje gång. "
                        "Rubrik: Resursåtgång i form av tidsuppskattning och "
                        "personella resurser. Ange i nedan tabell vilka "
                        "roller/kompetenser som behövs. Rubrik: Ekonomisk "
                        "nytta och kostnader. Ange beräknad totalkostnad för "
                        "genomförandet av lösningsförslaget. När alla steg är "
                        "klara så ska det i slutändan skapas ett "
                        "worddokument som output."
                    ),
                )
            ]
        )

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "runtime_metadata_fields",
                        "detailed_case_metadata",
                        "high",
                    ),
                )
            ),
            prompt_hash="b" * 64,
            freeform_text="",
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "detailed_case_metadata"
        assert slot.source == "model"
        assert state.resolved_slots["terminal_output"].value == "docx_document"
        assert state.resolved_slots["docx_output_mode"].value == "generated_docx"

    def test_real_runtime_fields_still_resolve_as_metadata_inputs(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Bygg ett ljudflöde där användaren ska fylla i "
                        "ärendenummer och ansvarig enhet vid körning innan "
                        "ljudet transkriberas."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "detailed_case_metadata"
        assert slot.source == "heuristic"


class TestSlotClassificationMetadataReplay:
    def test_replays_terminal_output_and_runtime_fields_from_conversation_metadata(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "The user uploads documents and provides customer name, "
                        "case type, and analysis request before receiving a report."
                    ),
                    metadata=_slot_classification_metadata(
                        _classified("primary_runtime_input", "documents", "high"),
                        _classified("terminal_output", "structured_text", "high"),
                        _classified(
                            "runtime_metadata_fields",
                            "detailed_case_metadata",
                            "high",
                        ),
                    ),
                )
            ]
        )

        assert state.resolved_slots["terminal_output"].value == "structured_text"
        assert state.resolved_slots["terminal_output"].source == "model"
        assert state.resolved_slots["runtime_metadata_fields"].value == (
            "detailed_case_metadata"
        )
        assert state.signals == []
        commit = derive_architecture_commit_draft(state)
        assert commit is not None
        assert commit.chosen_patterns == [
            "document_to_structured_report",
            "form_field_runtime_inputs",
        ]

    def test_replays_form_intake_signals_from_conversation_metadata(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Skapa ett formulär där användaren ska lämna fritext "
                        "under varje rubrik."
                    ),
                    metadata=_slot_classification_metadata(
                        form_intake=ClassifiedFormIntake(
                            needs_form_fields=True,
                            sectioned_form_intake=True,
                            confidence="high",
                            reason="runtime text per section",
                            evidence=_model_evidence("fritext under varje rubrik"),
                        )
                    ),
                )
            ]
        )

        assert [
            (signal.question_id, signal.value)
            for signal in state.signals
            if signal.question_id == "form_intake_pattern"
        ] == [
            ("form_intake_pattern", "needs_form_fields"),
            ("form_intake_pattern", "sectioned_form_intake"),
        ]

    def test_structured_answer_wins_over_classifier_metadata(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content="Make the final answer JSON.",
                    metadata={
                        "question_answer": {
                            "question_id": "final_output_mode",
                            "selected_option_id": "structured_json",
                            "selected_value": "structured_json",
                        },
                        **_slot_classification_metadata(
                            _classified("terminal_output", "structured_text", "high"),
                        ),
                    },
                )
            ]
        )

        slot = state.resolved_slots["terminal_output"]
        assert slot.value == "structured_json"
        assert slot.source == "structured_answer"

    def test_structured_report_answer_wins_after_classifier_prerequisite_replay(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content="Create a report from the supplied material.",
                    metadata=_slot_classification_metadata(
                        _classified("primary_runtime_input", "documents", "high"),
                        _classified(
                            "document_material_scope",
                            "multiple_documents_case",
                            "high",
                        ),
                        _classified("terminal_output", "pdf_document", "high"),
                        _classified(
                            "report_disposition",
                            "synthesized_overview",
                            "medium",
                        ),
                    ),
                ),
                ConversationMessage(
                    role="user",
                    content="PDF",
                    metadata={
                        "question_answer": {
                            "question_id": "final_output_mode",
                            "selected_option_ids": ["pdf_document"],
                            "selected_values": ["pdf_document"],
                        }
                    },
                ),
                ConversationMessage(
                    role="user",
                    content="Sections per source",
                    metadata={
                        "question_answer": {
                            "question_id": "report_disposition",
                            "selected_option_ids": ["per_source_sections"],
                            "selected_values": ["per_source_sections"],
                        }
                    },
                ),
            ]
        )

        terminal_output = state.resolved_slots["terminal_output"]
        report_disposition = state.resolved_slots["report_disposition"]
        assert terminal_output.value == "pdf_document"
        assert terminal_output.source == "structured_answer"
        assert report_disposition.value == "per_source_sections"
        assert report_disposition.source == "structured_answer"
        assert report_disposition.confidence == "high"

    def test_replays_metadata_in_conversation_order_with_latest_model_correction(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content="Initial preference.",
                    metadata=_slot_classification_metadata(
                        _classified("terminal_output", "structured_text", "high"),
                        prompt_hash="a" * 64,
                    ),
                ),
                ConversationMessage(
                    role="user",
                    content="Later preference.",
                    metadata=_slot_classification_metadata(
                        _classified("terminal_output", "structured_json", "high"),
                        prompt_hash="b" * 64,
                    ),
                ),
            ]
        )

        slot = state.resolved_slots["terminal_output"]
        assert slot.value == "structured_json"
        assert slot.evidence == [
            "model:terminal_output:" + "b" * 64,
            "quote:user_message:test-source:terminal_output evidence",
        ]

    def test_model_slot_without_quoted_evidence_is_ignored(self) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    ClassifiedSlot(
                        slot_name="terminal_output",
                        value="structured_text",
                        confidence="high",
                        reason="unsupported",
                    ),
                )
            ),
            prompt_hash="h" * 64,
            freeform_text="",
        )

        assert "terminal_output" not in state.resolved_slots

    def test_legacy_metadata_without_slot_classification_replays_without_error(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Skapa ett enkelt flöde som tar emot en kort text från "
                        "användaren och sammanfattar den."
                    ),
                    metadata={"legacy": "kept"},
                )
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "text"


class TestModelSlotMerge:
    def test_report_disposition_is_classified_only_for_multi_source_documents(
        self,
    ) -> None:
        state = _state()
        state.resolved_slots = {
            "primary_runtime_input": _slot(
                name="primary_runtime_input",
                value="documents",
                source="structured_answer",
            ),
            "terminal_output": _slot(
                name="terminal_output",
                value="pdf_document",
                source="structured_answer",
            ),
            "document_material_scope": _slot(
                name="document_material_scope",
                value="multiple_documents_case",
                source="structured_answer",
            ),
        }

        assert "report_disposition" in llm_resolvable_slot_values_for_state(state)

        state.resolved_slots["document_material_scope"] = _slot(
            name="document_material_scope",
            value="single_document_case",
            source="structured_answer",
        )

        assert "report_disposition" not in llm_resolvable_slot_values_for_state(state)

    def test_report_disposition_can_be_classified_with_unresolved_terminal_output(
        self,
    ) -> None:
        state = _state()
        state.resolved_slots = {
            "primary_runtime_input": _slot(
                name="primary_runtime_input",
                value="documents",
                source="structured_answer",
            ),
            "document_material_scope": _slot(
                name="document_material_scope",
                value="multiple_documents_case",
                source="structured_answer",
            ),
        }

        assert "report_disposition" in llm_resolvable_slot_values_for_state(state)

    def test_structured_io_contract_can_be_classified_when_json_side_is_unresolved(
        self,
    ) -> None:
        state = _state()
        state.resolved_slots = {
            "primary_runtime_input": _slot(
                name="primary_runtime_input",
                value="json",
                source="heuristic",
            ),
        }

        assert "structured_io_contract" in llm_resolvable_slot_values_for_state(state)

        state.resolved_slots["terminal_output"] = _slot(
            name="terminal_output",
            value="pdf_document",
            source="structured_answer",
        )

        assert "structured_io_contract" not in llm_resolvable_slot_values_for_state(
            state
        )

        state.resolved_slots = {
            "terminal_output": _slot(
                name="terminal_output",
                value="structured_json",
                source="heuristic",
            ),
        }

        assert "structured_io_contract" in llm_resolvable_slot_values_for_state(state)

    def test_structured_io_contract_is_not_classified_for_document_to_json(
        self,
    ) -> None:
        state = _state()
        state.resolved_slots = {
            "primary_runtime_input": _slot(
                name="primary_runtime_input",
                value="documents",
                source="structured_answer",
            ),
            "terminal_output": _slot(
                name="terminal_output",
                value="structured_json",
                source="heuristic",
            ),
        }

        assert "structured_io_contract" not in llm_resolvable_slot_values_for_state(
            state
        )

    def test_model_output_preserves_user_and_flow_sources_but_can_correct_summary(
        self,
    ) -> None:
        state = _state()
        state.resolved_slots = {
            "primary_runtime_input": _slot(
                name="primary_runtime_input",
                value="documents",
                source="structured_answer",
            ),
            "terminal_output": _slot(
                name="terminal_output",
                value="structured_text",
                source="requirements_summary",
            ),
            "runtime_metadata_fields": _slot(
                name="runtime_metadata_fields",
                value="no_extra_metadata",
                source="flow_default",
            ),
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified("primary_runtime_input", "text", "high"),
                    _classified("terminal_output", "pdf_document", "high"),
                    _classified(
                        "runtime_metadata_fields",
                        "detailed_case_metadata",
                        "high",
                    ),
                )
            ),
            prompt_hash="a" * 64,
            freeform_text="",
        )

        assert state.resolved_slots["primary_runtime_input"].value == "documents"
        corrected_output = state.resolved_slots["terminal_output"]
        assert corrected_output.value == "pdf_document"
        assert corrected_output.source == "model"
        assert state.resolved_slots["runtime_metadata_fields"].value == (
            "no_extra_metadata"
        )

    def test_model_post_processing_goal_uses_typed_evidence_without_raw_text_match(
        self,
    ) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "post_processing_goal",
                        "stop_after_primary_operation",
                        "high",
                    ),
                    _classified(
                        "structured_analysis_need",
                        "text_only_analysis",
                        "high",
                    ),
                )
            ),
            prompt_hash="a" * 64,
            freeform_text="Jag vill ha ett transkriberingsflöde.",
        )

        slot = state.resolved_slots["post_processing_goal"]
        assert slot.value == "stop_after_primary_operation"
        assert slot.source == "model"
        assert "structured_analysis_need" not in state.resolved_slots

    def test_model_raw_post_processing_goal_commits_when_explicit(
        self,
    ) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "post_processing_goal",
                        "stop_after_primary_operation",
                        "high",
                    ),
                )
            ),
            prompt_hash="a" * 64,
            freeform_text="Transkribera ljudet ordagrant utan sammanfattning.",
        )

        slot = state.resolved_slots["post_processing_goal"]
        assert slot.value == "stop_after_primary_operation"
        assert slot.source == "model"

    def test_replayed_model_post_processing_goal_uses_persisted_typed_evidence(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content="Jag vill ha ett transkriberingsflöde.",
                    metadata=_slot_classification_metadata(
                        _classified(
                            "post_processing_goal",
                            "stop_after_primary_operation",
                            "high",
                        ),
                        _classified(
                            "structured_analysis_need",
                            "text_only_analysis",
                            "high",
                        ),
                    ),
                )
            ]
        )

        slot = state.resolved_slots["post_processing_goal"]
        assert slot.value == "stop_after_primary_operation"
        assert slot.source == "model"
        assert "structured_analysis_need" not in state.resolved_slots

    def test_replay_accepts_typed_model_value_without_raw_phrase(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag vill bygga ett flöde som hjälper mig med dokument "
                        "jag laddar upp. Det ska läsa dokumentet och skapa "
                        "något användbart av det."
                    ),
                    metadata=_slot_classification_metadata(
                        _classified(
                            "post_processing_goal",
                            "structure_key_information",
                            "high",
                        ),
                    ),
                )
            ]
        )

        slot = state.resolved_slots["post_processing_goal"]
        assert slot.value == "structure_key_information"
        assert slot.source == "model"

    def test_model_post_processing_goal_accepts_empty_freeform_text_with_typed_evidence(
        self,
    ) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "post_processing_goal",
                        "stop_after_primary_operation",
                        "high",
                    ),
                )
            ),
            prompt_hash="a" * 64,
            freeform_text="",
        )

        slot = state.resolved_slots["post_processing_goal"]
        assert slot.value == "stop_after_primary_operation"
        assert slot.source == "model"

    def test_medium_model_output_does_not_replace_requirements_summary(self) -> None:
        state = _state()
        state.resolved_slots = {
            "terminal_output": _slot(
                name="terminal_output",
                value="structured_text",
                source="requirements_summary",
            )
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(_classified("terminal_output", "pdf_document", "medium"),)
            ),
            prompt_hash="a" * 64,
            freeform_text="",
        )

        assert state.resolved_slots["terminal_output"].value == "structured_text"

    def test_policy_defaults_generated_docx_after_model_terminal_output(self) -> None:
        state = _state()
        state.resolved_slots = {
            "terminal_output": _slot(
                name="terminal_output",
                value="docx_document",
                source="model",
            )
        }

        apply_policy_defaults_from_resolved_slots(
            state,
            freeform_text=("Slutlig DOCX-rapport skapas efter mänsklig granskning."),
        )

        slot = state.resolved_slots["docx_output_mode"]
        assert slot.value == "generated_docx"
        assert slot.source == "policy_default"

    def test_policy_defaults_do_not_mask_explicit_docx_template_mode(self) -> None:
        state = _state()
        state.resolved_slots = {
            "terminal_output": _slot(
                name="terminal_output",
                value="docx_document",
                source="model",
            )
        }

        apply_policy_defaults_from_resolved_slots(
            state,
            freeform_text="Slutrapporten ska fylla en DOCX-mall.",
        )

        assert "docx_output_mode" not in state.resolved_slots

    def test_high_model_runtime_metadata_replaces_policy_default_with_text_evidence(
        self,
    ) -> None:
        state = _state()
        state.resolved_slots = {
            "runtime_metadata_fields": _slot(
                name="runtime_metadata_fields",
                value="no_extra_metadata",
                source="policy_default",
            )
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "runtime_metadata_fields",
                        "detailed_case_metadata",
                        "high",
                    ),
                )
            ),
            prompt_hash="b" * 64,
            freeform_text=(
                "Användaren ska fylla i ärendenummer och kommun vid körning."
            ),
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "detailed_case_metadata"
        assert slot.source == "model"
        assert slot.evidence == [
            "model:runtime_metadata_fields:" + "b" * 64,
            "quote:user_message:test-source:runtime_metadata_fields evidence",
        ]

    def test_high_model_runtime_metadata_without_raw_text_match_replaces_policy_default(
        self,
    ) -> None:
        state = _state()
        state.resolved_slots = {
            "runtime_metadata_fields": _slot(
                name="runtime_metadata_fields",
                value="no_extra_metadata",
                source="policy_default",
            )
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "runtime_metadata_fields",
                        "detailed_case_metadata",
                        "high",
                    ),
                )
            ),
            prompt_hash="b" * 64,
            freeform_text=(
                "Läs dokumentet och extrahera dokumenttyp, datum, författare "
                "och slutsatser från källmaterialet."
            ),
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "detailed_case_metadata"
        assert slot.source == "model"

    def test_medium_model_output_does_not_replace_policy_default(self) -> None:
        state = _state()
        state.resolved_slots = {
            "runtime_metadata_fields": _slot(
                name="runtime_metadata_fields",
                value="no_extra_metadata",
                source="policy_default",
            )
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "runtime_metadata_fields",
                        "detailed_case_metadata",
                        "medium",
                    ),
                )
            ),
            prompt_hash="c" * 64,
            freeform_text="",
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "no_extra_metadata"
        assert slot.source == "policy_default"

    def test_medium_model_output_replaces_conflicting_high_runtime_field_heuristic(
        self,
    ) -> None:
        state = _state()
        state.resolved_slots = {
            "runtime_metadata_fields": _slot(
                name="runtime_metadata_fields",
                value="detailed_case_metadata",
                source="heuristic",
                confidence="high",
            )
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "runtime_metadata_fields",
                        "basic_case_metadata",
                        "medium",
                    ),
                )
            ),
            prompt_hash="c" * 64,
            freeform_text=(
                "Vid körning kan användaren ange vilken checklista eller regel "
                "som ska användas."
            ),
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "basic_case_metadata"
        assert slot.source == "model"
        assert slot.confidence == "medium"

    def test_medium_model_output_replaces_heuristic_and_fills_missing_slot(
        self,
    ) -> None:
        state = _state()
        state.resolved_slots = {
            "terminal_output": _slot(
                name="terminal_output",
                value="structured_text",
                source="heuristic",
                confidence="medium",
            )
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified("terminal_output", "pdf_document", "medium"),
                    _classified("primary_runtime_input", "text", "medium"),
                )
            ),
            prompt_hash="d" * 64,
            freeform_text="",
        )

        assert state.resolved_slots["terminal_output"].value == "pdf_document"
        assert state.resolved_slots["primary_runtime_input"].value == "text"

    def test_model_output_accepts_json_primary_runtime_input(self) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified("primary_runtime_input", "json", "high"),
                    _classified("terminal_output", "structured_json", "high"),
                )
            ),
            prompt_hash="d" * 64,
            freeform_text="",
        )

        assert state.resolved_slots["primary_runtime_input"].value == "json"
        assert state.resolved_slots["primary_runtime_input"].source == "model"
        assert state.resolved_slots["terminal_output"].value == "structured_json"

    def test_model_output_persists_secondary_result_obligations(self) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(secondary_obligations=("risks", "actions")),
            prompt_hash="a" * 64,
            freeform_text=(
                "Jämför dokumenten och ta också fram risker och rekommenderade åtgärder."
            ),
        )

        assert [
            signal.value
            for signal in state.signals
            if signal.question_id == "result_obligation"
        ] == ["risks", "actions"]

    def test_model_form_intake_persists_planning_signals(self) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                form_intake=ClassifiedFormIntake(
                    needs_form_fields=True,
                    sectioned_form_intake=True,
                    confidence="high",
                    reason="runtime text per section",
                    evidence=_model_evidence("fritext under varje rubrik"),
                )
            ),
            prompt_hash="b" * 64,
            freeform_text="",
        )

        assert [
            (signal.question_id, signal.value, signal.source)
            for signal in state.signals
        ] == [
            ("form_intake_pattern", "needs_form_fields", "model"),
            ("form_intake_pattern", "sectioned_form_intake", "model"),
        ]
        assert state.signals[0].provenance == [
            "model:form_intake_pattern:" + "b" * 64,
            "quote:user_message:test-source:fritext under varje rubrik",
        ]

    def test_model_form_intake_without_quoted_evidence_is_ignored(self) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                form_intake=ClassifiedFormIntake(
                    needs_form_fields=True,
                    sectioned_form_intake=False,
                    confidence="high",
                    reason="unsupported",
                )
            ),
            prompt_hash="c" * 64,
            freeform_text="",
        )

        assert state.signals == []

    def test_high_model_output_can_displace_high_confidence_input_heuristic(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Bygg ett flöde där användaren laddar upp en ljudfil vid "
                        "körning. Slutresultatet ska vara ett Word-dokument. "
                        "Användaren ska bara behöva lämna in ljudfilen vid körning."
                    ),
                )
            ]
        )

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "primary_runtime_input",
                        "text_and_documents",
                        "high",
                    ),
                )
            ),
            prompt_hash="d" * 64,
            freeform_text="",
        )

        assert (
            state.resolved_slots["primary_runtime_input"].value == "text_and_documents"
        )
        assert state.resolved_slots["primary_runtime_input"].source == "model"
        assert state.resolved_slots["primary_runtime_input"].confidence == "high"

    def test_low_model_slot_is_not_persisted(self) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(_classified("terminal_output", "pdf_document", "low"),)
            ),
            prompt_hash="e" * 64,
            freeform_text="",
        )

        assert state.resolved_slots == {}

    def test_unknown_model_slot_is_not_persisted(self) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(_classified("primary_runtime_input", "unknown", "high"),)
            ),
            prompt_hash="f" * 64,
            freeform_text="",
        )

        assert state.resolved_slots == {}

    def test_model_blocked_slot_clears_nonprotected_guess(self) -> None:
        state = _state()
        state.resolved_slots = {
            "terminal_output": _slot(
                name="terminal_output",
                value="structured_text",
                source="heuristic",
            )
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(_classified("terminal_output", "structured_text", "high"),)
            ),
            prompt_hash="f" * 64,
            freeform_text="",
            model_blocked_slots=frozenset({"terminal_output"}),
        )

        assert "terminal_output" not in state.resolved_slots

    def test_model_blocked_slot_preserves_structured_answer(self) -> None:
        state = _state()
        state.resolved_slots = {
            "terminal_output": _slot(
                name="terminal_output",
                value="docx_document",
                source="structured_answer",
            )
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(_classified("terminal_output", "structured_text", "high"),)
            ),
            prompt_hash="f" * 64,
            freeform_text="",
            model_blocked_slots=frozenset({"terminal_output"}),
        )

        assert state.resolved_slots["terminal_output"].value == "docx_document"
        assert state.resolved_slots["terminal_output"].source == "structured_answer"

    def test_non_llm_resolvable_slots_are_not_persisted(self) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified("docx_output_mode", "template_fill_docx", "high"),
                    _classified(
                        "pdf_generation_mode",
                        "pdf_template_requested",
                        "high",
                    ),
                )
            ),
            prompt_hash="g" * 64,
            freeform_text="",
        )

        assert state.resolved_slots == {}

    def test_model_file_role_overlays_unconfirmed_context_only_role(self) -> None:
        file_id = "00000000-0000-0000-0000-000000000701"
        state = _state()
        state.file_roles = [
            FileRoleEvidence(
                file_id=file_id,
                filename="bilaga.pdf",
                file_type="document",
                mimetype="application/pdf",
                has_readable_text=True,
                coverage="fully_seen",
                role="context_only",
                source="heuristic",
                confidence="low",
                evidence=["fallback:unclassified_file"],
            )
        ]

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                file_roles=(
                    ClassifiedFileRole(
                        file_id=UUID(file_id),
                        role="example_output",
                        confidence="medium",
                        reason="conversation says the upload is an example report",
                        evidence=_model_evidence("så här ska rapporten se ut"),
                    ),
                )
            ),
            prompt_hash="h" * 64,
            freeform_text="",
        )

        role = state.file_roles[0]
        assert role.role == "example_output"
        assert role.source == "model"
        assert role.confidence == "medium"
        assert role.evidence == [
            "fallback:unclassified_file",
            f"model:file_role:{'h' * 64}",
            "quote:user_message:test-source:så här ska rapporten se ut",
        ]
        assert role.candidate_roles == ["context_only", "example_output"]

    def test_model_example_output_constraints_follow_current_file_evidence(
        self,
    ) -> None:
        file_id = UUID("00000000-0000-0000-0000-000000000705")
        state = _state()
        state.file_roles = [
            FileRoleEvidence(
                file_id=file_id,
                filename="exempel.pdf",
                file_type="document",
                mimetype="application/pdf",
                has_readable_text=True,
                coverage="fully_seen",
                role="example_output",
                source="model",
                confidence="medium",
                evidence=["model:file_role"],
            )
        ]
        constraints = ExampleOutputConstraintEvidence(
            source_file_ids=[file_id],
            source_coverage=[
                ExampleOutputSourceCoverage(
                    file_id=file_id,
                    coverage="fully_seen",
                )
            ],
            headings=["Summary"],
            style_constraints=[
                ExampleOutputStyleConstraint(
                    category="tone",
                    description="Formal",
                )
            ],
            confidence="medium",
            citations=[
                ExampleOutputCitation(
                    source_id=f"uploaded_file:{file_id}",
                    file_id=file_id,
                    quote="# Summary",
                )
            ],
        )

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                example_output_constraints=constraints,
            ),
            prompt_hash="x" * 64,
            freeform_text="",
        )

        assert state.example_output_constraints == constraints

    def test_model_reclassification_atomically_clears_inferred_example_state(
        self,
    ) -> None:
        file_id = UUID("00000000-0000-0000-0000-000000000707")
        state = _state()
        state.file_roles = [_example_output_file_role(file_id)]
        state.example_output_constraints = _example_output_constraints(
            file_id,
            heading="Previous",
        )
        _apply_inferred_example_schema(state, file_id=file_id)

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                file_roles=(
                    ClassifiedFileRole(
                        file_id=file_id,
                        role="context_only",
                        confidence="medium",
                        reason="The attachment is background material.",
                        evidence=_model_evidence("background material"),
                    ),
                )
            ),
            prompt_hash="r" * 64,
            freeform_text="",
        )

        assert state.file_roles[0].role == "context_only"
        assert state.example_output_constraints is None
        assert state.output_schema_evidence is None
        assert state.example_output_schema_inference is None
        assert state.validated_snapshot() == state

    def test_model_constraint_replacement_atomically_drops_stale_inference(
        self,
    ) -> None:
        first_file_id = UUID("00000000-0000-0000-0000-000000000708")
        second_file_id = UUID("00000000-0000-0000-0000-000000000709")
        state = _state()
        state.file_roles = [
            _example_output_file_role(first_file_id),
            _example_output_file_role(second_file_id),
        ]
        state.example_output_constraints = _example_output_constraints(
            first_file_id,
            heading="Previous",
        )
        _apply_inferred_example_schema(state, file_id=first_file_id)
        replacement = _example_output_constraints(
            second_file_id,
            heading="Current",
        )

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(example_output_constraints=replacement),
            prompt_hash="s" * 64,
            freeform_text="",
        )

        assert state.example_output_constraints == replacement
        assert state.output_schema_evidence is None
        assert state.example_output_schema_inference is None
        assert state.validated_snapshot() == state

    @pytest.mark.parametrize(
        ("role", "coverage"),
        [
            ("context_only", "fully_seen"),
            ("example_output", "excerpt_truncated"),
        ],
    )
    def test_model_example_output_constraints_reject_stale_file_evidence(
        self,
        role: FileRole,
        coverage: AttachmentCoverage,
    ) -> None:
        file_id = UUID("00000000-0000-0000-0000-000000000706")
        state = _state()
        state.file_roles = [
            FileRoleEvidence(
                file_id=file_id,
                filename="exempel.pdf",
                file_type="document",
                mimetype="application/pdf",
                has_readable_text=True,
                coverage=coverage,
                role=role,
                source="model",
                confidence="medium",
                evidence=["model:file_role"],
            )
        ]
        constraints = ExampleOutputConstraintEvidence(
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
        )

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                example_output_constraints=constraints,
            ),
            prompt_hash="y" * 64,
            freeform_text="",
        )

        assert state.example_output_constraints is None

    def test_model_file_role_without_quoted_evidence_is_ignored(self) -> None:
        file_id = "00000000-0000-0000-0000-000000000703"
        state = _state()
        state.file_roles = [
            FileRoleEvidence(
                file_id=file_id,
                filename="bilaga.pdf",
                file_type="document",
                mimetype="application/pdf",
                has_readable_text=True,
                coverage="fully_seen",
                role="context_only",
                source="heuristic",
                confidence="low",
                evidence=["fallback:unclassified_file"],
            )
        ]

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                file_roles=(
                    ClassifiedFileRole(
                        file_id=UUID(file_id),
                        role="example_output",
                        confidence="medium",
                        reason="unsupported file role",
                    ),
                )
            ),
            prompt_hash="h" * 64,
            freeform_text="",
        )

        role = state.file_roles[0]
        assert role.role == "context_only"
        assert role.source == "heuristic"
        assert role.evidence == ["fallback:unclassified_file"]

    def test_model_file_role_does_not_replace_structural_runtime_sample(self) -> None:
        file_id = "00000000-0000-0000-0000-000000000702"
        state = _state()
        state.file_roles = [
            FileRoleEvidence(
                file_id=file_id,
                filename="meeting.m4a",
                file_type="audio",
                mimetype="audio/mp4",
                has_readable_text=True,
                coverage="fully_seen",
                role="runtime_input_sample",
                source="heuristic",
                confidence="high",
                evidence=["file_type:audio"],
            )
        ]

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                file_roles=(
                    ClassifiedFileRole(
                        file_id=UUID(file_id),
                        role="example_output",
                        confidence="medium",
                        reason="speculative file role",
                        evidence=_model_evidence("maybe an example"),
                    ),
                )
            ),
            prompt_hash="i" * 64,
            freeform_text="",
        )

        role = state.file_roles[0]
        assert role.role == "runtime_input_sample"
        assert role.source == "heuristic"
        assert role.evidence == ["file_type:audio"]

    def test_model_file_role_does_not_replace_structural_template(self) -> None:
        file_id = "00000000-0000-0000-0000-000000000704"
        state = _state()
        state.file_roles = [
            FileRoleEvidence(
                file_id=file_id,
                filename="mall.docx",
                file_type="document",
                mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                has_readable_text=True,
                coverage="fully_seen",
                role="template",
                source="heuristic",
                confidence="medium",
                evidence=["content:template_placeholder:kundnamn"],
            )
        ]

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                file_roles=(
                    ClassifiedFileRole(
                        file_id=UUID(file_id),
                        role="example_output",
                        confidence="high",
                        reason="semantic role from conversation",
                        evidence=_model_evidence("så här ska rapporten se ut"),
                    ),
                )
            ),
            prompt_hash="j" * 64,
            freeform_text="",
        )

        role = state.file_roles[0]
        assert role.role == "template"
        assert role.source == "heuristic"
        assert role.evidence == ["content:template_placeholder:kundnamn"]

    def test_prompt_hash_is_required(self) -> None:
        state = _state()

        with pytest.raises(ValueError, match="prompt_hash"):
            merge_llm_resolved_slots(
                state,
                SlotClassificationResult(
                    slots=(_classified("primary_runtime_input", "text", "high"),)
                ),
                prompt_hash="",
                freeform_text="",
            )


def _mapped_file_limit_conversation(
    *,
    selected_value: str | None = None,
    custom_value: str | None = None,
) -> list[ConversationMessage]:
    mapped_answer: dict[str, object] = {"question_id": "mapped_file_limit"}
    if selected_value is not None:
        mapped_answer.update(
            selected_option_id=selected_value,
            selected_value=selected_value,
        )
    if custom_value is not None:
        mapped_answer["custom_value"] = custom_value
    return [
        ConversationMessage(
            role="user",
            content="Process several documents in one run.",
            metadata={
                "question_answer": {
                    "question_id": "primary_runtime_input",
                    "selected_option_id": "documents",
                    "selected_value": "documents",
                }
            },
        ),
        ConversationMessage(
            role="user",
            content="Several documents.",
            metadata={
                "question_answer": {
                    "question_id": "document_material_scope",
                    "selected_option_id": "multiple_documents_case",
                    "selected_value": "multiple_documents_case",
                }
            },
        ),
        ConversationMessage(
            role="user",
            content=custom_value or selected_value or "",
            metadata={"question_answer": mapped_answer},
        ),
    ]


def test_mapped_file_limit_requires_explicit_policy_confirmation() -> None:
    state = build_planning_state_from_conversation(
        _mapped_file_limit_conversation(),
        mapped_execution_policy=FlowMappedExecutionPolicy(
            max_provider_calls_per_mapped_step=8
        ),
    )

    assert state.mapped_file_limit.accepted_value is None
    assert state.mapped_file_limit.proposed_value == 8
    assert state.mapped_file_limit.diagnostic == "confirmation_required"


def test_mapped_file_limit_accepts_organization_limit_with_provenance() -> None:
    state = build_planning_state_from_conversation(
        _mapped_file_limit_conversation(selected_value="organization_limit"),
        mapped_execution_policy=FlowMappedExecutionPolicy(
            max_provider_calls_per_mapped_step=8
        ),
    )

    assert state.mapped_file_limit.accepted_value == 8
    assert state.mapped_file_limit.provenance == "policy_default"
    assert state.mapped_file_limit.diagnostic is None


def test_mapped_file_limit_accepts_lower_custom_value_as_authored() -> None:
    state = build_planning_state_from_conversation(
        _mapped_file_limit_conversation(custom_value="3"),
        mapped_execution_policy=FlowMappedExecutionPolicy(
            max_provider_calls_per_mapped_step=8
        ),
    )

    assert state.mapped_file_limit.accepted_value == 3
    assert state.mapped_file_limit.provenance == "authored"
    assert state.mapped_file_limit.diagnostic is None


@pytest.mark.parametrize(
    ("custom_value", "diagnostic"),
    [
        ("true", "not_an_integer"),
        ("1.5", "not_an_integer"),
        ("0", "not_positive"),
        ("-1", "not_positive"),
        ("9", "exceeds_policy"),
    ],
)
def test_mapped_file_limit_rejects_non_commit_grade_custom_values(
    custom_value: str,
    diagnostic: str,
) -> None:
    state = build_planning_state_from_conversation(
        _mapped_file_limit_conversation(custom_value=custom_value),
        mapped_execution_policy=FlowMappedExecutionPolicy(
            max_provider_calls_per_mapped_step=8
        ),
    )

    assert state.mapped_file_limit.accepted_value is None
    assert state.mapped_file_limit.provenance is None
    assert state.mapped_file_limit.diagnostic == diagnostic


def test_mapped_file_limit_stays_uncommitted_when_policy_is_unset() -> None:
    state = build_planning_state_from_conversation(
        _mapped_file_limit_conversation(selected_value="organization_limit"),
        mapped_execution_policy=FlowMappedExecutionPolicy(),
    )

    assert state.mapped_file_limit.accepted_value is None
    assert state.mapped_file_limit.proposed_value is None
    assert state.mapped_file_limit.diagnostic == "policy_unset"
