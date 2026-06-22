"""Structured telemetry for AI Builder proposal and apply operations.

The canonical `planner_telemetry` dict shape stays in `ai_builder_telemetry`;
this module records proposal facts and apply failure facts.
Structured log payload schema versions are bumped when emitted field names or
field meanings change. Success rows omit failure fields because JSON logging
does not need null-valued keys.

`ToolProcessingFailureKind` is the internal repair-loop taxonomy.
`recoverable_parse` receives one extra self-correction attempt, so the repair
loop can distinguish malformed input from validation and quality feedback.
`ProposalFailureKind` is the sanitized proposal telemetry taxonomy: it maps
`recoverable_parse` to `parse`, adds `missing_submission_tool` for responses
that did not call the required proposal tool, and records backend-owned
architecture failures without treating them as repair invocations.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_telemetry import (
    build_assistant_message_metadata,
    build_planner_telemetry,
)
from intric.flows.ai_builder.ai_builder_token_usage import (
    CompletionTokenUsage,
    combine_token_usage,
    completion_token_usage_from_response,
)
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.flows.application.flow_authoring_command import FlowAuthoringPreview

ToolProcessingFailureKind = Literal[
    "parse",
    "recoverable_parse",
    "validation",
    "quality",
]
ProposalFailureKind = Literal[
    "parse",
    "validation",
    "quality",
    "missing_submission_tool",
    "architecture",
]
ProposalRepairReason = Literal[
    "parse",
    "validation",
    "quality",
    "missing_submission_tool",
]
ApplyFailurePhase = Literal["prepare_authoring", "apply_authoring"]
MaterializerProgressStage = Literal[
    "flow_created",
    "assistants_created",
    "assistants_configured",
    "assistants_updated",
    "flow_updated",
    "assistants_deleted",
]

PROPOSAL_TELEMETRY_LOG_KEY = "ai_builder_proposal_telemetry"
PROPOSAL_TELEMETRY_SCHEMA_VERSION = 1
APPLY_TELEMETRY_LOG_KEY = "ai_builder_apply_telemetry"
APPLY_TELEMETRY_SCHEMA_VERSION = 1

logger = get_logger(__name__)


def _safe_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _completion_text_from_response(response: Any) -> str:
    parts: list[str] = []
    for choice in getattr(response, "choices", []) or []:
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None)
        if isinstance(content, str) and content:
            parts.append(content)
    return "\n".join(parts)


def proposal_repair_reason_from_tool_failure(
    failure_kind: ToolProcessingFailureKind | None,
) -> ProposalRepairReason:
    if failure_kind in {"parse", "recoverable_parse"}:
        return "parse"
    if failure_kind == "validation":
        return "validation"
    if failure_kind == "quality":
        return "quality"
    # Missing failure_kind means the processor rejected the tool result without
    # classifying it; validation is the least surprising operational bucket.
    return "validation"


def _empty_token_usages() -> list[CompletionTokenUsage]:
    return []


def _empty_repair_reasons() -> list[ProposalRepairReason]:
    return []


@dataclass
class ProposalTurnTelemetry:
    request_id: str
    model: str
    target_kind: TargetKind
    token_usages: list[CompletionTokenUsage] = field(
        default_factory=_empty_token_usages
    )
    finish_reason: str | None = None
    repair_attempts: int = 0
    proposal_first_attempt_tool: str | None = None
    proposal_first_attempt_success: bool | None = None
    proposal_first_attempt_failure_kind: ProposalFailureKind | None = None
    proposal_repair_reasons: list[ProposalRepairReason] = field(
        default_factory=_empty_repair_reasons
    )

    @property
    def llm_calls_made(self) -> int:
        return len(self.token_usages)

    def record_response(
        self,
        response: Any,
        *,
        messages: list[dict[str, Any]],
        counts_as_repair: bool = False,
    ) -> None:
        choice = response.choices[0] if getattr(response, "choices", None) else None
        self.finish_reason = _safe_str(getattr(choice, "finish_reason", None))
        if counts_as_repair:
            self.repair_attempts += 1
        self.token_usages.append(
            completion_token_usage_from_response(
                response,
                model_name=self.model,
                messages=messages,
                completion_text=_completion_text_from_response(response),
            )
        )

    def record_first_attempt(
        self,
        *,
        tool_name: str,
        success: bool,
        failure_kind: ProposalFailureKind | None = None,
    ) -> bool:
        if self.proposal_first_attempt_success is not None:
            return False

        self.proposal_first_attempt_tool = tool_name
        self.proposal_first_attempt_success = success
        self.proposal_first_attempt_failure_kind = (
            None if success else failure_kind or "validation"
        )
        return True

    def record_repair_invocation(self, *, reason: ProposalRepairReason) -> None:
        self.proposal_repair_reasons.append(reason)

    def build_planner_telemetry(self, *, tool_call_count: int = 0) -> dict[str, Any]:
        usage = combine_token_usage(self.token_usages)
        proposal_repair_reasons: list[str] | None = None
        proposal_repair_count: int | None = None
        if self.proposal_first_attempt_success is not None:
            proposal_repair_reasons = list(self.proposal_repair_reasons)
            # Dashboards query scalar metadata fields more easily than list length.
            proposal_repair_count = len(self.proposal_repair_reasons)

        return build_planner_telemetry(
            request_id=self.request_id,
            model=self.model,
            finish_reason=self.finish_reason,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            tool_call_count=tool_call_count,
            used_auxiliary_llm=False,
            token_usage_source=usage.source if usage.has_tokens else None,
            token_usage_estimated=usage.estimated,
            outcome_kind="dispatched",
            wall_clock_ms=0,
            llm_calls_made=self.llm_calls_made,
            repair_attempts=self.repair_attempts,
            parse_repair_attempts=0,
            architecture_commit_populated=False,
            proposal_first_attempt_tool=self.proposal_first_attempt_tool,
            proposal_target_kind=self.target_kind.value,
            proposal_first_attempt_success=self.proposal_first_attempt_success,
            proposal_first_attempt_failure_kind=(
                self.proposal_first_attempt_failure_kind
            ),
            proposal_repair_invocation_count=proposal_repair_count,
            proposal_repair_invocation_reasons=proposal_repair_reasons,
        )


def assistant_metadata_with_usage(
    *,
    conversation: list[ConversationMessage],
    base_metadata: dict[str, Any] | None,
    usage_tracker: ProposalTurnTelemetry | None,
    tool_calls: Sequence[object] | None = None,
) -> dict[str, Any] | None:
    if usage_tracker is None:
        return base_metadata
    return build_assistant_message_metadata(
        conversation,
        planner_telemetry=usage_tracker.build_planner_telemetry(
            tool_call_count=len(tool_calls or [])
        ),
        base_metadata=base_metadata,
        tool_calls=tool_calls,
    )


def record_proposal_first_attempt(
    usage_tracker: ProposalTurnTelemetry | None,
    *,
    request_id: str,
    tool_name: str,
    success: bool,
    failure_kind: ProposalFailureKind | None = None,
) -> None:
    if usage_tracker is None:
        return
    if usage_tracker.record_first_attempt(
        tool_name=tool_name,
        success=success,
        failure_kind=failure_kind,
    ):
        log_proposal_first_attempt(
            request_id=request_id,
            tool_name=tool_name,
            success=success,
            failure_kind=failure_kind,
        )


class ChangesetCountSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    steps_created: int
    steps_updated: int
    steps_removed: int
    assistants_to_create: int
    assistants_to_update: int
    assistants_to_delete: int

    @classmethod
    def from_preview(cls, preview: FlowAuthoringPreview) -> ChangesetCountSummary:
        return cls(
            steps_created=preview.steps_created,
            steps_updated=preview.steps_updated,
            steps_removed=preview.steps_removed,
            assistants_to_create=preview.assistants_to_create,
            assistants_to_update=preview.assistants_to_update,
            assistants_to_delete=preview.assistants_to_delete,
        )


class MaterializerProgressSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: MaterializerProgressStage
    assistants_created: int = 0
    assistants_configured: int = 0
    assistants_updated: int = 0
    assistants_deleted: int = 0
    flow_created: bool = False
    flow_updated: bool = False


class ApplyFailureTelemetryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event: Literal["ai_builder.apply.failed"] = "ai_builder.apply.failed"
    schema_version: int = APPLY_TELEMETRY_SCHEMA_VERSION
    operation: Literal["apply_failed"] = "apply_failed"
    phase: ApplyFailurePhase
    plan_id: str
    session_id: str
    target_kind: str
    flow_id: str | None
    exception_class: str
    code: str | None = None
    changeset_counts: ChangesetCountSummary | None = None
    materializer_progress: MaterializerProgressSnapshot | None = None


def log_apply_failed(
    *,
    phase: ApplyFailurePhase,
    plan_id: UUID | str,
    session_id: UUID | str,
    target_kind: TargetKind,
    flow_id: UUID | str | None,
    exception: Exception,
    changeset_counts: ChangesetCountSummary | None,
    materializer_progress: MaterializerProgressSnapshot | None,
    event_logger: logging.Logger = logger,
) -> None:
    payload = ApplyFailureTelemetryPayload(
        phase=phase,
        plan_id=str(plan_id),
        session_id=str(session_id),
        target_kind=target_kind.value,
        flow_id=None if flow_id is None else str(flow_id),
        exception_class=type(exception).__name__,
        code=_safe_str(getattr(exception, "code", None)),
        changeset_counts=changeset_counts,
        materializer_progress=materializer_progress,
    )
    event_logger.info(
        "ai_builder_apply_failed",
        extra={
            APPLY_TELEMETRY_LOG_KEY: payload.model_dump(exclude_none=True),
        },
    )


def log_proposal_first_attempt(
    *,
    request_id: str,
    tool_name: str,
    success: bool,
    failure_kind: ProposalFailureKind | None,
    event_logger: logging.Logger = logger,
) -> None:
    payload: dict[str, object] = {
        "event": "ai_builder.proposal.first_attempt",
        "schema_version": PROPOSAL_TELEMETRY_SCHEMA_VERSION,
        "operation": "first_attempt",
        "request_id": request_id,
        "tool_name": tool_name,
        "success": success,
    }
    if failure_kind is not None:
        payload["failure_kind"] = failure_kind
    event_logger.info(
        "ai_builder_proposal_first_attempt",
        extra={PROPOSAL_TELEMETRY_LOG_KEY: payload},
    )


def log_proposal_repair_invoked(
    *,
    request_id: str,
    tool_name: str,
    reason: ProposalRepairReason,
    event_logger: logging.Logger = logger,
) -> None:
    payload: dict[str, object] = {
        "event": "ai_builder.proposal.repair_invoked",
        "schema_version": PROPOSAL_TELEMETRY_SCHEMA_VERSION,
        "operation": "repair_invoked",
        "request_id": request_id,
        "tool_name": tool_name,
        "reason": reason,
    }
    event_logger.info(
        "ai_builder_proposal_repair_invoked",
        extra={PROPOSAL_TELEMETRY_LOG_KEY: payload},
    )
