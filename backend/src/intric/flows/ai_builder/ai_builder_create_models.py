from __future__ import annotations

from typing import cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from intric.flows.ai_builder.ai_builder_flow_schema_values import BuilderFormFieldType
from intric.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
)
from intric.flows.ai_builder.ai_builder_new_step_models import (
    StructuredFieldDraft as _StructuredFieldDraft,
)
from intric.flows.flow_authoring_name import normalize_flow_name


class CreateFormFieldDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variable_name: str
    label: str
    field_type: BuilderFormFieldType
    required: bool = False
    options: list[str] = Field(default_factory=list)

    @field_validator("variable_name", "label")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Form fields require non-empty text values.")
        return normalized

    @field_validator("options")
    @classmethod
    def _normalize_options(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for option in value:
            candidate = option.strip()
            if not candidate or candidate in seen:
                continue
            normalized.append(candidate)
            seen.add(candidate)
        return normalized


class FlowCreateDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flow_name: str
    flow_description: str | None = None
    plan_rationale: str
    assumptions: list[str] = Field(default_factory=list)
    form_fields: list[CreateFormFieldDraft] = Field(
        default_factory=lambda: cast(list[CreateFormFieldDraft], [])
    )
    steps: list[NewStepDraft]
    document_body_writer_step_indexes: tuple[int, ...] = Field(
        default_factory=tuple,
        exclude=True,
    )

    @field_validator("plan_rationale")
    @classmethod
    def _normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Flow draft fields must not be empty.")
        if "{{" in normalized or "}}" in normalized:
            raise ValueError(
                "plan_rationale must not contain template variables. "
                "Describe the design in plain prose; the backend compiler "
                "synthesises any {{ step_n.output }} / underlag templates."
            )
        return normalized

    @field_validator("flow_name")
    @classmethod
    def _normalize_flow_name(cls, value: str) -> str:
        return normalize_flow_name(value)

    @field_validator("flow_description")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if normalized and ("{{" in normalized or "}}" in normalized):
            raise ValueError("flow_description must not contain template variables.")
        return normalized or None

    @field_validator("assumptions")
    @classmethod
    def _normalize_assumptions(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in values:
            candidate = raw.strip()
            if not candidate or candidate in seen:
                continue
            normalized.append(candidate)
            seen.add(candidate)
        return normalized


CreateStepDraft = NewStepDraft
StructuredFieldDraft = _StructuredFieldDraft
