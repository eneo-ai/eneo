"""Portable Flow authoring graph shared by planners, packages, and importers."""

from __future__ import annotations

import hashlib
import json
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator

from intric.flows.domain.flow import FlowPersistedJsonObject
from intric.flows.enums import (
    AIBuilderInputSource as InputSource,
)
from intric.flows.enums import (
    AIBuilderInputType as InputType,
)
from intric.flows.enums import (
    AIBuilderOutputMode as OutputMode,
)
from intric.flows.enums import (
    FlowMcpPolicy as MCPPolicy,
)
from intric.flows.enums import FlowOutputMode
from intric.flows.enums import (
    FlowOutputType as OutputType,
)
from intric.flows.flow_capability_manifest import requires_completion_model
from intric.flows.flow_resource_bindings import is_uuid_shaped_resource_ref
from intric.flows.flow_review_policy import FlowStepReviewPolicy


class AssistantSpecLocalRefNotPortableError(ValueError):
    def __init__(self, resource_ref: str) -> None:
        self.resource_ref = resource_ref
        super().__init__("Assistant resource refs must use portable slot refs.")


class AssistantSpec(BaseModel):
    instructions: str
    model_ref: str | None = None
    knowledge_refs: list[str] = Field(default_factory=list)
    mcp_server_refs: list[str] = Field(default_factory=list)
    mcp_tool_refs: list[str] = Field(default_factory=list)

    @field_validator("model_ref")
    @classmethod
    def normalize_model_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if is_uuid_shaped_resource_ref(normalized):
            raise AssistantSpecLocalRefNotPortableError(normalized)
        return normalized or None

    @field_validator("knowledge_refs", "mcp_server_refs", "mcp_tool_refs")
    @classmethod
    def normalize_resource_refs(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in values:
            candidate = str(raw).strip()
            if not candidate or candidate in seen:
                continue
            if is_uuid_shaped_resource_ref(candidate):
                raise AssistantSpecLocalRefNotPortableError(candidate)
            normalized.append(candidate)
            seen.add(candidate)
        return normalized

    @model_validator(mode="after")
    def validate_knowledge_mcp_exclusivity(self) -> "AssistantSpec":
        if self.knowledge_refs and (self.mcp_server_refs or self.mcp_tool_refs):
            raise ValueError(
                "A step assistant cannot use knowledge_refs and MCP refs at the same time."
            )
        return self


class StepSpec(BaseModel):
    plan_step_ref: str = Field(
        description="Stable reference like 'step_a', 'step_b'. Used for variable bindings."
    )
    existing_step_ref: str | None = Field(
        default=None,
        description="Server-provided alias for an existing step (not raw UUID). Set when modifying.",
    )
    name: str = Field(description="User-visible step name (user_description).")
    assistant_spec: AssistantSpec
    mcp_policy: MCPPolicy = MCPPolicy.INHERIT
    input_source: InputSource
    input_type: InputType = InputType.TEXT
    output_mode: OutputMode = OutputMode.PASS_THROUGH
    output_type: OutputType = OutputType.TEXT
    input_bindings: FlowPersistedJsonObject | None = None
    input_contract: FlowPersistedJsonObject | None = None
    output_contract: FlowPersistedJsonObject | None = None
    input_config: FlowPersistedJsonObject | None = None
    output_config: FlowPersistedJsonObject | None = None
    review_policy: FlowStepReviewPolicy | None = None

    @model_validator(mode="after")
    def normalize_completion_model_applicability(self) -> "StepSpec":
        return strip_inapplicable_completion_model(self)

    @field_validator("input_bindings")
    @classmethod
    def normalize_input_bindings(
        cls, value: FlowPersistedJsonObject | None
    ) -> FlowPersistedJsonObject | None:
        if value is None:
            return None
        question = value.get("question")
        if isinstance(question, str):
            return {
                **value,
                "question": question.strip(),
            }
        return value


def strip_inapplicable_completion_model(step: StepSpec) -> StepSpec:
    if requires_completion_model(FlowOutputMode(step.output_mode.value)):
        return step
    if step.assistant_spec.model_ref is None:
        return step
    step.assistant_spec = step.assistant_spec.model_copy(update={"model_ref": None})
    return step


def completion_model_ref_was_stripped(
    *,
    supplied_model_ref: str | None,
    validated_step: StepSpec,
) -> bool:
    return (
        supplied_model_ref is not None
        and validated_step.assistant_spec.model_ref is None
        and not requires_completion_model(
            FlowOutputMode(validated_step.output_mode.value)
        )
    )


def completion_model_ref_strip_log_extra(
    *,
    supplied_model_ref: str | None,
    validated_step: StepSpec,
    source: str,
) -> dict[str, str | None] | None:
    if not completion_model_ref_was_stripped(
        supplied_model_ref=supplied_model_ref,
        validated_step=validated_step,
    ):
        return None
    return {
        "plan_step_ref": validated_step.plan_step_ref,
        "existing_step_ref": validated_step.existing_step_ref,
        "source": source,
        "output_mode": validated_step.output_mode.value,
    }


_VALID_FORM_FIELD_TYPES = {"text", "number", "date", "select", "multiselect"}

_FORM_FIELD_TYPE_COERCIONS: dict[str, str] = {
    "textarea": "text",
    "string": "text",
    "email": "text",
    "url": "text",
    "phone": "text",
    "tel": "text",
    "password": "text",
    "integer": "number",
    "float": "number",
    "decimal": "number",
    "dropdown": "select",
    "radio": "select",
    "enum": "select",
    "checkbox": "multiselect",
    "checkboxes": "multiselect",
    "multi_select": "multiselect",
    "multi-select": "multiselect",
    "tags": "multiselect",
    "datetime": "date",
    "time": "date",
}


class FormFieldSpec(BaseModel):
    name: str
    type: str
    label: str
    required: bool = False
    options: list[str] | None = None

    @field_validator("type")
    @classmethod
    def coerce_field_type(cls, v: str) -> str:
        normalized = v.strip().casefold()
        if normalized in _VALID_FORM_FIELD_TYPES:
            return normalized
        coerced = _FORM_FIELD_TYPE_COERCIONS.get(normalized)
        if coerced is not None:
            return coerced
        return "text"


class FlowDraftSpecCore(BaseModel):
    flow_name: str
    flow_description: str = ""
    steps: list[StepSpec]
    form_fields: list[FormFieldSpec] | None = None
    document_body_writer_step_refs: tuple[str, ...] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def normalize_document_body_writer_step_refs(self) -> Self:
        refs = self.document_body_writer_step_refs
        if refs is None:
            return self

        valid_refs = {step.plan_step_ref for step in self.steps}
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_ref in refs:
            ref = raw_ref.strip()
            if not ref or ref in seen or ref not in valid_refs:
                continue
            normalized.append(ref)
            seen.add(ref)

        self.document_body_writer_step_refs = tuple(normalized) or None
        return self

    def spec_hash(self) -> str:
        payload = self.model_dump(
            mode="json",
            exclude={"document_body_writer_step_refs"},
        )
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


__all__ = [
    "AssistantSpec",
    "AssistantSpecLocalRefNotPortableError",
    "FlowDraftSpecCore",
    "FormFieldSpec",
    "InputSource",
    "InputType",
    "MCPPolicy",
    "OutputMode",
    "OutputType",
    "StepSpec",
    "completion_model_ref_strip_log_extra",
    "completion_model_ref_was_stripped",
    "strip_inapplicable_completion_model",
]
