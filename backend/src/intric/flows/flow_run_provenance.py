from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias, TypeVar, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from intric.flows.domain.flow import JsonObject
from intric.flows.source_display import (
    format_source_container_display_name,
    format_source_container_label,
    format_source_display_name,
    resolve_reference_title,
)

TEXT_PREVIEW_MAX_BYTES = 16 * 1024
JSON_PREVIEW_MAX_BYTES = 16 * 1024
ModelT = TypeVar("ModelT", bound=BaseModel)
DEFAULT_RAG_SELECTION_BASIS = "semantic_search_ranked_chunks_grouped_by_source"
FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION: Literal["flow-attempt-provenance.v1"] = (
    "flow-attempt-provenance.v1"
)
FLOW_ATTEMPT_PROVENANCE_MARKER_SCHEMA_VERSION: Literal[
    "flow-attempt-provenance-marker.v1"
] = "flow-attempt-provenance-marker.v1"

FlowAttemptProvenanceParseStatus: TypeAlias = Literal[
    "not_tracked", "tracked", "corrupt"
]
FlowAttemptProvenanceCorruptionCode: TypeAlias = Literal[
    "flow_attempt_provenance_invalid_type",
    "flow_attempt_provenance_schema_version_missing",
    "flow_attempt_provenance_schema_version_unsupported",
    "flow_attempt_provenance_unknown_top_level_keys",
    "flow_attempt_provenance_invalid_current_payload",
]


class PayloadPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview: Any
    truncated: bool
    byte_size: int
    sha256: str | None = None


class LlmProvenance(BaseModel):
    model_config = ConfigDict(extra="allow")

    effective_prompt: PayloadPreview | None = None
    model_parameters: dict[str, Any] | None = None
    tool_calls: PayloadPreview | None = None
    raw_completion_text: PayloadPreview | None = None


class RagProvenance(BaseModel):
    model_config = ConfigDict(extra="allow")


class HttpProvenance(BaseModel):
    model_config = ConfigDict(extra="allow")


class GuardsProvenance(BaseModel):
    model_config = ConfigDict(extra="allow")


class RuntimeInputProvenance(BaseModel):
    model_config = ConfigDict(extra="allow")


class TranscriptionProvenance(BaseModel):
    model_config = ConfigDict(extra="allow")


class TemplateProvenance(BaseModel):
    model_config = ConfigDict(extra="allow")


class ArtifactProvenance(BaseModel):
    model_config = ConfigDict(extra="allow")


class AgenticProvenance(BaseModel):
    model_config = ConfigDict(extra="allow")


class McpProvenance(BaseModel):
    model_config = ConfigDict(extra="allow")


class CitationsProvenance(BaseModel):
    model_config = ConfigDict(extra="allow")


class FlowAttemptProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["flow-attempt-provenance.v1"] = (
        FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION
    )
    llm: LlmProvenance | None = None
    rag: RagProvenance | None = None
    http: HttpProvenance | None = None
    template: TemplateProvenance | None = None
    runtime_input: RuntimeInputProvenance | None = None
    transcription: TranscriptionProvenance | None = None
    artifacts: ArtifactProvenance | None = None
    agentic: AgenticProvenance | None = None
    guards: GuardsProvenance | None = None
    mcp: McpProvenance | None = None
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

    def __post_init__(self) -> None:
        if self.status == "tracked" and (
            self.provenance is None or self.marker is not None
        ):
            raise ValueError("Tracked attempt provenance requires a provenance value.")
        if self.status == "corrupt" and (
            self.marker is None or self.provenance is not None
        ):
            raise ValueError("Corrupt attempt provenance requires a marker value.")
        if self.status == "not_tracked" and (
            self.provenance is not None or self.marker is not None
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

    def to_export_payload(self) -> dict[str, Any] | None:
        if self.status == "tracked" and self.provenance is not None:
            return self.provenance.to_payload()
        if self.status == "corrupt" and self.marker is not None:
            return self.marker.to_payload()
        return None


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
            _normalize_attempt_provenance_v1(raw_payload)
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


def _normalize_attempt_provenance_v1(raw: dict[str, Any]) -> FlowAttemptProvenance:
    llm_raw = raw.get("llm")
    llm: LlmProvenance | None = None
    if isinstance(llm_raw, dict):
        llm_payload: JsonObject = dict(cast(JsonObject, llm_raw))
        effective_prompt = llm_payload.get("effective_prompt")
        if isinstance(effective_prompt, str):
            llm_payload["effective_prompt"] = normalize_text_preview(effective_prompt)
        tool_calls = llm_payload.get("tool_calls")
        if tool_calls is not None:
            llm_payload["tool_calls"] = normalize_json_preview(tool_calls)
        raw_completion_text = llm_payload.get("raw_completion_text")
        if isinstance(raw_completion_text, str):
            llm_payload["raw_completion_text"] = normalize_text_preview(
                raw_completion_text
            )
        model_parameters = llm_payload.get("model_parameters")
        if isinstance(model_parameters, dict):
            llm_payload["model_parameters"] = normalize_model_parameters_payload(
                cast(JsonObject, model_parameters)
            )
        llm = LlmProvenance.model_validate(llm_payload)

    return FlowAttemptProvenance(
        schema_version=FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
        llm=llm,
        rag=_normalize_rag_provenance(raw.get("rag")),
        http=_validate_extra_model(HttpProvenance, raw.get("http")),
        template=_validate_extra_model(TemplateProvenance, raw.get("template")),
        runtime_input=_validate_extra_model(
            RuntimeInputProvenance, raw.get("runtime_input")
        ),
        transcription=_validate_extra_model(
            TranscriptionProvenance, raw.get("transcription")
        ),
        artifacts=_validate_extra_model(ArtifactProvenance, raw.get("artifacts")),
        agentic=_validate_extra_model(AgenticProvenance, raw.get("agentic")),
        guards=_validate_extra_model(GuardsProvenance, raw.get("guards")),
        mcp=_validate_extra_model(McpProvenance, raw.get("mcp")),
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
    payload: JsonObject = dict(cast(JsonObject, value))
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
            normalized_reference: JsonObject = dict(cast(JsonObject, reference))
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
    payload: JsonObject = dict(cast(JsonObject, value))

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
            normalized_group: JsonObject = dict(cast(JsonObject, group))
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


def normalize_model_parameters_payload(
    model_parameters: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(model_parameters)
    semantics = payload.get("parameter_semantics")
    payload["parameter_semantics"] = _normalize_parameter_semantics(
        payload,
        cast(JsonObject, semantics) if isinstance(semantics, dict) else None,
    )
    for key in ("temperature", "top_p", "reasoning_effort", "verbosity"):
        payload.setdefault(key, None)
    return payload


def _normalize_rag_tracking(value: Any) -> dict[str, Any]:
    defaults = default_rag_tracking()
    if not isinstance(value, dict):
        return defaults

    normalized = dict(defaults)
    value_dict = cast(JsonObject, value)
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


def _normalize_usage_state(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
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
    matched_chunk_count = _coerce_non_negative_int(reference.get("matched_chunk_count"))
    if matched_chunk_count is None:
        matched_chunk_count = _count_displayable_reference_chunks(
            reference.get("chunks")
        )

    reference["matched_chunk_count"] = matched_chunk_count


def _count_displayable_reference_chunks(value: Any) -> int:
    if not isinstance(value, list):
        return 0
    count = 0
    for chunk in cast(list[object], value):
        if not isinstance(chunk, Mapping):
            continue
        chunk_mapping = cast(Mapping[str, object], chunk)
        snippet = chunk_mapping.get("snippet")
        if isinstance(snippet, str) and snippet.strip():
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


def _normalize_parameter_semantics(
    model_parameters: dict[str, Any],
    semantics: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    semantics_dict = semantics or {}
    for key in ("temperature", "top_p", "reasoning_effort", "verbosity"):
        existing = semantics_dict.get(key)
        if isinstance(existing, dict):
            existing_dict = cast(JsonObject, existing)
            existing_mode = existing_dict.get("mode")
        else:
            existing_mode = None
        if isinstance(existing_mode, str):
            mode = existing_mode
        else:
            mode = (
                "configured"
                if model_parameters.get(key) is not None
                else "model_default"
            )
        normalized[key] = {"mode": mode}
    return normalized
