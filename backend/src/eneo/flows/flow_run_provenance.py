from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypeAlias, TypeVar, cast
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from eneo.flows.domain.canonical_json_hash import canonical_json_bytes
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.domain.flow_step_attempt_input import MappedExecutionMode
from eneo.flows.domain.rag_evidence import SourceUsageState
from eneo.flows.flow_retention_tombstone import (
    FLOW_ATTEMPT_RETENTION_MARKER_SCHEMA_VERSION,
    FlowAttemptRetentionMarker,
    RunDebugAttemptRetentionCounts,
    match_attempt_retention_counts,
)
from eneo.flows.source_display import (
    format_source_container_display_name,
    format_source_container_label,
    format_source_display_name,
    resolve_reference_title,
)

TEXT_PREVIEW_MAX_BYTES = 16 * 1024
JSON_PREVIEW_MAX_BYTES = 16 * 1024
ModelT = TypeVar("ModelT", bound=BaseModel)
DEFAULT_RAG_SELECTION_BASIS = "semantic_search_ranked_chunks_grouped_by_source"
FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION: Literal["flow-attempt-provenance.v3"] = (
    "flow-attempt-provenance.v3"
)
FLOW_ATTEMPT_PROVENANCE_MARKER_SCHEMA_VERSION: Literal[
    "flow-attempt-provenance-marker.v1"
] = "flow-attempt-provenance-marker.v1"
FLOW_RESOLVED_INPUT_SCHEMA_VERSION: Literal[1] = 1
FLOW_RESOLVED_INPUT_MAX_EDGES = 2048
FLOW_RESOLVED_INPUT_MAX_CANONICAL_BYTES = 1024 * 1024


class _FlowResolvedInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


FlowResolvedInputJsonPathSegment: TypeAlias = (
    Annotated[str, Field(strict=True, min_length=1)]
    | Annotated[int, Field(strict=True, ge=0)]
)


class FlowResolvedInputJsonPath(_FlowResolvedInputModel):
    kind: Literal["json_path"]
    path: tuple[FlowResolvedInputJsonPathSegment, ...]


class _FlowResolvedInputSelectedSource(_FlowResolvedInputModel):
    selector: FlowResolvedInputJsonPath


class FlowResolvedInputFlowInputSource(_FlowResolvedInputSelectedSource):
    kind: Literal["flow_input"]


class FlowResolvedInputStepResultSource(_FlowResolvedInputSelectedSource):
    kind: Literal["step_result"]
    source_step_id: UUID
    source_attempt_no: int = Field(strict=True, ge=1)


class FlowResolvedInputSystemValueSource(_FlowResolvedInputModel):
    kind: Literal["system_value"]
    name: str = Field(min_length=1)


class FlowResolvedInputRuntimeSource(_FlowResolvedInputSelectedSource):
    kind: Literal["runtime_input"]


class FlowResolvedInputRuntimeFileSource(_FlowResolvedInputSelectedSource):
    kind: Literal["runtime_file"]
    input_file_ordinal: int = Field(strict=True, ge=0, le=2**31 - 1)
    file_id: UUID
    checksum: str = Field(min_length=1)
    byte_size: int = Field(strict=True, ge=0)


class FlowResolvedInputHttpResponseSource(_FlowResolvedInputSelectedSource):
    kind: Literal["http_response"]


FlowResolvedInputSource: TypeAlias = Annotated[
    FlowResolvedInputFlowInputSource
    | FlowResolvedInputStepResultSource
    | FlowResolvedInputSystemValueSource
    | FlowResolvedInputRuntimeSource
    | FlowResolvedInputRuntimeFileSource
    | FlowResolvedInputHttpResponseSource,
    Field(discriminator="kind"),
]


class FlowResolvedInputHashedSelection(_FlowResolvedInputModel):
    encoding: Literal["utf8", "canonical_json"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(strict=True, ge=0)


class FlowResolvedInputBoundFileSelection(_FlowResolvedInputModel):
    encoding: Literal["bound_file"]


FlowResolvedInputSelection: TypeAlias = (
    FlowResolvedInputHashedSelection | FlowResolvedInputBoundFileSelection
)


class FlowResolvedInputEdge(_FlowResolvedInputModel):
    binding_ref: str = Field(min_length=1)
    source: FlowResolvedInputSource
    selection: FlowResolvedInputSelection

    @model_validator(mode="after")
    def _bound_file_selection_matches_runtime_file(self) -> "FlowResolvedInputEdge":
        is_runtime_file = self.source.kind == "runtime_file"
        is_bound_file = self.selection.encoding == "bound_file"
        if is_runtime_file != is_bound_file:
            raise ValueError(
                "bound_file selection must be used exactly for runtime_file sources"
            )
        return self


class _FlowResolvedInputEdgesFields(_FlowResolvedInputModel):
    schema_version: Literal[1]
    edges: tuple[FlowResolvedInputEdge, ...] = Field(
        max_length=FLOW_RESOLVED_INPUT_MAX_EDGES
    )

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version_is_integer(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("schema_version must be the integer 1.")
        return value


class FlowResolvedInputEdges(_FlowResolvedInputEdgesFields):
    @model_validator(mode="after")
    def _canonical_size_is_bounded(self) -> "FlowResolvedInputEdges":
        canonical_size = len(canonical_json_bytes(self.model_dump(mode="json")))
        if canonical_size > FLOW_RESOLVED_INPUT_MAX_CANONICAL_BYTES:
            raise ValueError(
                "Resolved input edges canonical JSON exceeds "
                f"{FLOW_RESOLVED_INPUT_MAX_CANONICAL_BYTES} bytes."
            )
        return self


FlowResolvedInputEdgeIndex: TypeAlias = Annotated[
    int,
    Field(strict=True, ge=0, lt=FLOW_RESOLVED_INPUT_MAX_EDGES),
]


def _require_canonical_resolved_input_edge_indexes(
    indexes: tuple[FlowResolvedInputEdgeIndex, ...],
) -> tuple[FlowResolvedInputEdgeIndex, ...]:
    if indexes != tuple(sorted(set(indexes))):
        raise ValueError("Resolved input edge indexes must be sorted and unique.")
    return indexes


FlowResolvedInputEdgeIndexes: TypeAlias = Annotated[
    tuple[FlowResolvedInputEdgeIndex, ...],
    Field(max_length=FLOW_RESOLVED_INPUT_MAX_EDGES),
    AfterValidator(_require_canonical_resolved_input_edge_indexes),
]


@dataclass(frozen=True)
class FlowResolvedInputEdgeGrouping:
    aggregate: FlowResolvedInputEdges
    indexes_by_group: tuple[FlowResolvedInputEdgeIndexes, ...]


def build_resolved_input_edge(
    *,
    binding_ref: str,
    source: FlowResolvedInputSource,
    selected_value: object,
) -> FlowResolvedInputEdge:
    if isinstance(selected_value, str):
        encoded = selected_value.encode("utf-8")
        encoding: Literal["utf8", "canonical_json"] = "utf8"
    else:
        encoded = canonical_json_bytes(selected_value)
        encoding = "canonical_json"
    return FlowResolvedInputEdge(
        binding_ref=binding_ref,
        source=source,
        selection=FlowResolvedInputHashedSelection(
            encoding=encoding,
            sha256=hashlib.sha256(encoded).hexdigest(),
            byte_size=len(encoded),
        ),
    )


def build_runtime_file_resolved_input_edge(
    *,
    binding_ref: str,
    input_file_ordinal: int,
    file_id: UUID,
    checksum: str,
    byte_size: int,
) -> FlowResolvedInputEdge:
    return FlowResolvedInputEdge(
        binding_ref=binding_ref,
        source=FlowResolvedInputRuntimeFileSource(
            kind="runtime_file",
            input_file_ordinal=input_file_ordinal,
            file_id=file_id,
            checksum=checksum,
            byte_size=byte_size,
            selector=FlowResolvedInputJsonPath(kind="json_path", path=()),
        ),
        selection=FlowResolvedInputBoundFileSelection(encoding="bound_file"),
    )


def _merge_and_index_resolved_input_edges(
    *edge_groups: Iterable[FlowResolvedInputEdge],
) -> tuple[
    tuple[FlowResolvedInputEdge, ...],
    tuple[FlowResolvedInputEdgeIndexes, ...],
]:
    merged: list[FlowResolvedInputEdge] = []
    indexes_by_identity: dict[bytes, int] = {}
    indexes_by_group: list[FlowResolvedInputEdgeIndexes] = []
    for edge_group in edge_groups:
        group_indexes: set[int] = set()
        for edge in edge_group:
            identity = canonical_json_bytes(edge.model_dump(mode="json"))
            index = indexes_by_identity.get(identity)
            if index is None:
                index = len(merged)
                indexes_by_identity[identity] = index
                merged.append(edge)
            group_indexes.add(index)
        indexes_by_group.append(tuple(sorted(group_indexes)))
    return tuple(merged), tuple(indexes_by_group)


def merge_resolved_input_edges(
    *edge_groups: Iterable[FlowResolvedInputEdge],
) -> tuple[FlowResolvedInputEdge, ...]:
    merged, _ = _merge_and_index_resolved_input_edges(*edge_groups)
    return merged


def group_resolved_input_edges(
    *edge_groups: Iterable[FlowResolvedInputEdge],
) -> FlowResolvedInputEdgeGrouping:
    merged, indexes_by_group = _merge_and_index_resolved_input_edges(*edge_groups)
    return FlowResolvedInputEdgeGrouping(
        aggregate=FlowResolvedInputEdges(
            schema_version=FLOW_RESOLVED_INPUT_SCHEMA_VERSION,
            edges=merged,
        ),
        indexes_by_group=indexes_by_group,
    )


FlowResolvedInputEdgesParseStatus: TypeAlias = Literal[
    "not_tracked", "tracked", "corrupt"
]
FlowResolvedInputEdgesCorruptionCode: TypeAlias = Literal[
    "flow_resolved_input_edges_invalid_type",
    "flow_resolved_input_edges_schema_version_missing",
    "flow_resolved_input_edges_schema_version_unsupported",
    "flow_resolved_input_edges_invalid_payload",
]


class FlowResolvedInputEdgesCorruptionMarker(_FlowResolvedInputModel):
    status: Literal["corrupt"]
    error_code: FlowResolvedInputEdgesCorruptionCode
    message: str
    raw_value_type: str | None = None
    persisted_schema_version: int | str | None = None


@dataclass(frozen=True)
class FlowResolvedInputEdgesParseResult:
    status: FlowResolvedInputEdgesParseStatus
    aggregate: FlowResolvedInputEdges | None = None
    marker: FlowResolvedInputEdgesCorruptionMarker | None = None

    def __post_init__(self) -> None:
        if self.status == "tracked" and (
            self.aggregate is None or self.marker is not None
        ):
            raise ValueError("Tracked resolved input edges require an aggregate.")
        if self.status == "corrupt" and (
            self.aggregate is not None or self.marker is None
        ):
            raise ValueError("Corrupt resolved input edges require a marker.")
        if self.status == "not_tracked" and (
            self.aggregate is not None or self.marker is not None
        ):
            raise ValueError("Untracked resolved input edges cannot carry evidence.")


class FlowResolvedInputLineageNotTracked(_FlowResolvedInputModel):
    status: Literal["not_tracked"]


class FlowResolvedInputLineageTracked(_FlowResolvedInputEdgesFields):
    status: Literal["tracked"]


class FlowResolvedInputLineageRetentionPurged(_FlowResolvedInputModel):
    status: Literal["retention_purged"]
    resolved_input_aggregate_count: int = Field(strict=True, ge=0)
    resolved_input_edge_count: int = Field(strict=True, ge=0)


FlowResolvedInputLineage: TypeAlias = Annotated[
    FlowResolvedInputLineageNotTracked
    | FlowResolvedInputLineageTracked
    | FlowResolvedInputEdgesCorruptionMarker
    | FlowResolvedInputLineageRetentionPurged,
    Field(discriminator="status"),
]


class FlowResolvedInputEdgesConflictError(RuntimeError):
    def __init__(self, *, attempt_id: UUID, tenant_id: UUID):
        self.attempt_id = attempt_id
        self.tenant_id = tenant_id
        super().__init__(
            "Resolved input edges are immutable and a different aggregate is "
            f"already stored (attempt_id={attempt_id}, tenant_id={tenant_id})."
        )


class FlowResolvedInputEdgesUnavailableError(RuntimeError):
    def __init__(
        self,
        *,
        attempt_id: UUID,
        tenant_id: UUID,
        error_code: FlowResolvedInputEdgesCorruptionCode,
    ):
        self.attempt_id = attempt_id
        self.tenant_id = tenant_id
        self.error_code = error_code
        super().__init__(
            "Resolved input edges cannot be updated because persisted evidence is "
            f"corrupt (attempt_id={attempt_id}, tenant_id={tenant_id}, "
            f"error_code={error_code})."
        )


def parse_resolved_input_edges(raw: Any) -> FlowResolvedInputEdgesParseResult:
    if raw is None:
        return FlowResolvedInputEdgesParseResult(status="not_tracked")
    if not isinstance(raw, dict):
        return FlowResolvedInputEdgesParseResult(
            status="corrupt",
            marker=FlowResolvedInputEdgesCorruptionMarker(
                status="corrupt",
                error_code="flow_resolved_input_edges_invalid_type",
                message="Resolved input edges must be a JSON object.",
                raw_value_type=type(raw).__name__,
            ),
        )

    raw_payload = cast(dict[str, Any], raw)
    schema_version = raw_payload.get("schema_version")
    if not isinstance(schema_version, (int, str)) or isinstance(schema_version, bool):
        return FlowResolvedInputEdgesParseResult(
            status="corrupt",
            marker=FlowResolvedInputEdgesCorruptionMarker(
                status="corrupt",
                error_code="flow_resolved_input_edges_schema_version_missing",
                message="Resolved input edges are missing schema_version.",
            ),
        )
    if schema_version != FLOW_RESOLVED_INPUT_SCHEMA_VERSION:
        return FlowResolvedInputEdgesParseResult(
            status="corrupt",
            marker=FlowResolvedInputEdgesCorruptionMarker(
                status="corrupt",
                error_code="flow_resolved_input_edges_schema_version_unsupported",
                message="Resolved input edges schema_version is not supported.",
                persisted_schema_version=schema_version,
            ),
        )

    try:
        aggregate = FlowResolvedInputEdges.model_validate(raw_payload)
    except (TypeError, ValueError):
        return FlowResolvedInputEdgesParseResult(
            status="corrupt",
            marker=FlowResolvedInputEdgesCorruptionMarker(
                status="corrupt",
                error_code="flow_resolved_input_edges_invalid_payload",
                message="Resolved input edges failed current schema validation.",
                persisted_schema_version=schema_version,
            ),
        )
    return FlowResolvedInputEdgesParseResult(status="tracked", aggregate=aggregate)


FlowAttemptProvenanceParseStatus: TypeAlias = Literal[
    "not_tracked", "tracked", "corrupt", "retention_purged"
]
FlowAttemptProvenanceCorruptionCode: TypeAlias = Literal[
    "flow_attempt_provenance_invalid_type",
    "flow_attempt_provenance_schema_version_missing",
    "flow_attempt_provenance_schema_version_unsupported",
    "flow_attempt_provenance_unknown_top_level_keys",
    "flow_attempt_provenance_invalid_current_payload",
    "flow_attempt_provenance_invalid_retention_marker",
]


class PayloadPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview: Any
    truncated: bool
    byte_size: int
    sha256: str | None = None


class LlmProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_calls: PayloadPreview | None = None
    raw_completion_text: PayloadPreview | None = None


class MappedProviderCallProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_mode: MappedExecutionMode
    item_index: int | None = Field(default=None, ge=1)
    source_index: int | None = Field(default=None, ge=1)
    source_id: str | None = None

    @model_validator(mode="after")
    def _index_matches_execution_mode(self) -> "MappedProviderCallProvenance":
        if self.execution_mode == "per_item":
            if self.item_index is None or self.source_index is not None:
                raise ValueError("per-item calls require only an item index")
        elif self.source_index is None or self.item_index is not None:
            raise ValueError("per-source calls require only a source index")
        return self


TokenCountSource = Literal[
    "provider", "estimated", "mixed", "not_applicable", "not_reported"
]


def sum_complete_token_counts(counts: Iterable[int | None]) -> int | None:
    total = 0
    observed = False
    for count in counts:
        if count is None:
            return None
        total += count
        observed = True
    return total if observed else None


class RagProvenance(BaseModel):
    model_config = ConfigDict(extra="allow")


class CitationsProvenance(BaseModel):
    model_config = ConfigDict(extra="allow")


class FlowAttemptProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flow-attempt-provenance.v3"] = (
        FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION
    )
    llm: LlmProvenance | None = None
    rag: RagProvenance | None = None
    citations: CitationsProvenance | None = None

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class FlowAttemptProvenanceCorruptionMarker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flow-attempt-provenance-marker.v1"] = (
        FLOW_ATTEMPT_PROVENANCE_MARKER_SCHEMA_VERSION
    )
    status: Literal["corrupt"] = "corrupt"
    error_code: FlowAttemptProvenanceCorruptionCode
    message: str
    raw_value_type: str | None = None
    persisted_schema_version: str | None = None
    unknown_keys: tuple[str, ...] | None = None

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


@dataclass(frozen=True)
class FlowAttemptProvenanceParseResult:
    status: FlowAttemptProvenanceParseStatus
    provenance: FlowAttemptProvenance | None = None
    marker: FlowAttemptProvenanceCorruptionMarker | None = None
    retention_marker: FlowAttemptRetentionMarker | None = None

    def __post_init__(self) -> None:
        if self.status == "tracked" and (
            self.provenance is None
            or self.marker is not None
            or self.retention_marker is not None
        ):
            raise ValueError("Tracked attempt provenance requires a provenance value.")
        if self.status == "corrupt" and (
            self.marker is None
            or self.provenance is not None
            or self.retention_marker is not None
        ):
            raise ValueError("Corrupt attempt provenance requires a marker value.")
        if self.status == "retention_purged" and (
            self.retention_marker is None
            or self.provenance is not None
            or self.marker is not None
        ):
            raise ValueError(
                "Retention-purged attempt provenance requires a retention marker."
            )
        if self.status == "not_tracked" and (
            self.provenance is not None
            or self.marker is not None
            or self.retention_marker is not None
        ):
            raise ValueError("Untracked attempt provenance cannot carry payload.")

    @classmethod
    def not_tracked(cls) -> "FlowAttemptProvenanceParseResult":
        return cls(status="not_tracked")

    @classmethod
    def tracked(
        cls, provenance: FlowAttemptProvenance
    ) -> "FlowAttemptProvenanceParseResult":
        return cls(status="tracked", provenance=provenance)

    @classmethod
    def corrupt(
        cls, marker: FlowAttemptProvenanceCorruptionMarker
    ) -> "FlowAttemptProvenanceParseResult":
        return cls(status="corrupt", marker=marker)

    @classmethod
    def retention_purged(
        cls, marker: FlowAttemptRetentionMarker
    ) -> "FlowAttemptProvenanceParseResult":
        return cls(status="retention_purged", retention_marker=marker)

    def to_export_payload(self) -> dict[str, Any] | None:
        if self.status == "tracked" and self.provenance is not None:
            return self.provenance.to_payload()
        if self.status == "corrupt" and self.marker is not None:
            return self.marker.to_payload()
        if self.status == "retention_purged" and self.retention_marker is not None:
            return self.retention_marker.to_payload()
        return None


@dataclass(frozen=True)
class FlowAttemptScopedProvenance:
    parse_result: FlowAttemptProvenanceParseResult
    retention_counts: RunDebugAttemptRetentionCounts | None = None

    def __post_init__(self) -> None:
        if (self.parse_result.status == "retention_purged") != (
            self.retention_counts is not None
        ):
            raise ValueError(
                "Scoped retention-purged provenance requires validated counts."
            )


def project_resolved_input_lineage(
    *,
    resolved_inputs: FlowResolvedInputEdgesParseResult,
    scoped_attempt_provenance: FlowAttemptScopedProvenance,
) -> FlowResolvedInputLineage:
    """Project exact lineage and explain a missing row after retention."""
    if resolved_inputs.status == "tracked":
        assert resolved_inputs.aggregate is not None
        return FlowResolvedInputLineageTracked(
            status="tracked",
            schema_version=resolved_inputs.aggregate.schema_version,
            edges=resolved_inputs.aggregate.edges,
        )
    if resolved_inputs.status == "corrupt":
        assert resolved_inputs.marker is not None
        return resolved_inputs.marker
    counts = scoped_attempt_provenance.retention_counts
    if counts is not None:
        return FlowResolvedInputLineageRetentionPurged(
            status="retention_purged",
            resolved_input_aggregate_count=counts.resolved_input_aggregate_count,
            resolved_input_edge_count=counts.resolved_input_edge_count,
        )
    return FlowResolvedInputLineageNotTracked(status="not_tracked")


class FlowAttemptRuntimeEvidencePurgedError(RuntimeError):
    def __init__(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        attempt_no: int,
        tenant_id: UUID,
    ):
        self.run_id = run_id
        self.step_id = step_id
        self.attempt_no = attempt_no
        self.tenant_id = tenant_id
        super().__init__(
            "Attempt runtime evidence cannot be written after retention purge "
            f"(run_id={run_id}, step_id={step_id}, "
            f"attempt_no={attempt_no}, tenant_id={tenant_id})."
        )


@dataclass(frozen=True)
class FlowAttemptTerminalizationEvidence:
    provenance_json: dict[str, Any] | None
    write_runtime_payloads: bool


def default_rag_tracking() -> dict[str, Any]:
    return {
        "retrieval_tracked": True,
        "prompt_context_inclusion_tracked": False,
        "citation_tracked": False,
        "material_influence_tracked": False,
        "selection_basis": DEFAULT_RAG_SELECTION_BASIS,
        "note": (
            "References record retrieved candidates. Exact prompt inclusion, citations, "
            "and material influence are not currently tracked."
        ),
    }


def normalize_text_preview(
    text: str, *, max_bytes: int = TEXT_PREVIEW_MAX_BYTES
) -> PayloadPreview:
    encoded = text.encode("utf-8")
    byte_size = len(encoded)
    truncated = byte_size > max_bytes
    preview = text if not truncated else _truncate_utf8(text, max_bytes)
    return PayloadPreview(
        preview=preview,
        truncated=truncated,
        byte_size=byte_size,
        sha256=hashlib.sha256(encoded).hexdigest(),
    )


def normalize_json_preview(
    value: Any, *, max_bytes: int = JSON_PREVIEW_MAX_BYTES
) -> PayloadPreview:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    encoded = serialized.encode("utf-8")
    byte_size = len(encoded)
    if byte_size <= max_bytes:
        preview: Any = value
    else:
        preview = _truncate_utf8(serialized, max_bytes)
    return PayloadPreview(
        preview=preview,
        truncated=byte_size > max_bytes,
        byte_size=byte_size,
        sha256=hashlib.sha256(encoded).hexdigest(),
    )


def normalize_attempt_provenance(
    raw: dict[str, Any] | None,
) -> FlowAttemptProvenance | None:
    parse_result = parse_attempt_provenance(raw)
    return parse_result.provenance if parse_result.status == "tracked" else None


def require_attempt_runtime_evidence_not_purged(
    raw: Any,
    *,
    run_id: UUID,
    step_id: UUID,
    attempt_no: int,
    tenant_id: UUID,
) -> None:
    """Reject writes that would resurrect an attempt's purged runtime evidence."""
    parsed = parse_attempt_provenance(raw)
    if parsed.status == "retention_purged":
        raise FlowAttemptRuntimeEvidencePurgedError(
            run_id=run_id,
            step_id=step_id,
            attempt_no=attempt_no,
            tenant_id=tenant_id,
        )


def resolve_attempt_terminalization_evidence(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
) -> FlowAttemptTerminalizationEvidence:
    """Preserve unavailable evidence during attempt terminalization."""
    existing_result = parse_attempt_provenance(existing)
    if existing_result.status in ("corrupt", "retention_purged"):
        return FlowAttemptTerminalizationEvidence(
            provenance_json=existing,
            write_runtime_payloads=existing_result.status == "corrupt",
        )
    if incoming is None:
        return FlowAttemptTerminalizationEvidence(
            provenance_json=existing,
            write_runtime_payloads=True,
        )
    return FlowAttemptTerminalizationEvidence(
        provenance_json=incoming,
        write_runtime_payloads=True,
    )


def parse_attempt_provenance(raw: Any) -> FlowAttemptProvenanceParseResult:
    if raw is None:
        return FlowAttemptProvenanceParseResult.not_tracked()
    if not isinstance(raw, dict):
        return FlowAttemptProvenanceParseResult.corrupt(
            _corruption_marker(
                error_code="flow_attempt_provenance_invalid_type",
                message="Attempt provenance must be a JSON object.",
                raw=raw,
                include_raw_value_type=True,
            )
        )
    raw_payload = cast(dict[str, Any], raw)

    schema_version = raw_payload.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version.strip():
        return FlowAttemptProvenanceParseResult.corrupt(
            _corruption_marker(
                error_code="flow_attempt_provenance_schema_version_missing",
                message="Attempt provenance is missing schema_version.",
                raw=raw_payload,
            )
        )
    if schema_version != FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION:
        if schema_version == FLOW_ATTEMPT_RETENTION_MARKER_SCHEMA_VERSION:
            try:
                return FlowAttemptProvenanceParseResult.retention_purged(
                    FlowAttemptRetentionMarker.model_validate(raw_payload)
                )
            except (TypeError, ValueError, ValidationError):
                return FlowAttemptProvenanceParseResult.corrupt(
                    _corruption_marker(
                        error_code="flow_attempt_provenance_invalid_retention_marker",
                        message="Attempt retention marker failed schema validation.",
                        raw=raw_payload,
                        persisted_schema_version=schema_version,
                    )
                )
        return FlowAttemptProvenanceParseResult.corrupt(
            _corruption_marker(
                error_code="flow_attempt_provenance_schema_version_unsupported",
                message="Attempt provenance schema_version is not supported.",
                raw=raw_payload,
                persisted_schema_version=schema_version,
            )
        )

    allowed_keys = set(FlowAttemptProvenance.model_fields)
    unknown_keys = tuple(sorted(set(raw_payload) - allowed_keys))
    if unknown_keys:
        return FlowAttemptProvenanceParseResult.corrupt(
            _corruption_marker(
                error_code="flow_attempt_provenance_unknown_top_level_keys",
                message="Attempt provenance contains unknown top-level keys.",
                raw=raw_payload,
                persisted_schema_version=schema_version,
                unknown_keys=unknown_keys,
            )
        )

    invalid_section = next(
        (
            key
            for key in raw_payload
            if key != "schema_version"
            and raw_payload.get(key) is not None
            and not isinstance(raw_payload.get(key), dict)
        ),
        None,
    )
    if invalid_section is not None:
        return FlowAttemptProvenanceParseResult.corrupt(
            _corruption_marker(
                error_code="flow_attempt_provenance_invalid_current_payload",
                message=f"Attempt provenance section '{invalid_section}' is invalid.",
                raw=raw_payload,
                persisted_schema_version=schema_version,
            )
        )

    try:
        return FlowAttemptProvenanceParseResult.tracked(
            _normalize_attempt_provenance_v3(raw_payload)
        )
    except (TypeError, ValueError, ValidationError):
        return FlowAttemptProvenanceParseResult.corrupt(
            _corruption_marker(
                error_code="flow_attempt_provenance_invalid_current_payload",
                message="Attempt provenance failed current schema validation.",
                raw=raw_payload,
                persisted_schema_version=schema_version,
            )
        )


def parse_attempt_provenance_for_attempt(
    raw: Any,
    *,
    tenant_id: UUID,
    run_id: UUID,
    attempt_id: UUID,
) -> FlowAttemptScopedProvenance:
    """Parse provenance and reject a retention marker for another attempt."""
    parse_result = parse_attempt_provenance(raw)
    if parse_result.status != "retention_purged":
        return FlowAttemptScopedProvenance(parse_result=parse_result)
    assert parse_result.retention_marker is not None

    retention_counts = match_attempt_retention_counts(
        parse_result.retention_marker,
        tenant_id=tenant_id,
        run_id=run_id,
        attempt_id=attempt_id,
    )
    if retention_counts is not None:
        return FlowAttemptScopedProvenance(
            parse_result=parse_result,
            retention_counts=retention_counts,
        )
    return FlowAttemptScopedProvenance(
        parse_result=FlowAttemptProvenanceParseResult.corrupt(
            _corruption_marker(
                error_code="flow_attempt_provenance_invalid_retention_marker",
                message="Attempt retention marker identity does not match its attempt.",
                raw=raw,
                persisted_schema_version=FLOW_ATTEMPT_RETENTION_MARKER_SCHEMA_VERSION,
            )
        )
    )


def _normalize_attempt_provenance_v3(raw: dict[str, Any]) -> FlowAttemptProvenance:
    llm_raw = raw.get("llm")
    llm: LlmProvenance | None = None
    if isinstance(llm_raw, dict):
        llm_payload: FlowPersistedJsonObject = dict(
            cast(FlowPersistedJsonObject, llm_raw)
        )
        tool_calls = llm_payload.get("tool_calls")
        if tool_calls is not None:
            llm_payload["tool_calls"] = normalize_json_preview(tool_calls)
        raw_completion_text = llm_payload.get("raw_completion_text")
        if isinstance(raw_completion_text, str):
            llm_payload["raw_completion_text"] = normalize_text_preview(
                raw_completion_text
            )
        llm = LlmProvenance.model_validate(llm_payload)

    return FlowAttemptProvenance(
        schema_version=FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
        llm=llm,
        rag=_normalize_rag_provenance(raw.get("rag")),
        citations=_validate_extra_model(CitationsProvenance, raw.get("citations")),
    )


def _corruption_marker(
    *,
    error_code: FlowAttemptProvenanceCorruptionCode,
    message: str,
    raw: Any,
    persisted_schema_version: str | None = None,
    unknown_keys: tuple[str, ...] | None = None,
    include_raw_value_type: bool = False,
) -> FlowAttemptProvenanceCorruptionMarker:
    return FlowAttemptProvenanceCorruptionMarker(
        error_code=error_code,
        message=message,
        raw_value_type=type(raw).__name__ if include_raw_value_type else None,
        persisted_schema_version=persisted_schema_version,
        unknown_keys=unknown_keys,
    )


def _validate_extra_model(model: type[ModelT], value: Any) -> ModelT | None:
    if not isinstance(value, dict):
        return None
    return model.model_validate(value)


def _normalize_rag_provenance(value: Any) -> RagProvenance | None:
    normalized_payload = normalize_rag_payload(value)
    if normalized_payload is None:
        return None
    return RagProvenance.model_validate(normalized_payload)


def normalize_rag_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    payload: FlowPersistedJsonObject = dict(cast(FlowPersistedJsonObject, value))
    payload["tracking"] = _normalize_rag_tracking(payload.get("tracking"))
    prompt_context = _normalize_rag_prompt_context(payload.get("prompt_context"))
    if prompt_context is not None:
        payload["prompt_context"] = prompt_context
    included_source_ids: set[str] = set()
    if isinstance(prompt_context, dict):
        included_source_ids = {
            source_id
            for source_id in cast(
                list[object], prompt_context.get("included_source_ids", [])
            )
            if isinstance(source_id, str) and source_id.strip()
        }
    references = payload.get("references")
    if isinstance(references, list):
        normalized_references: list[dict[str, Any]] = []
        source_names: list[str] = []
        source_display_names: list[str] = []
        for reference in cast(list[object], references):
            if not isinstance(reference, dict):
                continue
            normalized_reference: FlowPersistedJsonObject = dict(
                cast(FlowPersistedJsonObject, reference)
            )
            normalized_reference["usage_state"] = _normalize_usage_state(
                normalized_reference.get("usage_state")
            )
            _normalize_reference_display_fields(normalized_reference)
            _normalize_reference_chunk_counts(normalized_reference)
            if (
                included_source_ids
                and str(normalized_reference.get("id")) in included_source_ids
            ):
                normalized_reference["usage_state"] = "inserted_into_prompt"
            raw_title = resolve_reference_title(normalized_reference)
            if raw_title is not None:
                source_names.append(raw_title)
                display_name = format_source_display_name(raw_title)
                normalized_reference["display_title"] = display_name
                source_display_names.append(display_name)
            normalized_references.append(normalized_reference)
        payload["references"] = normalized_references
        if source_names:
            payload["source_names"] = list(dict.fromkeys(source_names))
            payload["source_display_names"] = list(dict.fromkeys(source_display_names))
            payload["has_named_sources"] = True
        else:
            payload["source_names"] = []
            payload["source_display_names"] = []
            payload["has_named_sources"] = False
    return payload


def _normalize_rag_prompt_context(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    payload: FlowPersistedJsonObject = dict(cast(FlowPersistedJsonObject, value))

    included_source_ids = [
        str(source_id).strip()
        for source_id in cast(list[object], payload.get("included_source_ids", []))
        if str(source_id).strip()
    ]
    not_included_source_ids = [
        str(source_id).strip()
        for source_id in cast(list[object], payload.get("not_included_source_ids", []))
        if str(source_id).strip()
    ]

    normalized_groups: list[dict[str, Any]] = []
    derived_titles: list[str] = []
    raw_groups = payload.get("included_groups")
    if isinstance(raw_groups, list):
        for group in cast(list[object], raw_groups):
            if not isinstance(group, dict):
                continue
            normalized_group: FlowPersistedJsonObject = dict(
                cast(FlowPersistedJsonObject, group)
            )
            source_id = normalized_group.get("source_id")
            if source_id is not None:
                normalized_group["source_id"] = str(source_id)
            source_title = normalized_group.get("source_title")
            if isinstance(source_title, str) and source_title.strip():
                stripped_title = source_title.strip()
                normalized_group["source_title"] = stripped_title
                derived_titles.append(stripped_title)
            normalized_groups.append(normalized_group)

    included_source_titles = list(
        dict.fromkeys(
            [
                title.strip()
                for title in cast(
                    list[object], payload.get("included_source_titles", [])
                )
                if isinstance(title, str) and title.strip()
            ]
            + derived_titles
        )
    )
    included_source_display_names = [
        format_source_display_name(title) for title in included_source_titles
    ]

    payload["tracked"] = bool(payload.get("tracked", True))
    payload["included_source_ids"] = included_source_ids
    payload["not_included_source_ids"] = not_included_source_ids
    payload["included_groups"] = normalized_groups
    payload["included_source_titles"] = included_source_titles
    payload["included_source_display_names"] = included_source_display_names
    payload["summary"] = {
        "total_sources": payload.get("included_source_count")
        or len(included_source_ids),
        "total_chunks": payload.get("included_chunk_count")
        or sum(int(group.get("chunk_count", 0) or 0) for group in normalized_groups),
        "truncated_by_token_budget": bool(payload.get("truncated_by_token_budget")),
    }
    return payload


def _truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes]
    return truncated.decode("utf-8", errors="ignore")


def _normalize_rag_tracking(value: Any) -> dict[str, Any]:
    defaults = default_rag_tracking()
    if not isinstance(value, dict):
        return defaults

    normalized = dict(defaults)
    value_dict = cast(FlowPersistedJsonObject, value)
    for key in (
        "retrieval_tracked",
        "prompt_context_inclusion_tracked",
        "citation_tracked",
        "material_influence_tracked",
    ):
        if isinstance(value_dict.get(key), bool):
            normalized[key] = value_dict[key]
    selection_basis = value_dict.get("selection_basis")
    if isinstance(selection_basis, str) and selection_basis.strip():
        normalized["selection_basis"] = selection_basis.strip()
    note = value_dict.get("note")
    if isinstance(note, str) and note.strip():
        normalized["note"] = note.strip()
    return normalized


def _normalize_usage_state(value: Any) -> SourceUsageState:
    # A stored state outside the closed family reads as a retrieval candidate,
    # which never overstates what the evidence proves.
    if value == "inserted_into_prompt":
        return "inserted_into_prompt"
    return "retrieved_candidate"


def _normalize_reference_display_fields(reference: dict[str, Any]) -> None:
    raw_title = resolve_reference_title(reference)
    if raw_title is not None:
        reference.setdefault("source_title_raw", raw_title)
        reference.setdefault(
            "source_display_name", format_source_display_name(raw_title)
        )
    raw_container_name = reference.get("source_container_name")
    if isinstance(raw_container_name, str) and raw_container_name.strip():
        reference.setdefault("source_container_name_raw", raw_container_name.strip())
    container_display_name = format_source_container_display_name(reference)
    if container_display_name is not None:
        reference["source_container_display_name"] = container_display_name
    container_label = format_source_container_label(reference)
    if container_label is not None:
        reference["source_container_label"] = container_label


def _normalize_reference_chunk_counts(reference: dict[str, Any]) -> None:
    recorded_passage_count = _count_recorded_passages(reference.get("passages"))
    matched_chunk_count = _coerce_non_negative_int(reference.get("matched_chunk_count"))
    if matched_chunk_count is None:
        matched_chunk_count = recorded_passage_count
    stored_recorded_count = _coerce_non_negative_int(
        reference.get("recorded_passage_count")
    )

    reference["matched_chunk_count"] = matched_chunk_count
    reference["recorded_passage_count"] = (
        stored_recorded_count
        if stored_recorded_count is not None
        else recorded_passage_count
    )


def _count_recorded_passages(value: Any) -> int:
    if not isinstance(value, list):
        return 0
    count = 0
    for passage in cast(list[object], value):
        if not isinstance(passage, Mapping):
            continue
        passage_mapping = cast(Mapping[str, object], passage)
        text = passage_mapping.get("text")
        if isinstance(text, str) and text.strip():
            count += 1
    return count


def _coerce_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and value.is_integer():
        return max(0, int(value))
    return None
