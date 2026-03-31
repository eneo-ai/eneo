from __future__ import annotations

import hashlib
import json
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict

TEXT_PREVIEW_MAX_BYTES = 16 * 1024
JSON_PREVIEW_MAX_BYTES = 16 * 1024
ModelT = TypeVar("ModelT", bound=BaseModel)


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

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


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
        llm = LlmProvenance.model_validate(llm_payload)

    return FlowAttemptProvenance(
        llm=llm,
        rag=_validate_extra_model(RagProvenance, raw.get("rag")),
        http=_validate_extra_model(HttpProvenance, raw.get("http")),
        template=_validate_extra_model(TemplateProvenance, raw.get("template")),
        runtime_input=_validate_extra_model(RuntimeInputProvenance, raw.get("runtime_input")),
        transcription=_validate_extra_model(TranscriptionProvenance, raw.get("transcription")),
        artifacts=_validate_extra_model(ArtifactProvenance, raw.get("artifacts")),
        agentic=_validate_extra_model(AgenticProvenance, raw.get("agentic")),
        guards=_validate_extra_model(GuardsProvenance, raw.get("guards")),
        mcp=_validate_extra_model(McpProvenance, raw.get("mcp")),
    )


def _validate_extra_model(model: type[ModelT], value: Any) -> ModelT | None:
    if not isinstance(value, dict):
        return None
    return model.model_validate(value)


def _truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes]
    return truncated.decode("utf-8", errors="ignore")
