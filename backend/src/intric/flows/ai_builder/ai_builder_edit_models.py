"""Edit-mode domain models for the AI Builder.

Defines the edit IR (Intermediate Representation) that separates what the LLM
describes (operations on an existing flow) from what the backend compiles
(a concrete preview + diff for user approval).

Key principle: The LLM describes the *intended change*. The backend determines
the *preserved state*, compiles the *concrete preview*, produces the *diff*,
and executes the *result*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from intric.flows.ai_builder.ai_builder_edit_preview_models import (
    EditAdvisory,
    EditConfidence,
    FlowEditDiff,
)
from intric.flows.ai_builder.ai_builder_new_step_models import (
    DocumentDeliveryMode,
    NewStepDraft,
    PreviousFieldRef,
)
from intric.flows.flow_authoring_name import normalize_optional_flow_name
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
)
from intric.flows.flow_review_policy import FlowStepReviewMode

# ---------------------------------------------------------------------------
# Step operations
# ---------------------------------------------------------------------------


class StepPlacement(BaseModel):
    """Where to insert a new step relative to existing steps."""

    position: Literal["before", "after", "append"]
    anchor_ref: str | None = None


class StepPatch(BaseModel):
    """Partial update for existing steps. Only include fields being changed."""

    name: str | None = None
    assistant_spec: AssistantSpec | None = None
    input_source: InputSource | None = None
    input_type: InputType | None = None
    output_mode: OutputMode | None = None
    output_type: OutputType | None = None
    document_delivery_mode: DocumentDeliveryMode | None = None
    mcp_policy: MCPPolicy | None = None
    uses_form_fields: list[str] | None = None
    uses_previous_fields: list[PreviousFieldRef] | None = None
    input_bindings: dict[str, Any] | None = None
    input_contract: dict[str, Any] | None = None
    output_contract: dict[str, Any] | None = None
    input_config: dict[str, Any] | None = None
    output_config: dict[str, Any] | None = None
    review_mode: FlowStepReviewMode | None = None


class StepEditOperation(BaseModel):
    """A single edit operation on a step."""

    op: Literal["add", "modify", "remove"]
    target_ref: str | None = None
    placement: StepPlacement | None = None
    add_payload: NewStepDraft | None = None
    patch: StepPatch | None = None


@dataclass(frozen=True, slots=True)
class StepOperationShapeIssue:
    code: str
    message: str
    step_ref: str | None = None


def validate_step_operation_shape(
    op: StepEditOperation,
    *,
    label: str,
    valid_refs: list[str] | None = None,
) -> tuple[StepOperationShapeIssue, ...]:
    issues: list[StepOperationShapeIssue] = []

    if op.op == "add":
        if op.target_ref is not None:
            issues.append(
                StepOperationShapeIssue(
                    code="add_with_target_ref",
                    message=(
                        f"{label}: 'add' operations must NOT have target_ref. "
                        "To modify an existing step, use op='modify' instead."
                    ),
                )
            )
        if op.add_payload is None:
            issues.append(
                StepOperationShapeIssue(
                    code="add_missing_payload",
                    message=(
                        f"{label}: 'add' operations require add_payload with a "
                        "typed new-step draft."
                    ),
                )
            )
        if (
            op.placement is not None
            and op.placement.position != "append"
            and op.placement.anchor_ref is None
        ):
            issues.append(
                StepOperationShapeIssue(
                    code="placement_missing_anchor",
                    message=(
                        f"{label}: placement position '{op.placement.position}' "
                        f"requires anchor_ref.{_valid_refs_suffix(valid_refs)}"
                    ),
                )
            )

    elif op.op == "modify":
        if op.target_ref is None:
            issues.append(
                StepOperationShapeIssue(
                    code="modify_missing_target",
                    message=(
                        f"{label}: 'modify' operations require target_ref."
                        f"{_valid_refs_suffix(valid_refs)}"
                    ),
                )
            )
        if op.patch is None:
            issues.append(
                StepOperationShapeIssue(
                    step_ref=op.target_ref,
                    code="modify_missing_patch",
                    message=(
                        f"{label}: 'modify' operations require a patch with at "
                        "least one field."
                    ),
                )
            )

    elif op.op == "remove":
        if op.target_ref is None:
            issues.append(
                StepOperationShapeIssue(
                    code="remove_missing_target",
                    message=(
                        f"{label}: 'remove' operations require target_ref."
                        f"{_valid_refs_suffix(valid_refs)}"
                    ),
                )
            )

    return tuple(issues)


def _valid_refs_suffix(valid_refs: list[str] | None) -> str:
    return f" Valid refs: {valid_refs}" if valid_refs is not None else ""


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
    field_payload: FormFieldSpec | None = None


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


def _default_form_operations() -> list["FormFieldOperation"]:
    return []


def _default_edit_warnings() -> list[str]:
    return []


def _default_edit_advisories() -> list["EditAdvisory"]:
    return []


class FlowEditDraft(BaseModel):
    """Edit-mode planner output. Compiled by backend into concrete preview."""

    flow_name: str | None = None
    flow_description: str | None = None
    operations: list[StepEditOperation]
    form_operations: list[FormFieldOperation] = Field(
        default_factory=_default_form_operations
    )
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
# Compiled result — what the user approves
# ---------------------------------------------------------------------------


class CompiledEditResult(BaseModel):
    """Backend-compiled concrete result. This is what the user approves."""

    compiled_spec: FlowDraftSpecCore
    diff: FlowEditDiff
    original_draft: FlowEditDraft
    base_flow_revision: int  # Stale-plan protection
    warnings: list[str] = Field(default_factory=_default_edit_warnings)
    advisories: list[EditAdvisory] = Field(default_factory=_default_edit_advisories)
    risk_flags: list[str] = Field(default_factory=list)  # "type_downgrade", etc.
    confidence: EditConfidence = "ready"


class BuilderPlanEditResult(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)

    compiled_edit: CompiledEditResult | None = None
    description_override_manual: bool = False

    @field_validator("description_override_manual", mode="before")
    @classmethod
    def _validate_description_override_manual(cls, value: object) -> bool:
        if not isinstance(value, bool):
            raise ValueError("description_override_manual must be a boolean")
        return value


AddStepPayload = NewStepDraft
