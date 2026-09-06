from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from eneo.flows.ai_builder.ai_builder_flow_schema_values import (
    FlowInputFieldProvenance,
)
from eneo.json_types import JsonValue

StepChangeField = Literal[
    "name",
    "input_source",
    "input_type",
    "output_mode",
    "output_type",
    "instructions",
    "model_ref",
    "knowledge_refs",
]


class StepFieldChange(BaseModel):
    """One field of a modified step, before and after, as the user reads it."""

    field: StepChangeField
    previous: str | None = None
    current: str | None = None


def _default_step_field_changes() -> list[StepFieldChange]:
    return []


class StepChange(BaseModel):
    kind: Literal["added", "modified", "removed", "unchanged"]
    step_name: str
    step_ref: str | None = None
    field_changes: list[StepFieldChange] = Field(
        default_factory=_default_step_field_changes
    )


class FormFieldChange(BaseModel):
    kind: Literal["added", "modified", "removed"]
    field_name: str
    details: str | None = None


class MetadataChange(BaseModel):
    kind: Literal["added", "modified", "removed"]
    path: str
    old_value: JsonValue = None
    new_value: JsonValue = None


def _default_form_changes() -> list[FormFieldChange]:
    return []


def _default_metadata_changes() -> list[MetadataChange]:
    return []


class FlowEditDiff(BaseModel):
    step_changes: list[StepChange]
    form_changes: list[FormFieldChange] = Field(default_factory=_default_form_changes)
    metadata_changes: list[MetadataChange] = Field(
        default_factory=_default_metadata_changes
    )
    flow_property_changes: dict[str, tuple[JsonValue, JsonValue]] = Field(
        default_factory=dict
    )
    net_steps_added: int = 0
    net_steps_removed: int = 0


EditConfidence = Literal["ready", "needs_review", "low_confidence"]


class EditAdvisory(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning", "error"]
    field: str | None = None
    field_provenance: FlowInputFieldProvenance | None = None


__all__ = [
    "EditAdvisory",
    "EditConfidence",
    "FlowEditDiff",
    "FormFieldChange",
    "MetadataChange",
    "StepChange",
    "StepChangeField",
    "StepFieldChange",
]
