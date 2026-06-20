from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from intric.json_types import JsonValue


class StepChange(BaseModel):
    kind: Literal["added", "modified", "removed", "unchanged"]
    step_name: str
    step_ref: str | None = None
    details: str | None = None


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


__all__ = [
    "EditAdvisory",
    "EditConfidence",
    "FlowEditDiff",
    "FormFieldChange",
    "MetadataChange",
    "StepChange",
]
