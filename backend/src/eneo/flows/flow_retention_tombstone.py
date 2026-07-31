from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self, TypeAlias, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eneo.flows.domain.flow import FlowRunTokenUsage

FLOW_RETENTION_TOMBSTONE_SCHEMA_VERSION: Literal["flow-retention-tombstone.v1"] = (
    "flow-retention-tombstone.v1"
)
FLOW_ATTEMPT_RETENTION_MARKER_SCHEMA_VERSION: Literal[
    "flow-attempt-retention-marker.v1"
] = "flow-attempt-retention-marker.v1"
FLOW_RETENTION_TOMBSTONES_KEY = "flow_retention_tombstones"
FLOW_RETENTION_ACTOR_SOURCE: Literal["data_retention_worker"] = "data_retention_worker"

FlowRetentionDataClass: TypeAlias = Literal["run_debug_evidence", "generated_artifact"]
FlowRetentionObjectType: TypeAlias = Literal["flow_step_attempt", "flow_step_result"]
FlowRetentionState: TypeAlias = Literal[
    "retention_purged", "artifact_content_purged", "redacted_for_deletion"
]


class RunDebugStepResultRetentionCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cleared_field_count: int = Field(strict=True, ge=0)
    pruned_output_key_count: int = Field(strict=True, ge=0)


class RunDebugAttemptRetentionCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cleared_field_count: int = Field(strict=True, ge=0)
    provider_call_count: int = Field(strict=True, ge=0)
    resolved_input_aggregate_count: int = Field(strict=True, ge=0)
    resolved_input_edge_count: int = Field(strict=True, ge=0)
    token_usage_state: Literal["recorded", "not_recorded", "unknown"] = "unknown"
    token_usage: FlowRunTokenUsage | None = None

    @model_validator(mode="after")
    def validate_token_usage_state(self) -> Self:
        if (self.token_usage_state == "recorded") != (self.token_usage is not None):
            raise ValueError(
                "Recorded token usage state must carry exactly one usage summary."
            )
        return self


class GeneratedArtifactRetentionCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    referenced_file_count: int = Field(strict=True, ge=0)


FlowRetentionTombstoneCounts: TypeAlias = (
    RunDebugStepResultRetentionCounts
    | RunDebugAttemptRetentionCounts
    | GeneratedArtifactRetentionCounts
)


class FlowRetentionTombstone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flow-retention-tombstone.v1"] = (
        FLOW_RETENTION_TOMBSTONE_SCHEMA_VERSION
    )
    tenant_id: str
    run_id: str
    trace_id: str
    data_class: FlowRetentionDataClass
    object_type: FlowRetentionObjectType
    object_id: str
    policy_source: str
    cutoff: datetime
    actor_source: Literal["data_retention_worker"] = FLOW_RETENTION_ACTOR_SOURCE
    counts: FlowRetentionTombstoneCounts
    timestamp: datetime
    retention_state: FlowRetentionState

    @model_validator(mode="after")
    def validate_count_shape(self) -> Self:
        expected_counts: type[BaseModel]
        if (
            self.data_class == "run_debug_evidence"
            and self.object_type == "flow_step_result"
            and self.retention_state == "retention_purged"
        ):
            expected_counts = RunDebugStepResultRetentionCounts
        elif (
            self.data_class == "run_debug_evidence"
            and self.object_type == "flow_step_attempt"
            and self.retention_state == "retention_purged"
        ):
            expected_counts = RunDebugAttemptRetentionCounts
        elif (
            self.data_class == "generated_artifact"
            and self.object_type == "flow_step_result"
            and self.retention_state == "artifact_content_purged"
        ):
            expected_counts = GeneratedArtifactRetentionCounts
        else:
            raise ValueError("Unsupported flow retention tombstone state")

        if type(self.counts) is not expected_counts:
            raise ValueError(
                "Flow retention tombstone count shape does not match marker"
            )
        return self

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class FlowAttemptRetentionMarker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flow-attempt-retention-marker.v1"] = (
        FLOW_ATTEMPT_RETENTION_MARKER_SCHEMA_VERSION
    )
    status: Literal["retention_purged"] = "retention_purged"
    tombstone: FlowRetentionTombstone

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


def parse_attempt_retention_counts(
    payload: object,
    *,
    tenant_id: UUID,
    run_id: UUID,
    attempt_id: UUID,
) -> RunDebugAttemptRetentionCounts | None:
    """Return counts only when a marker belongs to the requested attempt row."""
    if not isinstance(payload, dict):
        return None
    try:
        marker = FlowAttemptRetentionMarker.model_validate(
            cast(dict[str, Any], payload)
        )
    except ValueError:
        return None
    tombstone = marker.tombstone
    if (
        tombstone.tenant_id != str(tenant_id)
        or tombstone.run_id != str(run_id)
        or tombstone.object_id != str(attempt_id)
    ):
        return None
    counts = tombstone.counts
    return counts if isinstance(counts, RunDebugAttemptRetentionCounts) else None


def append_retention_tombstone(
    payload: Any, tombstone: FlowRetentionTombstone
) -> dict[str, Any]:
    payload_dict: dict[str, Any] = (
        dict(cast(dict[str, Any], payload)) if isinstance(payload, dict) else {}
    )
    tombstones = [
        item.to_payload()
        for item in extract_retention_tombstones(payload_dict)
        if not _same_marker(item, tombstone)
    ]
    tombstones.append(tombstone.to_payload())
    payload_dict[FLOW_RETENTION_TOMBSTONES_KEY] = tombstones
    return payload_dict


def extract_retention_tombstones(payload: Any) -> tuple[FlowRetentionTombstone, ...]:
    if not isinstance(payload, dict):
        return ()
    payload_dict = cast(dict[str, Any], payload)
    raw_tombstones = payload_dict.get(FLOW_RETENTION_TOMBSTONES_KEY)
    if not isinstance(raw_tombstones, list):
        return ()
    tombstones: list[FlowRetentionTombstone] = []
    for item in cast(list[Any], raw_tombstones):
        if not isinstance(item, dict):
            continue
        try:
            tombstones.append(
                FlowRetentionTombstone.model_validate(cast(dict[str, Any], item))
            )
        except ValueError:
            continue
    return tuple(tombstones)


def has_retention_tombstone(
    payload: Any,
    *,
    data_class: FlowRetentionDataClass,
    object_type: FlowRetentionObjectType,
    object_id: str,
    retention_state: FlowRetentionState,
) -> bool:
    return any(
        tombstone.data_class == data_class
        and tombstone.object_type == object_type
        and tombstone.object_id == object_id
        and tombstone.retention_state == retention_state
        for tombstone in extract_retention_tombstones(payload)
    )


def _same_marker(left: FlowRetentionTombstone, right: FlowRetentionTombstone) -> bool:
    return (
        left.data_class == right.data_class
        and left.object_type == right.object_type
        and left.object_id == right.object_id
        and left.retention_state == right.retention_state
    )
