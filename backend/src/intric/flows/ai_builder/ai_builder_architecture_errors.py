from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

from intric.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderErrorPhase,
    build_ai_builder_error_event,
    coerce_ai_builder_error_code,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
    record_proposal_first_attempt,
)
from intric.main.logging import get_logger

ArchitectureErrorCode = Literal[
    "architecture_materialization_failed",
    "architecture_critic_invariant_failed",
]
ArchitectureLogValue = str | int | bool | None

logger = get_logger(__name__)


class AIBuilderArchitectureError(Exception):
    def __init__(
        self,
        *,
        public_code: ArchitectureErrorCode,
        detail: str,
        log_context: Mapping[str, ArchitectureLogValue] | None = None,
    ) -> None:
        super().__init__(detail)
        self.public_code = public_code
        self.detail = detail
        self.log_context: Mapping[str, ArchitectureLogValue] = MappingProxyType(
            dict(log_context or {})
        )

    def log_extra(self) -> dict[str, ArchitectureLogValue]:
        return {
            "architecture_error_code": self.public_code,
            "architecture_error_detail": self.detail,
            **self.log_context,
        }


def record_proposal_architecture_failure(
    usage_tracker: ProposalTurnTelemetry | None,
    *,
    request_id: str | None,
    tool_name: str,
) -> None:
    if usage_tracker is None:
        return
    record_proposal_first_attempt(
        usage_tracker,
        request_id=request_id or usage_tracker.request_id,
        tool_name=tool_name,
        success=False,
        failure_kind="architecture",
    )


def build_proposal_architecture_error_event(
    error: AIBuilderArchitectureError,
    *,
    request_id: str | None,
    tool_name: str,
) -> dict[str, str]:
    log_extra = error.log_extra()
    log_extra["tool_name"] = tool_name
    if request_id is not None:
        log_extra["request_id"] = request_id
    logger.error(
        "ai_builder_architecture_error",
        extra=log_extra,
    )
    return build_ai_builder_error_event(
        message=(
            "The AI planner could not build a valid flow from the confirmed "
            "requirements. Please adjust the requirements and try again."
        ),
        code=coerce_ai_builder_error_code(error.public_code),
        phase=AIBuilderErrorPhase.PROPOSAL,
        request_id=request_id,
        details=error.log_extra(),
    )
