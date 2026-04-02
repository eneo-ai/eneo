from __future__ import annotations

import hashlib
import json
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict
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


def normalize_text_preview(text: str, *, max_bytes: int = TEXT_PREVIEW_MAX_BYTES) -> PayloadPreview:
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


def normalize_json_preview(value: Any, *, max_bytes: int = JSON_PREVIEW_MAX_BYTES) -> PayloadPreview:
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


def normalize_attempt_provenance(raw: dict[str, Any] | None) -> FlowAttemptProvenance | None:
    if not isinstance(raw, dict):
        return None

    llm_raw = raw.get("llm")
    llm: LlmProvenance | None = None
    if isinstance(llm_raw, dict):
        llm_payload = dict(llm_raw)
        effective_prompt = llm_payload.get("effective_prompt")
        if isinstance(effective_prompt, str):
            llm_payload["effective_prompt"] = normalize_text_preview(effective_prompt)
        tool_calls = llm_payload.get("tool_calls")
        if tool_calls is not None:
            llm_payload["tool_calls"] = normalize_json_preview(tool_calls)
        raw_completion_text = llm_payload.get("raw_completion_text")
        if isinstance(raw_completion_text, str):
            llm_payload["raw_completion_text"] = normalize_text_preview(raw_completion_text)
        model_parameters = llm_payload.get("model_parameters")
        if isinstance(model_parameters, dict):
            llm_payload["model_parameters"] = normalize_model_parameters_payload(
                model_parameters
            )
        llm = LlmProvenance.model_validate(llm_payload)

    return FlowAttemptProvenance(
        llm=llm,
        rag=_normalize_rag_provenance(raw.get("rag")),
        http=_validate_extra_model(HttpProvenance, raw.get("http")),
        template=_validate_extra_model(TemplateProvenance, raw.get("template")),
        runtime_input=_validate_extra_model(RuntimeInputProvenance, raw.get("runtime_input")),
        transcription=_validate_extra_model(TranscriptionProvenance, raw.get("transcription")),
        artifacts=_validate_extra_model(ArtifactProvenance, raw.get("artifacts")),
        agentic=_validate_extra_model(AgenticProvenance, raw.get("agentic")),
        guards=_validate_extra_model(GuardsProvenance, raw.get("guards")),
        mcp=_validate_extra_model(McpProvenance, raw.get("mcp")),
        citations=_validate_extra_model(CitationsProvenance, raw.get("citations")),
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
    payload = dict(value)
    payload["tracking"] = _normalize_rag_tracking(payload.get("tracking"))
    prompt_context = _normalize_rag_prompt_context(payload.get("prompt_context"))
    if prompt_context is not None:
        payload["prompt_context"] = prompt_context
    included_source_ids = set()
    if isinstance(prompt_context, dict):
        included_source_ids = {
            source_id
            for source_id in prompt_context.get("included_source_ids", [])
            if isinstance(source_id, str) and source_id.strip()
        }
    references = payload.get("references")
    if isinstance(references, list):
        normalized_references: list[dict[str, Any]] = []
        source_names: list[str] = []
        source_display_names: list[str] = []
        for reference in references:
            if not isinstance(reference, dict):
                continue
            normalized_reference = dict(reference)
            normalized_reference["usage_state"] = _normalize_usage_state(
                reference.get("usage_state")
            )
            _normalize_reference_display_fields(normalized_reference)
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
    payload = dict(value)

    included_source_ids = [
        str(source_id).strip()
        for source_id in payload.get("included_source_ids", [])
        if str(source_id).strip()
    ]
    not_included_source_ids = [
        str(source_id).strip()
        for source_id in payload.get("not_included_source_ids", [])
        if str(source_id).strip()
    ]

    normalized_groups: list[dict[str, Any]] = []
    derived_titles: list[str] = []
    raw_groups = payload.get("included_groups")
    if isinstance(raw_groups, list):
        for group in raw_groups:
            if not isinstance(group, dict):
                continue
            normalized_group = dict(group)
            source_id = group.get("source_id")
            if source_id is not None:
                normalized_group["source_id"] = str(source_id)
            source_title = group.get("source_title")
            if isinstance(source_title, str) and source_title.strip():
                stripped_title = source_title.strip()
                normalized_group["source_title"] = stripped_title
                derived_titles.append(stripped_title)
            normalized_groups.append(normalized_group)

    included_source_titles = list(
        dict.fromkeys(
            [
                title.strip()
                for title in payload.get("included_source_titles", [])
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
        "total_sources": payload.get("included_source_count") or len(included_source_ids),
        "total_chunks": payload.get("included_chunk_count") or sum(
            int(group.get("chunk_count", 0) or 0) for group in normalized_groups
        ),
        "truncated_by_token_budget": bool(payload.get("truncated_by_token_budget")),
    }
    return payload


def _truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes]
    return truncated.decode("utf-8", errors="ignore")


def normalize_model_parameters_payload(model_parameters: dict[str, Any]) -> dict[str, Any]:
    payload = dict(model_parameters)
    semantics = payload.get("parameter_semantics")
    payload["parameter_semantics"] = _normalize_parameter_semantics(
        payload,
        semantics if isinstance(semantics, dict) else None,
    )
    for key in ("temperature", "top_p", "reasoning_effort", "verbosity"):
        payload.setdefault(key, None)
    return payload


def _normalize_rag_tracking(value: Any) -> dict[str, Any]:
    defaults = default_rag_tracking()
    if not isinstance(value, dict):
        return defaults

    normalized = dict(defaults)
    for key in (
        "retrieval_tracked",
        "prompt_context_inclusion_tracked",
        "citation_tracked",
        "material_influence_tracked",
    ):
        if isinstance(value.get(key), bool):
            normalized[key] = value[key]
    selection_basis = value.get("selection_basis")
    if isinstance(selection_basis, str) and selection_basis.strip():
        normalized["selection_basis"] = selection_basis.strip()
    note = value.get("note")
    if isinstance(note, str) and note.strip():
        normalized["note"] = note.strip()
    return normalized


def _resolve_reference_url(reference: dict[str, Any]) -> str | None:
    for key in ("source_url", "source_title", "title"):
        raw_value = reference.get(key)
        if not isinstance(raw_value, str):
            continue
        stripped = raw_value.strip()
        if stripped.startswith(("http://", "https://")):
            return stripped
    return None


def _normalize_usage_state(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "retrieved_candidate"


def _normalize_reference_display_fields(reference: dict[str, Any]) -> None:
    raw_title = resolve_reference_title(reference)
    if raw_title is not None:
        reference.setdefault("source_title_raw", raw_title)
        reference.setdefault("source_display_name", format_source_display_name(raw_title))
    raw_container_name = reference.get("source_container_name")
    if isinstance(raw_container_name, str) and raw_container_name.strip():
        reference.setdefault("source_container_name_raw", raw_container_name.strip())
    container_display_name = format_source_container_display_name(reference)
    if container_display_name is not None:
        reference["source_container_display_name"] = container_display_name
    container_label = format_source_container_label(reference)
    if container_label is not None:
        reference["source_container_label"] = container_label


def _normalize_parameter_semantics(
    model_parameters: dict[str, Any],
    semantics: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key in ("temperature", "top_p", "reasoning_effort", "verbosity"):
        existing = semantics.get(key) if isinstance(semantics, dict) else None
        if isinstance(existing, dict) and isinstance(existing.get("mode"), str):
            mode = existing["mode"]
        else:
            mode = "configured" if model_parameters.get(key) is not None else "model_default"
        normalized[key] = {"mode": mode}
    return normalized
