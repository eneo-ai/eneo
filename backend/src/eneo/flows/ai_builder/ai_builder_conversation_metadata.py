"""Typed owners for AI Builder conversation metadata JSON shapes.

Request-only discriminators such as question_answer.kind are removed before
persistence. Persisted conversation metadata keeps the historical compact keys
but all production readers/writers should go through this module so the JSONB
contract has one owner.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal, Protocol, TypeAlias, cast, get_args
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from eneo.flows.ai_builder.ai_builder_canonicalization import (
    canonical_question_id,
    is_supported_structured_question_id,
    normalize_question_answer,
    normalize_structured_question_payload,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    RequirementsSummaryPayload,
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_field_identity import fold_result_field_name
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderEditContext,
    ResolvedAIBuilderEditContext,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import FlowInputFieldIntent
from eneo.flows.ai_builder.ai_builder_result_contract import (
    RESULT_OBLIGATION_VALUES,
    ResultObligation,
)
from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    CLASSIFICATION_EVIDENCE_MAX_ITEMS,
    CLASSIFICATION_EVIDENCE_MAX_LENGTH,
    CLASSIFICATION_NOTE_MAX_LENGTH,
    CLASSIFICATION_NOTES_MAX_ITEMS,
    CLASSIFICATION_REASON_MAX_LENGTH,
    SLOT_CLASSIFICATION_SCHEMA_VERSION,
    UNKNOWN_SLOT_VALUE,
    CheckpointUpdateOperation,
    ClassifiedCheckpointUpdate,
    ClassifiedEvidence,
    ClassifiedFileRole,
    ClassifiedFormIntake,
    ClassifiedSchemaDirection,
    ClassifiedSlot,
    SlotClassificationAttempt,
    SlotClassificationAttemptOutcome,
    SlotClassificationConfidence,
    SlotClassificationEvidenceLevel,
    SlotClassificationInput,
    SlotClassificationResult,
    SlotClassificationSource,
    SlotClassificationSourceKind,
    classification_evidence_has_user_owned_source,
)
from eneo.flows.ai_builder.ai_builder_slot_vocabulary import (
    LLM_RESOLVABLE_SLOT_NAMES,
)
from eneo.flows.ai_builder.planning_state import (
    NAMED_RESULT_EVIDENCE_MAX_ITEMS,
    NAMED_RESULT_FIELD_NAME_MAX_LENGTH,
    NAMED_RESULT_PROVENANCE_MAX_ITEMS,
    AttachmentCoverage,
    CheckpointProducerKind,
    ExampleOutputConstraintEvidence,
    FileRole,
    NamedResultEvidence,
    RuntimeMetadataFieldPurpose,
    is_named_content_fields_edit_reference,
)
from eneo.flows.ai_builder.question_catalog import legal_slot_values
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.flow_review_policy import FlowStepReviewMode
from eneo.main.logging import get_logger

logger = get_logger(__name__)

_EDIT_CONTEXT_ADAPTER: TypeAdapter[AIBuilderEditContext] = TypeAdapter(
    AIBuilderEditContext
)

QUESTION_ANSWER_METADATA_KEY = "question_answer"
QUESTION_RESPONSE_METADATA_KEY = "question_response"
REQUIREMENTS_CONFIRMED_METADATA_KEY = "requirements_confirmed"
REQUIREMENTS_SUMMARY_METADATA_KEY = "requirements_summary"
REQUIREMENTS_VERSION_METADATA_KEY = "requirements_version"
UI_LANGUAGE_METADATA_KEY = "ui_language"
FILE_IDS_METADATA_KEY = "file_ids"
EDIT_CONTEXT_METADATA_KEY = "edit_context"
ASSISTANT_QUESTION_ID_METADATA_KEY = "question_id"
ASSISTANT_QUESTION_INDEX_METADATA_KEY = "question_index"
SLOT_CLASSIFICATION_METADATA_KEY = "slot_classification"
NAMED_CONTENT_FIELDS_EDIT_METADATA_KEY = "named_content_fields_edit"
PROVIDER_TOOL_CALL_ID_MAX_LENGTH = 64

JsonScalar: TypeAlias = str | int | float | bool | None
QuestionAnswerId: TypeAlias = Annotated[str, Field(max_length=128)]
QuestionAnswerStringValue: TypeAlias = Annotated[str, Field(max_length=500)]
QuestionAnswerScalar: TypeAlias = QuestionAnswerStringValue | int | float | bool | None
LLMResolvableSlotName: TypeAlias = Literal[
    "primary_runtime_input",
    "terminal_output",
    "document_material_scope",
    "comparison_scope",
    "report_disposition",
    "post_processing_goal",
    "structured_io_contract",
    "runtime_metadata_fields",
]
ClassifierRetentionClass: TypeAlias = Literal[
    "slot",
    "file_role",
    "checkpoint_update",
    "form_intake",
    "named_result_evidence",
    "example_output_constraint",
    "secondary_obligation",
    "schema_direction",
]
ClassifierRetentionIdentity: TypeAlias = tuple[ClassifierRetentionClass, str]
CLASSIFIER_RETENTION_CLASSES: frozenset[ClassifierRetentionClass] = frozenset(
    {
        "slot",
        "file_role",
        "checkpoint_update",
        "form_intake",
        "named_result_evidence",
        "example_output_constraint",
        "secondary_obligation",
        "schema_direction",
    }
)

_MAX_RESULT_OBLIGATIONS = len(RESULT_OBLIGATION_VALUES)
_MAX_QUESTION_ANSWER_SELECTIONS = 20
_MAX_UI_LANGUAGE_LENGTH = 16
_MAX_REQUIREMENTS_VERSION_LENGTH = 128


class SlotClassificationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    quote: str = Field(min_length=1, max_length=CLASSIFICATION_EVIDENCE_MAX_LENGTH)

    def to_classified_evidence(self) -> ClassifiedEvidence:
        return ClassifiedEvidence(source_id=self.source_id, quote=self.quote)


class SlotClassificationSourceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    kind: SlotClassificationSourceKind
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    message_id: str | None = Field(default=None, min_length=1)
    question_id: str | None = Field(default=None, min_length=1)
    selected_value: str | None = None
    file_id: UUID | None = None
    coverage: AttachmentCoverage | None = None
    truncated: bool = False

    @model_validator(mode="after")
    def require_kind_identity(self) -> "SlotClassificationSourceMetadata":
        if self.kind == "user_message" and self.message_id is None:
            raise ValueError("user-message classification source requires message_id")
        if self.kind == "structured_answer" and (
            self.message_id is None
            or self.question_id is None
            or not self.selected_value
        ):
            raise ValueError(
                "structured-answer classification source requires message, question, "
                "and selected value"
            )
        if self.kind == "uploaded_file" and (
            self.file_id is None or self.coverage is None
        ):
            raise ValueError(
                "uploaded-file classification source requires file id and coverage"
            )
        return self


def _empty_slot_classification_evidence() -> list[SlotClassificationEvidence]:
    return []


class SlotClassificationFileRoleMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: UUID
    role: FileRole
    confidence: SlotClassificationConfidence
    reason: str = Field(min_length=1, max_length=CLASSIFICATION_REASON_MAX_LENGTH)
    evidence: list[SlotClassificationEvidence] = Field(
        default_factory=_empty_slot_classification_evidence,
        max_length=CLASSIFICATION_EVIDENCE_MAX_ITEMS,
    )
    evidence_level: SlotClassificationEvidenceLevel = "inferred"

    @model_validator(mode="after")
    def require_evidence_for_supported_confidence(
        self,
    ) -> "SlotClassificationFileRoleMetadata":
        if self.confidence != "low" and not self.evidence:
            raise ValueError("supported file role classification requires evidence")
        return self

    def to_classified_file_role(self) -> ClassifiedFileRole:
        return ClassifiedFileRole(
            file_id=self.file_id,
            role=self.role,
            confidence=self.confidence,
            reason=self.reason,
            evidence=tuple(item.to_classified_evidence() for item in self.evidence),
            evidence_level=self.evidence_level,
        )


class SlotClassificationCheckpointUpdateMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: CheckpointUpdateOperation
    producer_kind: CheckpointProducerKind
    mode: FlowStepReviewMode | None = None
    confidence: SlotClassificationConfidence
    reason: str = Field(min_length=1, max_length=CLASSIFICATION_REASON_MAX_LENGTH)
    evidence: list[SlotClassificationEvidence] = Field(
        default_factory=_empty_slot_classification_evidence,
        min_length=1,
        max_length=CLASSIFICATION_EVIDENCE_MAX_ITEMS,
    )
    evidence_level: SlotClassificationEvidenceLevel = "inferred"

    @model_validator(mode="after")
    def validate_update_contract(self) -> SlotClassificationCheckpointUpdateMetadata:
        if self.confidence == "low":
            raise ValueError("checkpoint update requires supported confidence")
        if (self.operation == "update") != (self.mode is not None):
            raise ValueError("checkpoint update mode must match its operation")
        return self

    def to_classified_checkpoint_update(self) -> ClassifiedCheckpointUpdate:
        return ClassifiedCheckpointUpdate(
            operation=self.operation,
            producer_kind=self.producer_kind,
            mode=self.mode,
            confidence=self.confidence,
            reason=self.reason,
            evidence=tuple(item.to_classified_evidence() for item in self.evidence),
            evidence_level=self.evidence_level,
        )


class SlotClassificationSlotMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_name: LLMResolvableSlotName
    value: str = Field(min_length=1, max_length=128)
    confidence: SlotClassificationConfidence
    reason: str = Field(min_length=1, max_length=CLASSIFICATION_REASON_MAX_LENGTH)
    evidence: list[SlotClassificationEvidence] = Field(
        default_factory=_empty_slot_classification_evidence,
        max_length=CLASSIFICATION_EVIDENCE_MAX_ITEMS,
    )
    evidence_level: SlotClassificationEvidenceLevel = "inferred"

    @model_validator(mode="after")
    def validate_slot_value(self) -> "SlotClassificationSlotMetadata":
        legal_values = legal_slot_values(self.slot_name) | {"unknown"}
        if self.value not in legal_values:
            raise ValueError(f"unsupported slot value for {self.slot_name}")
        if self.confidence != "low" and not self.evidence:
            raise ValueError("supported slot classification requires evidence")
        return self

    def to_classified_slot(self) -> ClassifiedSlot:
        return ClassifiedSlot(
            slot_name=self.slot_name,
            value=self.value,
            confidence=self.confidence,
            reason=self.reason,
            evidence=tuple(item.to_classified_evidence() for item in self.evidence),
            evidence_level=self.evidence_level,
        )


class SlotClassificationFormIntakeMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    needs_form_fields: bool = False
    sectioned_form_intake: bool = False
    confidence: SlotClassificationConfidence
    reason: str = Field(min_length=1, max_length=CLASSIFICATION_REASON_MAX_LENGTH)
    evidence: list[SlotClassificationEvidence] = Field(
        default_factory=_empty_slot_classification_evidence,
        max_length=CLASSIFICATION_EVIDENCE_MAX_ITEMS,
    )
    evidence_level: SlotClassificationEvidenceLevel = "inferred"

    @model_validator(mode="after")
    def require_positive_signal(self) -> "SlotClassificationFormIntakeMetadata":
        if not self.needs_form_fields and not self.sectioned_form_intake:
            raise ValueError("form_intake metadata must contain a positive signal")
        if self.confidence != "low" and not self.evidence:
            raise ValueError("supported form intake classification requires evidence")
        return self

    def to_classified_form_intake(self) -> ClassifiedFormIntake:
        return ClassifiedFormIntake(
            needs_form_fields=self.needs_form_fields or self.sectioned_form_intake,
            sectioned_form_intake=self.sectioned_form_intake,
            confidence=self.confidence,
            reason=self.reason,
            evidence=tuple(item.to_classified_evidence() for item in self.evidence),
            evidence_level=self.evidence_level,
        )


class SlotClassificationNamedResultEvidenceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["replace", "clear"]
    named_results: list[NamedResultEvidence] = Field(
        max_length=NAMED_RESULT_EVIDENCE_MAX_ITEMS
    )
    confidence: SlotClassificationConfidence
    reason: str = Field(min_length=1, max_length=CLASSIFICATION_REASON_MAX_LENGTH)
    evidence: list[SlotClassificationEvidence] = Field(
        min_length=1,
        max_length=NAMED_RESULT_PROVENANCE_MAX_ITEMS,
    )

    @model_validator(mode="after")
    def require_operation_shape(
        self,
    ) -> "SlotClassificationNamedResultEvidenceMetadata":
        if self.operation == "replace" and not self.named_results:
            raise ValueError("replace named-result evidence requires named results")
        if self.operation == "clear" and self.named_results:
            raise ValueError(
                "clear named-result evidence must not contain named results"
            )
        folded_names = [
            fold_result_field_name(item.name) for item in self.named_results
        ]
        if any(not name for name in folded_names) or len(folded_names) != len(
            set(folded_names)
        ):
            raise ValueError("named-result evidence names must be uniquely foldable")
        planning_references = {
            item.to_classified_evidence().planning_reference() for item in self.evidence
        }
        if any(
            reference not in planning_references
            # A name the user typed into the confirmation card cites that
            # edit, not a quote this reading found. The snapshot still has to
            # carry the name — it states the whole set — but it cannot account
            # for provenance that was never the classifier's to begin with.
            and not is_named_content_fields_edit_reference(reference)
            for item in self.named_results
            for reference in item.evidence
        ):
            raise ValueError(
                "named-result evidence must cite snapshot planning references"
            )
        return self

    @classmethod
    def from_materialized_state(
        cls,
        *,
        operation: Literal["replace", "clear"],
        named_results: Sequence[NamedResultEvidence],
        confidence: SlotClassificationConfidence,
        reason: str,
        evidence: Sequence[ClassifiedEvidence],
    ) -> "SlotClassificationNamedResultEvidenceMetadata":
        return cls(
            operation=operation,
            named_results=list(named_results),
            confidence=confidence,
            reason=_bounded_metadata_text(
                reason,
                fallback="named-result classification",
            ),
            evidence=[
                SlotClassificationEvidence(
                    source_id=item.source_id,
                    quote=item.quote,
                )
                for item in evidence
            ],
        )


SchemaFingerprint: TypeAlias = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SlotClassificationSchemaDirectionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_fingerprints: list[SchemaFingerprint] = Field(
        min_length=1,
        max_length=100,
    )
    input_fingerprint: SchemaFingerprint | None = None
    output_fingerprint: SchemaFingerprint | None = None
    reference_only: bool
    confidence: SlotClassificationConfidence
    reason: str = Field(min_length=1, max_length=CLASSIFICATION_REASON_MAX_LENGTH)
    evidence: list[SlotClassificationEvidence] = Field(
        default_factory=_empty_slot_classification_evidence,
        max_length=CLASSIFICATION_EVIDENCE_MAX_ITEMS,
    )

    @model_validator(mode="after")
    def validate_complete_direction(
        self,
    ) -> "SlotClassificationSchemaDirectionMetadata":
        if self.candidate_fingerprints != sorted(set(self.candidate_fingerprints)):
            raise ValueError("schema direction candidate set must be unique and sorted")
        current = set(self.candidate_fingerprints)
        if any(
            fingerprint not in current
            for fingerprint in (self.input_fingerprint, self.output_fingerprint)
            if fingerprint is not None
        ):
            raise ValueError("schema direction must select a current candidate")
        if self.reference_only:
            if (
                self.input_fingerprint is not None
                or self.output_fingerprint is not None
            ):
                raise ValueError("reference-only direction cannot select a boundary")
        elif self.input_fingerprint is None and self.output_fingerprint is None:
            raise ValueError("schema direction must select a boundary")
        if self.confidence != "low" and not self.evidence:
            raise ValueError("supported schema direction requires cited evidence")
        return self

    def to_classified_schema_direction(self) -> ClassifiedSchemaDirection:
        return ClassifiedSchemaDirection(
            candidate_fingerprints=tuple(self.candidate_fingerprints),
            input_fingerprint=self.input_fingerprint,
            output_fingerprint=self.output_fingerprint,
            reference_only=self.reference_only,
            confidence=self.confidence,
            reason=self.reason,
            evidence=tuple(item.to_classified_evidence() for item in self.evidence),
        )


SlotClassificationNote: TypeAlias = Annotated[
    str,
    Field(min_length=1, max_length=CLASSIFICATION_NOTE_MAX_LENGTH),
]


def _empty_slot_classification_slots() -> list[SlotClassificationSlotMetadata]:
    return []


def _empty_slot_classification_sources() -> list[SlotClassificationSourceMetadata]:
    return []


def _empty_slot_classification_file_roles() -> list[SlotClassificationFileRoleMetadata]:
    return []


def _empty_slot_classification_checkpoint_updates() -> list[
    SlotClassificationCheckpointUpdateMetadata
]:
    return []


def _empty_slot_classification_notes() -> list[SlotClassificationNote]:
    return []


def _empty_result_obligations() -> list[ResultObligation]:
    return []


class SlotClassificationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    outcome: SlotClassificationAttemptOutcome
    prompt_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    model: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    source_inventory: list[SlotClassificationSourceMetadata] = Field(
        default_factory=_empty_slot_classification_sources,
        max_length=500,
    )
    slots: list[SlotClassificationSlotMetadata] = Field(
        default_factory=_empty_slot_classification_slots,
        max_length=len(LLM_RESOLVABLE_SLOT_NAMES),
    )
    file_roles: list[SlotClassificationFileRoleMetadata] = Field(
        default_factory=_empty_slot_classification_file_roles,
        max_length=100,
    )
    checkpoint_updates: list[SlotClassificationCheckpointUpdateMetadata] = Field(
        default_factory=_empty_slot_classification_checkpoint_updates,
        max_length=len(get_args(CheckpointProducerKind)),
    )
    secondary_obligations: list[ResultObligation] = Field(
        default_factory=_empty_result_obligations,
        max_length=_MAX_RESULT_OBLIGATIONS,
    )
    form_intake: SlotClassificationFormIntakeMetadata | None = None
    named_result_evidence: SlotClassificationNamedResultEvidenceMetadata | None = None
    example_output_constraints: ExampleOutputConstraintEvidence | None = None
    schema_direction: SlotClassificationSchemaDirectionMetadata | None = None
    assumptions: list[SlotClassificationNote] = Field(
        default_factory=_empty_slot_classification_notes,
        max_length=CLASSIFICATION_NOTES_MAX_ITEMS,
    )
    contradictions: list[SlotClassificationNote] = Field(
        default_factory=_empty_slot_classification_notes,
        max_length=CLASSIFICATION_NOTES_MAX_ITEMS,
    )

    @field_validator("schema_version")
    @classmethod
    def require_current_schema_version(cls, schema_version: int) -> int:
        if schema_version != SLOT_CLASSIFICATION_SCHEMA_VERSION:
            raise ValueError("unsupported slot classification metadata version")
        return schema_version

    @field_validator("slots")
    @classmethod
    def ensure_unique_slots(
        cls,
        slots: list[SlotClassificationSlotMetadata],
    ) -> list[SlotClassificationSlotMetadata]:
        slot_names = [slot.slot_name for slot in slots]
        if len(slot_names) != len(set(slot_names)):
            raise ValueError("slot classification metadata must not duplicate slots")
        return slots

    @field_validator("source_inventory")
    @classmethod
    def ensure_unique_sources(
        cls,
        sources: list[SlotClassificationSourceMetadata],
    ) -> list[SlotClassificationSourceMetadata]:
        source_ids = [source.source_id for source in sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("slot classification metadata must not duplicate sources")
        return sources

    @field_validator("file_roles")
    @classmethod
    def ensure_unique_file_roles(
        cls,
        file_roles: list[SlotClassificationFileRoleMetadata],
    ) -> list[SlotClassificationFileRoleMetadata]:
        file_ids = [item.file_id for item in file_roles]
        if len(file_ids) != len(set(file_ids)):
            raise ValueError(
                "slot classification metadata must not duplicate file roles"
            )
        return file_roles

    @field_validator("checkpoint_updates")
    @classmethod
    def ensure_unique_checkpoint_producers(
        cls,
        checkpoint_updates: list[SlotClassificationCheckpointUpdateMetadata],
    ) -> list[SlotClassificationCheckpointUpdateMetadata]:
        producers = [update.producer_kind for update in checkpoint_updates]
        if len(producers) != len(set(producers)):
            raise ValueError(
                "slot classification metadata must not duplicate checkpoint producers"
            )
        return checkpoint_updates

    @model_validator(mode="after")
    def validate_evidence_sources(self) -> "SlotClassificationMetadata":
        if self.outcome in {
            "skipped_context_budget",
            "skipped_no_resolvable_slots",
        }:
            if self.prompt_hash is not None:
                raise ValueError(
                    "skipped slot classification metadata must not carry prompt_hash"
                )
        elif self.prompt_hash is None:
            raise ValueError(
                "provider-call slot classification metadata requires prompt_hash"
            )
        if self.outcome != "resolved" and any(
            (
                self.slots,
                self.assumptions,
                self.file_roles,
                self.checkpoint_updates,
                self.secondary_obligations,
                self.form_intake is not None,
                self.named_result_evidence is not None,
                self.example_output_constraints is not None,
                self.schema_direction is not None,
                self.contradictions,
            )
        ):
            raise ValueError(
                "non-resolved slot classification metadata cannot carry semantic facts"
            )
        sources_by_id = {source.source_id: source for source in self.source_inventory}
        source_ids = set(sources_by_id)
        evidence_items = [evidence for slot in self.slots for evidence in slot.evidence]
        evidence_items.extend(
            evidence for file_role in self.file_roles for evidence in file_role.evidence
        )
        evidence_items.extend(
            evidence
            for checkpoint_update in self.checkpoint_updates
            for evidence in checkpoint_update.evidence
        )
        if self.form_intake is not None:
            evidence_items.extend(self.form_intake.evidence)
        if self.named_result_evidence is not None:
            evidence_items.extend(self.named_result_evidence.evidence)
        if self.schema_direction is not None:
            evidence_items.extend(self.schema_direction.evidence)
        if any(evidence.source_id not in source_ids for evidence in evidence_items):
            raise ValueError("classification evidence must cite inventoried sources")
        source_kinds_by_id: dict[str, SlotClassificationSourceKind] = {
            source.source_id: source.kind for source in self.source_inventory
        }
        if any(
            not classification_evidence_has_user_owned_source(
                (evidence.source_id for evidence in update.evidence),
                source_kinds_by_id=source_kinds_by_id,
            )
            for update in self.checkpoint_updates
        ):
            raise ValueError("checkpoint updates require user-owned evidence")
        if any(
            slot.slot_name == "terminal_output"
            and not classification_evidence_has_user_owned_source(
                (evidence.source_id for evidence in slot.evidence),
                source_kinds_by_id=source_kinds_by_id,
            )
            for slot in self.slots
        ):
            raise ValueError(
                "terminal-output classification requires user-owned evidence"
            )
        if (
            self.schema_direction is not None
            and self.schema_direction.confidence != "low"
            and not classification_evidence_has_user_owned_source(
                (evidence.source_id for evidence in self.schema_direction.evidence),
                source_kinds_by_id=source_kinds_by_id,
            )
        ):
            raise ValueError("schema direction requires user-owned evidence")
        if (
            self.named_result_evidence is not None
            and not classification_evidence_has_user_owned_source(
                (
                    evidence.source_id
                    for evidence in self.named_result_evidence.evidence
                ),
                source_kinds_by_id=source_kinds_by_id,
            )
        ):
            raise ValueError("named-result evidence requires user-owned evidence")
        file_ids = {
            source.file_id
            for source in self.source_inventory
            if source.kind == "uploaded_file" and source.file_id is not None
        }
        if any(file_role.file_id not in file_ids for file_role in self.file_roles):
            raise ValueError("classified file roles must cite inventoried files")
        constraints = self.example_output_constraints
        if constraints is None:
            return self
        if any(
            citation.source_id not in source_ids for citation in constraints.citations
        ):
            raise ValueError("example output constraints must cite inventoried sources")
        for citation in constraints.citations:
            source = sources_by_id[citation.source_id]
            expected_file_id = (
                source.file_id if source.kind == "uploaded_file" else None
            )
            if citation.file_id != expected_file_id:
                raise ValueError(
                    "example output citation file_id must match its source"
                )
        uploaded_sources_by_file_id = {
            source.file_id: source
            for source in self.source_inventory
            if source.kind == "uploaded_file" and source.file_id is not None
        }
        coverage_by_file_id = {
            item.file_id: item.coverage for item in constraints.source_coverage
        }
        if any(
            uploaded_sources_by_file_id.get(file_id) is None
            for file_id in constraints.source_file_ids
        ):
            raise ValueError("example output constraints must cite inventoried files")
        if any(
            uploaded_sources_by_file_id[file_id].coverage
            != coverage_by_file_id[file_id]
            for file_id in constraints.source_file_ids
        ):
            raise ValueError("example output coverage must match inventoried sources")
        cited_file_ids = {
            citation.file_id
            for citation in constraints.citations
            if citation.file_id is not None
        }
        if cited_file_ids != set(constraints.source_file_ids):
            raise ValueError("example output constraints must cite every selected file")
        return self

    def to_result(self) -> SlotClassificationResult:
        if self.outcome != "resolved":
            raise ValueError(
                "Only resolved slot classification metadata carries a result"
            )
        return SlotClassificationResult(
            slots=tuple(slot.to_classified_slot() for slot in self.slots),
            file_roles=tuple(
                file_role.to_classified_file_role() for file_role in self.file_roles
            ),
            checkpoint_updates=tuple(
                update.to_classified_checkpoint_update()
                for update in self.checkpoint_updates
            ),
            form_intake=self.form_intake.to_classified_form_intake()
            if self.form_intake is not None
            else None,
            example_output_constraints=self.example_output_constraints,
            schema_direction=(
                self.schema_direction.to_classified_schema_direction()
                if self.schema_direction is not None
                else None
            ),
            secondary_obligations=tuple(self.secondary_obligations),
            assumptions=tuple(self.assumptions),
            contradictions=tuple(self.contradictions),
        )

    def effective_retention_identities(self) -> frozenset[ClassifierRetentionIdentity]:
        """Return classifier facts that can affect deterministic rebuild replay."""
        if self.outcome != "resolved":
            return frozenset()
        identities: set[ClassifierRetentionIdentity] = set()
        for slot in self.slots:
            if slot.value == UNKNOWN_SLOT_VALUE or (
                slot.confidence != "low" and slot.evidence
            ):
                identities.add(("slot", slot.slot_name))
        identities.update(
            ("file_role", str(file_role.file_id))
            for file_role in self.file_roles
            if file_role.confidence != "low" and file_role.evidence
        )
        identities.update(
            ("checkpoint_update", update.producer_kind)
            for update in self.checkpoint_updates
        )
        if (
            self.form_intake is not None
            and self.form_intake.confidence != "low"
            and self.form_intake.evidence
        ):
            identities.add(("form_intake", "form_intake"))
        if (
            self.example_output_constraints is not None
            and self.example_output_constraints.confidence != "low"
            and self.example_output_constraints.citations
        ):
            identities.add(("example_output_constraint", "current"))
        if (
            self.named_result_evidence is not None
            and self.named_result_evidence.confidence != "low"
            and self.named_result_evidence.evidence
        ):
            identities.add(("named_result_evidence", "current"))
        identities.update(
            ("secondary_obligation", obligation)
            for obligation in self.secondary_obligations
        )
        if self.schema_direction is not None:
            identities.add(("schema_direction", "complete"))
        return frozenset(identities)

    def retain_effective_semantics(
        self,
        identities: frozenset[ClassifierRetentionIdentity],
        *,
        compaction_limits: frozenset[Literal["count", "bytes"]] = frozenset(),
    ) -> "SlotClassificationMetadata":
        """Project one classifier run to effective rebuild facts and their sources."""
        slots = [slot for slot in self.slots if ("slot", slot.slot_name) in identities]
        file_roles = [
            file_role
            for file_role in self.file_roles
            if ("file_role", str(file_role.file_id)) in identities
        ]
        checkpoint_updates = [
            update
            for update in self.checkpoint_updates
            if ("checkpoint_update", update.producer_kind) in identities
        ]
        form_intake = (
            self.form_intake if ("form_intake", "form_intake") in identities else None
        )
        named_result_evidence = (
            self.named_result_evidence
            if ("named_result_evidence", "current") in identities
            else None
        )
        example_output_constraints = (
            self.example_output_constraints
            if ("example_output_constraint", "current") in identities
            else None
        )
        schema_direction = (
            self.schema_direction
            if ("schema_direction", "complete") in identities
            else None
        )
        secondary_obligations = [
            obligation
            for obligation in self.secondary_obligations
            if ("secondary_obligation", obligation) in identities
        ]
        evidence_source_ids = {
            evidence.source_id
            for evidence in (
                *[evidence for slot in slots for evidence in slot.evidence],
                *[
                    evidence
                    for file_role in file_roles
                    for evidence in file_role.evidence
                ],
                *[
                    evidence
                    for checkpoint_update in checkpoint_updates
                    for evidence in checkpoint_update.evidence
                ],
                *([] if form_intake is None else form_intake.evidence),
                *(
                    []
                    if named_result_evidence is None
                    else named_result_evidence.evidence
                ),
                *(
                    []
                    if example_output_constraints is None
                    else example_output_constraints.citations
                ),
                *([] if schema_direction is None else schema_direction.evidence),
            )
        }
        retained_file_ids = {
            *[file_role.file_id for file_role in file_roles],
            *(
                []
                if example_output_constraints is None
                else example_output_constraints.source_file_ids
            ),
        }
        source_inventory = [
            source
            for source in self.source_inventory
            if source.source_id in evidence_source_ids
            or source.file_id in retained_file_ids
        ]
        contradictions = (
            [
                "conversation_compaction:"
                + ",".join(
                    limit for limit in ("count", "bytes") if limit in compaction_limits
                )
            ]
            if compaction_limits
            else []
        )
        return self.model_copy(
            update={
                "source_inventory": source_inventory,
                "slots": slots,
                "file_roles": file_roles,
                "checkpoint_updates": checkpoint_updates,
                "secondary_obligations": secondary_obligations,
                "form_intake": form_intake,
                "named_result_evidence": named_result_evidence,
                "example_output_constraints": example_output_constraints,
                "schema_direction": schema_direction,
                # Free-form model notes are diagnostics, not rebuild facts, and
                # never reach the requirements disclosure. Compaction keeps only
                # its typed, consumer-visible degradation marker here.
                "assumptions": [],
                "contradictions": contradictions,
            }
        )


if set(get_args(LLMResolvableSlotName)) != set(LLM_RESOLVABLE_SLOT_NAMES):
    raise RuntimeError("LLMResolvableSlotName must match LLM_RESOLVABLE_SLOT_NAMES")


class RuntimeMetadataFieldAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: FlowInputFieldIntent
    purpose: RuntimeMetadataFieldPurpose

    @field_validator("value", mode="after")
    @classmethod
    def confirm_submitted_value(
        cls,
        value: FlowInputFieldIntent,
    ) -> FlowInputFieldIntent:
        return value.model_copy(update={"provenance": "user_confirmed"})


class StructuredQuestionAnswerRequest(BaseModel):
    """A selection the user made, exactly as a client may state it."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["structured_question_answer"] = "structured_question_answer"
    question_id: QuestionAnswerId | None = None
    selected_option_ids: list[QuestionAnswerId] | None = Field(
        default=None,
        max_length=_MAX_QUESTION_ANSWER_SELECTIONS,
    )
    selected_values: list[QuestionAnswerScalar] | None = Field(
        default=None,
        max_length=_MAX_QUESTION_ANSWER_SELECTIONS,
    )
    selected_option_id: QuestionAnswerId | None = None
    selected_value: QuestionAnswerScalar = None
    answer: QuestionAnswerScalar = None
    custom_value: str | None = Field(default=None, max_length=500)
    input_fields: list[RuntimeMetadataFieldAnswer] | None = Field(
        default=None,
        max_length=20,
    )
    ui_language: str | None = Field(
        default=None,
        max_length=_MAX_UI_LANGUAGE_LENGTH,
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_ids(cls, data: object) -> object:
        if not isinstance(data, Mapping):
            return data
        payload = dict(cast(Mapping[str, Any], data))
        payload.setdefault("kind", "structured_question_answer")
        return normalize_question_answer(payload)

    @model_validator(mode="after")
    def require_answer_specific_payload(self) -> "StructuredQuestionAnswerRequest":
        is_field_details = self.question_id == "runtime_metadata_field_details"
        if is_field_details and not self.input_fields:
            raise ValueError(
                "runtime metadata field details require at least one field"
            )
        if is_field_details and self.input_fields:
            field_names = [
                field.value.variable_name.casefold() for field in self.input_fields
            ]
            if len(field_names) != len(set(field_names)):
                raise ValueError(
                    "runtime metadata field details require unique field names"
                )
        if is_field_details and any(
            value is not None
            for value in (
                self.selected_option_ids,
                self.selected_values,
                self.selected_option_id,
                self.selected_value,
                self.answer,
                self.custom_value,
            )
        ):
            raise ValueError("runtime metadata field details accept only input_fields")
        if not is_field_details and self.input_fields is not None:
            raise ValueError(
                "input_fields are only valid for runtime metadata field details"
            )
        return self


class StructuredQuestionAnswerMetadata(StructuredQuestionAnswerRequest):
    """A recorded answer, including who chose the option in it.

    Delegation is the server's account of how the answer came about, so it
    lives only on the persisted shape; a client that could set it could make
    replay claim Eneo chose something the user picked.
    """

    delegated: bool = Field(
        default=False,
        exclude_if=lambda value: value is False,
    )


class QuestionResponseMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: Annotated[str, Field(min_length=1, max_length=128)]

    @field_validator("question_id", mode="before")
    @classmethod
    def normalize_question_id(cls, question_id: object) -> object:
        if not isinstance(question_id, str):
            return question_id
        return canonical_question_id(question_id)

    @field_validator("question_id")
    @classmethod
    def require_supported_question_id(cls, question_id: str) -> str:
        if not is_supported_structured_question_id(question_id):
            raise ValueError("question response requires a supported question id")
        return question_id


class RequirementsConfirmationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["requirements_confirmation"] = "requirements_confirmation"
    requirements_confirmed: Literal[True] = True
    # A confirmation names the exact disclosure it attests to. Without the
    # version there is no way to tell which summary the user actually saw.
    requirements_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    ui_language: str | None = Field(
        default=None,
        max_length=_MAX_UI_LANGUAGE_LENGTH,
    )


class DelegatedQuestionAnswerRequest(BaseModel):
    """The user handing one question back to Eneo, naming no option.

    A delegation carries no selection because the user is declining to make
    one; the server answers it with the recommendation the question showed.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["delegated_question_answer"] = "delegated_question_answer"
    question_id: QuestionAnswerId
    ui_language: str | None = Field(
        default=None,
        max_length=_MAX_UI_LANGUAGE_LENGTH,
    )

    @field_validator("question_id", mode="before")
    @classmethod
    def normalize_question_id(cls, question_id: object) -> object:
        if not isinstance(question_id, str):
            return question_id
        return canonical_question_id(question_id)


class NamedContentFieldsEditRequest(BaseModel):
    """The names the user leaves standing on the confirmation card.

    The payload is the resulting full set, not a delta: the user is answering
    a disclosure they can see in front of them, so what they submit is simply
    what the card should say. That also makes the edit idempotent and makes
    `requirements_version` mean something — it names the exact disclosure
    whose fields these are, and an edit against an older one is refused rather
    than merged.

    Names only. The label the card shows is prose the disclosure owner renders
    from the name and the shape the user declared, so a client-supplied label
    could only disagree with it.

    `added_field_names` is the server's own reading of the same submission, not
    something a client states: which of these names the card did not already
    show. Keeping a chip and re-adding a chip look identical in the resulting
    set but mean different things — the first carries the shape and quotes the
    name already had, the second starts over — and the difference is only
    visible against the disclosure being answered. Recorded here so the edit
    still means the same thing on a later replay, when earlier turns may have
    been compacted away.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["named_content_fields_edit"] = "named_content_fields_edit"
    requirements_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    field_names: list[
        Annotated[str, Field(max_length=NAMED_RESULT_FIELD_NAME_MAX_LENGTH)]
    ] = Field(max_length=NAMED_RESULT_EVIDENCE_MAX_ITEMS)
    added_field_names: list[
        Annotated[str, Field(max_length=NAMED_RESULT_FIELD_NAME_MAX_LENGTH)]
    ] = Field(default_factory=list[str], max_length=NAMED_RESULT_EVIDENCE_MAX_ITEMS)
    ui_language: str | None = Field(
        default=None,
        max_length=_MAX_UI_LANGUAGE_LENGTH,
    )

    @model_validator(mode="after")
    def require_added_names_among_the_set(self) -> "NamedContentFieldsEditRequest":
        submitted = {fold_result_field_name(name) for name in self.field_names}
        if any(
            fold_result_field_name(name) not in submitted
            for name in self.added_field_names
        ):
            raise ValueError("added named-result fields must be part of the edited set")
        return self

    @property
    def added_field_folds(self) -> frozenset[str]:
        return frozenset(
            fold_result_field_name(name) for name in self.added_field_names
        )


AIBuilderQuestionAnswerRequest: TypeAlias = Annotated[
    StructuredQuestionAnswerRequest
    | DelegatedQuestionAnswerRequest
    | RequirementsConfirmationMetadata
    | NamedContentFieldsEditRequest,
    Field(discriminator="kind"),
]

AIBuilderQuestionAnswerInput: TypeAlias = (
    StructuredQuestionAnswerRequest
    | DelegatedQuestionAnswerRequest
    | RequirementsConfirmationMetadata
    | NamedContentFieldsEditRequest
    | Mapping[str, Any]
)


def named_content_fields_edit_from_input(
    value: AIBuilderQuestionAnswerInput | None,
) -> NamedContentFieldsEditRequest | None:
    if value is None:
        return None
    data = _model_or_mapping_data(value)
    if data.get("kind") != "named_content_fields_edit":
        return None
    try:
        return NamedContentFieldsEditRequest.model_validate(data)
    except ValidationError:
        return None


def named_content_fields_edit_from_metadata(
    metadata: object,
) -> NamedContentFieldsEditRequest | None:
    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return None
    edit = _mapping_value(metadata_map.get(NAMED_CONTENT_FIELDS_EDIT_METADATA_KEY))
    if edit is None:
        return None
    data = dict(edit)
    data.setdefault("kind", "named_content_fields_edit")
    try:
        return NamedContentFieldsEditRequest.model_validate(data)
    except ValidationError as error:
        _warn_invalid_persisted_metadata(
            NAMED_CONTENT_FIELDS_EDIT_METADATA_KEY,
            error,
        )
        return None


def named_content_fields_edit_to_metadata(
    edit: NamedContentFieldsEditRequest,
) -> FlowPersistedJsonObject:
    return {
        NAMED_CONTENT_FIELDS_EDIT_METADATA_KEY: edit.model_dump(
            mode="json",
            exclude={"kind", "ui_language"},
        )
    }


def delegated_question_answer_from_input(
    value: AIBuilderQuestionAnswerInput | None,
) -> DelegatedQuestionAnswerRequest | None:
    if value is None:
        return None
    data = _model_or_mapping_data(value)
    if data.get("kind") != "delegated_question_answer":
        return None
    try:
        return DelegatedQuestionAnswerRequest.model_validate(data)
    except ValidationError:
        return None


def structured_question_answer_request_from_input(
    value: AIBuilderQuestionAnswerInput | None,
) -> StructuredQuestionAnswerRequest | None:
    """Read a selection a client stated, refusing any server-owned field."""
    if value is None:
        return None
    data = _model_or_mapping_data(value)
    if data.get("kind") not in (None, "structured_question_answer"):
        return None
    if data.get("requirements_confirmed") is True:
        return None
    data.setdefault("kind", "structured_question_answer")
    try:
        return StructuredQuestionAnswerRequest.model_validate(data)
    except ValidationError:
        return None


class PersistedAssistantToolCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    arguments: FlowPersistedJsonObject = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def parse_json_arguments(cls, data: object) -> object:
        if not isinstance(data, Mapping):
            return data
        payload = dict(cast(Mapping[str, Any], data))
        raw_arguments = payload.get("arguments")
        if isinstance(raw_arguments, str):
            try:
                parsed = json.loads(raw_arguments)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                payload["arguments"] = parsed
        return payload


def provider_safe_tool_call_id(tool_call_id: str) -> str:
    if len(tool_call_id) <= PROVIDER_TOOL_CALL_ID_MAX_LENGTH:
        return tool_call_id
    digest = hashlib.sha256(tool_call_id.encode("utf-8")).hexdigest()[:32]
    return f"tc_{digest}"


def make_provider_safe_server_tool_call_id(
    *,
    kind: str,
    stable_key: str,
) -> str:
    kind_part = _tool_call_id_segment(kind, max_length=22) or "tool"
    key_part = _tool_call_id_segment(stable_key, max_length=12) or "key"
    digest = hashlib.sha256(f"{kind}:{stable_key}".encode("utf-8")).hexdigest()[:16]
    return provider_safe_tool_call_id(f"srv_{kind_part}_{key_part}_{digest}")


def _tool_call_id_segment(value: str, *, max_length: int) -> str:
    compact = "".join(
        char.casefold() for char in value if char.isalnum() or char in {"_", "-"}
    ).strip("_-")
    return compact[:max_length]


class RuntimeToolFunction(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def arguments(self) -> str: ...


class RuntimeToolCall(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def function(self) -> RuntimeToolFunction: ...


def _metadata_mapping(metadata: object) -> Mapping[str, Any] | None:
    return cast(Mapping[str, Any], metadata) if isinstance(metadata, Mapping) else None


def _mapping_value(value: object) -> Mapping[str, Any] | None:
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else None


def _model_or_mapping_data(value: AIBuilderQuestionAnswerInput) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    return dict(value)


def _question_answer_payload(
    answer: StructuredQuestionAnswerMetadata | Mapping[str, Any],
) -> FlowPersistedJsonObject:
    if isinstance(answer, StructuredQuestionAnswerMetadata):
        return answer.model_dump(mode="json", exclude_none=True)
    return normalize_question_answer(answer)


def _object_sequence(value: object) -> Sequence[object] | None:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return None
    return cast(Sequence[object], value)


def _raw_tool_call_values_from_message(message: object) -> Sequence[object] | None:
    raw_tool_calls: object = None
    if isinstance(message, Mapping):
        message_map = cast(Mapping[str, object], message)
        raw_tool_calls = message_map.get("tool_calls")
    else:
        raw_tool_calls = getattr(message, "tool_calls", None)
    return _object_sequence(raw_tool_calls)


def _bounded_metadata_text(
    value: str,
    *,
    fallback: str,
    max_length: int = CLASSIFICATION_NOTE_MAX_LENGTH,
) -> str:
    stripped = value.strip()
    if not stripped:
        return fallback
    return stripped[:max_length]


def _warn_invalid_persisted_metadata(
    metadata_kind: str,
    error: ValidationError,
) -> None:
    logger.warning(
        "AI Builder ignored invalid persisted conversation metadata",
        extra={
            "metadata_kind": metadata_kind,
            "validation_errors": error.errors(include_input=False, include_url=False),
        },
    )


def requirements_confirmation_from_question_answer(
    value: AIBuilderQuestionAnswerInput | None,
) -> RequirementsConfirmationMetadata | None:
    if value is None:
        return None
    data = _model_or_mapping_data(value)
    if data.get("kind") not in (None, "requirements_confirmation"):
        return None
    if data.get("requirements_confirmed") is not True:
        return None
    data.setdefault("kind", "requirements_confirmation")
    try:
        return RequirementsConfirmationMetadata.model_validate(data)
    except ValidationError:
        return None


def structured_question_answer_from_input(
    value: AIBuilderQuestionAnswerInput | None,
) -> StructuredQuestionAnswerMetadata | None:
    if value is None:
        return None
    data = _model_or_mapping_data(value)
    if data.get("kind") not in (None, "structured_question_answer"):
        return None
    if data.get("requirements_confirmed") is True:
        return None
    data.setdefault("kind", "structured_question_answer")
    try:
        return StructuredQuestionAnswerMetadata.model_validate(data)
    except ValidationError:
        return None


def question_answer_from_metadata(
    metadata: object,
) -> StructuredQuestionAnswerMetadata | None:
    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return None
    answer = _mapping_value(metadata_map.get(QUESTION_ANSWER_METADATA_KEY))
    if answer is None:
        return None
    data = dict(answer)
    data.setdefault("kind", "structured_question_answer")
    if data.get("requirements_confirmed") is True:
        return None
    try:
        return StructuredQuestionAnswerMetadata.model_validate(data)
    except ValidationError as error:
        _warn_invalid_persisted_metadata(QUESTION_ANSWER_METADATA_KEY, error)
        return None


def question_response_from_metadata(
    metadata: object,
) -> QuestionResponseMetadata | None:
    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return None
    response = _mapping_value(metadata_map.get(QUESTION_RESPONSE_METADATA_KEY))
    if response is None:
        return None
    try:
        return QuestionResponseMetadata.model_validate(response)
    except ValidationError as error:
        _warn_invalid_persisted_metadata(QUESTION_RESPONSE_METADATA_KEY, error)
        return None


def question_response_to_metadata(question_id: str) -> FlowPersistedJsonObject:
    response = QuestionResponseMetadata(question_id=question_id)
    return {
        QUESTION_RESPONSE_METADATA_KEY: response.model_dump(mode="json"),
    }


def question_answer_to_metadata(
    value: AIBuilderQuestionAnswerInput,
) -> FlowPersistedJsonObject:
    answer = structured_question_answer_from_input(value)
    if answer is None:
        return {}
    payload = answer.model_dump(
        mode="json",
        exclude_none=True,
        exclude={"kind", "ui_language"},
    )
    return {QUESTION_ANSWER_METADATA_KEY: payload}


def requirements_confirmation_to_metadata(
    value: AIBuilderQuestionAnswerInput,
) -> FlowPersistedJsonObject:
    confirmation = requirements_confirmation_from_question_answer(value)
    if confirmation is None:
        return {}
    return confirmation.model_dump(
        mode="json",
        exclude_none=True,
        exclude={"kind", "ui_language"},
    )


def requirements_confirmation_from_metadata(
    metadata: object,
) -> RequirementsConfirmationMetadata | None:
    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return None
    if metadata_map.get(REQUIREMENTS_CONFIRMED_METADATA_KEY) is not True:
        return None
    try:
        return RequirementsConfirmationMetadata.model_validate(
            {
                "kind": "requirements_confirmation",
                "requirements_confirmed": True,
                "requirements_version": metadata_map.get(
                    REQUIREMENTS_VERSION_METADATA_KEY
                ),
            }
        )
    except ValidationError as error:
        _warn_invalid_persisted_metadata(REQUIREMENTS_CONFIRMED_METADATA_KEY, error)
        return None


def slot_classification_metadata_from_attempt(
    attempt: SlotClassificationAttempt,
    *,
    prompt_hash: str | None,
    classification_input: SlotClassificationInput,
    model: str,
    provider: str,
    retained_source_inventory: Sequence[SlotClassificationSourceMetadata] = (),
    named_result_evidence_snapshot: SlotClassificationNamedResultEvidenceMetadata
    | None = None,
) -> SlotClassificationMetadata:
    result = attempt.result or SlotClassificationResult()
    if (
        result.named_result_evidence is not None
        and named_result_evidence_snapshot is None
    ):
        raise ValueError(
            "Live named-result deltas require a materialized replay snapshot"
        )
    slot_payloads: list[dict[str, object]] = []
    seen_slot_names: set[str] = set()
    for slot in result.slots:
        payload = _slot_classification_slot_payload(slot)
        if payload is None:
            continue
        slot_name = payload.get("slot_name")
        if not isinstance(slot_name, str) or slot_name in seen_slot_names:
            continue
        slot_payloads.append(payload)
        seen_slot_names.add(slot_name)
    form_intake_payload = _slot_classification_form_intake_payload(result.form_intake)
    file_role_payloads = [
        _slot_classification_file_role_payload(file_role)
        for file_role in result.file_roles
    ]
    checkpoint_update_payloads = [
        _slot_classification_checkpoint_update_payload(update)
        for update in result.checkpoint_updates
    ]
    secondary_obligations = [
        obligation
        for obligation in result.secondary_obligations
        if obligation in RESULT_OBLIGATION_VALUES
    ][:_MAX_RESULT_OBLIGATIONS]
    retained_source_ids = {
        item.source_id
        for item in (
            named_result_evidence_snapshot.evidence
            if named_result_evidence_snapshot is not None
            else ()
        )
    }
    source_inventory_by_id: dict[str, dict[str, object]] = {
        source.source_id: source.model_dump(mode="python", exclude_none=True)
        for source in retained_source_inventory
        if source.source_id in retained_source_ids
    }
    source_inventory_by_id.update(
        {
            source.source_id: _slot_classification_source_payload(source)
            for source in classification_input.sources
        }
    )
    return SlotClassificationMetadata.model_validate(
        {
            "schema_version": SLOT_CLASSIFICATION_SCHEMA_VERSION,
            "outcome": attempt.outcome,
            "prompt_hash": prompt_hash,
            "model": model,
            "provider": provider,
            "source_inventory": list(source_inventory_by_id.values()),
            "slots": slot_payloads,
            "file_roles": file_role_payloads,
            "checkpoint_updates": checkpoint_update_payloads,
            "secondary_obligations": secondary_obligations,
            "form_intake": form_intake_payload,
            "named_result_evidence": (
                named_result_evidence_snapshot.model_dump(mode="python")
                if named_result_evidence_snapshot is not None
                else None
            ),
            "example_output_constraints": (
                result.example_output_constraints.model_dump(mode="python")
                if result.example_output_constraints is not None
                else None
            ),
            "schema_direction": _slot_classification_schema_direction_payload(
                result.schema_direction
            ),
            "assumptions": [
                _bounded_metadata_text(value, fallback="assumption")
                for value in result.assumptions
                if value.strip()
            ][:CLASSIFICATION_NOTES_MAX_ITEMS],
            "contradictions": [
                _bounded_metadata_text(value, fallback="contradiction")
                for value in result.contradictions
                if value.strip()
            ][:CLASSIFICATION_NOTES_MAX_ITEMS],
        }
    )


def _slot_classification_slot_payload(slot: ClassifiedSlot) -> dict[str, object] | None:
    if slot.slot_name not in LLM_RESOLVABLE_SLOT_NAMES:
        return None
    if slot.value != UNKNOWN_SLOT_VALUE and slot.value not in legal_slot_values(
        slot.slot_name
    ):
        return None
    return {
        "slot_name": slot.slot_name,
        "value": slot.value,
        "confidence": slot.confidence,
        "reason": _bounded_metadata_text(
            slot.reason,
            fallback="slot classification",
        ),
        "evidence": _slot_classification_evidence_payloads(slot.evidence),
        "evidence_level": slot.evidence_level,
    }


def _slot_classification_form_intake_payload(
    form_intake: ClassifiedFormIntake | None,
) -> dict[str, object] | None:
    if form_intake is None:
        return None
    if not form_intake.needs_form_fields and not form_intake.sectioned_form_intake:
        return None
    return {
        "needs_form_fields": form_intake.needs_form_fields
        or form_intake.sectioned_form_intake,
        "sectioned_form_intake": form_intake.sectioned_form_intake,
        "confidence": form_intake.confidence,
        "reason": _bounded_metadata_text(
            form_intake.reason,
            fallback="form intake classification",
        ),
        "evidence": _slot_classification_evidence_payloads(form_intake.evidence),
        "evidence_level": form_intake.evidence_level,
    }


def _slot_classification_schema_direction_payload(
    direction: ClassifiedSchemaDirection | None,
) -> dict[str, object] | None:
    if direction is None:
        return None
    return {
        "candidate_fingerprints": list(direction.candidate_fingerprints),
        "input_fingerprint": direction.input_fingerprint,
        "output_fingerprint": direction.output_fingerprint,
        "reference_only": direction.reference_only,
        "confidence": direction.confidence,
        "reason": _bounded_metadata_text(
            direction.reason,
            fallback="schema direction classification",
        ),
        "evidence": _slot_classification_evidence_payloads(direction.evidence),
    }


def _slot_classification_file_role_payload(
    file_role: ClassifiedFileRole,
) -> dict[str, object]:
    return {
        "file_id": str(file_role.file_id),
        "role": file_role.role,
        "confidence": file_role.confidence,
        "reason": _bounded_metadata_text(
            file_role.reason,
            fallback="file role classification",
        ),
        "evidence": _slot_classification_evidence_payloads(file_role.evidence),
        "evidence_level": file_role.evidence_level,
    }


def _slot_classification_checkpoint_update_payload(
    update: ClassifiedCheckpointUpdate,
) -> dict[str, object]:
    return {
        "operation": update.operation,
        "producer_kind": update.producer_kind,
        "mode": update.mode.value if update.mode is not None else None,
        "confidence": update.confidence,
        "reason": _bounded_metadata_text(
            update.reason,
            fallback="checkpoint update classification",
        ),
        "evidence": _slot_classification_evidence_payloads(update.evidence),
        "evidence_level": update.evidence_level,
    }


def _slot_classification_evidence_payloads(
    evidence: tuple[ClassifiedEvidence, ...],
) -> list[dict[str, str]]:
    return [
        {
            "source_id": item.source_id,
            "quote": _bounded_metadata_text(
                item.quote,
                fallback="classification evidence",
                max_length=CLASSIFICATION_EVIDENCE_MAX_LENGTH,
            ),
        }
        for item in evidence
        if item.source_id.strip() and item.quote.strip()
    ][:CLASSIFICATION_EVIDENCE_MAX_ITEMS]


def _slot_classification_source_payload(
    source: SlotClassificationSource,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "source_id": source.source_id,
        "kind": source.kind,
        "source_sha256": hashlib.sha256(source.text.encode("utf-8")).hexdigest(),
    }
    if source.message_id is not None:
        payload["message_id"] = source.message_id
    if source.question_id is not None:
        payload["question_id"] = source.question_id
    if source.selected_value is not None:
        payload["selected_value"] = source.selected_value[:500]
    if source.file_id is not None:
        payload["file_id"] = str(source.file_id)
    if source.coverage is not None:
        payload["coverage"] = source.coverage
    payload["truncated"] = source.truncated
    return payload


def slot_classification_to_metadata(
    classification: SlotClassificationMetadata,
) -> FlowPersistedJsonObject:
    return {
        SLOT_CLASSIFICATION_METADATA_KEY: classification.model_dump(
            mode="json",
            exclude_none=True,
        )
    }


def slot_classification_from_metadata(
    metadata: object,
) -> SlotClassificationMetadata | None:
    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return None
    classification = _mapping_value(metadata_map.get(SLOT_CLASSIFICATION_METADATA_KEY))
    if classification is None:
        return None
    try:
        return SlotClassificationMetadata.model_validate(classification)
    except ValidationError as error:
        _warn_invalid_persisted_metadata(SLOT_CLASSIFICATION_METADATA_KEY, error)
        return None


def metadata_with_slot_classification(
    metadata: FlowPersistedJsonObject | None,
    classification: SlotClassificationMetadata | None,
) -> FlowPersistedJsonObject | None:
    if classification is None:
        return metadata
    return {
        **(metadata or {}),
        **slot_classification_to_metadata(classification),
    }


def requirements_summary_to_metadata(
    payload: RequirementsSummaryPayload,
) -> FlowPersistedJsonObject:
    return {
        REQUIREMENTS_SUMMARY_METADATA_KEY: payload.model_dump(
            mode="json", exclude_none=True
        ),
        # A top-level index so conversation compaction can find the version
        # without parsing the whole disclosure. The payload owns the value.
        REQUIREMENTS_VERSION_METADATA_KEY: payload.requirements_version,
    }


def requirements_summary_from_metadata(
    metadata: object,
) -> RequirementsSummaryPayload | None:
    """The persisted disclosure, which carries its own version."""

    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return None
    summary = _mapping_value(metadata_map.get(REQUIREMENTS_SUMMARY_METADATA_KEY))
    if summary is None:
        return None
    try:
        return RequirementsSummaryPayload.model_validate(summary)
    except ValidationError as error:
        _warn_invalid_persisted_metadata(REQUIREMENTS_SUMMARY_METADATA_KEY, error)
        return None


def metadata_has_requirements_summary(metadata: object) -> bool:
    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return False
    return (
        _mapping_value(metadata_map.get(REQUIREMENTS_SUMMARY_METADATA_KEY)) is not None
    )


def requirements_version_from_metadata(metadata: object) -> str | None:
    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return None
    version = metadata_map.get(REQUIREMENTS_VERSION_METADATA_KEY)
    return version if isinstance(version, str) and version else None


def metadata_has_question_answer(metadata: object) -> bool:
    return question_answer_from_metadata(metadata) is not None


def question_answer_has_real_payload(
    answer: StructuredQuestionAnswerMetadata | Mapping[str, Any],
) -> bool:
    payload = _question_answer_payload(answer)
    question_id = payload.get("question_id")
    if not isinstance(question_id, str) or not question_id:
        return False
    input_fields = _object_sequence(payload.get("input_fields"))
    if input_fields:
        return True
    for key in (
        "selected_option_id",
        "selected_value",
        "answer",
        "custom_value",
    ):
        raw_value = payload.get(key)
        if _text_from_scalar(raw_value):
            return True
    for key in ("selected_option_ids", "selected_values"):
        raw_values = _object_sequence(payload.get(key))
        if raw_values is None:
            continue
        if any(_text_from_scalar(value) for value in raw_values):
            return True
    return False


def question_answer_values(
    answer: StructuredQuestionAnswerMetadata | Mapping[str, Any],
) -> set[str]:
    payload = _question_answer_payload(answer)
    values: set[str] = set()
    for raw_values in (
        payload.get("selected_option_ids"),
        payload.get("selected_values"),
    ):
        value_sequence = _object_sequence(raw_values)
        if value_sequence is None:
            continue
        for value in value_sequence:
            text = _text_from_scalar(value)
            if text is not None:
                values.add(text.casefold())
    for raw_key in ("selected_option_id", "selected_value", "answer", "custom_value"):
        raw_value = payload.get(raw_key)
        text = _text_from_scalar(raw_value)
        if text is not None:
            values.add(text.casefold())
    return values


def question_answer_question_id(
    answer: StructuredQuestionAnswerMetadata | Mapping[str, Any],
) -> str | None:
    payload = _question_answer_payload(answer)
    question_id = payload.get("question_id")
    return question_id if isinstance(question_id, str) and question_id else None


def question_interaction_id_from_metadata(metadata: object) -> str | None:
    answer = question_answer_from_metadata(metadata)
    if answer is not None:
        question_id = question_answer_question_id(answer)
        if question_id is not None:
            return question_id
    response = question_response_from_metadata(metadata)
    return response.question_id if response is not None else None


def ui_language_from_metadata(metadata: object) -> Literal["sv", "en"] | None:
    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return None
    value = metadata_map.get(UI_LANGUAGE_METADATA_KEY)
    return value if value in {"sv", "en"} else None


def ui_language_from_question_answer(
    value: AIBuilderQuestionAnswerInput | None,
) -> Literal["sv", "en"] | None:
    if value is None:
        return None
    data = _model_or_mapping_data(value)
    raw = data.get(UI_LANGUAGE_METADATA_KEY)
    return raw if raw in {"sv", "en"} else None


def assistant_question_id_from_metadata(metadata: object) -> str | None:
    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return None
    question_id = metadata_map.get(ASSISTANT_QUESTION_ID_METADATA_KEY)
    return question_id if isinstance(question_id, str) and question_id else None


def assistant_question_index_from_metadata(metadata: object) -> int | None:
    """The number this question was shown with, as persisted when it was asked.

    Stored beside the question id so the number survives every later reading of
    the conversation. `bool` is excluded because it is an `int` in Python and a
    persisted `true` is corrupt metadata, not the first question.
    """

    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return None
    question_index = metadata_map.get(ASSISTANT_QUESTION_INDEX_METADATA_KEY)
    if isinstance(question_index, bool) or not isinstance(question_index, int):
        return None
    return question_index if question_index >= 1 else None


def file_ids_from_metadata(metadata: object) -> list[UUID]:
    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return []
    raw_file_ids = metadata_map.get(FILE_IDS_METADATA_KEY)
    file_id_values = _object_sequence(raw_file_ids)
    if file_id_values is None:
        return []
    file_ids: list[UUID] = []
    for raw_file_id in file_id_values:
        try:
            file_ids.append(
                raw_file_id if isinstance(raw_file_id, UUID) else UUID(str(raw_file_id))
            )
        except (TypeError, ValueError):
            continue
    return file_ids


def edit_context_from_metadata(metadata: object) -> AIBuilderEditContext | None:
    metadata_map = _metadata_mapping(metadata)
    if metadata_map is None:
        return None
    raw_context = metadata_map.get(EDIT_CONTEXT_METADATA_KEY)
    if raw_context is None:
        return None
    try:
        return _EDIT_CONTEXT_ADAPTER.validate_python(raw_context)
    except ValidationError as error:
        _warn_invalid_persisted_metadata(EDIT_CONTEXT_METADATA_KEY, error)
        return None


class _ConversationMetadataMessage(Protocol):
    @property
    def role(self) -> str: ...

    @property
    def metadata(self) -> FlowPersistedJsonObject | None: ...


def latest_user_edit_context(
    conversation: Sequence[_ConversationMetadataMessage],
) -> AIBuilderEditContext | None:
    """Return scope only when it belongs to the latest user intent."""

    for message in reversed(conversation):
        if message.role == "user":
            return edit_context_from_metadata(message.metadata)
    return None


def metadata_for_user_message(
    *,
    question_answer: AIBuilderQuestionAnswerInput | None = None,
    ui_language: str | None = None,
    file_ids: Sequence[UUID] | None = None,
    edit_context: AIBuilderEditContext | ResolvedAIBuilderEditContext | None = None,
) -> FlowPersistedJsonObject | None:
    metadata: FlowPersistedJsonObject = {}
    if question_answer is not None:
        field_edit = named_content_fields_edit_from_input(question_answer)
        confirmation_metadata = requirements_confirmation_to_metadata(question_answer)
        metadata.update(
            named_content_fields_edit_to_metadata(field_edit)
            if field_edit is not None
            else confirmation_metadata or question_answer_to_metadata(question_answer)
        )
    if ui_language is not None:
        metadata[UI_LANGUAGE_METADATA_KEY] = ui_language
    if file_ids:
        metadata[FILE_IDS_METADATA_KEY] = [str(file_id) for file_id in file_ids]
    if edit_context is not None:
        metadata[EDIT_CONTEXT_METADATA_KEY] = edit_context.to_metadata()
    return metadata or None


def metadata_for_assistant_question(
    question_data: StructuredQuestionPayload,
) -> FlowPersistedJsonObject | None:
    """What the message must carry so the question can be recognised later.

    The number goes down with the id because it is part of what the user was
    shown. Recomputing it from message order would let compaction — which keeps
    the latest interaction of a re-asked question, not its first — hand the same
    question a different number afterwards.

    A question dispatched unnumbered — because an earlier question in the
    session predates numbers being persisted — is persisted without one, so the
    session keeps working and never renumbers: an unknown sequence stays
    unknown rather than being invented from message order.
    """

    question_id = canonical_question_id(question_data.question_id)
    if not question_id:
        return None
    metadata: FlowPersistedJsonObject = {
        ASSISTANT_QUESTION_ID_METADATA_KEY: question_id,
    }
    if question_data.question_index is not None:
        metadata[ASSISTANT_QUESTION_INDEX_METADATA_KEY] = question_data.question_index
    return metadata


def structured_question_payload_from_tool_arguments(
    arguments: object,
) -> FlowPersistedJsonObject | None:
    arguments_map = _mapping_value(arguments)
    if arguments_map is None:
        return None
    normalized = normalize_structured_question_payload(arguments_map)
    question_id = normalized.get("question_id")
    if not isinstance(question_id, str) or not question_id:
        return None
    return normalized


def make_persisted_assistant_tool_call(
    *,
    tool_call_id: str,
    tool_name: str,
    arguments: Mapping[str, Any] | None = None,
) -> PersistedAssistantToolCall:
    return PersistedAssistantToolCall(
        id=tool_call_id,
        name=tool_name,
        arguments=dict(arguments or {}),
    )


def persisted_assistant_tool_call_from_raw(
    value: object,
) -> PersistedAssistantToolCall | None:
    value_map = _mapping_value(value)
    if value_map is None:
        return None
    try:
        return PersistedAssistantToolCall.model_validate(value_map)
    except ValidationError as error:
        _warn_invalid_persisted_metadata("tool_call", error)
        return None


def tool_calls_from_message(message: object) -> tuple[PersistedAssistantToolCall, ...]:
    tool_call_values = _raw_tool_call_values_from_message(message)
    if tool_call_values is None:
        return tuple()
    parsed: list[PersistedAssistantToolCall] = []
    for raw_tool_call in tool_call_values:
        tool_call = persisted_assistant_tool_call_from_raw(raw_tool_call)
        if tool_call is not None:
            parsed.append(tool_call)
    return tuple(parsed)


def loose_tool_call_name(value: object) -> str | None:
    value_map = _mapping_value(value)
    if value_map is not None:
        name = value_map.get("name")
        return name if isinstance(name, str) and name else None
    function = getattr(value, "function", None)
    name = getattr(function, "name", None)
    return name if isinstance(name, str) and name else None


def loose_tool_call_names_from_message(message: object) -> tuple[str, ...]:
    """Loose by design: telemetry preserves legacy counts for invalid tool rows."""
    tool_call_values = _raw_tool_call_values_from_message(message)
    if tool_call_values is None:
        return tuple()
    return tuple(
        name
        for raw_tool_call in tool_call_values
        if (name := loose_tool_call_name(raw_tool_call)) is not None
    )


def _text_from_scalar(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip() if not isinstance(value, str) else value.strip()
    return text or None


def tool_call_ids(tool_calls: Sequence[PersistedAssistantToolCall]) -> set[str]:
    return {tool_call.id for tool_call in tool_calls if tool_call.id}
