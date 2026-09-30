"""Portable Flow authoring graph shared by planners, packages, and importers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Self, cast

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from eneo.flows.domain.flow import (
    FlowPersistedJsonObject,
    parse_flow_step_retrieval_policy,
)
from eneo.flows.enums import (
    FlowAuthoringInputSource as InputSource,
)
from eneo.flows.enums import (
    FlowAuthoringInputType as InputType,
)
from eneo.flows.enums import (
    FlowAuthoringOutputMode as OutputMode,
)
from eneo.flows.enums import FlowOutputMode
from eneo.flows.enums import (
    FlowOutputType as OutputType,
)
from eneo.flows.flow_capability_manifest import requires_completion_model
from eneo.flows.flow_metadata import (
    parse_flow_form_field_type,
    parse_saved_form_field_type,
)
from eneo.flows.flow_resource_bindings import is_uuid_shaped_resource_ref
from eneo.flows.flow_review_policy import FlowStepReviewPolicy
from eneo.flows.input_binding_contract_rules import validate_source_refs_binding

# Safety guard against runaway tool output and oversized requests. This should
# not be a practical product cap for legitimate advanced flows.
MAX_FLOW_AUTHORING_STEPS = 256
# The most bytes one step of an authoring request may take on the wire: its
# settings, contracts and templates plus the prompt of its assistant. An
# allowance sized to hold a long prompt with room to spare, not a measurement.
MAX_FLOW_AUTHORING_STEP_BYTES = 64 * 1024
# The most a request that carries a flow's steps may take:
# 256 steps x 64 KiB = 16 MiB.
MAX_FLOW_AUTHORING_REQUEST_BYTES = (
    MAX_FLOW_AUTHORING_STEPS * MAX_FLOW_AUTHORING_STEP_BYTES
)


class AssistantSpecLocalRefNotPortableError(ValueError):
    def __init__(self, resource_ref: str) -> None:
        self.resource_ref = resource_ref
        super().__init__("Assistant resource refs must use portable slot refs.")


class FlowMcpUnsupportedError(ValueError):
    def __init__(self) -> None:
        super().__init__("Flow MCP fields are unsupported.")


def has_flow_mcp_unsupported_error(exc: ValidationError) -> bool:
    for error in exc.errors(include_input=False):
        context = error.get("ctx")
        if isinstance(context, Mapping) and isinstance(
            context.get("error"), FlowMcpUnsupportedError
        ):
            return True
    return False


class AssistantSpec(BaseModel):
    instructions: str
    model_ref: str | None = None
    knowledge_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def reject_removed_mcp_fields(cls, value: object) -> object:
        original: object = value
        if isinstance(value, Mapping):
            raw_value = cast(Mapping[object, object], value)
            if any(
                field in raw_value for field in ("mcp_server_refs", "mcp_tool_refs")
            ):
                raise FlowMcpUnsupportedError
        return original

    @field_validator("model_ref")
    @classmethod
    def normalize_model_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if is_uuid_shaped_resource_ref(normalized):
            raise AssistantSpecLocalRefNotPortableError(normalized)
        return normalized or None

    @field_validator("knowledge_refs")
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

    @model_validator(mode="before")
    @classmethod
    def reject_removed_mcp_policy(cls, value: object) -> object:
        original: object = value
        if isinstance(value, Mapping):
            raw_value = cast(Mapping[object, object], value)
            if "mcp_policy" in raw_value:
                raise FlowMcpUnsupportedError
        return original

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
        validate_source_refs_binding(value)
        question = value.get("question")
        if isinstance(question, str):
            return {
                **value,
                "question": question.strip(),
            }
        return value

    @field_validator("output_config")
    @classmethod
    def validate_retrieval_policy(
        cls, value: FlowPersistedJsonObject | None
    ) -> FlowPersistedJsonObject | None:
        parse_flow_step_retrieval_policy(value)
        return value


def strip_inapplicable_completion_model(step: StepSpec) -> StepSpec:
    if requires_completion_model(FlowOutputMode(step.output_mode.value)):
        return step
    if step.assistant_spec.model_ref is None:
        return step
    step.assistant_spec = step.assistant_spec.model_copy(update={"model_ref": None})
    return step


class FormFieldSpec(BaseModel):
    name: str
    type: str
    label: str
    required: bool = False
    options: list[str] | None = None

    @field_validator("type")
    @classmethod
    def accept_platform_field_type(cls, v: str) -> str:
        return parse_flow_form_field_type(v).value


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


def authoring_form_field(
    field: Mapping[str, object], *, index: int
) -> FormFieldSpec | None:
    """What the authoring view models of a saved form field (index = its place
    in the saved array); a field the editor left unlabelled reads as its name,
    as the editor shows it. A saved type the platform does not accept raises the
    persisted read's error."""

    name = str(field.get("name", "")).strip()
    if not name:
        return None
    options = field.get("options")
    return FormFieldSpec(
        name=name,
        type=parse_saved_form_field_type(field, index=index).value,
        label=str(field.get("label") or name).strip() or name,
        required=bool(field.get("required", False)),
        options=(
            [str(option) for option in cast(list[object], options)]
            if isinstance(options, list)
            else None
        ),
    )


def authoring_form_field_payload(field: FormFieldSpec) -> FlowPersistedJsonObject:
    return {
        "name": field.name,
        "type": field.type,
        "label": field.label,
        "required": field.required,
        **({"options": field.options} if field.options is not None else {}),
    }


def metadata_json_from_authoring_form_fields(
    form_fields: list[FormFieldSpec] | None,
) -> FlowPersistedJsonObject | None:
    if form_fields is None:
        return None
    return {
        "form_schema": {
            "fields": [authoring_form_field_payload(field) for field in form_fields]
        }
    }


__all__ = [
    "AssistantSpec",
    "AssistantSpecLocalRefNotPortableError",
    "FlowDraftSpecCore",
    "FlowMcpUnsupportedError",
    "FormFieldSpec",
    "InputSource",
    "InputType",
    "OutputMode",
    "OutputType",
    "StepSpec",
    "authoring_form_field",
    "authoring_form_field_payload",
    "has_flow_mcp_unsupported_error",
    "metadata_json_from_authoring_form_fields",
    "strip_inapplicable_completion_model",
]
