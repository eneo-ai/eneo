"""The reason a reviewer gives for rejecting a checkpoint, checked one way for
the request model and the review service."""

from __future__ import annotations

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException

FLOW_REVIEW_REJECT_REASON_MAX_LENGTH = 1024


def normalize_review_reject_reason(reason: str) -> str:
    """The reason without surrounding whitespace; blank or longer than the
    limit after trimming is refused with `400` and its flow code."""
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise FlowBadRequestException(
            "Review rejection reason is required.",
            code=FlowApiErrorCode.REVIEW_REJECT_REASON_REQUIRED,
        )
    if len(normalized_reason) > FLOW_REVIEW_REJECT_REASON_MAX_LENGTH:
        raise FlowBadRequestException(
            "Review rejection reason must be at most "
            f"{FLOW_REVIEW_REJECT_REASON_MAX_LENGTH} characters.",
            code=FlowApiErrorCode.REVIEW_REJECT_REASON_TOO_LONG,
            context={"max_length": FLOW_REVIEW_REJECT_REASON_MAX_LENGTH},
        )
    return normalized_reason
