from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderErrorPhase,
    coerce_ai_builder_error_code,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CorrectableFailure,
    TerminalFailure,
)
from eneo.main.logging import get_logger

ArchitectureErrorCode = Literal[
    "architecture_materialization_failed",
    "architecture_critic_invariant_failed",
]
# Who can change the rejected input: the model in one more proposal call, the
# user by changing what they confirmed or attached, or nobody because the
# server broke one of its own invariants. Every producer declares this at the
# raise site; no consumer infers it from the failure code.
ArchitectureRepairDisposition = Literal[
    "model_correctable",
    "user_action",
    "server_defect",
]
ArchitectureLogValue = str | int | bool | None

logger = get_logger(__name__)


class AIBuilderArchitectureError(Exception):
    def __init__(
        self,
        *,
        public_code: ArchitectureErrorCode,
        repair_disposition: ArchitectureRepairDisposition,
        detail: str,
        log_context: Mapping[str, ArchitectureLogValue] | None = None,
    ) -> None:
        super().__init__(detail)
        self.public_code = public_code
        self.repair_disposition: ArchitectureRepairDisposition = repair_disposition
        self.detail = detail
        self.log_context: Mapping[str, ArchitectureLogValue] = MappingProxyType(
            dict(log_context or {})
        )

    @property
    def failure_code(self) -> str | None:
        value = self.log_context.get("failure_code")
        return value if isinstance(value, str) and value else None

    def log_extra(self) -> dict[str, ArchitectureLogValue]:
        return {
            "architecture_error_code": self.public_code,
            "architecture_error_detail": self.detail,
            "architecture_repair_disposition": self.repair_disposition,
            **self.log_context,
        }


_TERMINAL_MESSAGES: Mapping[Literal["user_action", "server_defect"], str] = {
    "user_action": (
        "The AI planner could not build a valid flow from the confirmed "
        "requirements. Please adjust the requirements and try again."
    ),
    "server_defect": (
        "The AI planner could not build this flow because of a server-side "
        "limitation. Try a different flow shape or contact support."
    ),
}


def architecture_failure_outcome(
    error: AIBuilderArchitectureError,
) -> CorrectableFailure | TerminalFailure:
    """The producer's typed outcome for an architecture error it declared."""

    failure_code = error.failure_code
    codes: frozenset[str] = (
        frozenset({failure_code}) if failure_code is not None else frozenset()
    )
    disposition = error.repair_disposition
    if disposition == "model_correctable":
        return CorrectableFailure(
            feedback=error.detail,
            kind="validation",
            codes=codes,
        )
    logger.error("ai_builder_architecture_error", extra=error.log_extra())
    return TerminalFailure(
        kind="architecture",
        message=_TERMINAL_MESSAGES[disposition],
        code=coerce_ai_builder_error_code(error.public_code),
        phase=AIBuilderErrorPhase.PROPOSAL,
        details=error.log_extra(),
        codes=codes,
    )
