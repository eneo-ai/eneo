"""Unit tests for `planning_state_builder.carry_forward_persisted_planner_state`.

The helper is the single place the save path merges planner-owned
architecture_commit from the previously persisted state onto a freshly
rebuilt one. Integration tests pin the savepoint wiring; these unit tests
pin the merge semantics in isolation so regressions show up at the merge
layer, not two containers deep.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from eneo.flows.ai_builder import ai_builder_discovery_runtime as discovery_runtime
from eneo.flows.ai_builder.ai_builder_action_policy import (
    build_planner_action_policy,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    SlotClassificationMetadata,
    SlotClassificationNamedResultEvidenceMetadata,
    metadata_with_slot_classification,
    slot_classification_metadata_from_attempt,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    RequirementsSummaryPayload,
    ResolvedRequirementPayload,
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    build_schema_evidence,
    derive_freeform_schema_candidates,
)
from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    CheckpointUpdateOperation,
    ClassifiedCheckpointUpdate,
    ClassifiedEvidence,
    ClassifiedFileRole,
    ClassifiedFormIntake,
    ClassifiedNamedResultDelta,
    ClassifiedNamedResultEvidence,
    ClassifiedSlot,
    SlotClassificationAttempt,
    SlotClassificationConfidence,
    SlotClassificationEvidenceLevel,
    SlotClassificationInput,
    SlotClassificationResult,
    SlotClassificationSource,
    parse_slot_classification_response,
)
from eneo.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    NAMED_RESULT_EVIDENCE_MAX_CITATIONS,
    NAMED_RESULT_EVIDENCE_MAX_ITEMS,
    NAMED_RESULT_PROVENANCE_MAX_ITEMS,
    PLANNER_CONTRACT_VERSION,
    PLANNING_STATE_PAYLOAD_CAP_BYTES,
    ArchitectureCommit,
    AttachmentCoverage,
    CheckpointProducerKind,
    ExampleOutputCitation,
    ExampleOutputConstraintEvidence,
    ExampleOutputSchemaInferenceOutcome,
    ExampleOutputSourceCoverage,
    ExampleOutputStyleConstraint,
    FileRole,
    FileRoleEvidence,
    MappedFileLimit,
    NamedResultDeclaredShape,
    NamedResultEvidence,
    PlanningState,
    ResolvedSlot,
    SchemaEvidence,
    SchemaResolution,
    SlotConfidence,
    SlotSource,
    StepTriple,
)
from eneo.flows.ai_builder.planning_state_builder import (
    apply_policy_defaults_from_resolved_slots,
    build_planning_state_from_conversation,
    carry_forward_persisted_planner_state,
    carry_forward_turn_resolved_planner_state,
    llm_resolvable_slot_values_for_state,
    merge_llm_resolved_slots,
    resolve_docx_mode_from_template_evidence,
)
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
from eneo.flows.flow_review_policy import FlowStepReviewMode


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


def test_rebuild_restores_typed_requirements_without_reading_display_copy() -> None:
    payload = RequirementsSummaryPayload(
        requirements_version="0" * 64,
        summary="Checkpoint ready.",
        key_decisions=[],
        input_description="Input confirmed.",
        output_description="Output confirmed.",
        resolved_requirements=[
            ResolvedRequirementPayload(
                requirement_id="primary_runtime_input",
                selected_value="documents",
            ),
            ResolvedRequirementPayload(
                requirement_id="terminal_output",
                selected_value="structured_text",
            ),
            ResolvedRequirementPayload(
                requirement_id="document_material_scope",
                selected_value="flexible_document_case",
            ),
            ResolvedRequirementPayload(
                requirement_id="runtime_metadata_fields",
                selected_value="no_extra_metadata",
            ),
        ],
    )
    version = payload.requirements_version

    state = build_planning_state_from_conversation(
        [
            ConversationMessage(
                role="assistant",
                content="Requirements presented to user.",
                metadata={
                    "requirements_summary": payload.model_dump(mode="json"),
                    "requirements_version": version,
                },
            ),
            ConversationMessage(
                role="user",
                content="",
                metadata={
                    "requirements_confirmed": True,
                    "requirements_version": version,
                },
            ),
        ]
    )

    assert {
        name: (slot.value, slot.source, slot.confidence)
        for name, slot in state.resolved_slots.items()
    } == {
        "document_material_scope": (
            "flexible_document_case",
            "requirements_summary",
            "high",
        ),
        "primary_runtime_input": ("documents", "requirements_summary", "high"),
        "runtime_metadata_fields": (
            "no_extra_metadata",
            "requirements_summary",
            "high",
        ),
        "terminal_output": ("structured_text", "requirements_summary", "high"),
    }


def test_rebuild_uses_latest_confirmed_runtime_metadata_field_set() -> None:
    conversation = [
        ConversationMessage(
            message_id="answer-old",
            role="user",
            content="Old field",
            metadata={
                "question_answer": {
                    "question_id": "runtime_metadata_field_details",
                    "input_fields": [
                        {
                            "value": {"name": "old", "label": "Old"},
                            "purpose": "shape_result",
                        }
                    ],
                }
            },
        ),
        ConversationMessage(
            message_id="answer-latest",
            role="user",
            content="Case id",
            metadata={
                "question_answer": {
                    "question_id": "runtime_metadata_field_details",
                    "input_fields": [
                        {
                            "value": {"name": "case_id", "label": "Case id"},
                            "purpose": "interpret_input",
                        }
                    ],
                }
            },
        ),
    ]

    state = build_planning_state_from_conversation(conversation)

    assert len(state.input_fields) == 1
    assert state.input_fields[0].value.variable_name == "case_id"
    assert state.input_fields[0].value.provenance == "user_confirmed"
    assert state.input_fields[0].purpose == "interpret_input"
    assert state.input_fields[0].structured_answer_message_id == "answer-latest"


def test_rebuild_does_not_admit_unconfirmed_requirements_projection() -> None:
    payload = RequirementsSummaryPayload(
        requirements_version="0" * 64,
        summary="Checkpoint ready.",
        key_decisions=[],
        input_description="Input pending confirmation.",
        output_description="Output pending confirmation.",
        resolved_requirements=[
            ResolvedRequirementPayload(
                requirement_id="primary_runtime_input",
                selected_value="documents",
            ),
            ResolvedRequirementPayload(
                requirement_id="terminal_output",
                selected_value="structured_text",
            ),
        ],
    )
    version = payload.requirements_version

    state = build_planning_state_from_conversation(
        [
            ConversationMessage(
                role="assistant",
                content="Requirements presented to user.",
                metadata={
                    "requirements_summary": payload.model_dump(mode="json"),
                    "requirements_version": version,
                },
            )
        ]
    )

    assert all(
        slot.source != "requirements_summary" for slot in state.resolved_slots.values()
    )
    assert not any(slot.is_commit_grade for slot in state.resolved_slots.values())


def _output_schema_evidence() -> SchemaEvidence:
    return build_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {"decision": {"type": "string"}},
            "required": ["decision"],
            "additionalProperties": False,
        },
        source="declared_schema",
        confidence="high",
        evidence=["message:msg_schema", "fenced_json_schema"],
    )


def _input_schema_evidence() -> SchemaEvidence:
    return build_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {"arendenummer": {"type": "string"}},
            "required": ["arendenummer"],
            "additionalProperties": False,
        },
        source="declared_schema",
        confidence="high",
        evidence=["message:msg_input_schema", "fenced_json_schema"],
    )


def _pasted_schema_conversation() -> list[ConversationMessage]:
    """The user's own message offering both schemas as fenced JSON."""

    return [
        ConversationMessage(
            role="user",
            content=(
                "Indata:\n```json\n"
                f"{json.dumps(_input_schema_evidence().json_schema)}"
                "\n```\nUtdata:\n```json\n"
                f"{json.dumps(_output_schema_evidence().json_schema)}"
                "\n```"
            ),
        )
    ]


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
    state.replace_schema_resolution(
        input_evidence=state.input_schema_evidence,
        output_evidence=build_schema_evidence(
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
        evidence=[
            f"quote:user_message:test:{name}"
            if source == "model"
            else f"{source}:{name}"
        ],
        confidence=resolved_confidence,
        evidence_level="inferred" if source == "model" else None,
    )


def _classified(
    slot_name: str,
    value: str,
    confidence: SlotClassificationConfidence,
    *,
    evidence: tuple[str, ...] | None = None,
    evidence_level: SlotClassificationEvidenceLevel = "inferred",
) -> ClassifiedSlot:
    return ClassifiedSlot(
        slot_name=slot_name,
        value=value,
        confidence=confidence,
        reason=f"{slot_name} classified",
        evidence=_model_evidence(*(evidence or (f"{slot_name} evidence",))),
        evidence_level=evidence_level,
    )


def _model_evidence(
    *quotes: str,
    source_id: str = "user_message:test-source",
) -> tuple[ClassifiedEvidence, ...]:
    return tuple(
        ClassifiedEvidence(source_id=source_id, quote=quote) for quote in quotes
    )


def _parse_named_result_delta(
    *,
    names: tuple[str, ...],
    removed_names: tuple[str, ...] = (),
    confidence: SlotClassificationConfidence = "high",
    classification_input: SlotClassificationInput,
) -> SlotClassificationResult:
    parsed = parse_slot_classification_response(
        json.dumps(
            {
                "slots": [],
                "file_roles": [],
                "checkpoint_updates": [],
                "form_intake": None,
                "named_result_evidence": {
                    "operation": "update",
                    "names": list(names),
                    "removed_names": list(removed_names),
                    "confidence": confidence,
                    "reason": "The user explicitly changed named results.",
                    "evidence": [
                        {
                            "source_id": source.source_id,
                            "quote": source.text,
                        }
                        for source in classification_input.sources
                    ],
                },
                "example_output_constraints": None,
                "schema_direction": None,
                "secondary_obligations": [],
                "assumptions": [],
                "contradictions": [],
            }
        ),
        allowed_slot_values={},
        classification_input=classification_input,
    )
    assert parsed is not None
    assert parsed.named_result_evidence is not None
    return parsed


def _slot_classification_metadata(
    *slots: ClassifiedSlot,
    prompt_hash: str = "a" * 64,
    form_intake: ClassifiedFormIntake | None = None,
    checkpoint_updates: tuple[ClassifiedCheckpointUpdate, ...] = (),
) -> dict[str, object]:
    evidence_quotes = [item.quote for slot in slots for item in slot.evidence]
    if form_intake is not None:
        evidence_quotes.extend(item.quote for item in form_intake.evidence)
    evidence_quotes.extend(
        item.quote for update in checkpoint_updates for item in update.evidence
    )
    result = SlotClassificationResult(
        slots=slots,
        form_intake=form_intake,
        checkpoint_updates=checkpoint_updates,
    )
    metadata = slot_classification_metadata_from_attempt(
        SlotClassificationAttempt(outcome="resolved", result=result),
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
    result = SlotClassificationResult(
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
    )
    metadata = slot_classification_metadata_from_attempt(
        SlotClassificationAttempt(outcome="resolved", result=result),
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


class TestAttachmentDerivedSlotPreservation:
    """Slots resolved from file bytes cannot be rebuilt from conversation.

    The live defect (2026-08-07): dispatch resolved
    `docx_output_mode=template_fill_docx` from placeholders found in the
    uploaded template; `commit_turn`'s rebuild lost the slot, re-derived
    `pass_through`, and the commit-invariance guard refused every commit —
    the whole docx-template case family died deterministically as
    `provider_outcome_unknown`.
    """

    @staticmethod
    def _structural_slot(file_id: UUID) -> ResolvedSlot:
        return ResolvedSlot(
            name="docx_output_mode",
            value="template_fill_docx",
            source="attachment_structure",
            evidence=[f"file:{file_id}:template_placeholders:kundnamn"],
            confidence="high",
        )

    def test_carries_slot_while_its_file_is_attached(self) -> None:
        file_id = uuid4()
        rebuilt = _state()
        persisted = _state()
        persisted.resolved_slots["docx_output_mode"] = self._structural_slot(file_id)

        carry_forward_persisted_planner_state(
            rebuilt, persisted, attached_file_ids={file_id}
        )

        carried = rebuilt.resolved_slots.get("docx_output_mode")
        assert carried is not None
        assert carried.value == "template_fill_docx"
        assert carried.is_commit_grade

    def test_drops_carried_slot_when_the_terminal_is_no_longer_docx(self) -> None:
        # Keeping a file attached preserves its structural mode, but choosing a
        # different terminal contradicts it outright — and no later pass
        # reconciles dependent slots on this path.
        file_id = uuid4()
        rebuilt = _state()
        rebuilt.resolved_slots["terminal_output"] = ResolvedSlot(
            name="terminal_output",
            value="pdf_document",
            source="structured_answer",
            evidence=["question_answer:terminal_output"],
            confidence="high",
        )
        persisted = _state()
        persisted.resolved_slots["docx_output_mode"] = self._structural_slot(file_id)

        carry_forward_persisted_planner_state(
            rebuilt, persisted, attached_file_ids={file_id}
        )

        assert "docx_output_mode" not in rebuilt.resolved_slots

    def test_drops_slot_when_its_file_is_detached(self) -> None:
        rebuilt = _state()
        persisted = _state()
        persisted.resolved_slots["docx_output_mode"] = self._structural_slot(uuid4())

        carry_forward_persisted_planner_state(
            rebuilt, persisted, attached_file_ids=set()
        )

        assert "docx_output_mode" not in rebuilt.resolved_slots

    def test_never_overwrites_a_commit_grade_rebuilt_slot(self) -> None:
        # The user's explicit answer in conversation outranks structure.
        file_id = uuid4()
        rebuilt = _state()
        rebuilt.resolved_slots["docx_output_mode"] = ResolvedSlot(
            name="docx_output_mode",
            value="generated_docx",
            source="structured_answer",
            evidence=["answer:generated_docx"],
            confidence="high",
        )
        persisted = _state()
        persisted.resolved_slots["docx_output_mode"] = self._structural_slot(file_id)

        carry_forward_persisted_planner_state(
            rebuilt, persisted, attached_file_ids={file_id}
        )

        assert rebuilt.resolved_slots["docx_output_mode"].value == "generated_docx"

    def test_replaces_a_policy_default_rebuilt_slot(self) -> None:
        file_id = uuid4()
        rebuilt = _state()
        rebuilt.resolved_slots["docx_output_mode"] = ResolvedSlot(
            name="docx_output_mode",
            value="generated_docx",
            source="policy_default",
            evidence=[],
            confidence="low",
        )
        persisted = _state()
        persisted.resolved_slots["docx_output_mode"] = self._structural_slot(file_id)

        carry_forward_persisted_planner_state(
            rebuilt, persisted, attached_file_ids={file_id}
        )

        assert rebuilt.resolved_slots["docx_output_mode"].value == "template_fill_docx"

    def test_conversation_derived_slots_are_not_carried(self) -> None:
        # Conversation-derived slots are the rebuild's job; carrying them
        # would let stale answers shadow the current conversation.
        rebuilt = _state()
        persisted = _state()
        persisted.resolved_slots["terminal_output"] = ResolvedSlot(
            name="terminal_output",
            value="docx_document",
            source="structured_answer",
            evidence=["answer:docx_document"],
            confidence="high",
        )

        carry_forward_persisted_planner_state(
            rebuilt, persisted, attached_file_ids=set()
        )

        assert "terminal_output" not in rebuilt.resolved_slots

    def test_slot_without_parseable_file_evidence_is_not_carried(self) -> None:
        # Fail closed: a structural slot that cannot name its files cannot
        # prove they are still attached.
        rebuilt = _state()
        persisted = _state()
        persisted.resolved_slots["docx_output_mode"] = ResolvedSlot(
            name="docx_output_mode",
            value="template_fill_docx",
            source="attachment_structure",
            evidence=["structure:placeholders_present"],
            confidence="high",
        )

        carry_forward_persisted_planner_state(
            rebuilt, persisted, attached_file_ids={uuid4()}
        )

        assert "docx_output_mode" not in rebuilt.resolved_slots


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

    def test_drops_accepted_value_when_policy_now_blocks_mapped_authoring(
        self,
    ) -> None:
        """An explicit organization opt-out (or invalid policy) rebuilds with no
        proposal; a previously accepted limit must not survive and re-enable
        publication."""
        rebuilt = _state()
        rebuilt.mapped_file_limit = MappedFileLimit(diagnostic="policy_unset")
        persisted = _state()
        persisted.mapped_file_limit = MappedFileLimit(
            proposed_value=8,
            accepted_value=4,
            provenance="authored",
        )

        carry_forward_persisted_planner_state(
            rebuilt, persisted, attached_file_ids=set()
        )

        assert rebuilt.mapped_file_limit == MappedFileLimit(diagnostic="policy_unset")


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
    def test_drops_persisted_declared_output_schema_evidence(self) -> None:
        persisted_evidence = _output_schema_evidence()
        rebuilt = _state()
        persisted = _state()
        persisted.output_schema_evidence = persisted_evidence

        carry_forward_persisted_planner_state(
            rebuilt, persisted, attached_file_ids=set()
        )

        assert rebuilt.output_schema_evidence is None

    def test_current_turn_output_schema_evidence_wins(self) -> None:
        current = _output_schema_evidence()
        stale = build_schema_evidence(
            json_schema={
                "type": "object",
                "properties": {"old": {"type": "string"}},
            },
            source="declared_schema",
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

        assert rebuilt.output_schema_evidence == current

    def test_filters_template_output_schema_evidence_to_attached_files(self) -> None:
        active_file_id = UUID("00000000-0000-0000-0000-000000000701")
        detached_file_id = UUID("00000000-0000-0000-0000-000000000702")
        persisted = _state()
        persisted.output_schema_evidence = build_schema_evidence(
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
        persisted.output_schema_evidence = build_schema_evidence(
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
        persisted.output_schema_evidence = build_schema_evidence(
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
        persisted.output_schema_evidence = build_schema_evidence(
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
        persisted.output_schema_evidence = build_schema_evidence(
            json_schema={
                "type": "object",
                "properties": {"decision": {"type": "string"}},
            },
            source="declared_schema",
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
        persisted.output_schema_evidence = build_schema_evidence(
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

    def test_turn_resolved_declared_input_and_output_assignments_survive(self) -> None:
        # The turn resolved both assignments against the candidate set its own
        # conversation produced; the conversation rebuild carries no
        # candidates, so without this the save drops the schema the user
        # assigned and a later turn works without it.
        resolved = _state()
        resolved.replace_schema_resolution(
            input_evidence=_input_schema_evidence(),
            output_evidence=_output_schema_evidence(),
            example_inference=None,
        )
        rebuilt = _state()

        carry_forward_turn_resolved_planner_state(
            rebuilt,
            resolved,
            conversation=_pasted_schema_conversation(),
            attached_file_ids=set(),
        )

        assert rebuilt.input_schema_evidence == _input_schema_evidence()
        assert rebuilt.output_schema_evidence == _output_schema_evidence()

    def test_turn_resolved_declared_assignment_needs_its_paste_to_survive(self) -> None:
        # The save persists the compacted conversation, which can be shorter
        # than the one the turn resolved against. A pasted schema whose
        # message compaction dropped is no longer offered, and persisting the
        # assignment anyway would record a contract the session cannot show.
        resolved = _state()
        resolved.replace_schema_resolution(
            input_evidence=_input_schema_evidence(),
            output_evidence=_output_schema_evidence(),
            example_inference=None,
        )
        rebuilt = _state()

        carry_forward_turn_resolved_planner_state(
            rebuilt,
            resolved,
            conversation=[
                ConversationMessage(
                    role="user",
                    content="Fortsätt med planen.",
                )
            ],
            attached_file_ids=set(),
        )

        assert rebuilt.input_schema_evidence is None
        assert rebuilt.output_schema_evidence is None

    def test_turn_resolved_declared_assignment_needs_its_file_attached(self) -> None:
        # Session membership is read inside the save, after the turn resolved
        # the assignment: a schema read from bytes that are no longer attached
        # cannot be persisted as the user's contract.
        file_id = UUID("00000000-0000-0000-0000-000000000731")
        resolved = _state()
        resolved.output_schema_evidence = build_schema_evidence(
            json_schema={
                "type": "object",
                "properties": {"decision": {"type": "string"}},
            },
            source="declared_schema",
            source_file_ids=(file_id,),
            confidence="high",
            evidence=[f"file:{file_id}:json_schema_attachment"],
        )
        rebuilt = _state()

        carry_forward_turn_resolved_planner_state(
            rebuilt,
            resolved,
            conversation=[],
            attached_file_ids=set(),
        )

        assert rebuilt.output_schema_evidence is None

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
        evidence = build_schema_evidence(
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
                "schema_resolution": SchemaResolution.from_evidence(
                    input_evidence=None,
                    output_evidence=evidence,
                ),
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
                "schema_resolution": SchemaResolution.from_evidence(
                    input_evidence=None,
                    output_evidence=build_schema_evidence(
                        json_schema={
                            "type": "object",
                            "properties": {"decision": {"type": "string"}},
                        },
                        source="inferred_example",
                        source_file_ids=(file_id,),
                        confidence="medium",
                        evidence=(f"file:{file_id}:inferred_example_shape",),
                    ),
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


class TestSchemaCandidateDerivation:
    def test_captures_fenced_json_schema_without_assigning_direction(self) -> None:
        conversation = [
            ConversationMessage(
                message_id="msg_schema",
                role="user",
                content=(
                    "Använd denna struktur:\n"
                    "```json\n"
                    '{"type":"object","properties":{"decision":{"type":"string"}},'
                    '"required":["decision"],"additionalProperties":false}\n'
                    "```"
                ),
            )
        ]

        candidates = derive_freeform_schema_candidates(conversation)
        state = build_planning_state_from_conversation(conversation)

        assert len(candidates) == 1
        assert candidates[0].json_schema["properties"] == {
            "decision": {"type": "string"}
        }
        assert candidates[0].provenance == (
            "message:msg_schema",
            "fenced_json_schema",
        )
        assert state.input_schema_evidence is None
        assert state.output_schema_evidence is None

    @pytest.mark.parametrize(
        "raw_json",
        [
            '{"decision":"bevilja"}',
            '{"type":"object","properties":{"decision":{"type":3}}}',
            '{"type":"array","items":{"type":"string"}}',
        ],
    )
    def test_ignores_non_schema_or_non_object_shape_fences(self, raw_json: str) -> None:
        candidates = derive_freeform_schema_candidates(
            [
                ConversationMessage(
                    message_id="msg_ignored",
                    role="user",
                    content=f"```json\n{raw_json}\n```",
                )
            ]
        )

        assert candidates == ()

    def test_retains_all_distinct_candidates_with_their_sources(self) -> None:
        conversation = [
            ConversationMessage(
                message_id="msg_first",
                role="user",
                content=(
                    "```json\n"
                    '{"type":"object","properties":{"first":{"type":"string"}}}\n'
                    "```"
                ),
            ),
            ConversationMessage(
                message_id="msg_second",
                role="user",
                content=(
                    "```json\n"
                    '{"type":"object","properties":{"second":{"type":"string"}}}\n'
                    "```"
                ),
            ),
        ]

        candidates = derive_freeform_schema_candidates(conversation)

        assert len(candidates) == 2
        assert {candidate.provenance[0] for candidate in candidates} == {
            "message:msg_first",
            "message:msg_second",
        }

    @pytest.mark.parametrize("schema_first", [False, True])
    def test_candidate_does_not_override_structured_text_answer(
        self,
        schema_first: bool,
    ) -> None:
        schema_message = ConversationMessage(
            message_id="msg_schema",
            role="user",
            content=(
                "```json\n"
                '{"type":"object","properties":{"decision":{"type":"string"}}}\n'
                "```"
            ),
        )
        answer_message = ConversationMessage(
            message_id="msg_text_answer",
            role="user",
            content="Jag vill ha ett strukturerat textresultat.",
            metadata={
                "question_answer": {
                    "question_id": "final_output_mode",
                    "selected_option_id": "structured_text",
                    "selected_value": "structured_text",
                }
            },
        )
        conversation = (
            [schema_message, answer_message]
            if schema_first
            else [answer_message, schema_message]
        )

        state = build_planning_state_from_conversation(conversation)

        assert len(derive_freeform_schema_candidates(conversation)) == 1
        assert state.input_schema_evidence is None
        assert state.output_schema_evidence is None
        slot = state.resolved_slots["terminal_output"]
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

    def test_explicit_runtime_input_fields_remain_non_commit_grade_heuristic(
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
        assert slot.value == "basic_runtime_metadata"
        assert slot.source == "heuristic"
        assert slot.confidence == "medium"
        assert not slot.is_commit_grade

    def test_optional_checklist_or_rule_runtime_fields_require_admissible_evidence(
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
        assert slot.value == "basic_runtime_metadata"
        assert slot.source == "heuristic"
        assert slot.confidence == "medium"
        assert not slot.is_commit_grade

        policy = build_planner_action_policy(
            session_state=state,
            selected_discovery_question_ids=("runtime_metadata_fields",),
        )
        assert "runtime_metadata_fields" in policy.allowed_ask_question_targets

    def test_user_supplies_prompt_resolves_basic_runtime_metadata(
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
        assert slot.value == "basic_runtime_metadata"
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
                        "detailed_runtime_metadata",
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
                        "detailed_runtime_metadata",
                        "high",
                    ),
                )
            ),
            prompt_hash="a" * 64,
            freeform_text="",
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "detailed_runtime_metadata"
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
                        "detailed_runtime_metadata",
                        "high",
                    ),
                )
            ),
            prompt_hash="b" * 64,
            freeform_text="",
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "detailed_runtime_metadata"
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
        assert slot.value == "basic_runtime_metadata"
        assert slot.source == "heuristic"
        assert slot.confidence == "medium"


class TestSlotClassificationMetadataReplay:
    def test_replay_applies_checkpoint_updates_per_producer(
        self,
    ) -> None:
        def checkpoint_update(
            operation: CheckpointUpdateOperation,
            producer_kind: CheckpointProducerKind,
            mode: FlowStepReviewMode | None,
            quote: str,
        ) -> ClassifiedCheckpointUpdate:
            return ClassifiedCheckpointUpdate(
                operation=operation,
                producer_kind=producer_kind,
                mode=mode,
                confidence="high",
                reason="Typed checkpoint requirement.",
                evidence=_model_evidence(quote),
                evidence_level="explicit",
            )

        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="assistant",
                    content="Classifier evidence.",
                    metadata=_slot_classification_metadata(
                        checkpoint_updates=(
                            checkpoint_update(
                                "update",
                                "transcript",
                                FlowStepReviewMode.VIEW,
                                "Approve the transcript before analysis.",
                            ),
                            checkpoint_update(
                                "update",
                                "structured_result",
                                FlowStepReviewMode.VIEW,
                                "Approve the structured result before delivery.",
                            ),
                        ),
                    ),
                ),
                ConversationMessage(
                    role="assistant",
                    content="Unrelated classifier evidence.",
                    metadata=_slot_classification_metadata(checkpoint_updates=()),
                ),
                ConversationMessage(
                    role="assistant",
                    content="Updated classifier evidence.",
                    metadata=_slot_classification_metadata(
                        checkpoint_updates=(
                            checkpoint_update(
                                "update",
                                "transcript",
                                FlowStepReviewMode.EDIT,
                                "Edit the transcript before analysis.",
                            ),
                        )
                    ),
                ),
                ConversationMessage(
                    role="assistant",
                    content="Checkpoint removal evidence.",
                    metadata=_slot_classification_metadata(
                        checkpoint_updates=(
                            checkpoint_update(
                                "clear",
                                "structured_result",
                                None,
                                "Do not pause for structured result approval.",
                            ),
                        )
                    ),
                ),
            ]
        )

        assert [
            (
                intent.producer_kind,
                intent.operation,
                intent.mode.value if intent.mode is not None else None,
                intent.evidence,
            )
            for intent in state.checkpoint_intents
        ] == [
            (
                "structured_result",
                "clear",
                None,
                [
                    "quote:user_message:test-source:"
                    "Do not pause for structured result approval."
                ],
            ),
            (
                "transcript",
                "set",
                "edit",
                ["quote:user_message:test-source:Edit the transcript before analysis."],
            ),
        ]

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
                        _classified(
                            "primary_runtime_input",
                            "documents",
                            "medium",
                            evidence_level="explicit",
                        ),
                        _classified(
                            "terminal_output",
                            "structured_text",
                            "medium",
                            evidence_level="explicit",
                        ),
                        _classified(
                            "runtime_metadata_fields",
                            "detailed_runtime_metadata",
                            "high",
                        ),
                    ),
                )
            ]
        )

        assert state.resolved_slots["terminal_output"].value == "structured_text"
        assert state.resolved_slots["terminal_output"].source == "model"
        assert state.resolved_slots["terminal_output"].evidence_level == "explicit"
        assert state.resolved_slots["runtime_metadata_fields"].value == (
            "detailed_runtime_metadata"
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

    def test_question_response_is_unresolved_without_cited_classifier_evidence(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    message_id="test-source",
                    role="user",
                    content="PDF-dokument",
                    metadata={"question_response": {"question_id": "terminal_output"}},
                )
            ]
        )

        assert "terminal_output" not in state.resolved_slots

    def test_question_response_resolves_from_cited_classifier_evidence(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    message_id="test-source",
                    role="user",
                    content="PDF-dokument",
                    metadata={
                        "question_response": {"question_id": "terminal_output"},
                        **_slot_classification_metadata(
                            _classified(
                                "terminal_output",
                                "pdf_document",
                                "high",
                                evidence=("PDF-dokument",),
                            )
                        ),
                    },
                )
            ]
        )

        slot = state.resolved_slots["terminal_output"]
        assert slot.value == "pdf_document"
        assert slot.source == "model"

    def test_unprompted_free_text_retains_heuristic_fallback(self) -> None:
        state = build_planning_state_from_conversation(
            [ConversationMessage(role="user", content="PDF-dokument")]
        )

        slot = state.resolved_slots["terminal_output"]
        assert slot.value == "pdf_document"
        assert slot.source == "heuristic"

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


class TestFlowObservedSlotsYieldToTheEdit:
    """An edit that names a different output must be able to change it.

    Reading the Flow being edited states what it produces today. A user asking
    for a PDF instead of the DOCX it produces is describing what it should
    produce next, and the disclosure quoted that sentence back while every
    decision under it still said DOCX.
    """

    def _docx_flow(self) -> Flow:
        return Flow(
            id=uuid4(),
            tenant_id=uuid4(),
            space_id=uuid4(),
            name="Strukturerad samtalsrapport",
            description="Befintligt dokumentflöde",
            steps=[
                FlowStep(
                    assistant_id=uuid4(),
                    step_order=1,
                    user_description="Läs underlaget",
                    input_source="flow_input",
                    input_type="document",
                    output_mode="pass_through",
                    output_type="text",
                ),
                FlowStep(
                    assistant_id=uuid4(),
                    step_order=2,
                    user_description="Skapa DOCX",
                    input_source="previous_step",
                    input_type="text",
                    output_mode="pass_through",
                    output_type="docx",
                ),
            ],
        )

    def test_flow_observed_output_is_offered_to_the_classifier(self) -> None:
        state = _state()
        state.resolved_slots = {
            "primary_runtime_input": _slot(
                name="primary_runtime_input",
                value="documents",
                source="flow_default",
            ),
            "terminal_output": _slot(
                name="terminal_output",
                value="docx_document",
                source="flow_default",
            ),
        }

        assert "terminal_output" in llm_resolvable_slot_values_for_state(state)

    def test_cited_edit_replaces_the_observed_output_and_its_dependent_mode(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Jag vill ha en PDF fil istället som utdata än en docx fil.",
                metadata=_slot_classification_metadata(
                    _classified(
                        "terminal_output",
                        "pdf_document",
                        "high",
                        evidence=("PDF fil istället som utdata än en docx fil",),
                        evidence_level="explicit",
                    ),
                ),
            ),
        ]

        state = build_planning_state_from_conversation(
            conversation,
            flow=self._docx_flow(),
        )

        terminal_output = state.resolved_slots["terminal_output"]
        assert terminal_output.value == "pdf_document"
        assert terminal_output.source == "model"
        assert "docx_output_mode" not in state.resolved_slots
        assert state.resolved_slots["pdf_generation_mode"].value == "generated_pdf"

    def test_replacement_holds_when_the_classifier_never_answered(self) -> None:
        """Classification is skipped or unsure often enough to matter.

        The request is stated plainly, and the output resolver reads it without
        a provider: it ranks an explicit replacement above what the Flow
        produces today. Reading the Flow's own output a second time here
        overruled that, so a skipped classification silently kept the DOCX.

        The replacement lands as a heuristic reading, which is deliberately not
        commit-grade: the user is asked to settle the output instead of the
        Flow answering for them.
        """

        conversation = [
            ConversationMessage(
                role="user",
                content="Jag vill ha en PDF fil istället som utdata än en docx fil.",
            ),
        ]

        state = build_planning_state_from_conversation(
            conversation,
            flow=self._docx_flow(),
        )

        terminal_output = state.resolved_slots["terminal_output"]
        assert terminal_output.value == "pdf_document"
        assert not terminal_output.is_commit_grade
        assert "docx_output_mode" not in state.resolved_slots

    def test_an_edit_that_asks_for_no_output_change_keeps_the_flow_output(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Behåll flödet men gör sammanfattningen kortare.",
            ),
        ]

        state = build_planning_state_from_conversation(
            conversation,
            flow=self._docx_flow(),
        )

        terminal_output = state.resolved_slots["terminal_output"]
        assert terminal_output.value == "docx_document"
        assert terminal_output.source == "flow_default"
        assert state.resolved_slots["docx_output_mode"].value == "generated_docx"


class TestModelSlotMerge:
    def test_named_result_delta_rejects_missing_per_name_evidence(self) -> None:
        with pytest.raises(
            ValueError,
            match="evidence_by_name must exactly cover named-result changes",
        ):
            ClassifiedNamedResultDelta(
                operation="update",
                names=("case_id",),
                confidence="high",
                reason="The user explicitly named the result field.",
                evidence=_model_evidence("case_id"),
            )

    def test_named_result_delta_rejects_per_name_evidence_outside_delta(
        self,
    ) -> None:
        with pytest.raises(
            ValueError,
            match="evidence_by_name citations must belong to delta evidence",
        ):
            ClassifiedNamedResultDelta(
                operation="update",
                names=("case_id",),
                confidence="high",
                reason="The user explicitly named the result field.",
                evidence=_model_evidence("case_id"),
                evidence_by_name=(
                    ClassifiedNamedResultEvidence(
                        name="case_id",
                        evidence=_model_evidence("unrelated evidence"),
                    ),
                ),
            )

    def test_checkpoint_needs_evidence_that_states_the_review(self) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "primary_runtime_input",
                        "audio",
                        "high",
                        evidence_level="explicit",
                    ),
                ),
                checkpoint_updates=(
                    ClassifiedCheckpointUpdate(
                        operation="update",
                        producer_kind="transcript",
                        mode=FlowStepReviewMode.VIEW,
                        confidence="high",
                        reason="The transcription step produces a result.",
                        evidence=_model_evidence("transcribe the audio"),
                        evidence_level="inferred",
                    ),
                ),
            ),
            prompt_hash="a" * 64,
            freeform_text="transcribe the audio",
        )

        assert state.checkpoint_intents == []
        assert state.resolved_slots["primary_runtime_input"].value == "audio"

    def test_checkpoint_removal_needs_evidence_that_states_the_removal(self) -> None:
        state = _state()
        requested = ClassifiedCheckpointUpdate(
            operation="update",
            producer_kind="report_text",
            mode=FlowStepReviewMode.VIEW,
            confidence="high",
            reason="The user asked to approve the report.",
            evidence=_model_evidence("I want to approve the report before delivery."),
            evidence_level="explicit",
        )
        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(checkpoint_updates=(requested,)),
            prompt_hash="a" * 64,
            freeform_text="I want to approve the report before delivery.",
        )

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                checkpoint_updates=(
                    ClassifiedCheckpointUpdate(
                        operation="clear",
                        producer_kind="report_text",
                        mode=None,
                        confidence="high",
                        reason="The report is the final deliverable.",
                        evidence=_model_evidence("send the report to the applicant"),
                        evidence_level="inferred",
                    ),
                )
            ),
            prompt_hash="b" * 64,
            freeform_text="send the report to the applicant",
        )

        assert [
            (intent.producer_kind, intent.operation)
            for intent in state.checkpoint_intents
        ] == [("report_text", "set")]

    def test_duplicate_checkpoint_producer_is_rejected_at_merge_boundary(
        self,
    ) -> None:
        checkpoint = ClassifiedCheckpointUpdate(
            evidence_level="explicit",
            operation="update",
            producer_kind="report_text",
            mode=FlowStepReviewMode.VIEW,
            confidence="high",
            reason="Report approval requested.",
            evidence=_model_evidence("Approve the report before delivery."),
        )

        with pytest.raises(
            ValueError,
            match="checkpoint_updates must contain unique producer_kind values",
        ):
            merge_llm_resolved_slots(
                _state(),
                SlotClassificationResult(
                    checkpoint_updates=(checkpoint, checkpoint),
                ),
                prompt_hash="a" * 64,
                freeform_text="Approve the report before delivery.",
            )

    def test_mixed_attachment_evidence_cannot_enter_output_schema_provenance(
        self,
    ) -> None:
        user_source = SlotClassificationSource(
            source_id="user_message:user-1",
            kind="user_message",
            text="JSON output field: case_id.",
            message_id="user-1",
        )
        attachment_source = SlotClassificationSource(
            source_id="uploaded_file:00000000-0000-0000-0000-000000000001",
            kind="uploaded_file",
            text="The attachment also mentions case_id.",
            file_id=UUID("00000000-0000-0000-0000-000000000001"),
        )
        parsed = parse_slot_classification_response(
            json.dumps(
                {
                    "slots": [],
                    "file_roles": [],
                    "checkpoint_updates": [],
                    "form_intake": None,
                    "named_result_evidence": {
                        "operation": "update",
                        "names": ["case_id"],
                        "removed_names": [],
                        "confidence": "high",
                        "reason": "The user explicitly named the JSON field.",
                        "evidence": [
                            {
                                "source_id": user_source.source_id,
                                "quote": user_source.text,
                            },
                            {
                                "source_id": attachment_source.source_id,
                                "quote": attachment_source.text,
                            },
                        ],
                    },
                    "example_output_constraints": None,
                    "schema_direction": None,
                    "secondary_obligations": [],
                    "assumptions": [],
                    "contradictions": [],
                }
            ),
            allowed_slot_values={},
            classification_input=SlotClassificationInput(
                sources=(user_source, attachment_source),
                current_user_message_id="user-1",
            ),
        )
        assert parsed is not None
        assert parsed.named_result_evidence is not None
        assert parsed.named_result_evidence.evidence == (
            ClassifiedEvidence(
                source_id=user_source.source_id,
                quote=user_source.text,
            ),
        )

        state = _state()
        state.resolved_slots["terminal_output"] = _slot(
            name="terminal_output",
            value="structured_json",
            source="structured_answer",
        )
        merge_llm_resolved_slots(
            state,
            parsed,
            prompt_hash="a" * 64,
            freeform_text=user_source.text,
        )

        assert state.output_schema_evidence is None
        assert state.named_result_evidence == [
            NamedResultEvidence(
                name="case_id",
                confidence="high",
                evidence=["quote:user_message:user-1:JSON output field: case_id."],
            )
        ]

    def test_named_result_evidence_survives_replay_and_coexists_with_schema(
        self,
    ) -> None:
        state = _state()
        state.resolved_slots["terminal_output"] = _slot(
            name="terminal_output",
            value="structured_json",
            source="structured_answer",
        )

        initial_evidence = _model_evidence(
            "JSON-resultatet ska innehålla case_id och status[]."
        )
        declared_shapes: dict[str, NamedResultDeclaredShape | None] = {
            "case_id": None,
            "status": "array",
        }
        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                named_result_evidence=ClassifiedNamedResultDelta(
                    operation="update",
                    names=("case_id", "status"),
                    confidence="high",
                    reason="The user explicitly named the JSON result fields.",
                    evidence=initial_evidence,
                    evidence_by_name=tuple(
                        ClassifiedNamedResultEvidence(
                            name=name,
                            evidence=initial_evidence,
                            declared_shape=declared_shapes[name],
                        )
                        for name in ("case_id", "status")
                    ),
                )
            ),
            prompt_hash="a" * 64,
            freeform_text="JSON-resultatet ska innehålla case_id och status[].",
        )

        assert state.output_schema_evidence is None
        assert state.named_result_evidence == [
            NamedResultEvidence(
                name=name,
                confidence="high",
                declared_shape=declared_shapes[name],
                evidence=[
                    "quote:user_message:test-source:JSON-resultatet ska innehålla "
                    "case_id och status[]."
                ],
            )
            for name in ("case_id", "status")
        ]

        source = SlotClassificationSource(
            source_id="user_message:test-source",
            kind="user_message",
            text="JSON-resultatet ska innehålla case_id och status[].",
            message_id="test-source",
        )
        snapshot = (
            SlotClassificationNamedResultEvidenceMetadata.from_materialized_state(
                operation="replace",
                named_results=state.named_result_evidence,
                confidence="high",
                reason="The current complete user-named field snapshot.",
                evidence=_model_evidence(source.text),
            )
        )
        classification = slot_classification_metadata_from_attempt(
            SlotClassificationAttempt(
                outcome="resolved",
                result=SlotClassificationResult(
                    slots=(
                        ClassifiedSlot(
                            slot_name="terminal_output",
                            value="structured_json",
                            confidence="high",
                            reason="The user explicitly requested JSON.",
                            evidence=_model_evidence(source.text),
                            evidence_level="explicit",
                        ),
                    ),
                ),
            ),
            prompt_hash="b" * 64,
            classification_input=SlotClassificationInput(sources=(source,)),
            model="openai/gpt-test",
            provider="openai",
            named_result_evidence_snapshot=snapshot,
        )
        metadata = metadata_with_slot_classification(None, classification)
        assert metadata is not None
        replayed = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    message_id="test-source",
                    role="user",
                    content=source.text,
                    metadata=metadata,
                )
            ]
        )
        assert replayed.output_schema_evidence is None
        assert replayed.named_result_evidence == state.named_result_evidence

        declared = build_schema_evidence(
            json_schema={
                "type": "object",
                "properties": {"official_id": {"type": "string"}},
            },
            source="declared_schema",
            confidence="high",
            evidence=("message:user-2",),
        )
        replayed.replace_schema_resolution(
            input_evidence=None,
            output_evidence=declared,
            example_inference=None,
        )
        priority_evidence = _model_evidence("Lägg även till priority.")
        merge_llm_resolved_slots(
            replayed,
            SlotClassificationResult(
                named_result_evidence=ClassifiedNamedResultDelta(
                    operation="update",
                    names=("priority",),
                    confidence="high",
                    reason="The user named another field.",
                    evidence=priority_evidence,
                    evidence_by_name=(
                        ClassifiedNamedResultEvidence(
                            name="priority",
                            evidence=priority_evidence,
                        ),
                    ),
                )
            ),
            prompt_hash="c" * 64,
            freeform_text="Lägg även till priority.",
        )
        assert replayed.output_schema_evidence == declared
        assert replayed.named_result_obligations == ("case_id", "status", "priority")

        clear_source = SlotClassificationSource(
            source_id="user_message:clear-source",
            kind="user_message",
            text="Remove every named result.",
            message_id="clear-source",
        )
        clear_evidence = (
            ClassifiedEvidence(
                source_id=clear_source.source_id,
                quote=clear_source.text,
            ),
        )
        clear_delta = ClassifiedNamedResultDelta(
            operation="clear",
            names=(),
            confidence="high",
            reason="The user removed all named results.",
            evidence=clear_evidence,
        )
        clear_classification = slot_classification_metadata_from_attempt(
            SlotClassificationAttempt(
                outcome="resolved",
                result=SlotClassificationResult(named_result_evidence=clear_delta),
            ),
            prompt_hash="d" * 64,
            classification_input=SlotClassificationInput(
                sources=(clear_source,),
                current_user_message_id="clear-source",
            ),
            model="openai/gpt-test",
            provider="openai",
            named_result_evidence_snapshot=(
                SlotClassificationNamedResultEvidenceMetadata.from_materialized_state(
                    operation="clear",
                    named_results=(),
                    confidence="high",
                    reason=clear_delta.reason,
                    evidence=clear_evidence,
                )
            ),
        )
        clear_metadata = metadata_with_slot_classification(None, clear_classification)
        assert clear_metadata is not None
        cleared = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    message_id="test-source",
                    role="user",
                    content=source.text,
                    metadata=metadata,
                ),
                ConversationMessage(
                    message_id="clear-source",
                    role="user",
                    content=clear_source.text,
                    metadata=clear_metadata,
                ),
            ]
        )
        assert cleared.named_result_evidence == []

    def test_named_result_evidence_enforces_existing_field_count_bound(self) -> None:
        state = _state()
        state.resolved_slots["terminal_output"] = _slot(
            name="terminal_output",
            value="structured_json",
            source="structured_answer",
        )
        state.named_result_evidence = [
            NamedResultEvidence(
                name=f"field_{index}",
                confidence="high",
                evidence=[f"quote:user_message:user-1:field_{index}"],
            )
            for index in range(NAMED_RESULT_EVIDENCE_MAX_ITEMS)
        ]

        overflow_evidence = _model_evidence("Add overflow.")
        with pytest.raises(AIBuilderBadRequestException) as exc_info:
            merge_llm_resolved_slots(
                state,
                SlotClassificationResult(
                    named_result_evidence=ClassifiedNamedResultDelta(
                        operation="update",
                        names=("overflow",),
                        confidence="high",
                        reason="The user added a field.",
                        evidence=overflow_evidence,
                        evidence_by_name=(
                            ClassifiedNamedResultEvidence(
                                name="overflow",
                                evidence=overflow_evidence,
                            ),
                        ),
                    )
                ),
                prompt_hash="a" * 64,
                freeform_text="Add overflow.",
            )

        assert exc_info.value.code is AIBuilderErrorCode.SCHEMA_LIMIT_EXCEEDED
        assert exc_info.value.context == {
            "reason": "named_result_count",
            "max_value": NAMED_RESULT_EVIDENCE_MAX_ITEMS,
            "actual_value": NAMED_RESULT_EVIDENCE_MAX_ITEMS + 1,
        }

    def test_maximum_named_result_evidence_completes_persisted_lifecycle(self) -> None:
        state = _state()
        prior_classification: SlotClassificationMetadata | None = None
        latest_classification: SlotClassificationMetadata | None = None
        for index in range(NAMED_RESULT_EVIDENCE_MAX_ITEMS):
            prefix = f"field_{index:03d}_"
            name = prefix + "n" * (240 - len(prefix))
            message_id = f"maximum-{index}"
            sources = tuple(
                SlotClassificationSource(
                    source_id=f"user_message:{message_id}:{citation_index}",
                    kind="user_message",
                    text=name,
                    message_id=message_id,
                )
                for citation_index in range(NAMED_RESULT_EVIDENCE_MAX_CITATIONS)
            )
            classification_input = SlotClassificationInput(
                sources=sources,
                current_user_message_id=message_id,
            )
            parsed = _parse_named_result_delta(
                names=(name,),
                classification_input=classification_input,
            )
            classified_evidence = parsed.named_result_evidence
            assert classified_evidence is not None
            merge_llm_resolved_slots(
                state,
                parsed,
                prompt_hash=f"{index:064x}",
                freeform_text=name,
            )
            snapshot = discovery_runtime._materialized_named_result_snapshot(
                state,
                classified_evidence=classified_evidence,
                prior_classification=prior_classification,
            )
            assert snapshot is not None
            latest_classification = slot_classification_metadata_from_attempt(
                SlotClassificationAttempt(outcome="resolved", result=parsed),
                prompt_hash=f"{index:064x}",
                classification_input=classification_input,
                model="openai/gpt-test",
                provider="openai",
                retained_source_inventory=(
                    ()
                    if prior_classification is None
                    else prior_classification.source_inventory
                ),
                named_result_evidence_snapshot=snapshot,
            )
            prior_classification = latest_classification

        assert latest_classification is not None
        metadata = metadata_with_slot_classification(None, latest_classification)
        assert metadata is not None
        replayed = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    message_id="maximum-replay",
                    role="user",
                    content="Replay the maximum named-result snapshot.",
                    metadata=metadata,
                )
            ]
        )
        assert replayed.named_result_evidence == state.named_result_evidence
        assert len(state.named_result_evidence) == NAMED_RESULT_EVIDENCE_MAX_ITEMS
        assert sum(len(item.evidence) for item in state.named_result_evidence) == (
            NAMED_RESULT_EVIDENCE_MAX_ITEMS * NAMED_RESULT_EVIDENCE_MAX_CITATIONS
        )
        payload_bytes = len(
            json.dumps(
                state.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        assert payload_bytes < PLANNING_STATE_PAYLOAD_CAP_BYTES

        removed_item = state.named_result_evidence[0]
        removed_name = removed_item.name
        removed_references = set(removed_item.evidence)
        replacement_prefix = "replacement_"
        replacement_name = replacement_prefix + "r" * (240 - len(replacement_prefix))
        churn_message_id = "maximum-churn"
        churn_sources = (
            SlotClassificationSource(
                source_id=f"user_message:{churn_message_id}:replacement",
                kind="user_message",
                text=replacement_name,
                message_id=churn_message_id,
            ),
            SlotClassificationSource(
                source_id=f"user_message:{churn_message_id}:removed",
                kind="user_message",
                text=removed_name,
                message_id=churn_message_id,
            ),
        )
        churn_input = SlotClassificationInput(
            sources=churn_sources,
            current_user_message_id=churn_message_id,
        )
        churn_result = _parse_named_result_delta(
            names=(replacement_name,),
            removed_names=(removed_name,),
            classification_input=churn_input,
        )
        churn_evidence = churn_result.named_result_evidence
        assert churn_evidence is not None
        merge_llm_resolved_slots(
            state,
            churn_result,
            prompt_hash="f" * 64,
            freeform_text=replacement_name,
        )
        replacement = next(
            item
            for item in state.named_result_evidence
            if item.name == replacement_name
        )
        replacement_reference = ClassifiedEvidence(
            source_id=churn_sources[0].source_id,
            quote=churn_sources[0].text,
        ).planning_reference()
        removal_reference = ClassifiedEvidence(
            source_id=churn_sources[1].source_id,
            quote=churn_sources[1].text,
        ).planning_reference()
        assert replacement.evidence == [replacement_reference]
        assert removal_reference not in replacement.evidence
        churn_snapshot = discovery_runtime._materialized_named_result_snapshot(
            state,
            classified_evidence=churn_evidence,
            prior_classification=latest_classification,
        )
        assert churn_snapshot is not None
        assert len(churn_snapshot.evidence) == NAMED_RESULT_PROVENANCE_MAX_ITEMS
        snapshot_references = {
            item.to_classified_evidence().planning_reference()
            for item in churn_snapshot.evidence
        }
        assert removal_reference in snapshot_references
        assert all(
            item.to_classified_evidence().planning_reference() not in removed_references
            for item in churn_snapshot.evidence
        )
        churn_classification = slot_classification_metadata_from_attempt(
            SlotClassificationAttempt(outcome="resolved", result=churn_result),
            prompt_hash="f" * 64,
            classification_input=churn_input,
            model="openai/gpt-test",
            provider="openai",
            retained_source_inventory=latest_classification.source_inventory,
            named_result_evidence_snapshot=churn_snapshot,
        )
        churn_metadata = metadata_with_slot_classification(
            None,
            churn_classification,
        )
        assert churn_metadata is not None
        churn_replayed = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    message_id=churn_message_id,
                    role="user",
                    content=replacement_name,
                    metadata=churn_metadata,
                )
            ]
        )
        assert churn_replayed.named_result_evidence == state.named_result_evidence

    def test_recited_folded_identity_replaces_the_earlier_spelling_in_place(
        self,
    ) -> None:
        state = _state()
        state.named_result_evidence = [
            NamedResultEvidence(
                name="case-id",
                confidence="high",
                evidence=["quote:user_message:user-1:case-id"],
            ),
            NamedResultEvidence(
                name="status",
                confidence="high",
                evidence=["quote:user_message:user-1:status"],
            ),
        ]
        corrected_evidence = _model_evidence("Case ID")

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                named_result_evidence=ClassifiedNamedResultDelta(
                    operation="update",
                    names=("Case ID",),
                    confidence="high",
                    reason="The user corrected the spelling of one result name.",
                    evidence=corrected_evidence,
                    evidence_by_name=(
                        ClassifiedNamedResultEvidence(
                            name="Case ID",
                            evidence=corrected_evidence,
                        ),
                    ),
                )
            ),
            prompt_hash="f" * 64,
            freeform_text="Case ID",
        )

        # Identity is folded, wording is the author's: the newest citation
        # owns the spelling, and it keeps the position the identity already
        # held.
        assert state.named_result_obligations == ("Case ID", "status")
        assert state.named_result_evidence[0].evidence == [
            "quote:user_message:test-source:Case ID"
        ]

    def test_recitation_declares_and_replaces_the_shape_in_place(self) -> None:
        state = _state()
        state.resolved_slots["terminal_output"] = _slot(
            name="terminal_output",
            value="structured_json",
            source="structured_answer",
        )

        def _recite(text: str, *, confidence: SlotClassificationConfidence) -> None:
            merge_llm_resolved_slots(
                state,
                _parse_named_result_delta(
                    names=("bids",),
                    confidence=confidence,
                    classification_input=SlotClassificationInput(
                        sources=(
                            SlotClassificationSource(
                                source_id="user_message:user-1",
                                kind="user_message",
                                text=text,
                                message_id="user-1",
                            ),
                        ),
                        current_user_message_id="user-1",
                    ),
                ),
                prompt_hash="a" * 64,
                freeform_text=text,
            )

        _recite("JSON-resultatet ska innehålla bids.", confidence="high")
        assert state.named_result_evidence == [
            NamedResultEvidence(
                name="bids",
                confidence="high",
                declared_shape=None,
                evidence=[
                    "quote:user_message:user-1:JSON-resultatet ska innehålla bids."
                ],
            )
        ]

        _recite("Fältet bids[] ska vara en lista.", confidence="high")
        assert state.named_result_evidence == [
            NamedResultEvidence(
                name="bids",
                confidence="high",
                declared_shape="array",
                evidence=["quote:user_message:user-1:Fältet bids[] ska vara en lista."],
            )
        ]

        # A re-citation carrying the same notation replaces provenance and
        # confidence and leaves the shape as it was.
        _recite("Behåll bids[] som förut.", confidence="medium")
        assert state.named_result_evidence == [
            NamedResultEvidence(
                name="bids",
                confidence="medium",
                declared_shape="array",
                evidence=["quote:user_message:user-1:Behåll bids[] som förut."],
            )
        ]

        # An absent marker is silence, not a retraction: naming the field
        # again without notation replaces provenance and confidence and keeps
        # the shape the user already declared.
        _recite("Skriv bara bids i resultatet.", confidence="high")
        assert state.named_result_evidence == [
            NamedResultEvidence(
                name="bids",
                confidence="high",
                declared_shape="array",
                evidence=["quote:user_message:user-1:Skriv bara bids i resultatet."],
            )
        ]

        # A different literal marker is a new declaration, and it replaces.
        _recite("Gör om bids{} till ett objekt.", confidence="high")
        assert state.named_result_evidence == [
            NamedResultEvidence(
                name="bids",
                confidence="high",
                declared_shape="object",
                evidence=["quote:user_message:user-1:Gör om bids{} till ett objekt."],
            )
        ]

    def test_conflicting_shape_citations_leave_the_established_shape_untouched(
        self,
    ) -> None:
        state = _state()
        state.resolved_slots["terminal_output"] = _slot(
            name="terminal_output",
            value="structured_json",
            source="structured_answer",
        )
        state.named_result_evidence = [
            NamedResultEvidence(
                name="bids",
                confidence="high",
                declared_shape="array",
                evidence=["quote:user_message:user-0:Fältet bids[] är en lista."],
            )
        ]
        established = [
            item.model_copy(deep=True) for item in state.named_result_evidence
        ]

        quotes = [
            "Utdata ska innehålla bids[].",
            "Fältet bids{} ska också finnas.",
        ]
        text = " ".join(quotes)
        conflicting = parse_slot_classification_response(
            json.dumps(
                {
                    "slots": [],
                    "file_roles": [],
                    "checkpoint_updates": [],
                    "form_intake": None,
                    "named_result_evidence": {
                        "operation": "update",
                        "names": ["bids"],
                        "removed_names": [],
                        "confidence": "high",
                        "reason": "The user described the same field twice.",
                        "evidence": [
                            {"source_id": "user_message:user-1", "quote": quote}
                            for quote in quotes
                        ],
                    },
                    "example_output_constraints": None,
                    "schema_direction": None,
                    "secondary_obligations": [],
                    "assumptions": [],
                    "contradictions": [],
                }
            ),
            allowed_slot_values={},
            classification_input=SlotClassificationInput(
                sources=(
                    SlotClassificationSource(
                        source_id="user_message:user-1",
                        kind="user_message",
                        text=text,
                        message_id="user-1",
                    ),
                ),
                current_user_message_id="user-1",
            ),
        )
        assert conflicting is not None
        assert conflicting.named_result_evidence is None

        merge_llm_resolved_slots(
            state,
            conflicting,
            prompt_hash="d" * 64,
            freeform_text=text,
        )

        # The delta is atomic: a shape the server cannot read rejects the whole
        # change, and neither the shape nor its provenance moves.
        assert state.named_result_evidence == established

    def test_cited_output_names_do_not_replace_declared_schema(self) -> None:
        state = _state()
        state.resolved_slots["terminal_output"] = _slot(
            name="terminal_output",
            value="structured_json",
            source="structured_answer",
        )
        declared = build_schema_evidence(
            json_schema={
                "type": "object",
                "properties": {"official_id": {"type": "string"}},
            },
            source="declared_schema",
            confidence="high",
            evidence=("message:user-1",),
        )
        state.replace_schema_resolution(
            input_evidence=None,
            output_evidence=declared,
            example_inference=None,
        )

        named_evidence = _model_evidence("case_id och status")
        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                named_result_evidence=ClassifiedNamedResultDelta(
                    operation="update",
                    names=("case_id", "status"),
                    confidence="high",
                    reason="The user also mentioned field names in prose.",
                    evidence=named_evidence,
                    evidence_by_name=tuple(
                        ClassifiedNamedResultEvidence(
                            name=name,
                            evidence=named_evidence,
                        )
                        for name in ("case_id", "status")
                    ),
                )
            ),
            prompt_hash="b" * 64,
            freeform_text="case_id och status",
        )

        assert state.output_schema_evidence == declared
        assert state.named_result_obligations == ("case_id", "status")

    def test_explicit_clear_removes_only_named_result_evidence(self) -> None:
        state = _state()
        state.resolved_slots["terminal_output"] = _slot(
            name="terminal_output",
            value="structured_json",
            source="structured_answer",
        )
        state.named_result_evidence = [
            NamedResultEvidence(
                name=name,
                confidence="high",
                evidence=["quote:user_message:user-1:case_id and status"],
            )
            for name in ("case_id", "status")
        ]

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                named_result_evidence=ClassifiedNamedResultDelta(
                    operation="clear",
                    names=(),
                    confidence="high",
                    reason="The user removed all named field constraints.",
                    evidence=_model_evidence(
                        "Ta bort alla särskilt namngivna JSON-fält."
                    ),
                )
            ),
            prompt_hash="c" * 64,
            freeform_text="Ta bort alla särskilt namngivna JSON-fält.",
        )

        assert state.named_result_evidence == []
        assert state.output_schema_evidence is None

    def test_terminal_transition_retains_named_result_evidence(self) -> None:
        state = _state()
        state.resolved_slots["terminal_output"] = _slot(
            name="terminal_output",
            value="structured_json",
            source="model",
        )
        state.named_result_evidence = [
            NamedResultEvidence(
                name=name,
                confidence="high",
                evidence=["quote:user_message:user-1:case_id and status"],
            )
            for name in ("case_id", "status")
        ]

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(_classified("terminal_output", "pdf_document", "high"),)
            ),
            prompt_hash="d" * 64,
            freeform_text="",
        )

        assert state.resolved_slots["terminal_output"].value == "pdf_document"
        assert [item.name for item in getattr(state, "named_result_evidence", ())] == [
            "case_id",
            "status",
        ]
        assert state.output_schema_evidence is None

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(_classified("terminal_output", "structured_json", "high"),)
            ),
            prompt_hash="e" * 64,
            freeform_text="",
        )

        assert state.resolved_slots["terminal_output"].value == "structured_json"
        assert [item.name for item in getattr(state, "named_result_evidence", ())] == [
            "case_id",
            "status",
        ]
        assert state.output_schema_evidence is None

    def test_explicit_medium_core_slots_are_admitted_without_redundant_questions(
        self,
    ) -> None:
        state = _state()
        source_text = "Användaren skriver text och vill få ett läsbart textresultat."
        classification_input = SlotClassificationInput(
            sources=(
                SlotClassificationSource(
                    source_id="user_message:user-1",
                    kind="user_message",
                    text=source_text,
                    message_id="user-1",
                ),
            )
        )
        classification_result = parse_slot_classification_response(
            json.dumps(
                {
                    "slots": [
                        {
                            "slot_name": "primary_runtime_input",
                            "value": "text",
                            "confidence": "medium",
                            "reason": "The user explicitly supplies text.",
                            "evidence": [
                                {
                                    "source_id": "user_message:user-1",
                                    "quote": "skriver text",
                                }
                            ],
                            "evidence_level": "explicit",
                        },
                        {
                            "slot_name": "terminal_output",
                            "value": "structured_text",
                            "confidence": "medium",
                            "reason": "The user explicitly requests readable text.",
                            "evidence": [
                                {
                                    "source_id": "user_message:user-1",
                                    "quote": "läsbart textresultat",
                                }
                            ],
                            "evidence_level": "explicit",
                        },
                    ],
                    "file_roles": [],
                    "checkpoint_updates": [],
                    "form_intake": None,
                    "named_result_evidence": None,
                    "example_output_constraints": None,
                    "schema_direction": None,
                    "secondary_obligations": [],
                    "assumptions": [],
                    "contradictions": [],
                }
            ),
            allowed_slot_values=llm_resolvable_slot_values_for_state(state),
            classification_input=classification_input,
        )
        assert classification_result is not None

        merge_llm_resolved_slots(
            state,
            classification_result,
            prompt_hash="a" * 64,
            freeform_text="",
        )

        assert {
            name: slot.evidence_level for name, slot in state.resolved_slots.items()
        } == {
            "primary_runtime_input": "explicit",
            "terminal_output": "explicit",
        }
        policy = build_planner_action_policy(
            session_state=state,
            selected_discovery_question_ids=(),
        )
        assert policy.allowed_action_kinds == ("commit_architecture",)
        assert policy.allowed_ask_question_targets == ()

    def test_mismatched_structured_answer_cannot_confirm_a_different_slot(
        self,
    ) -> None:
        state = _state()
        state.resolved_slots["primary_runtime_input"] = ResolvedSlot(
            name="primary_runtime_input",
            value="text",
            source="structured_answer",
            confidence="high",
        )
        classification_result = parse_slot_classification_response(
            json.dumps(
                {
                    "slots": [
                        {
                            "slot_name": "terminal_output",
                            "value": "structured_text",
                            "confidence": "medium",
                            "reason": "The answer says text.",
                            "evidence": [
                                {
                                    "source_id": "structured_answer:input",
                                    "quote": "text",
                                }
                            ],
                            "evidence_level": "explicit",
                        }
                    ],
                    "file_roles": [],
                    "checkpoint_updates": [],
                    "form_intake": None,
                    "named_result_evidence": None,
                    "example_output_constraints": None,
                    "schema_direction": None,
                    "secondary_obligations": [],
                    "assumptions": [],
                    "contradictions": [],
                }
            ),
            allowed_slot_values=llm_resolvable_slot_values_for_state(state),
            classification_input=SlotClassificationInput(
                sources=(
                    SlotClassificationSource(
                        source_id="structured_answer:input",
                        kind="structured_answer",
                        text="text",
                        message_id="user-1",
                        question_id="primary_runtime_input",
                        selected_value="text",
                    ),
                )
            ),
        )
        assert classification_result is not None

        merge_llm_resolved_slots(
            state,
            classification_result,
            prompt_hash="b" * 64,
            freeform_text="",
        )

        terminal_slot = state.resolved_slots["terminal_output"]
        assert terminal_slot.evidence_level == "inferred"
        assert terminal_slot.is_commit_grade is False
        policy = build_planner_action_policy(
            session_state=state,
            selected_discovery_question_ids=(),
        )
        assert policy.allowed_action_kinds == ("ask_question",)
        assert policy.allowed_ask_question_targets == ("terminal_output",)

    def test_comparison_scope_is_classified_only_until_input_is_known_non_document(
        self,
    ) -> None:
        state = _state()
        assert "comparison_scope" in llm_resolvable_slot_values_for_state(state)

        state.resolved_slots["primary_runtime_input"] = _slot(
            name="primary_runtime_input",
            value="audio",
            source="structured_answer",
        )
        assert "comparison_scope" not in llm_resolvable_slot_values_for_state(state)

        state.resolved_slots["primary_runtime_input"] = _slot(
            name="primary_runtime_input",
            value="documents",
            source="structured_answer",
        )
        assert "comparison_scope" in llm_resolvable_slot_values_for_state(state)

        state.resolved_slots["primary_runtime_input"] = _slot(
            name="primary_runtime_input",
            value="audio",
            source="heuristic",
        )
        assert "comparison_scope" in llm_resolvable_slot_values_for_state(state)

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

    def test_model_output_preserves_the_answer_and_corrects_summary_and_flow(
        self,
    ) -> None:
        """What the user answered stands; what was read off the Flow does not.

        A structured answer is the user's own choice. A summary they accepted
        and a fact observed on the Flow being edited are both derived, so a
        cited high-confidence reading of what they said this turn replaces
        them.
        """

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
                        "detailed_runtime_metadata",
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
        corrected_metadata = state.resolved_slots["runtime_metadata_fields"]
        assert corrected_metadata.value == "detailed_runtime_metadata"
        assert corrected_metadata.source == "model"

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

    def test_policy_defaults_prune_weak_slots_after_input_changes_to_audio(
        self,
    ) -> None:
        state = _state()
        state.resolved_slots = {
            "primary_runtime_input": _slot(
                name="primary_runtime_input",
                value="documents",
                source="heuristic",
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
            "comparison_scope": _slot(
                name="comparison_scope",
                value="same_run_compare",
                source="heuristic",
            ),
            "report_disposition": _slot(
                name="report_disposition",
                value="both",
                source="heuristic",
            ),
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(_classified("primary_runtime_input", "audio", "high"),)
            ),
            prompt_hash="c" * 64,
            freeform_text="The runtime input is an audio recording.",
        )
        apply_policy_defaults_from_resolved_slots(
            state,
            freeform_text="The runtime input is an audio recording.",
        )

        assert state.resolved_slots["primary_runtime_input"].value == "audio"
        assert "document_material_scope" not in state.resolved_slots
        assert "comparison_scope" not in state.resolved_slots
        assert "report_disposition" not in state.resolved_slots

    def test_rebuild_prunes_explicit_dependent_slots_after_input_changes(
        self,
    ) -> None:
        def answer(question_id: str, value: str) -> ConversationMessage:
            return ConversationMessage(
                role="user",
                content=value,
                metadata={
                    "question_answer": {
                        "question_id": question_id,
                        "selected_option_id": value,
                        "selected_value": value,
                    }
                },
            )

        state = build_planning_state_from_conversation(
            [
                answer("primary_runtime_input", "documents"),
                answer("terminal_output", "structured_text"),
                answer("document_material_scope", "multiple_documents_case"),
                answer("comparison_scope", "same_run_compare"),
                answer("primary_runtime_input", "audio"),
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "audio"
        assert "document_material_scope" not in state.resolved_slots
        assert "comparison_scope" not in state.resolved_slots

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
                        "detailed_runtime_metadata",
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
        assert slot.value == "detailed_runtime_metadata"
        assert slot.source == "model"
        assert slot.evidence == [
            "model:runtime_metadata_fields:" + "b" * 64,
            "quote:user_message:test-source:runtime_metadata_fields evidence",
        ]

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
                        "detailed_runtime_metadata",
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
                value="detailed_runtime_metadata",
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
                        "basic_runtime_metadata",
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
        assert slot.value == "basic_runtime_metadata"
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
        # The model decision replaces the heuristic's evidence: evidence
        # describes the current decision, not the history of decisions.
        assert role.evidence == [
            f"model:file_role:{'h' * 64}",
            "quote:user_message:test-source:så här ska rapporten se ut",
        ]
        assert role.candidate_roles == ["context_only", "example_output"]

    def test_identical_reclassification_does_not_touch_the_role(self) -> None:
        """An unchanged decision must not churn the persisted role.

        Every turn re-classifies attachments. Appending a fresh
        model:file_role:<hash> plus a duplicate quote on each identical
        decision grew the evidence list without bound and moved every
        state hash derived from it (2026-08-07: the confirmation loop).
        """

        file_id = UUID("00000000-0000-0000-0000-000000000706")
        state = _state()
        state.file_roles = [
            FileRoleEvidence(
                file_id=file_id,
                filename="protokoll.pdf",
                file_type="document",
                mimetype="application/pdf",
                has_readable_text=True,
                coverage="fully_seen",
                role="runtime_input_sample",
                source="model",
                confidence="high",
                evidence_level="explicit",
                evidence=[
                    f"model:file_role:{'a' * 64}",
                    "quote:user_message:test-source:ett typiskt exempel",
                ],
                candidate_roles=["context_only", "runtime_input_sample"],
            )
        ]
        before = state.file_roles[0].model_copy(deep=True)

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                file_roles=(
                    ClassifiedFileRole(
                        file_id=file_id,
                        role="runtime_input_sample",
                        confidence="high",
                        evidence_level="explicit",
                        reason="same decision, new turn",
                        evidence=_model_evidence("ett typiskt exempel"),
                    ),
                )
            ),
            prompt_hash="b" * 64,
            freeform_text="",
        )

        assert state.file_roles[0] == before

    @pytest.mark.parametrize(
        "replacement_quote",
        [
            "ett typiskt exempel",
            "protokollet visar hur resultatet ska se ut",
        ],
    )
    def test_explicit_file_role_cannot_flip_within_the_same_user_source(
        self,
        replacement_quote: str,
    ) -> None:
        file_id = UUID("00000000-0000-0000-0000-000000000707")
        state = _state()
        state.file_roles = [
            FileRoleEvidence(
                file_id=file_id,
                filename="protokoll.pdf",
                file_type="document",
                mimetype="application/pdf",
                has_readable_text=True,
                coverage="fully_seen",
                role="runtime_input_sample",
                source="model",
                confidence="high",
                evidence_level="explicit",
                evidence=[
                    f"model:file_role:{'a' * 64}",
                    "quote:user_message:original-source:ett typiskt exempel",
                ],
                candidate_roles=["context_only", "runtime_input_sample"],
            )
        ]
        before = state.file_roles[0].model_copy(deep=True)

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                file_roles=(
                    ClassifiedFileRole(
                        file_id=file_id,
                        role="example_output",
                        confidence="high",
                        evidence_level="explicit",
                        reason="reinterprets the original request",
                        evidence=_model_evidence(
                            replacement_quote,
                            source_id="user_message:original-source",
                        ),
                    ),
                )
            ),
            prompt_hash="b" * 64,
            freeform_text="",
        )

        assert state.file_roles[0] == before

    def test_inferred_file_role_cannot_replace_an_explicit_role(self) -> None:
        file_id = UUID("00000000-0000-0000-0000-000000000708")
        state = _state()
        state.file_roles = [
            FileRoleEvidence(
                file_id=file_id,
                filename="protokoll.pdf",
                file_type="document",
                mimetype="application/pdf",
                has_readable_text=True,
                coverage="fully_seen",
                role="runtime_input_sample",
                source="model",
                confidence="high",
                evidence_level="explicit",
                evidence=[
                    f"model:file_role:{'a' * 64}",
                    "quote:user_message:original-source:typiskt körningsunderlag",
                ],
            )
        ]
        before = state.file_roles[0].model_copy(deep=True)

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                file_roles=(
                    ClassifiedFileRole(
                        file_id=file_id,
                        role="example_output",
                        confidence="high",
                        evidence_level="inferred",
                        reason="a later inference without an explicit correction",
                        evidence=_model_evidence(
                            "rapportens utseende",
                            source_id="user_message:later-source",
                        ),
                    ),
                )
            ),
            prompt_hash="b" * 64,
            freeform_text="",
        )

        assert state.file_roles[0] == before

    def test_later_explicit_file_role_correction_replaces_evidence_not_appends(
        self,
    ) -> None:
        file_id = UUID("00000000-0000-0000-0000-000000000709")
        state = _state()
        state.file_roles = [
            FileRoleEvidence(
                file_id=file_id,
                filename="mall.docx",
                file_type="document",
                mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                has_readable_text=True,
                coverage="fully_seen",
                role="context_only",
                source="model",
                confidence="medium",
                evidence_level="explicit",
                evidence=[
                    f"model:file_role:{'a' * 64}",
                    "quote:user_message:original-source:använd som bakgrund",
                ],
            )
        ]

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                file_roles=(
                    ClassifiedFileRole(
                        file_id=file_id,
                        role="template",
                        confidence="high",
                        evidence_level="explicit",
                        reason="the user explicitly corrects the upload role",
                        evidence=_model_evidence(
                            "nej, använd den bifogade filen som mall",
                            source_id="user_message:correction-source",
                        ),
                    ),
                )
            ),
            prompt_hash="b" * 64,
            freeform_text="",
        )

        role = state.file_roles[0]
        assert role.role == "template"
        assert role.evidence == [
            f"model:file_role:{'b' * 64}",
            (
                "quote:user_message:correction-source:"
                "nej, använd den bifogade filen som mall"
            ),
        ]

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


def test_deployment_default_reaches_the_mapped_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Config default -> resolver -> Builder proposal: an organization that
    never configured a ceiling proposes the derived item bound (default - 1
    reserved fallback call) instead of blocking authoring."""
    from types import SimpleNamespace

    from eneo.flows.domain.mapped_execution_policy import (
        resolve_flow_mapped_execution_policy,
    )

    monkeypatch.setattr(
        "eneo.flows.domain.mapped_execution_policy.get_settings",
        lambda: SimpleNamespace(flow_mapped_step_max_provider_calls_default=100),
    )
    policy = resolve_flow_mapped_execution_policy(None)

    state = build_planning_state_from_conversation(
        _mapped_file_limit_conversation(),
        mapped_execution_policy=policy,
    )

    assert state.mapped_file_limit.proposed_value == 99
    assert state.mapped_file_limit.accepted_value == 99
    assert state.mapped_file_limit.provenance == "policy_default"
    assert state.mapped_file_limit.diagnostic is None


def test_mapped_file_limit_auto_accepts_the_policy_default_silently() -> None:
    # The shipped default IS the answer: defaults exist to avoid questions.
    # Asking every document flow to confirm the organization ceiling wasted a
    # turn and stalled journeys; authored answers below the ceiling still win.
    state = build_planning_state_from_conversation(
        _mapped_file_limit_conversation(),
        mapped_execution_policy=FlowMappedExecutionPolicy(
            max_provider_calls_per_mapped_step=8
        ),
    )

    # Policy ceiling 8 proposes 7 items: one call stays reserved for the
    # runtime native-JSON fallback attempt.
    assert state.mapped_file_limit.proposed_value == 7
    assert state.mapped_file_limit.accepted_value == 7
    assert state.mapped_file_limit.provenance == "policy_default"
    assert state.mapped_file_limit.diagnostic is None


def test_mapped_file_limit_accepts_organization_limit_with_provenance() -> None:
    state = build_planning_state_from_conversation(
        _mapped_file_limit_conversation(selected_value="organization_limit"),
        mapped_execution_policy=FlowMappedExecutionPolicy(
            max_provider_calls_per_mapped_step=8
        ),
    )

    assert state.mapped_file_limit.accepted_value == 7
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


def test_mapped_file_limit_free_text_response_falls_back_to_the_default() -> None:
    conversation = _mapped_file_limit_conversation()[:-1]
    conversation.append(
        ConversationMessage(
            role="user",
            content="3",
            metadata={"question_response": {"question_id": "mapped_file_limit"}},
        )
    )

    state = build_planning_state_from_conversation(
        conversation,
        mapped_execution_policy=FlowMappedExecutionPolicy(
            max_provider_calls_per_mapped_step=8
        ),
    )

    # An out-of-band free-text reply is not a structured answer; the shipped
    # default applies rather than blocking the journey on a re-ask.
    assert state.mapped_file_limit.proposed_value == 7
    assert state.mapped_file_limit.accepted_value == 7
    assert state.mapped_file_limit.provenance == "policy_default"


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


class TestDocxModeFromTemplateEvidence:
    @staticmethod
    def _template_role(
        *,
        evidence_level: str | None,
        file_id: str = "00000000-0000-0000-0000-000000000801",
    ) -> FileRoleEvidence:
        return FileRoleEvidence(
            file_id=file_id,
            filename="mall.docx",
            file_type="document",
            mimetype=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            has_readable_text=True,
            coverage="fully_seen",
            role="template",
            source="model",
            confidence="high",
            evidence=["quote:user_message:m-1:använd mallen för svaret"],
            evidence_level=evidence_level,
        )

    @staticmethod
    def _placeholder_role(
        file_id: str = "00000000-0000-0000-0000-000000000803",
    ) -> FileRoleEvidence:
        return FileRoleEvidence(
            file_id=file_id,
            filename="mall.docx",
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
            evidence=["content:template_placeholder:kundnamn"],
            template_placeholders=["kundnamn"],
        )

    def test_one_owner_settles_fill_from_either_evidence_kind(self) -> None:
        from_placeholders = self._docx_state()
        from_placeholders.file_roles = [self._placeholder_role()]
        from_words = self._docx_state()
        from_words.file_roles = [self._template_role(evidence_level="explicit")]

        resolve_docx_mode_from_template_evidence(from_placeholders)
        resolve_docx_mode_from_template_evidence(from_words)

        placeholder_slot = from_placeholders.resolved_slots["docx_output_mode"]
        assert placeholder_slot.value == "template_fill_docx"
        assert placeholder_slot.source == "attachment_structure"
        assert placeholder_slot.evidence == [
            "file:00000000-0000-0000-0000-000000000803"
            ":content:template_placeholder:kundnamn"
        ]
        word_slot = from_words.resolved_slots["docx_output_mode"]
        assert word_slot.value == "template_fill_docx"
        assert word_slot.source == "model"

    @staticmethod
    def _docx_state() -> PlanningState:
        state = _state()
        state.resolved_slots["terminal_output"] = ResolvedSlot(
            name="terminal_output",
            value="docx_document",
            source="structured_answer",
            confidence="high",
            evidence=["question_answer:terminal_output"],
        )
        state.resolved_slots["docx_output_mode"] = ResolvedSlot(
            name="docx_output_mode",
            value="generated_docx",
            source="policy_default",
            confidence="medium",
            evidence=["policy_default:docx_output_mode=generated_docx"],
        )
        return state

    def test_single_explicit_template_resolves_template_fill(self) -> None:
        state = self._docx_state()
        state.file_roles = [self._template_role(evidence_level="explicit")]

        resolve_docx_mode_from_template_evidence(state)

        slot = state.resolved_slots["docx_output_mode"]
        assert slot.value == "template_fill_docx"
        assert slot.source == "model"
        assert slot.evidence_level == "explicit"

    def test_inferred_template_keeps_the_question_path(self) -> None:
        state = self._docx_state()
        state.file_roles = [self._template_role(evidence_level="inferred")]

        resolve_docx_mode_from_template_evidence(state)

        assert state.resolved_slots["docx_output_mode"].source == "policy_default"

    def test_multiple_templates_keep_the_question_path(self) -> None:
        state = self._docx_state()
        state.file_roles = [
            self._template_role(evidence_level="explicit"),
            self._template_role(
                evidence_level="explicit",
                file_id="00000000-0000-0000-0000-000000000802",
            ),
        ]

        resolve_docx_mode_from_template_evidence(state)

        assert state.resolved_slots["docx_output_mode"].source == "policy_default"

    def test_explicit_authored_generated_choice_always_wins(self) -> None:
        state = self._docx_state()
        state.resolved_slots["docx_output_mode"] = ResolvedSlot(
            name="docx_output_mode",
            value="generated_docx",
            source="structured_answer",
            confidence="high",
            evidence=["question_answer:docx_output_mode"],
        )
        state.file_roles = [self._template_role(evidence_level="explicit")]

        resolve_docx_mode_from_template_evidence(state)

        slot = state.resolved_slots["docx_output_mode"]
        assert slot.value == "generated_docx"
        assert slot.source == "structured_answer"


class TestMixedRuntimeMaterialChoice:
    """The mixed-material question settles which material a run receives."""

    PROMPT = (
        "Jag vill skapa ett flöde för beslutsberedning där jag vid körning kan "
        "ladda upp mötesljud och flera bilagor. Flödet ska transkribera ljudet, "
        "koppla uttalanden till bilagorna och skapa en besluts-PM i PDF."
    )

    def _answer(
        self,
        question_id: str,
        selected_value: str,
    ) -> ConversationMessage:
        return ConversationMessage(
            role="user",
            content=selected_value,
            metadata={
                "question_answer": {
                    "question_id": question_id,
                    "selected_values": [selected_value],
                }
            },
        )

    def _conversation(self, selected_value: str) -> list[ConversationMessage]:
        return [
            ConversationMessage(role="user", content=self.PROMPT),
            self._answer("flow_input_architecture", selected_value),
        ]

    @pytest.mark.parametrize(
        ("answers", "expected_input", "expected_evidence_question"),
        [
            (
                (
                    ("flow_input_architecture", "audio_primary_input"),
                    ("primary_runtime_input", "documents"),
                ),
                "documents",
                "primary_runtime_input",
            ),
            (
                (
                    ("primary_runtime_input", "documents"),
                    ("flow_input_architecture", "audio_primary_input"),
                ),
                "audio",
                "flow_input_architecture",
            ),
        ],
    )
    def test_the_newest_answer_decides(
        self,
        answers: tuple[tuple[str, str], ...],
        expected_input: str,
        expected_evidence_question: str,
    ) -> None:
        conversation = [
            ConversationMessage(role="user", content=self.PROMPT),
            *(self._answer(question_id, value) for question_id, value in answers),
        ]

        state = build_planning_state_from_conversation(conversation)

        slot = state.resolved_slots["primary_runtime_input"]
        assert slot.value == expected_input
        assert slot.evidence == [f"question_answer:{expected_evidence_question}"]

    @pytest.mark.parametrize(
        "selected_values",
        [
            ("banana",),
            ("audio_primary_input", "banana"),
            ("audio_primary_input", "document_primary_input"),
        ],
    )
    def test_a_selection_the_question_never_offered_settles_nothing(
        self,
        selected_values: tuple[str, ...],
    ) -> None:
        conversation = [
            ConversationMessage(role="user", content=self.PROMPT),
            ConversationMessage(
                role="user",
                content=", ".join(selected_values),
                metadata={
                    "question_answer": {
                        "question_id": "flow_input_architecture",
                        "selected_values": list(selected_values),
                    }
                },
            ),
        ]

        state = build_planning_state_from_conversation(conversation)

        assert "primary_runtime_input" not in state.resolved_slots

    def test_a_later_correction_in_the_users_own_words_wins(self) -> None:
        conversation = [
            ConversationMessage(role="user", content=self.PROMPT),
            self._answer("flow_input_architecture", "audio_primary_input"),
            ConversationMessage(
                role="user",
                content="Jag laddar hellre upp dokumenten vid körning i stället.",
            ),
        ]

        state = build_planning_state_from_conversation(conversation)

        slot = state.resolved_slots["primary_runtime_input"]
        assert slot.value == "documents"
        assert slot.source == "heuristic"

    def test_a_free_text_question_response_is_left_to_the_classifier(self) -> None:
        conversation = [
            ConversationMessage(
                message_id="test-source",
                role="user",
                content="Jag laddar upp dokumenten vid körning.",
                metadata={
                    "question_response": {"question_id": "primary_runtime_input"}
                },
            )
        ]

        state = build_planning_state_from_conversation(conversation)

        assert "primary_runtime_input" not in state.resolved_slots

    @pytest.mark.parametrize(
        ("selected_value", "expected_input"),
        [
            ("audio_primary_input", "audio"),
            ("document_primary_input", "documents"),
        ],
    )
    def test_answer_becomes_the_committed_primary_input(
        self,
        selected_value: str,
        expected_input: str,
    ) -> None:
        state = build_planning_state_from_conversation(
            self._conversation(selected_value)
        )

        slot = state.resolved_slots["primary_runtime_input"]
        assert slot.value == expected_input
        assert slot.source == "structured_answer"
        assert slot.is_commit_grade is True
        assert state.commit_grade_slot_value("primary_runtime_input") == expected_input

    def test_the_choice_outranks_an_earlier_model_reading(self) -> None:
        state = build_planning_state_from_conversation(
            self._conversation("document_primary_input")
        )
        classification = SlotClassificationResult(
            slots=[
                _classified(
                    "primary_runtime_input",
                    "audio",
                    "high",
                    evidence=("ladda upp mötesljud",),
                    evidence_level="explicit",
                )
            ]
        )

        merge_llm_resolved_slots(
            state,
            classification,
            prompt_hash="test-prompt-hash",
            freeform_text=self.PROMPT,
        )

        slot = state.resolved_slots["primary_runtime_input"]
        assert slot.value == "documents"
        assert slot.source == "structured_answer"
