from __future__ import annotations

from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from intric.flows.ai_builder.ai_builder_domain_models import AssistantSpec
from intric.flows.ai_builder.ai_builder_models import InputSource, InputType, OutputType
from intric.flows.flow_review_policy import FlowStepReviewMode

DocumentDeliveryMode = Literal["not_applicable", "generated", "template_fill"]
StructuredFieldType = Literal["string", "number", "boolean", "object", "array"]

MAX_STRUCTURED_FIELD_DEPTH = 3


class PreviousFieldRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_step: int
    field_path: str
    label: str | None = None

    @field_validator("from_step")
    @classmethod
    def _validate_from_step(cls, value: int) -> int:
        if value < 1:
            raise ValueError("uses_previous_fields.from_step must be at least 1.")
        return value

    @field_validator("field_path")
    @classmethod
    def _normalize_field_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("uses_previous_fields.field_path must not be empty.")
        if any(not segment.strip() for segment in normalized.split(".")):
            raise ValueError(
                "uses_previous_fields.field_path must not contain empty path segments."
            )
        return normalized

    @field_validator("label")
    @classmethod
    def _normalize_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PreviousOutputRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_step: int
    label: str | None = None

    @field_validator("from_step")
    @classmethod
    def _validate_from_step(cls, value: int) -> int:
        if value < 1:
            raise ValueError("uses_previous_outputs.from_step must be at least 1.")
        return value

    @field_validator("label")
    @classmethod
    def _normalize_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class StructuredFieldDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    field_type: StructuredFieldType
    description: str
    required: bool = True
    fields: list["StructuredFieldDraft"] | None = None
    item_fields: list["StructuredFieldDraft"] | None = None

    @field_validator("name", "description")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Structured fields require non-empty text values.")
        return normalized

    @model_validator(mode="after")
    def _validate_shape(self) -> "StructuredFieldDraft":
        if self.field_type == "object" and not self.fields:
            raise ValueError("Object fields must declare nested fields.")
        if self.field_type != "object" and self.fields is not None:
            raise ValueError("Only object fields may declare nested fields.")
        if self.field_type == "array" and self.fields is not None:
            raise ValueError("Array fields must use item_fields, not fields.")
        if self.field_type != "array" and self.item_fields is not None:
            raise ValueError("Only array fields may declare item_fields.")
        return self


class NewStepDraft(BaseModel):
    """Shared authoring contract for a brand-new step."""

    model_config = ConfigDict(extra="forbid")

    name: str
    instructions: str | None = None
    assistant_spec: AssistantSpec | None = None
    input_source: InputSource
    input_type: InputType = InputType.TEXT
    output_type: OutputType = OutputType.TEXT
    model_ref: str | None = None
    knowledge_refs: list[str] = Field(default_factory=list)
    mcp_server_refs: list[str] = Field(default_factory=list)
    mcp_tool_refs: list[str] = Field(default_factory=list)
    runtime_upload: bool = False
    runtime_required: bool = False
    runtime_max_files: int | None = None
    uses_form_fields: list[str] = Field(default_factory=list)
    uses_previous_fields: list[PreviousFieldRef] = Field(
        default_factory=lambda: cast(list[PreviousFieldRef], [])
    )
    uses_previous_outputs: list[PreviousOutputRef] = Field(
        default_factory=lambda: cast(list[PreviousOutputRef], [])
    )
    document_delivery_mode: DocumentDeliveryMode = "not_applicable"
    citations_requested: bool = False
    review_mode: FlowStepReviewMode | None = None
    output_fields: list[StructuredFieldDraft] | None = None

    @field_validator("name", "instructions")
    @classmethod
    def _normalize_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Steps require non-empty text values.")
        return normalized

    @field_validator("instructions")
    @classmethod
    def _reject_template_tokens(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if "{{" in value or "}}" in value:
            raise ValueError("Step instructions must not contain template variables.")
        return value

    @field_validator("model_ref")
    @classmethod
    def _normalize_model_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator(
        "knowledge_refs",
        "mcp_server_refs",
        "mcp_tool_refs",
        "uses_form_fields",
        mode="before",
    )
    @classmethod
    def _coerce_missing_string_lists(cls, values: object) -> object:
        if values is None:
            return []
        return values

    @field_validator(
        "knowledge_refs", "mcp_server_refs", "mcp_tool_refs", "uses_form_fields"
    )
    @classmethod
    def _normalize_string_lists(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in values:
            candidate = raw.strip()
            if not candidate or candidate in seen:
                continue
            normalized.append(candidate)
            seen.add(candidate)
        return normalized

    @field_validator("runtime_max_files")
    @classmethod
    def _validate_max_files(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("runtime_max_files must be at least 1 when provided.")
        return value

    @model_validator(mode="after")
    def _validate_structured_depth(self) -> "NewStepDraft":
        if self.instructions is None and self.assistant_spec is not None:
            self.instructions = self.assistant_spec.instructions
        if self.instructions is None:
            raise ValueError("Steps require non-empty text values.")
        if self.assistant_spec is not None:
            if self.model_ref is None:
                self.model_ref = self.assistant_spec.model_ref
            if not self.knowledge_refs:
                self.knowledge_refs = list(self.assistant_spec.knowledge_refs)
            if not self.mcp_server_refs:
                self.mcp_server_refs = list(self.assistant_spec.mcp_server_refs)
            if not self.mcp_tool_refs:
                self.mcp_tool_refs = list(self.assistant_spec.mcp_tool_refs)
        if self.knowledge_refs and (self.mcp_server_refs or self.mcp_tool_refs):
            raise ValueError(
                "A step cannot use knowledge_refs and MCP refs at the same time."
            )
        if self.output_fields:
            _ensure_field_depth(self.output_fields)
        return self


def _ensure_field_depth(
    fields: list[StructuredFieldDraft],
    *,
    depth: int = 1,
) -> None:
    if depth > MAX_STRUCTURED_FIELD_DEPTH:
        raise ValueError(
            f"Structured field nesting depth cannot exceed {MAX_STRUCTURED_FIELD_DEPTH}."
        )
    for field in fields:
        if field.fields:
            _ensure_field_depth(field.fields, depth=depth + 1)
        if field.item_fields:
            _ensure_field_depth(field.item_fields, depth=depth + 1)
