from __future__ import annotations

from datetime import datetime
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict

from intric.flows.enums import FlowRunReviewCheckpointState
from intric.flows.flow_run_step_result_file import (
    FlowRunStepResultFileAvailability,
    FlowRunStepResultFileSource,
)

EVIDENCE_EXPORT_SCHEMA_VERSION: Literal["flow-evidence-export.v5"] = (
    "flow-evidence-export.v5"
)

EvidenceExportContentHashInput: TypeAlias = Literal["raw", "redacted"]
EvidenceExportDetailMode: TypeAlias = Literal["raw", "redacted"]
EvidenceProvenancePersistedVersionStatus: TypeAlias = Literal[
    "not_tracked", "tracked", "corrupt", "retention_purged"
]
EvidenceRetentionTrackingState: TypeAlias = Literal["not_tracked", "tracked"]
EvidenceArtifactAvailabilityTrackingState: TypeAlias = Literal["tracked"]


class EvidenceExportContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail_mode: EvidenceExportDetailMode
    export_reason: str
    exported_by_user_id: str | None = None


class EvidenceRetentionStateSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    tracking_state: EvidenceRetentionTrackingState
    tombstone_count: int
    retention_purged_count: int
    artifact_content_purged_count: int
    redacted_for_deletion_count: int
    note: str


class EvidenceArtifactManifestItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flow_run_id: str
    flow_id: str
    tenant_id: str
    file_id: str
    step_id: str
    step_result_id: str
    step_order: int
    attempt_no: int
    ordinal: int
    source: FlowRunStepResultFileSource
    name: str
    checksum: str
    size: int
    mimetype: str | None
    file_type: str
    availability: FlowRunStepResultFileAvailability


class EvidenceArtifactAvailabilitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tracking_state: EvidenceArtifactAvailabilityTrackingState
    artifact_count: int
    available_count: int
    content_purged_count: int
    total_size_bytes: int
    artifacts: list[EvidenceArtifactManifestItem]
    note: str


class EvidenceReviewCheckpointSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
    by_state: dict[FlowRunReviewCheckpointState, int]
    any_edited: bool
    any_resumed: bool
    active_checkpoint_id: str | None = None
    active_checkpoint_conflict: bool


class EvidenceExportManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flow-evidence-export.v5"]
    provenance_schema_version_min: str
    provenance_schema_version_current: str
    provenance_persisted_version_status: EvidenceProvenancePersistedVersionStatus
    content_hash: str
    content_hash_input: EvidenceExportContentHashInput
    exported_at: datetime
    tenant_id: str
    run_id: str
    trace_id: str
    flow_id: str
    flow_version: int
    exported_by_user_id: str | None
    export_reason: str
    detail_mode: EvidenceExportDetailMode
    redaction_applied: bool
    masked_fields_count: int
    redaction_policy_version: str
    retention_state_summary: EvidenceRetentionStateSummary
    artifact_availability_summary: EvidenceArtifactAvailabilitySummary
    review_checkpoint_summary: EvidenceReviewCheckpointSummary
