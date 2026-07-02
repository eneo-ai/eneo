from __future__ import annotations

from enum import Enum
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.enums import (
    FlowOutputMode,
    FlowOutputType,
    FlowRuntimeInputFormat,
    FlowTemplateAssetStatus,
)
from eneo.flows.flow_input_limits import (
    FlowRuntimeUploadPolicy,
    effective_runtime_upload_policy,
)
from eneo.flows.flow_metadata import FlowFormFieldType
from eneo.flows.flow_review_expiry_policy import FLOW_REVIEW_EXPIRY_DEFAULT_SECONDS
from eneo.flows.flow_review_policy import FlowStepReviewMode

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
    "runtime_upload_policy": {
        "min_timeout_seconds": 120,
        "seconds_per_mebibyte": 8,
        "max_timeout_seconds": 600,
        "idle_timeout_seconds": 120,
    },
    "steps_requiring_review": [
        {
            "step_id": "00000000-0000-0000-0000-000000000103",
            "step_order": 2,
            "label": "Review transcription",
            "review_mode": "edit",
            "output_type": "json",
            "expires_after_seconds": FLOW_REVIEW_EXPIRY_DEFAULT_SECONDS,
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


FLOW_RUNTIME_UPLOAD_POLICY_DESCRIPTION = (
    "Client-side timeout policy for runtime file uploads. Consumers should "
    "calculate each upload's initial timeout from the actual file size: "
    "`clamp(min_timeout_seconds, max_timeout_seconds, "
    "ceil(file_size_mib * seconds_per_mebibyte))`, then keep a progressing "
    "upload alive until `idle_timeout_seconds` passes without progress."
)


class FlowRuntimeUploadPolicyPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_timeout_seconds: int = Field(
        gt=0,
        description="Minimum wall-clock timeout clients should allow for each runtime file upload.",
    )
    seconds_per_mebibyte: int = Field(
        gt=0,
        description=(
            "Multiplier clients should apply to the actual file size when calculating "
            "a per-file upload timeout."
        ),
    )
    max_timeout_seconds: int = Field(
        gt=0,
        description="Cap on the initial no-progress timeout for each runtime file upload.",
    )
    idle_timeout_seconds: int = Field(
        gt=0,
        description="Timeout clients should allow after the latest upload progress event.",
    )

    @classmethod
    def from_domain(
        cls, policy: FlowRuntimeUploadPolicy
    ) -> "FlowRuntimeUploadPolicyPublic":
        return cls(
            min_timeout_seconds=policy.min_timeout_seconds,
            seconds_per_mebibyte=policy.seconds_per_mebibyte,
            max_timeout_seconds=policy.max_timeout_seconds,
            idle_timeout_seconds=policy.idle_timeout_seconds,
        )


def default_runtime_upload_policy_public() -> FlowRuntimeUploadPolicyPublic:
    return FlowRuntimeUploadPolicyPublic.from_domain(effective_runtime_upload_policy())


class FlowRuntimeInputContractPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    model_config = ConfigDict(extra="forbid")

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
    expires_after_seconds: int = Field(
        default=FLOW_REVIEW_EXPIRY_DEFAULT_SECONDS,
        description=(
            "Effective review window in seconds, starting when this checkpoint "
            "opens. This value is already resolved from the step policy and the "
            "platform default, so clients can prepare review deadlines before the "
            "run reaches awaiting_review."
        ),
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
    model_config = ConfigDict(extra="forbid")

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
    model_config = ConfigDict(extra="forbid")

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
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        description=(
            "Runtime input key clients send in `input_payload_json`. This is also "
            "available to prompts as `{{flow_input.<name>}}`."
        ),
    )
    type: FlowFormFieldType = Field(
        description=(
            "Form control type clients should render. One of: text, number, "
            "date, select, multiselect."
        ),
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
        extra="forbid", json_schema_extra={"example": FLOW_RUN_CONTRACT_PUBLIC_EXAMPLE}
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
    runtime_upload_policy: FlowRuntimeUploadPolicyPublic = Field(
        default_factory=default_runtime_upload_policy_public,
        description=FLOW_RUNTIME_UPLOAD_POLICY_DESCRIPTION,
    )
    steps_requiring_review: list[FlowReviewStepContractPublic] = Field(
        default_factory=lambda: cast(list[FlowReviewStepContractPublic], []),
        description=(
            "Published steps that can pause the run for human review. API consumers "
            "can use this before starting a run to decide whether their app needs "
            "review screens, then use the active checkpoint endpoint once the run "
            "status becomes `awaiting_review`. An empty list means this published "
            "flow version will not pause for human-in-the-loop review."
        ),
    )
    aggregate_max_files: int | None = Field(
        default=None,
        description=(
            "Total number of files a caller may attach across all runtime-input "
            "steps for this published flow version. `0` means no published steps "
            "currently require runtime files. `null` means at least one runtime "
            "file-input step is intentionally unbounded, so clients should enforce "
            "the per-step limits in `steps_requiring_input` instead."
        ),
    )
    template_readiness: list[FlowTemplateReadinessPublic] = Field(
        default_factory=lambda: cast(list[FlowTemplateReadinessPublic], [])
    )
