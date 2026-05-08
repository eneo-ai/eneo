from __future__ import annotations

from enum import Enum
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from intric.flows.enums import (
    FlowOutputMode,
    FlowOutputType,
    FlowRuntimeInputFormat,
    FlowTemplateAssetStatus,
)
from intric.flows.flow_review_policy import FlowStepReviewMode

FLOW_RUN_CONTRACT_PUBLIC_EXAMPLE: dict[str, Any] = {
    "flow_id": "00000000-0000-0000-0000-000000000001",
    "published_flow_version": 3,
    "final_output": {
        "step_id": "00000000-0000-0000-0000-000000000104",
        "step_order": 3,
        "label": "Create Word report",
        "output_type": "docx",
        "output_mode": "pass_through",
        "delivery": "artifact",
        "output_contract": None,
    },
    "form_fields": [
        {
            "name": "employee_name",
            "type": "text",
            "label": "Employee name",
            "required": True,
        }
    ],
    "steps_requiring_input": [
        {
            "step_id": "00000000-0000-0000-0000-000000000101",
            "step_order": 1,
            "label": "Upload audio",
            "description": "Provide the recorded review conversation.",
            "required": True,
            "input_format": "audio",
            "max_files": 1,
            "max_file_size_bytes": 52428800,
            "accepted_mimetypes": ["audio/wav", "audio/mpeg"],
        }
    ],
    "steps_requiring_review": [
        {
            "step_id": "00000000-0000-0000-0000-000000000103",
            "step_order": 2,
            "label": "Review transcription",
            "review_mode": "edit",
            "output_type": "json",
            "output_contract": {
                "type": "object",
                "properties": {"transcription": {"type": "string"}},
            },
        }
    ],
    "aggregate_max_files": 1,
    "template_readiness": [
        {
            "step_id": "00000000-0000-0000-0000-000000000102",
            "template_asset_id": None,
            "template_file_id": None,
            "template_name": None,
            "checksum": None,
            "published_flow_version": 3,
            "status": "unavailable",
            "can_edit": False,
            "can_download": False,
            "message_code": None,
        }
    ],
}


class FlowRuntimeInputContractPublic(BaseModel):
    step_id: UUID
    step_order: int
    label: str | None = None
    description: str | None = None
    required: bool
    input_format: FlowRuntimeInputFormat
    max_files: int | None = None
    max_file_size_bytes: int | None = None
    accepted_mimetypes: list[str] = Field(default_factory=list)


class FlowReviewStepContractPublic(BaseModel):
    step_id: UUID
    step_order: int
    label: str | None = Field(
        default=None,
        description="Published step label to show before a run reaches review.",
    )
    review_mode: FlowStepReviewMode = Field(
        description="Review behavior the runtime will use when this step completes.",
    )
    output_type: FlowOutputType = Field(
        description="Published output type of the step that can pause for review.",
    )
    output_contract: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Published output contract for the step, when one is configured. "
            "This is useful for prebuilding review forms before the run starts."
        ),
    )


class FlowOutputDelivery(str, Enum):
    PAYLOAD = "payload"
    ARTIFACT = "artifact"
    OUTBOUND_HTTP = "outbound_http"


class FlowFinalOutputContractPublic(BaseModel):
    step_id: UUID = Field(
        description="Published step id that produces the run's terminal output.",
    )
    step_order: int = Field(
        description="Published order of the step that produces the terminal output.",
    )
    label: str | None = Field(
        default=None,
        description="Published label of the step that produces the terminal output.",
    )
    output_type: FlowOutputType = Field(
        description=(
            "Terminal output type clients should expect after a successful run. "
            "`docx` and `pdf` outputs are returned as generated file download "
            "artifacts; "
            "`text` and `json` outputs are returned as step output payloads."
        ),
    )
    output_mode: FlowOutputMode = Field(
        description=(
            "Terminal output mode configured for the published final step. This "
            "helps clients distinguish ordinary document generation from "
            "template-fill flows."
        ),
    )
    delivery: FlowOutputDelivery = Field(
        description=(
            "How clients should retrieve or present the terminal result. `payload` "
            "means read the final step output payload, `artifact` means offer a "
            "generated file download, and `outbound_http` means the step sends its "
            "result to the configured HTTP endpoint."
        ),
    )
    output_contract: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Published terminal output contract when the final step is structured. "
            "Null means the final output is unstructured text or a generated document."
        ),
    )


class FlowTemplateReadinessPublic(BaseModel):
    step_id: UUID
    template_asset_id: UUID | None = None
    template_file_id: UUID | None = None
    template_name: str | None = None
    checksum: str | None = None
    published_flow_version: int | None = None
    status: FlowTemplateAssetStatus
    can_edit: bool = False
    can_download: bool = False
    message_code: str | None = None


class FormFieldPublic(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(
        description=(
            "Runtime input key clients send in `input_payload_json`. This is also "
            "available to prompts as `{{flow_input.<name>}}`."
        ),
    )
    type: str = Field(
        description="Form control type clients should render, such as text, number, date, select, or multiselect.",
    )
    label: str | None = Field(
        default=None,
        description="Human-readable label to show in the run form. Falls back to `name` when null.",
    )
    required: bool = Field(
        default=False,
        description="Whether run creation requires a value for this input field.",
    )
    options: list[str] | None = Field(
        default=None,
        description="Allowed choices for select and multiselect fields.",
    )
    order: int | None = Field(
        default=None,
        description="Display order for generated run forms.",
    )


class FlowRunContractPublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_RUN_CONTRACT_PUBLIC_EXAMPLE}
    )

    flow_id: UUID
    published_flow_version: int
    final_output: FlowFinalOutputContractPublic | None = Field(
        default=None,
        description=(
            "Published terminal output contract for this flow version. API consumers "
            "should use this before starting a run to decide whether their app will "
            "display text/JSON output or offer a generated file download such as "
            "PDF or DOCX."
        ),
    )
    form_fields: list[FormFieldPublic] = Field(
        default_factory=lambda: cast(list[FormFieldPublic], [])
    )
    steps_requiring_input: list[FlowRuntimeInputContractPublic] = Field(
        default_factory=lambda: cast(list[FlowRuntimeInputContractPublic], [])
    )
    steps_requiring_review: list[FlowReviewStepContractPublic] = Field(
        default_factory=lambda: cast(list[FlowReviewStepContractPublic], []),
        description=(
            "Published steps that can pause the run for human review. API consumers "
            "can use this before starting a run to decide whether their app needs "
            "review screens, then use the active checkpoint endpoint once the run "
            "status becomes `awaiting_review`."
        ),
    )
    aggregate_max_files: int | None = None
    template_readiness: list[FlowTemplateReadinessPublic] = Field(
        default_factory=lambda: cast(list[FlowTemplateReadinessPublic], [])
    )
