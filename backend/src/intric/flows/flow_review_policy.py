from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from intric.flows.enums import FlowOutputMode, flow_output_mode_has_outbound_delivery
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.flows.flow_review_expiry_policy import (
    FLOW_REVIEW_EXPIRY_DEFAULT_SECONDS,
    FLOW_REVIEW_EXPIRY_MAX_SECONDS,
    FLOW_REVIEW_EXPIRY_MIN_SECONDS,
)
from intric.main.exceptions import BadRequestException

FLOW_REVIEW_POLICY_INVALID = FlowApiErrorCode.REVIEW_POLICY_INVALID.value
FLOW_REVIEW_POLICY_OUTBOUND_OUTPUT_UNSUPPORTED = (
    "flow_review_policy_outbound_output_unsupported"
)
FLOW_STEP_REVIEW_POLICY_DESCRIPTION = (
    "Optional human-in-the-loop checkpoint for this step. Set mode to `view` "
    "to pause after the step until a reviewer approves it, or `edit` to let "
    "the reviewer edit the step output before downstream steps continue. Use "
    "`null` or omit the field for no pause. Review policy cannot be combined "
    "with outbound delivery output modes."
)
FlowStepReviewPolicyJson: TypeAlias = dict[str, str | int]


class FlowStepReviewMode(str, Enum):
    VIEW = "view"
    EDIT = "edit"


class FlowStepReviewPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: FlowStepReviewMode = Field(
        description=(
            "`view` pauses the run for approval of this step output. `edit` "
            "also lets the reviewer replace the output used by downstream steps."
        )
    )
    expires_after_seconds: int | None = Field(
        default=None,
        ge=FLOW_REVIEW_EXPIRY_MIN_SECONDS,
        le=FLOW_REVIEW_EXPIRY_MAX_SECONDS,
        description=(
            "How long the unresolved review checkpoint may wait before it expires. "
            "Null inherits the platform default "
            f"({FLOW_REVIEW_EXPIRY_DEFAULT_SECONDS // 86_400} days)."
        ),
    )


def dump_flow_step_review_policy(
    review_policy: FlowStepReviewPolicy | None,
) -> FlowStepReviewPolicyJson | None:
    if review_policy is None:
        return None
    serialized: FlowStepReviewPolicyJson = {"mode": review_policy.mode.value}
    if review_policy.expires_after_seconds is not None:
        serialized["expires_after_seconds"] = review_policy.expires_after_seconds
    return serialized


def parse_flow_step_review_policy(
    *,
    raw_policy: object,
    output_mode: FlowOutputMode,
) -> FlowStepReviewPolicy | None:
    if raw_policy is None:
        return None
    if flow_output_mode_has_outbound_delivery(output_mode):
        raise BadRequestException(
            "Step review_policy cannot be combined with outbound delivery output modes.",
            code=FLOW_REVIEW_POLICY_OUTBOUND_OUTPUT_UNSUPPORTED,
        )
    if isinstance(raw_policy, FlowStepReviewPolicy):
        return raw_policy
    if not isinstance(raw_policy, Mapping):
        raise BadRequestException(
            "Step review_policy must be an object.",
            code=FLOW_REVIEW_POLICY_INVALID,
        )
    try:
        policy = FlowStepReviewPolicy.model_validate(raw_policy)
    except ValidationError as exc:
        raise BadRequestException(
            "Step review_policy is invalid.",
            code=FLOW_REVIEW_POLICY_INVALID,
        ) from exc
    return policy
