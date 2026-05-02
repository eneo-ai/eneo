from __future__ import annotations

from datetime import datetime
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict

EVIDENCE_EXPORT_SCHEMA_VERSION: Literal["flow-evidence-export.v3"] = (
    "flow-evidence-export.v3"
)

EvidenceExportContentHashInput: TypeAlias = Literal["raw", "redacted"]
EvidenceExportDetailMode: TypeAlias = Literal["raw", "redacted"]
EvidenceProvenancePersistedVersionStatus: TypeAlias = Literal[
    "not_tracked", "tracked", "corrupt", "retention_purged"
]
EvidenceRetentionTrackingState: TypeAlias = Literal["not_tracked", "tracked"]
EvidenceArtifactAvailabilityTrackingState: TypeAlias = Literal["payload_derived"]


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


class EvidenceArtifactAvailabilitySummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    tracking_state: EvidenceArtifactAvailabilityTrackingState
    payload_artifact_count: int
    note: str


class EvidenceExportManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flow-evidence-export.v3"]
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
