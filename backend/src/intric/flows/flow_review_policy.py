from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

from pydantic import BaseModel, ConfigDict, ValidationError

from intric.flows.enums import FlowOutputMode, flow_output_mode_has_outbound_delivery
from intric.main.exceptions import BadRequestException

FLOW_REVIEW_POLICY_INVALID = "flow_review_policy_invalid"
FLOW_REVIEW_POLICY_OUTBOUND_OUTPUT_UNSUPPORTED = (
    "flow_review_policy_outbound_output_unsupported"
)


class FlowStepReviewMode(str, Enum):
    VIEW = "view"
    EDIT = "edit"


class FlowStepReviewPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: FlowStepReviewMode


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
