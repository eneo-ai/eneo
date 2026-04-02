"""Edit-mode domain models for the AI Builder.

Defines the edit IR (Intermediate Representation) that separates what the LLM
describes (operations on an existing flow) from what the backend compiles
(a concrete preview + diff for user approval).

Key principle: The LLM describes the *intended change*. The backend determines
the *preserved state*, compiles the *concrete preview*, produces the *diff*,
and executes the *result*.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from intric.flows.ai_builder.ai_builder_flow_name import normalize_optional_flow_name
from intric.flows.ai_builder.ai_builder_new_step_models import NewStepDraft
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
)


# ---------------------------------------------------------------------------
# Step operations
# ---------------------------------------------------------------------------


class StepPlacement(BaseModel):
    """Where to insert a new step relative to existing steps."""

    position: Literal["before", "after", "append"]
    anchor_ref: str | None = None  # Required for before/after


class StepPatch(BaseModel):
    """Partial update for existing steps. Only include fields being changed."""

    name: str | None = None
    assistant_spec: AssistantSpec | None = None
    input_source: InputSource | None = None
    input_type: InputType | None = None
    output_mode: OutputMode | None = None
    output_type: OutputType | None = None
    mcp_policy: MCPPolicy | None = None
    input_bindings: dict[str, Any] | None = None
    input_contract: dict[str, Any] | None = None
    output_contract: dict[str, Any] | None = None
    input_config: dict[str, Any] | None = None
    output_config: dict[str, Any] | None = None


class StepEditOperation(BaseModel):
    """A single edit operation on a step."""

    op: Literal["add", "modify", "remove"]
    target_ref: str | None = None  # Required for modify/remove
    placement: StepPlacement | None = None  # Required for add
    add_payload: NewStepDraft | None = None  # For add ops only
    patch: StepPatch | None = None  # For modify ops only


# ---------------------------------------------------------------------------
# Form field operations
# ---------------------------------------------------------------------------


class FormFieldSpec(BaseModel):
    """Spec for a form field (add or modify)."""

    label: str | None = None
    field_type: str | None = None
    required: bool | None = None
    description: str | None = None
    options: list[str] | None = None


class FormFieldOperation(BaseModel):
    """Operation on a form field."""

    op: Literal["add", "modify", "remove"]
    field_name: str
    field_payload: FormFieldSpec | None = None  # For add/modify


# ---------------------------------------------------------------------------
# Typed metadata patches (NOT generic key paths)
# ---------------------------------------------------------------------------


class TranscriptionPatch(BaseModel):
    enabled: bool | None = None
    model_id: str | None = None
    language: str | None = None


class RuntimeInputPatch(BaseModel):
    enabled: bool | None = None
    required: bool | None = None
    max_files: int | None = None
    input_format: str | None = None


class FlowMetadataPatch(BaseModel):
    transcription: TranscriptionPatch | None = None
    runtime_input: RuntimeInputPatch | None = None


# ---------------------------------------------------------------------------
# Edit draft — the LLM's output
# ---------------------------------------------------------------------------


class FlowEditDraft(BaseModel):
    """Edit-mode planner output. Compiled by backend into concrete preview."""

    flow_name: str | None = None
    flow_description: str | None = None
    operations: list[StepEditOperation]
    form_operations: list[FormFieldOperation] = Field(default_factory=list)
    metadata_patch: FlowMetadataPatch | None = None
    assumptions: list[str] = Field(default_factory=list)
    plan_rationale: str = ""

    @field_validator("flow_name")
    @classmethod
    def _normalize_flow_name(cls, value: str | None) -> str | None:
        return normalize_optional_flow_name(value)

    @field_validator("flow_description")
    @classmethod
    def _normalize_optional_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("plan_rationale")
    @classmethod
    def _normalize_plan_rationale(cls, value: str) -> str:
        return value.strip()


# ---------------------------------------------------------------------------
# Diff models — what the user sees
# ---------------------------------------------------------------------------


class StepChange(BaseModel):
    """One entry in the step diff."""

    kind: Literal["added", "modified", "removed", "unchanged"]
    step_name: str
    step_ref: str | None = None
    details: str | None = None  # e.g., "input_source: flow_input → previous_step"


class FormFieldChange(BaseModel):
    kind: Literal["added", "modified", "removed"]
    field_name: str
    details: str | None = None


class MetadataChange(BaseModel):
    kind: Literal["added", "modified", "removed"]
    path: str
    old_value: Any = None
    new_value: Any = None


class FlowEditDiff(BaseModel):
    """Complete diff between original flow and proposed changes."""

    step_changes: list[StepChange]
    form_changes: list[FormFieldChange] = Field(default_factory=list)
    metadata_changes: list[MetadataChange] = Field(default_factory=list)
    flow_property_changes: dict[str, tuple[Any, Any]] = Field(default_factory=dict)
    net_steps_added: int = 0
    net_steps_removed: int = 0


# ---------------------------------------------------------------------------
# Compiled result — what the user approves
# ---------------------------------------------------------------------------

EditConfidence = Literal["ready", "needs_review", "low_confidence"]


class EditAdvisory(BaseModel):
    """Structured advisory for the user about an edit result."""

    code: str
    message: str
    severity: Literal["info", "warning", "error"]
    field: str | None = None


class CompiledEditResult(BaseModel):
    """Backend-compiled concrete result. This is what the user approves."""

    compiled_spec: FlowDraftSpecCore
    diff: FlowEditDiff
    original_draft: FlowEditDraft
    base_flow_revision: int  # Stale-plan protection
    warnings: list[str] = Field(default_factory=list)
    advisories: list[EditAdvisory] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)  # "type_downgrade", etc.
    confidence: EditConfidence = "ready"


AddStepPayload = NewStepDraft
