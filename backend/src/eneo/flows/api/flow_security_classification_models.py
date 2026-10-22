from __future__ import annotations

from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eneo.flows.api.flow_models import FlowAssistantUpdateRequest, FlowStepUpdateRequest
from eneo.flows.flow_authoring_spec import MAX_FLOW_AUTHORING_STEPS
from eneo.flows.flow_security_classification import (
    ClassificationCause,
    ClassificationViolationCode,
    FlowStepClassificationExplanation,
    FlowStepClassificationViolation,
)

_STEP_ID = "00000000-0000-0000-0000-000000000101"
_SECOND_STEP_ID = "00000000-0000-0000-0000-000000000102"
_ASSISTANT_ID = "00000000-0000-0000-0000-000000000002"
_MODEL_ID = "00000000-0000-0000-0000-000000000031"

# Both steps use one assistant; the change is to the second step's own copy.
_STEP_MODEL_CANDIDATE: dict[str, Any] = {
    "assistant_id": _ASSISTANT_ID,
    "step_id": _SECOND_STEP_ID,
    "update": {"completion_model": {"id": _MODEL_ID}},
}

FLOW_SECURITY_CLASSIFICATION_PREVIEW_REQUEST_EXAMPLE: dict[str, Any] = {
    "steps": [
        {
            "id": _STEP_ID,
            "assistant_id": _ASSISTANT_ID,
            "step_order": 1,
            "user_description": "Summarize the case file",
            "input_source": "flow_input",
            "input_type": "text",
            "output_mode": "pass_through",
            "output_type": "text",
        },
        {
            "id": _SECOND_STEP_ID,
            "assistant_id": _ASSISTANT_ID,
            "step_order": 2,
            "user_description": "Draft the reply",
            "input_source": "previous_step",
            "input_type": "text",
            "output_mode": "pass_through",
            "output_type": "text",
        },
    ],
    "assistants": [_STEP_MODEL_CANDIDATE],
}

FLOW_SECURITY_CLASSIFICATION_PREVIEW_EXAMPLE: dict[str, Any] = {
    "steps": [
        {
            "step_order": 1,
            "step_id": _STEP_ID,
            "reads": [],
            "input_level": 2,
            "external_source_level": None,
            "knowledge_level": None,
            "required_model_level": 2,
            "model_level": 1,
            "qualifying_model_ids": [_MODEL_ID],
            "effective_output_level": 2,
            "output_floor": 2,
            "violation": {
                "code": ClassificationViolationCode.MODEL_BELOW_REQUIRED.value,
                "message": (
                    "Step 1: assistant model does not meet the required "
                    "security classification."
                ),
                "required_level": 2,
                "current_level": 1,
                "cause": "space",
                "source_step_orders": [],
            },
        },
        {
            "step_order": 2,
            "step_id": _SECOND_STEP_ID,
            "reads": [1],
            "input_level": 2,
            "external_source_level": None,
            "knowledge_level": None,
            "required_model_level": 2,
            "model_level": 2,
            "qualifying_model_ids": [_MODEL_ID],
            "effective_output_level": 2,
            "output_floor": 2,
            "violation": None,
        },
    ]
}


class FlowSecurityClassificationAssistantCandidate(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"example": _STEP_MODEL_CANDIDATE}
    )

    assistant_id: UUID = Field(
        description="The flow-managed assistant the unsaved change is to.",
        examples=[_ASSISTANT_ID],
    )
    step_id: UUID | None = Field(
        default=None,
        description=(
            "The step whose assistant this changes, as `step_id` of an "
            "assistant change in `PATCH /flows/{id}/editor/`. When other "
            "candidate steps share the assistant, this step is explained with "
            "its own copy of it with the change, and the other steps with the "
            "assistant as it was (after any change without `step_id`). Without "
            "`step_id` the change reaches every step that uses the assistant. "
            "The step must be a candidate step that uses `assistant_id`."
        ),
        examples=[_SECOND_STEP_ID],
    )
    update: FlowAssistantUpdateRequest


def _no_candidates() -> list[FlowSecurityClassificationAssistantCandidate]:
    return []


class FlowSecurityClassificationPreviewRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": FLOW_SECURITY_CLASSIFICATION_PREVIEW_REQUEST_EXAMPLE
        },
    )

    steps: list[FlowStepUpdateRequest] | None = Field(
        default=None,
        description=(
            "The editor's unsaved steps, in the shape a flow update accepts. Omit "
            "to evaluate the steps that are saved. More steps than a flow can have "
            "are refused with `flow_step_limit_exceeded`."
        ),
    )
    assistants: list[FlowSecurityClassificationAssistantCandidate] = Field(
        default_factory=_no_candidates,
        max_length=MAX_FLOW_AUTHORING_STEPS,
        description=(
            "Unsaved changes to the flow-managed assistants the steps use, in the "
            "shape an assistant update accepts. Only the model, the knowledge and "
            "the prompt affect the result. At most one entry per assistant and "
            "`step_id`, and no more entries than a flow can have steps."
        ),
    )

    @model_validator(mode="after")
    def _one_candidate_per_assistant_and_step(self) -> Self:
        keys = [
            (candidate.assistant_id, candidate.step_id) for candidate in self.assistants
        ]
        if len(keys) != len(set(keys)):
            raise ValueError(
                "Send at most one candidate change per assistant and step."
            )
        return self


class FlowStepSecurityClassificationViolationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: ClassificationViolationCode = Field(
        description=(
            "`flow_step_tool_arguments_classification_write_down`: the step's "
            "tool arguments read steps above the level of the tool's server. "
            "`flow_step_security_classification_mismatch`: the step's model is "
            "below the level the step must clear. "
            "`flow_step_output_classification_write_down`: the step's output "
            "override is below the level its output already carries. A step that "
            "breaks several is reported with the first of them in this order."
        )
    )
    message: str
    required_level: int = Field(
        description=(
            "The level the model, the output override or, for the tool "
            "arguments, the tool's server must reach."
        )
    )
    current_level: int | None = Field(
        description=(
            "The model's level (null when the step has no model or an unclassified "
            "one), the output override for an output write-down, or the level of "
            "the tool's server (null for an unclassified one) for the tool "
            "arguments."
        )
    )
    cause: ClassificationCause = Field(
        description=(
            "What sets `required_level`: `reads` (the steps in `source_step_orders`), "
            "`external_source` (the server of the step's tool), `knowledge` (the "
            "step's knowledge sources) or `space`. When several sit at that level, "
            "the first of them in this order is named."
        )
    )
    source_step_orders: list[int]

    @classmethod
    def from_violation(cls, violation: FlowStepClassificationViolation) -> Self:
        return cls(
            code=violation.code,
            message=violation.message,
            required_level=violation.required_level,
            current_level=violation.current_level,
            cause=violation.cause,
            source_step_orders=list(violation.source_step_orders),
        )


class FlowStepSecurityClassificationPublic(BaseModel):
    step_order: int
    step_id: UUID | None = None
    reads: list[int] = Field(description="The earlier steps this step reads.")
    input_level: int | None = Field(
        description=(
            "The level the step's inputs carry: the space's level, the output "
            "levels of the steps it reads and `external_source_level`. Null when "
            "nothing is classified."
        )
    )
    external_source_level: int | None = Field(
        description=(
            "The level of the server of the tool the step reads its input from. "
            "Null for a step without a tool, for an unclassified server, for a "
            "server that no longer exists and for a server the flow's space "
            "has not activated: such a server has no level in this rule."
        )
    )
    knowledge_level: int | None = Field(
        description="The highest level among the step's knowledge sources."
    )
    required_model_level: int | None = Field(
        description=(
            "The level the step's model must clear. Null for a step that runs no "
            "completion model, or when nothing is classified."
        )
    )
    model_level: int | None = Field(
        description="The level of the step's current model, or null."
    )
    qualifying_model_ids: list[UUID] = Field(
        description=(
            "Completion models of the space that can be used and clear "
            "`required_model_level`, lowest level first. Every usable model "
            "qualifies when nothing is required."
        )
    )
    effective_output_level: int | None = Field(
        description="The level the step's output carries."
    )
    output_floor: int | None = Field(
        description=(
            "The lowest output override the rule accepts; an override can raise "
            "the output level but never lower it below this."
        )
    )
    violation: FlowStepSecurityClassificationViolationPublic | None = Field(
        description="The rule the step breaks, or null when it clears every check."
    )

    @classmethod
    def from_explanation(cls, explanation: FlowStepClassificationExplanation) -> Self:
        return cls(
            step_order=explanation.step_order,
            step_id=explanation.step_id,
            reads=list(explanation.reads),
            input_level=explanation.input_level,
            external_source_level=explanation.external_source_level,
            knowledge_level=explanation.knowledge_level,
            required_model_level=explanation.required_model_level,
            model_level=explanation.model_level,
            qualifying_model_ids=list(explanation.qualifying_model_ids or ()),
            effective_output_level=explanation.effective_output_level,
            output_floor=explanation.output_floor,
            violation=(
                FlowStepSecurityClassificationViolationPublic.from_violation(
                    explanation.violation
                )
                if explanation.violation is not None
                else None
            ),
        )


class FlowSecurityClassificationPreviewPublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_SECURITY_CLASSIFICATION_PREVIEW_EXAMPLE}
    )

    steps: list[FlowStepSecurityClassificationPublic] = Field(
        description=(
            "One entry per step, in step order. Every level is null and no step "
            "has a violation while security classifications are off or nothing is "
            "classified."
        )
    )

    @classmethod
    def from_explanations(
        cls, explanations: list[FlowStepClassificationExplanation]
    ) -> Self:
        return cls(
            steps=[
                FlowStepSecurityClassificationPublic.from_explanation(explanation)
                for explanation in explanations
            ]
        )
