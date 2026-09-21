from __future__ import annotations

from eneo.flows.domain.flow_run_recovery_policy import (
    FlowRunAbandonmentDeadlineExceeded,
    flow_run_abandonment_deadline,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import FlowRunAbandonmentFacts
from eneo.main.exceptions import BadRequestException


class FlowBadRequestException(BadRequestException):
    """Flow bad-request exception with code narrowed to FlowApiErrorCode."""

    code: FlowApiErrorCode

    def __init__(
        self,
        message: str = "",
        *,
        code: FlowApiErrorCode,
        context: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message, code=code.value, context=context)
        self.code = code


def flow_run_abandonment_refusal(
    exc: FlowRunAbandonmentDeadlineExceeded,
) -> FlowBadRequestException:
    facts = FlowRunAbandonmentFacts(
        wait=exc.wait,
        anchor_at=exc.anchor_at,
        deadline=flow_run_abandonment_deadline(exc.anchor_at),
        checkpoint_id=exc.checkpoint_id,
    )
    return FlowBadRequestException(
        "Flow run exceeded its abandonment deadline.",
        code=FlowApiErrorCode.RUN_ABANDONED,
        context={
            "abandonment": facts.model_dump(mode="json", exclude_none=True),
            "retryable": False,
        },
    )
