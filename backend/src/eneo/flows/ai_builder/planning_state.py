"""Typed derived PlanningState cache persisted in session JSONB.

PlanningState is rebuilt each turn from the compacted persisted conversation;
it does not replace turn-by-turn reconstruction or become the sole authority
for learned state. Slots, signals, and classifier semantics are derived from
that conversation, whose compaction retains the latest effective typed
classifier classes needed by rebuild. Carry-forward is limited to facts that
cannot be reconstructed safely: `architecture_commit`, an accepted mapped-file
limit, current attachment roles, and still-attached output/example evidence.
Input schema direction is rebuilt from retained conversation evidence instead
of being copied blindly. Session and plan lifecycle status remain on their own
tables.

Business logic consumes the typed Pydantic model here. Partial JSONB operators
(`jsonb_set`, `||`, path updates) are forbidden. Every mutation follows load →
validate → mutate-in-python → serialize-full-snapshot, so the JSONB column
never drifts out of Pydantic's typed world.

Three first-class version stamps travel on every persisted state:
`fcm_version` (the Flow Capability Manifest in force), a
`planner_contract_version` (the planner I/O schema in force), and
`builder_schema_version` (this Pydantic shape itself). The Pydantic model
preserves those stamps verbatim; load/rebuild policy lives at the repository
or planner boundary, not inside the model. `pattern_registry_version` and
`question_catalog_version` are module-internal hygiene counters owned by
their respective modules and are NOT stamped here.

Mutability vs revalidation: models are mutable because full-snapshot
discipline mutates in Python before re-serializing. Direct attribute
reassignment is revalidated (`validate_assignment=True`). Container
mutations (list/dict edits that bypass the validator) can still
introduce drift, so the save path must call `validated_snapshot()`
before writing.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Annotated, Literal, assert_never
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eneo.files.file_models import FileType
from eneo.flows.ai_builder.ai_builder_proposal_intent import FlowInputFieldIntent
from eneo.flows.enums import (
    FlowAuthoringInputType,
    FlowAuthoringOutputMode,
    FlowOutputType,
)
from eneo.flows.flow_capability_manifest import FCM_VERSION
from eneo.json_types import JsonObject

PLANNER_CONTRACT_VERSION: int = 1
BUILDER_SCHEMA_VERSION: int = 12
# One state can retain two independently assigned 128-KiB schemas. The persisted
# envelope leaves the other half for provenance, file roles, slots, and future
# state growth without coupling the per-schema ceiling to the state ceiling.
PLANNING_STATE_PAYLOAD_CAP_BYTES: int = 512 * 1024
ARCHITECTURE_HASH_HEX_LENGTH: int = 64

_ARCHITECTURE_HASH_RE = re.compile(rf"^[0-9a-f]{{{ARCHITECTURE_HASH_HEX_LENGTH}}}$")

SignalConfidence = Literal["high", "medium", "low"]

SignalSource = Literal[
    "structured_answer",
    "freeform_text",
    "flow_default",
    "policy_default",
    "heuristic",
    "model",
]

SlotSource = Literal[
    "structured_answer",
    "requirements_summary",
    "flow_default",
    "attachment_structure",
    "policy_default",
    "heuristic",
    "model",
]

SlotConfidence = Literal["high", "medium", "low"]
SlotEvidenceLevel = Literal["explicit", "inferred"]
MappedFileLimitProvenance = Literal["policy_default", "authored"]
MappedFileLimitDiagnostic = Literal[
    "confirmation_required",
    "policy_unset",
    "not_an_integer",
    "not_positive",
    "exceeds_policy",
]

FileRole = Literal[
    "runtime_input_sample",
    "template",
    "reference_material",
    "example_output",
    "context_only",
]

FileRoleSource = Literal["structured_answer", "heuristic", "model"]
AttachmentCoverage = Literal[
    "fully_seen",
    "excerpt_truncated",
    "inventory_only",
]
SchemaEvidenceSource = Literal[
    "declared_schema",
    "template_placeholders",
    "inferred_example",
]
SchemaEvidenceStrength = Literal["explicit", "inferred"]
ExampleOutputStyleCategory = Literal[
    "tone",
    "detail_level",
    "organization",
    "formatting",
    "audience",
]
ExampleOutputSchemaInferenceStatus = Literal["inferred", "not_inferred"]
ExampleOutputSchemaInferenceReason = Literal[
    "higher_priority_schema",
    "no_json_object",
    "incomplete_content",
    "invalid_json",
    "top_level_not_object",
    "raw_bytes",
    "field_count",
    "depth",
    "conflicting_shapes",
]

ATTACHMENT_JSON_SCHEMA_EVIDENCE_SUFFIX = ":json_schema_attachment"
TEMPLATE_PLACEHOLDER_EVIDENCE_PREFIX = "content:template_placeholder:"
TEMPLATE_PLACEHOLDER_SOURCE_EVIDENCE_SUFFIX = ":template_placeholder_source"

AggregationIntent = Literal["linear", "aggregate", "compare"]
ReportDisposition = Literal["per_source_sections", "synthesized_overview", "both"]


class PlanningStatePayloadTooLargeError(ValueError):
    """The serialized planning state exceeds the persisted payload cap."""

    def __init__(self, *, byte_size: int, cap_bytes: int) -> None:
        super().__init__(
            f"Planning state payload is {byte_size} bytes, over the "
            f"{cap_bytes}-byte cap."
        )
        self.byte_size = byte_size
        self.cap_bytes = cap_bytes


def enforce_planning_state_payload_cap(payload: JsonObject) -> JsonObject:
    """Refuse to persist a planning state larger than the cap.

    Checked on the serialized form, since that is what the column stores. The
    turn is not resumable from an oversized state: persisting it would either
    be rejected by the database or produce a session that cannot be loaded
    again, so failing here keeps the last good state intact.
    """
    byte_size = len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    if byte_size > PLANNING_STATE_PAYLOAD_CAP_BYTES:
        raise PlanningStatePayloadTooLargeError(
            byte_size=byte_size,
            cap_bytes=PLANNING_STATE_PAYLOAD_CAP_BYTES,
        )
    return payload


class _PlanningModel(BaseModel):
    """Strict base for every persisted PlanningState model.

    `extra="forbid"` fails on unknown fields so JSONB drift is caught
    at load time. `validate_assignment=True` re-runs validators on
    direct attribute reassignment — container-level mutations (list
    appends, dict sets) are still the caller's responsibility; the
    save path must revalidate via `PlanningState.validated_snapshot`.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class PlanningSignal(_PlanningModel):
    question_id: str
    value: str
    confidence: SignalConfidence
    source: SignalSource
    provenance: list[str] = Field(default_factory=list[str])


class ResolvedSlot(_PlanningModel):
    name: str
    value: str
    source: SlotSource
    evidence: list[str] = Field(default_factory=list[str])
    confidence: SlotConfidence
    evidence_level: SlotEvidenceLevel | None = None

    @model_validator(mode="after")
    def validate_model_provenance(self) -> ResolvedSlot:
        if self.source != "model":
            if self.evidence_level is not None:
                raise ValueError(
                    "evidence_level is only valid for model-resolved slots"
                )
            return self

        if self.evidence_level is None:
            raise ValueError("model-resolved slots require an evidence_level")
        if self.confidence == "low":
            raise ValueError("low-confidence model evidence cannot resolve a slot")
        if not any(item.startswith("quote:") for item in self.evidence):
            raise ValueError("model-resolved slots require cited evidence")
        return self

    @property
    def is_commit_grade(self) -> bool:
        """Whether this slot can drive irreversible planner decisions."""

        match self.source:
            case (
                "structured_answer"
                | "requirements_summary"
                | "flow_default"
                | "attachment_structure"
            ):
                return True
            case "policy_default" | "heuristic":
                return False
            case "model":
                has_cited_evidence = any(
                    item.startswith("quote:") for item in self.evidence
                )
                return has_cited_evidence and (
                    self.confidence == "high"
                    or (
                        self.confidence == "medium"
                        and self.evidence_level == "explicit"
                    )
                )
        return assert_never(self.source)


class StepTriple(_PlanningModel):
    input_type: FlowAuthoringInputType
    output_type: FlowOutputType
    output_mode: FlowAuthoringOutputMode


class ArchitectureCommitDraft(_PlanningModel):
    """Semantic architecture commitment.

    The model may choose the high-level `commit_architecture` action,
    but the server should derive this draft whenever possible. The
    tuple chain is a capability envelope from primary input to terminal
    output; it is not an exact implementation-step count. Deterministic
    mechanics (`architecture_hash`, `committed_at`) are server-owned
    and added only when the draft is finalized into a persisted
    `ArchitectureCommit`.
    """

    tuples_chain: list[StepTriple]
    chosen_patterns: list[str]
    required_capabilities: list[str] = Field(default_factory=list[str])
    aggregation_intent: AggregationIntent = "linear"
    report_disposition: ReportDisposition | None = None

    @model_validator(mode="after")
    def _validate_chosen_patterns(self) -> "ArchitectureCommitDraft":
        from eneo.flows.ai_builder.pattern_registry import (
            PATTERN_REGISTRY,
            compiled_chain_pattern_ids,
        )

        unknown_pattern_ids = sorted(
            pattern_id
            for pattern_id in self.chosen_patterns
            if pattern_id not in PATTERN_REGISTRY
        )
        if unknown_pattern_ids:
            raise ValueError(
                "architecture_commit.chosen_patterns contains unknown pattern ids: "
                f"{unknown_pattern_ids}"
            )

        compiled_pattern_ids = compiled_chain_pattern_ids(self.chosen_patterns)
        if len(compiled_pattern_ids) > 1:
            raise ValueError(
                "architecture_commit.chosen_patterns may include at most one "
                "compiler-backed chain pattern; got "
                f"{sorted(compiled_pattern_ids)}"
            )
        return self


class ArchitectureCommit(ArchitectureCommitDraft):
    """Persisted architecture commitment with server-owned metadata."""

    committed_at: datetime
    architecture_hash: str

    @field_validator("architecture_hash")
    @classmethod
    def _hash_is_64_hex(cls, value: str) -> str:
        if not _ARCHITECTURE_HASH_RE.fullmatch(value):
            raise ValueError(
                f"architecture_hash must be {ARCHITECTURE_HASH_HEX_LENGTH} "
                "lowercase hex characters (no prefix)"
            )
        return value


class FileRoleEvidence(_PlanningModel):
    file_id: UUID
    filename: str
    file_type: FileType
    mimetype: str | None = None
    has_readable_text: bool
    coverage: AttachmentCoverage
    role: FileRole
    source: FileRoleSource
    confidence: SignalConfidence
    evidence: list[str] = Field(default_factory=list[str])
    candidate_roles: list[FileRole] = Field(default_factory=list[FileRole])
    template_placeholders: list[str] | None = None

    @model_validator(mode="after")
    def _validate_role_evidence(self) -> FileRoleEvidence:
        if not self.has_readable_text and self.coverage != "inventory_only":
            raise ValueError(
                "non-readable file role evidence must have inventory_only coverage"
            )
        if self.template_placeholders is not None:
            if len(self.template_placeholders) != len(set(self.template_placeholders)):
                raise ValueError("template_placeholders must be unique")
            if any(not item.strip() for item in self.template_placeholders):
                raise ValueError("template_placeholders must be non-empty")
        if not self.candidate_roles:
            return self
        seen: set[FileRole] = set()
        for candidate in self.candidate_roles:
            if candidate in seen:
                raise ValueError("candidate_roles must be unique")
            seen.add(candidate)
        if self.role not in seen:
            raise ValueError("candidate_roles must include role")
        return self


class SchemaEvidence(_PlanningModel):
    json_schema: JsonObject
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: SchemaEvidenceSource
    strength: SchemaEvidenceStrength
    source_file_ids: list[UUID] = Field(max_length=100)
    confidence: SignalConfidence
    evidence: list[str] = Field(default_factory=list[str], max_length=200)
    total_count: int | None = Field(default=None, ge=0)
    truncated: bool = False

    @model_validator(mode="after")
    def _validate_truncation_metadata(self) -> SchemaEvidence:
        from eneo.flows.domain.canonical_json_hash import canonical_json_hash

        expected_fingerprint = canonical_json_hash(self.json_schema)
        if self.fingerprint != expected_fingerprint:
            raise ValueError("schema fingerprint must match json_schema")
        expected_strength: SchemaEvidenceStrength = (
            "explicit" if self.source == "declared_schema" else "inferred"
        )
        if self.strength != expected_strength:
            raise ValueError("schema strength must match its source")
        if self.source_file_ids != sorted(set(self.source_file_ids), key=str):
            raise ValueError("schema source_file_ids must be unique and sorted")
        if self.source != "declared_schema" and not self.source_file_ids:
            raise ValueError("inferred output schema requires source_file_ids")
        if self.source != "template_placeholders":
            if self.total_count is not None or self.truncated:
                raise ValueError(
                    "placeholder count metadata requires template_placeholders source"
                )
            return self
        if self.truncated and self.total_count is None:
            raise ValueError("truncated placeholder evidence requires total_count")
        properties = self.json_schema.get("properties")
        visible_count = len(properties) if isinstance(properties, dict) else 0
        if self.total_count is not None and self.total_count < visible_count:
            raise ValueError("total_count cannot be smaller than visible schema fields")
        if self.truncated and self.total_count == visible_count:
            raise ValueError("truncated evidence must omit at least one placeholder")
        if self.truncated and self.confidence == "high":
            raise ValueError(
                "truncated placeholder evidence cannot have high confidence"
            )
        return self


class SchemaAssignmentEvidence(_PlanningModel):
    """Direction-specific evidence that references one canonical schema shape."""

    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: SchemaEvidenceSource
    strength: SchemaEvidenceStrength
    source_file_ids: list[UUID] = Field(max_length=100)
    confidence: SignalConfidence
    evidence: list[str] = Field(default_factory=list[str], max_length=200)
    total_count: int | None = Field(default=None, ge=0)
    truncated: bool = False

    @classmethod
    def from_evidence(cls, evidence: SchemaEvidence) -> SchemaAssignmentEvidence:
        return cls.model_validate(
            evidence.model_dump(exclude={"json_schema"}, mode="python")
        )

    def materialize(self, json_schema: JsonObject) -> SchemaEvidence:
        return SchemaEvidence.model_validate(
            {
                "json_schema": json_schema,
                **self.model_dump(mode="python"),
            }
        )


class SchemaResolution(_PlanningModel):
    """Bounded schema shapes with independent input and output assignments.

    A shape is stored once even when both boundaries use it. Assignment evidence
    remains separate because input and output decisions can have different
    provenance and confidence.
    """

    schemas: dict[str, JsonObject] = Field(
        default_factory=dict[str, JsonObject],
        max_length=2,
    )
    input: SchemaAssignmentEvidence | None = None
    output: SchemaAssignmentEvidence | None = None

    @model_validator(mode="after")
    def _validate_schema_references(self) -> SchemaResolution:
        from eneo.flows.domain.canonical_json_hash import canonical_json_hash

        if list(self.schemas) != sorted(self.schemas):
            raise ValueError("schema resolution shapes must be fingerprint-sorted")
        for fingerprint, schema in self.schemas.items():
            if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                raise ValueError("schema resolution keys must be fingerprints")
            if canonical_json_hash(schema) != fingerprint:
                raise ValueError("schema resolution fingerprint must match shape")

        assignments = tuple(
            assignment
            for assignment in (self.input, self.output)
            if assignment is not None
        )
        referenced = {assignment.fingerprint for assignment in assignments}
        if referenced != set(self.schemas):
            raise ValueError(
                "schema resolution must store exactly the assigned schema shapes"
            )
        if self.input is not None and self.input.source != "declared_schema":
            raise ValueError(
                "input schema evidence cannot use an output-only inferred source"
            )
        return self

    @classmethod
    def from_evidence(
        cls,
        *,
        input_evidence: SchemaEvidence | None,
        output_evidence: SchemaEvidence | None,
    ) -> SchemaResolution:
        evidence_items = tuple(
            evidence
            for evidence in (input_evidence, output_evidence)
            if evidence is not None
        )
        shapes: dict[str, JsonObject] = {}
        for evidence in evidence_items:
            existing = shapes.get(evidence.fingerprint)
            if existing is not None and existing != evidence.json_schema:
                raise ValueError("one schema fingerprint cannot identify two shapes")
            shapes[evidence.fingerprint] = evidence.json_schema
        return cls(
            schemas={
                fingerprint: shapes[fingerprint] for fingerprint in sorted(shapes)
            },
            input=(
                SchemaAssignmentEvidence.from_evidence(input_evidence)
                if input_evidence is not None
                else None
            ),
            output=(
                SchemaAssignmentEvidence.from_evidence(output_evidence)
                if output_evidence is not None
                else None
            ),
        )

    def input_evidence(self) -> SchemaEvidence | None:
        return (
            self.input.materialize(self.schemas[self.input.fingerprint])
            if self.input is not None
            else None
        )

    def output_evidence(self) -> SchemaEvidence | None:
        return (
            self.output.materialize(self.schemas[self.output.fingerprint])
            if self.output is not None
            else None
        )


ExampleOutputHeading = Annotated[str, Field(min_length=1, max_length=160)]


class ExampleOutputSourceCoverage(_PlanningModel):
    file_id: UUID
    coverage: AttachmentCoverage


class ExampleOutputCitation(_PlanningModel):
    source_id: str = Field(min_length=1, max_length=256)
    file_id: UUID | None = None
    quote: str = Field(min_length=1, max_length=240)


class ExampleOutputStyleConstraint(_PlanningModel):
    category: ExampleOutputStyleCategory
    description: str = Field(min_length=1, max_length=240)


class ExampleOutputConstraintEvidence(_PlanningModel):
    source_file_ids: list[UUID] = Field(min_length=1, max_length=100)
    source_coverage: list[ExampleOutputSourceCoverage] = Field(
        min_length=1,
        max_length=100,
    )
    headings: list[ExampleOutputHeading] = Field(
        default_factory=list[ExampleOutputHeading],
        max_length=20,
    )
    style_constraints: list[ExampleOutputStyleConstraint] = Field(
        default_factory=list[ExampleOutputStyleConstraint],
        max_length=20,
    )
    confidence: SignalConfidence
    citations: list[ExampleOutputCitation] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def _validate_example_output_evidence(self) -> ExampleOutputConstraintEvidence:
        if self.source_file_ids != sorted(set(self.source_file_ids), key=str):
            raise ValueError("example output source_file_ids must be unique and sorted")
        coverage_ids = [item.file_id for item in self.source_coverage]
        if coverage_ids != sorted(set(coverage_ids), key=str):
            raise ValueError("example output coverage must be unique and sorted")
        if coverage_ids != self.source_file_ids:
            raise ValueError("example output coverage must describe every source file")
        if not self.headings and not self.style_constraints:
            raise ValueError("example output evidence requires structure or style")
        if len({heading.casefold() for heading in self.headings}) != len(self.headings):
            raise ValueError("example output headings must be unique")
        style_keys = [
            (item.category, item.description.casefold())
            for item in self.style_constraints
        ]
        if len(style_keys) != len(set(style_keys)):
            raise ValueError("example output style constraints must be unique")
        cited_file_ids = {
            citation.file_id
            for citation in self.citations
            if citation.file_id is not None
        }
        if not cited_file_ids <= set(self.source_file_ids):
            raise ValueError("example output citations must cite selected source files")
        if self.confidence == "high" and all(
            citation.file_id is not None for citation in self.citations
        ):
            raise ValueError(
                "attachment-only example output evidence cannot have high confidence"
            )
        return self


class ExampleOutputSchemaInferenceOutcome(_PlanningModel):
    status: ExampleOutputSchemaInferenceStatus
    reason: ExampleOutputSchemaInferenceReason | None = None
    source_file_ids: list[UUID] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _validate_inference_outcome(self) -> ExampleOutputSchemaInferenceOutcome:
        if self.source_file_ids != sorted(set(self.source_file_ids), key=str):
            raise ValueError(
                "example output schema inference source_file_ids must be unique "
                "and sorted"
            )
        if (self.status == "inferred") != (self.reason is None):
            raise ValueError(
                "inferred example output schema requires no refusal reason; "
                "not_inferred requires one"
            )
        return self


class MappedFileLimit(_PlanningModel):
    """Tenant proposal and explicitly accepted mapped file ceiling."""

    proposed_value: int | None = Field(default=None, ge=1)
    accepted_value: int | None = Field(default=None, ge=1)
    provenance: MappedFileLimitProvenance | None = None
    diagnostic: MappedFileLimitDiagnostic | None = None

    @model_validator(mode="after")
    def _accepted_value_is_coherent(self) -> "MappedFileLimit":
        if (self.accepted_value is None) != (self.provenance is None):
            raise ValueError("mapped file limit acceptance requires provenance")
        if (
            self.accepted_value is not None
            and self.proposed_value is not None
            and self.accepted_value > self.proposed_value
        ):
            raise ValueError("accepted mapped file limit cannot exceed policy")
        return self


class PlanningState(_PlanningModel):
    fcm_version: int
    planner_contract_version: int
    builder_schema_version: int
    signals: list[PlanningSignal] = Field(default_factory=list[PlanningSignal])
    resolved_slots: dict[str, ResolvedSlot] = Field(
        default_factory=dict[str, ResolvedSlot]
    )
    file_roles: list[FileRoleEvidence] = Field(default_factory=list[FileRoleEvidence])
    schema_resolution: SchemaResolution = Field(default_factory=SchemaResolution)
    example_output_constraints: ExampleOutputConstraintEvidence | None = None
    example_output_schema_inference: ExampleOutputSchemaInferenceOutcome | None = None
    input_fields: list[FlowInputFieldIntent] = Field(
        default_factory=list[FlowInputFieldIntent]
    )
    architecture_commit: ArchitectureCommit | None = None
    mapped_file_limit: MappedFileLimit = Field(default_factory=MappedFileLimit)

    @property
    def input_schema_evidence(self) -> SchemaEvidence | None:
        return self.schema_resolution.input_evidence()

    @input_schema_evidence.setter
    def input_schema_evidence(self, evidence: SchemaEvidence | None) -> None:
        self.replace_schema_resolution(
            input_evidence=evidence,
            output_evidence=self.output_schema_evidence,
            example_inference=self.example_output_schema_inference,
        )

    @property
    def output_schema_evidence(self) -> SchemaEvidence | None:
        return self.schema_resolution.output_evidence()

    @output_schema_evidence.setter
    def output_schema_evidence(self, evidence: SchemaEvidence | None) -> None:
        self.replace_schema_resolution(
            input_evidence=self.input_schema_evidence,
            output_evidence=evidence,
            example_inference=self.example_output_schema_inference,
        )

    @model_validator(mode="after")
    def _file_role_ids_are_unique(self) -> PlanningState:
        seen: set[UUID] = set()
        for item in self.file_roles:
            if item.file_id in seen:
                raise ValueError("file_roles must contain unique file_id values")
            seen.add(item.file_id)
        if self.example_output_constraints is not None:
            source_ids = set(self.example_output_constraints.source_file_ids)
            if not source_ids <= seen:
                raise ValueError(
                    "example output constraints must cite current file role evidence"
                )
            roles_by_file_id = {item.file_id: item.role for item in self.file_roles}
            if any(
                roles_by_file_id[file_id] != "example_output" for file_id in source_ids
            ):
                raise ValueError(
                    "example output constraints require example_output file roles"
                )
            coverage_by_file_id = {
                item.file_id: item.coverage for item in self.file_roles
            }
            if any(
                coverage.coverage != coverage_by_file_id[coverage.file_id]
                for coverage in self.example_output_constraints.source_coverage
            ):
                raise ValueError(
                    "example output constraint coverage must match file role evidence"
                )
        inference = self.example_output_schema_inference
        if inference is not None:
            constraints = self.example_output_constraints
            if constraints is None:
                raise ValueError(
                    "example output schema inference requires example output "
                    "constraints"
                )
            if not set(inference.source_file_ids) <= set(constraints.source_file_ids):
                raise ValueError(
                    "example output schema inference must cite selected example "
                    "output files"
                )
        inferred_schema = (
            self.output_schema_evidence
            if self.output_schema_evidence is not None
            and self.output_schema_evidence.source == "inferred_example"
            else None
        )
        if inferred_schema is not None:
            if inference is None or inference.status != "inferred":
                raise ValueError(
                    "inferred output schema evidence requires an inferred outcome"
                )
            if inferred_schema.source_file_ids != inference.source_file_ids:
                raise ValueError(
                    "inferred output schema evidence and outcome must cite the "
                    "same files"
                )
        elif inference is not None and inference.status == "inferred":
            raise ValueError(
                "inferred example output outcome requires output schema evidence"
            )
        return self

    def has_template_file_role(self) -> bool:
        return any(item.role == "template" for item in self.file_roles)

    def replace_schema_resolution(
        self,
        *,
        input_evidence: SchemaEvidence | None,
        output_evidence: SchemaEvidence | None,
        example_inference: ExampleOutputSchemaInferenceOutcome | None,
    ) -> None:
        """Atomically replace the fields that form one schema resolution."""

        self.replace_attachment_interpretation(
            file_roles=self.file_roles,
            example_constraints=self.example_output_constraints,
            input_evidence=input_evidence,
            output_evidence=output_evidence,
            example_inference=example_inference,
        )

    def replace_attachment_interpretation(
        self,
        *,
        file_roles: list[FileRoleEvidence],
        example_constraints: ExampleOutputConstraintEvidence | None,
        input_evidence: SchemaEvidence | None,
        output_evidence: SchemaEvidence | None,
        example_inference: ExampleOutputSchemaInferenceOutcome | None,
    ) -> None:
        """Replace the coupled attachment interpretation as one valid snapshot.

        Assignment validation cannot safely observe these fields one at a time.
        Validate the complete candidate first, then copy only validated values onto
        this mutable full-snapshot model.
        """

        candidate = type(self).model_validate(
            {
                **dict(self),
                "file_roles": file_roles,
                "example_output_constraints": example_constraints,
                "schema_resolution": SchemaResolution.from_evidence(
                    input_evidence=input_evidence,
                    output_evidence=output_evidence,
                ),
                "example_output_schema_inference": example_inference,
            }
        )
        object.__setattr__(self, "file_roles", candidate.file_roles)
        object.__setattr__(
            self,
            "example_output_constraints",
            candidate.example_output_constraints,
        )
        object.__setattr__(self, "schema_resolution", candidate.schema_resolution)
        object.__setattr__(
            self,
            "example_output_schema_inference",
            candidate.example_output_schema_inference,
        )

    @classmethod
    def empty(cls) -> PlanningState:
        """Fresh state for a new session — stamped at the current versions."""
        return cls(
            fcm_version=FCM_VERSION,
            planner_contract_version=PLANNER_CONTRACT_VERSION,
            builder_schema_version=BUILDER_SCHEMA_VERSION,
        )

    def validated_snapshot(self) -> PlanningState:
        """Return a freshly revalidated copy suitable for the save path.

        Container-level mutations (list appends, dict inserts) bypass
        Pydantic's field validators. The save path calls this before
        writing so drift fails loudly instead of persisting.
        """
        # Use Python objects, not JSON serialization, so drift inside nested
        # model containers fails during re-validation instead of serializing.
        return type(self).model_validate(dict(self))
