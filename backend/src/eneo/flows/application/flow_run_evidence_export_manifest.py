from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.authentication.principal_types import PrincipalType
from eneo.flows.enums import FlowRunReviewCheckpointState
from eneo.flows.flow_run_step_result_file import (
    FlowRunStepResultFileAvailability,
    FlowRunStepResultFileSource,
)
from eneo.flows.principal import FlowPrincipal

EVIDENCE_EXPORT_SCHEMA_VERSION: Literal["flow-evidence-export.v11"] = (
    "flow-evidence-export.v11"
)

EvidenceExportContentHashInput: TypeAlias = Literal["raw", "redacted"]
EvidenceExportDetailMode: TypeAlias = Literal["raw", "redacted"]
EvidenceProvenancePersistedVersionStatus: TypeAlias = Literal[
    "not_tracked", "tracked", "corrupt", "retention_purged"
]
EvidenceRetentionTrackingState: TypeAlias = Literal["not_tracked", "tracked"]
EvidenceArtifactAvailabilityTrackingState: TypeAlias = Literal["tracked"]


class EvidenceExportUserActor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["user"]
    user_id: UUID


class EvidenceExportServiceKeyActor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["service_key"]
    key_id: UUID


EvidenceExportActor: TypeAlias = Annotated[
    EvidenceExportUserActor | EvidenceExportServiceKeyActor,
    Field(discriminator="type"),
]


def evidence_export_actor_from_principal(
    principal: FlowPrincipal,
) -> EvidenceExportActor:
    if principal.principal_type == PrincipalType.USER:
        if principal.principal_user_id is None:
            raise ValueError("principal_user_id required for evidence export actor")
        return EvidenceExportUserActor(
            type="user",
            user_id=principal.principal_user_id,
        )
    if principal.principal_type == PrincipalType.SERVICE_KEY:
        if principal.actor_api_key_id is None:
            raise ValueError("actor_api_key_id required for evidence export actor")
        return EvidenceExportServiceKeyActor(
            type="service_key",
            key_id=principal.actor_api_key_id,
        )
    raise ValueError("unsupported evidence export principal type")


class EvidenceExportContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail_mode: EvidenceExportDetailMode
    export_reason: str
    actor: EvidenceExportActor


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

    schema_version: Literal["flow-evidence-export.v11"]
    app_version: str
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
    actor: EvidenceExportActor
    export_reason: str
    detail_mode: EvidenceExportDetailMode
    redaction_applied: bool
    masked_fields_count: int
    redaction_policy_version: str
    retention_state_summary: EvidenceRetentionStateSummary
    artifact_availability_summary: EvidenceArtifactAvailabilitySummary
    review_checkpoint_summary: EvidenceReviewCheckpointSummary
