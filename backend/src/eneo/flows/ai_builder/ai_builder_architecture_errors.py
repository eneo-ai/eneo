from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderErrorEvent,
    AIBuilderErrorPhase,
    build_ai_builder_error_event,
    coerce_ai_builder_error_code,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
    record_proposal_first_attempt,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import TerminalFailure
from eneo.main.logging import get_logger

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


# Architecture failures no model call can repair: the assembler's own
# invariants, server-synthesized references, template attachments only the
# user can change. Producers end the turn on these; every other architecture
# failure names something the model wrote and is correctable.
TERMINAL_ARCHITECTURE_FAILURE_CODES = frozenset(
    {
        "checkpoint_transcript_producer_missing",
        "assembly_unsupported_architecture_hints",
        "assembly_document_report_compose_topology_missing",
        "flow_input_schema_composite_bindings_unsupported",
        "flow_input_schema_target_missing",
        # Admission verified the model's attested result contract, so a
        # compiled-postcondition breach is a server defect. No model can repair
        # a server bug, and asking one to try would spend the turn's budget
        # hiding it.
        "attested_result_contract_broken",
        # The assembly invariants assert on fields the assembler itself wrote
        # (PlannedStep construction, underlag channels, step ordering), and the
        # projection error rejects source refs the server synthesized. In create
        # mode the model authors neither, so a failure here is a server defect:
        # its feedback names nothing the model can edit, and the sealed receipts
        # show retries burning the whole call budget without ever repairing one.
        "assembly_plan_invariant_failed",
        "invalid_structured_underlag_projection",
        "section_writer_structured_source_ambiguous",
        "terminal_output_type_mismatch",
        "template_attachment_selection_invalid",
        "template_attachment_unreadable",
        "template_placeholder_unresolved",
    }
)


def model_correctable_architecture_failure_code(
    error: AIBuilderArchitectureError,
) -> str | None:
    value = error.log_context.get("failure_code")
    if not isinstance(value, str) or not value:
        return None
    if value in TERMINAL_ARCHITECTURE_FAILURE_CODES:
        return None
    return value


_ARCHITECTURE_FAILURE_MESSAGE = (
    "The AI planner could not build a valid flow from the confirmed "
    "requirements. Please adjust the requirements and try again."
)


def terminal_architecture_failure(error: AIBuilderArchitectureError) -> TerminalFailure:
    """The producer's typed end of the turn for an unrepairable architecture error."""

    logger.error("ai_builder_architecture_error", extra=error.log_extra())
    failure_code = error.log_context.get("failure_code")
    return TerminalFailure(
        kind="architecture",
        message=_ARCHITECTURE_FAILURE_MESSAGE,
        code=coerce_ai_builder_error_code(error.public_code),
        phase=AIBuilderErrorPhase.PROPOSAL,
        details=error.log_extra(),
        codes=(
            frozenset({failure_code})
            if isinstance(failure_code, str) and failure_code
            else frozenset()
        ),
    )


def build_proposal_architecture_error_event(
    error: AIBuilderArchitectureError,
    *,
    request_id: str | None,
    tool_name: str,
) -> AIBuilderErrorEvent:
    log_extra = error.log_extra()
    log_extra["tool_name"] = tool_name
    if request_id is not None:
        log_extra["request_id"] = request_id
    logger.error(
        "ai_builder_architecture_error",
        extra=log_extra,
    )
    return build_ai_builder_error_event(
        message=_ARCHITECTURE_FAILURE_MESSAGE,
        code=coerce_ai_builder_error_code(error.public_code),
        phase=AIBuilderErrorPhase.PROPOSAL,
        request_id=request_id,
        details=error.log_extra(),
    )
