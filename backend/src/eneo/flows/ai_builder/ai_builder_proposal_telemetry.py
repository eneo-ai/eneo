"""Structured telemetry for AI Builder proposal and apply operations.

The canonical `planner_telemetry` dict shape stays in `ai_builder_telemetry`;
this module records proposal facts and apply failure facts.
Structured log payload schema versions are bumped when emitted field names or
field meanings change. Success rows omit failure fields because JSON logging
does not need null-valued keys.

`ToolProcessingFailureKind` is the internal repair-loop taxonomy.
`ProposalFailureKind` adds `missing_submission_tool` for responses that did
not call the required proposal tool, and records backend-owned architecture
failures without treating them as repair invocations.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from time import monotonic_ns
from typing import TYPE_CHECKING, Any, Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_settings import AIBuilderResolvedRequestBudget
from eneo.flows.ai_builder.ai_builder_telemetry import (
    PlannerCallRecordMetadata,
    ProviderCallKind,
    build_assistant_message_metadata,
    build_planner_telemetry,
)
from eneo.flows.ai_builder.ai_builder_token_usage import (
    CompletionTokenUsage,
    TokenUsageSource,
    combine_token_usage,
)
from eneo.flows.ai_builder.ai_builder_tools import AdmissionNormalizerFamily
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.flows.ai_builder.ai_builder_error_contract import (
        AIBuilderLocalDeadline,
        AIBuilderProviderFailure,
        AIBuilderProviderFailureKind,
        AIBuilderProviderStatusClass,
        AIBuilderProviderTurnState,
        JsonScalar,
    )
    from eneo.flows.ai_builder.ai_builder_provider_call import ProviderCallTiming
    from eneo.flows.application.flow_authoring_command import FlowAuthoringPreview

ToolProcessingFailureKind = Literal[
    "parse",
    "validation",
    "quality",
]
# The owner of the rule that wrote a correctable failure's feedback, named for
# its module family: argument parsing and tool admission, spec assembly by the
# compilers, the platform's spec validator and resource resolution, its lint
# warnings, the plan critic, and the review and scoped-edit guards.
FailureProducer = Literal[
    "parse",
    "assembly",
    "platform_validator",
    "lint",
    "critic",
    "review_guard",
    "scope_guard",
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
ProposalFailedTurnBranch = Literal[
    "internal_submission_error",
    "empty_completion_choices",
    "provider_truncation",
    "forced_tool_retry_missing_submission",
    "forced_tool_retry_completion_error",
    "forced_tool_retry_invalid_tool_result",
    "self_correction_completion_error",
    "self_correction_invalid_tool_result",
    "self_correction_missing_tool_response",
]
ProposalTerminalFailureKind = Literal[
    "provider_error",
    "internal_error",
    "missing_submission_tool",
    "provider_truncation",
    "architecture",
    "invalid_repair_payload",
    "invalid_repair_plan",
    "repair_quality_failure",
]
ProposalAttemptKind = Literal["initial", "repair"]
ProposalCallKind = ProviderCallKind
ProposalAttemptFailureKind = Literal[
    "parse",
    "validation",
    "quality",
    "missing_submission_tool",
    "architecture",
    "provider_error",
    "provider_truncation",
    "internal_error",
]
# A failure the model can correct carries the owners of the rules that wrote it.
_CORRECTABLE_FAILURE_KINDS = frozenset[str](get_args(ToolProcessingFailureKind))
ApplyFailurePhase = Literal["prepare_authoring", "apply_authoring"]
MaterializerProgressStage = Literal[
    "flow_created",
    "assistants_created",
    "assistants_configured",
    "assistants_updated",
    "flow_updated",
]

PROPOSAL_TELEMETRY_LOG_KEY = "ai_builder_proposal_telemetry"
PROPOSAL_TELEMETRY_SCHEMA_VERSION = 3
APPLY_TELEMETRY_LOG_KEY = "ai_builder_apply_telemetry"
APPLY_TELEMETRY_SCHEMA_VERSION = 2

logger = get_logger(__name__)
_FAILURE_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_ATTEMPT_FAILURE_CODES = 3
PROPOSAL_PARSE_JSON_FAILURE_CODE = "proposal_parse_json"
PROPOSAL_PARSE_SCHEMA_FAILURE_CODE = "proposal_parse_schema"
PROPOSAL_PARSE_MODEL_FAILURE_CODE = "proposal_parse_model"


def _safe_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def proposal_repair_reason_from_tool_failure(
    failure_kind: ToolProcessingFailureKind | None,
) -> ProposalRepairReason:
    if failure_kind == "parse":
        return "parse"
    if failure_kind == "validation":
        return "validation"
    if failure_kind == "quality":
        return "quality"
    # Missing failure_kind means the processor rejected the tool result without
    # classifying it; validation is the least surprising operational bucket.
    return "validation"


def _empty_call_records() -> list[ProposalCallRecord]:
    return []


def _empty_repair_reasons() -> list[ProposalRepairReason]:
    return []


def _empty_attempts() -> list[ProposalAttemptTelemetryPayload]:
    return []


def _empty_admission_normalization_hits() -> dict[AdmissionNormalizerFamily, int]:
    return {}


class ProposalAttemptTelemetryPayload(BaseModel):
    """Bounded, content-free facts for one proposal provider attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt: int = Field(ge=1)
    kind: ProposalAttemptKind
    elapsed_ms: int = Field(ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    token_usage_source: TokenUsageSource
    token_usage_estimated: bool = False
    failure_kind: ProposalAttemptFailureKind | None = None
    failure_codes: tuple[str, ...] = ()
    failure_code_count: int = Field(default=0, ge=0)
    # Sorted and closed, so bounded by the producer set itself.
    producers: tuple[FailureProducer, ...] = ()


@dataclass(frozen=True, slots=True)
class ProposalCallRecord:
    """Content-free accounting fact for one provider call in a send turn."""

    call_kind: ProposalCallKind
    usage: CompletionTokenUsage
    request_id: str
    attempt: int
    request_budget: AIBuilderResolvedRequestBudget | None = None
    provider_failure_kind: AIBuilderProviderFailureKind | None = None
    provider_status_class: AIBuilderProviderStatusClass | None = None
    provider_turn_state: AIBuilderProviderTurnState | None = None
    local_deadline: AIBuilderLocalDeadline | None = None
    first_chunk_ms: int | None = None
    max_gap_ms: int | None = None
    provider_elapsed_ms: int | None = None


def _call_record_metadata(record: ProposalCallRecord) -> PlannerCallRecordMetadata:
    budget = record.request_budget
    return PlannerCallRecordMetadata(
        call_kind=record.call_kind,
        request_id=record.request_id,
        attempt=record.attempt,
        token_usage_source=record.usage.source,
        token_usage_estimated=record.usage.estimated,
        prompt_tokens=record.usage.prompt_tokens,
        completion_tokens=record.usage.completion_tokens,
        total_tokens=record.usage.total_tokens,
        request_budget_tokens=(
            budget.request_budget_tokens if budget is not None else None
        ),
        model_output_ceiling_tokens=(
            budget.model_output_ceiling_tokens if budget is not None else None
        ),
        output_reserve_tokens=(
            budget.reserved_output_tokens if budget is not None else None
        ),
        provider_output_cap_tokens=(
            budget.provider_output_cap_tokens if budget is not None else None
        ),
        fixed_input_tokens=(budget.fixed_input_tokens if budget is not None else None),
        safety_buffer_tokens=(
            budget.safety_buffer_tokens if budget is not None else None
        ),
        timeout_seconds=(budget.timeout_seconds if budget is not None else None),
        provider_failure_kind=record.provider_failure_kind,
        provider_status_class=record.provider_status_class,
        provider_turn_state=record.provider_turn_state,
        local_deadline=record.local_deadline,
        first_chunk_ms=record.first_chunk_ms,
        max_gap_ms=record.max_gap_ms,
        provider_elapsed_ms=record.provider_elapsed_ms,
    )


# The failed-turn call evidence: a closed set, in priority order. It shares the
# persisted error-details bound with the error's own details, so an error with
# many own keys keeps only the leading keys. The per-call facts come first, then
# the qualifiers, then the token sums, then the call count: a published token sum
# always carries its source and missing-usage qualifier, and sums are what gets
# dropped under key pressure.
FailedTurnEvidenceKey = Literal[
    "last_response_finish_reason",
    "last_call_output_cap_tokens",
    "token_usage_source",
    "calls_without_usage",
    "turn_reasoning_tokens",
    "turn_completion_tokens",
    "turn_prompt_tokens",
    "llm_calls",
]
FAILED_TURN_EVIDENCE_KEYS: tuple[FailedTurnEvidenceKey, ...] = get_args(
    FailedTurnEvidenceKey
)

PUBLISHED_FINISH_REASONS = frozenset(
    {"stop", "length", "tool_calls", "content_filter", "function_call"}
)


def _published_finish_reason(finish_reason: str | None) -> str | None:
    if finish_reason is None:
        return None
    return finish_reason if finish_reason in PUBLISHED_FINISH_REASONS else "other"


def _summed_when_reported(counts: Iterable[int | None]) -> int | None:
    reported = list(counts)
    if not reported or None in reported:
        return None
    return sum(count for count in reported if count is not None)


@dataclass
class ProposalTurnTelemetry:
    request_id: str
    model: str
    target_kind: TargetKind
    call_records: list[ProposalCallRecord] = field(default_factory=_empty_call_records)
    finish_reason: str | None = None
    repair_attempts: int = 0
    proposal_first_attempt_tool: str | None = None
    proposal_first_attempt_success: bool | None = None
    proposal_first_attempt_failure_kind: ProposalFailureKind | None = None
    proposal_repair_reasons: list[ProposalRepairReason] = field(
        default_factory=_empty_repair_reasons
    )
    proposal_attempts: list[ProposalAttemptTelemetryPayload] = field(
        default_factory=_empty_attempts
    )
    admission_normalization_hits: dict[AdmissionNormalizerFamily, int] = field(
        default_factory=_empty_admission_normalization_hits
    )
    _turn_started_ns: int = field(default_factory=monotonic_ns, repr=False)
    _attempt_started_ns: int | None = field(default=None, init=False, repr=False)
    _attempt_counts_as_repair: bool = field(default=False, init=False, repr=False)
    _pending_call: ProposalCallRecord | None = field(
        default=None, init=False, repr=False
    )

    @property
    def token_usages(self) -> list[CompletionTokenUsage]:
        return [record.usage for record in self.call_records]

    @property
    def llm_calls_made(self) -> int:
        return len(self.call_records)

    def begin_call(
        self,
        *,
        call_kind: ProposalCallKind,
        request_budget: AIBuilderResolvedRequestBudget | None = None,
    ) -> ProposalCallRecord:
        record = ProposalCallRecord(
            call_kind=call_kind,
            usage=CompletionTokenUsage(),
            request_id=self.request_id,
            attempt=len(self.call_records) + 1,
            request_budget=request_budget,
        )
        self.call_records.append(record)
        return record

    def complete_call(
        self,
        *,
        call: ProposalCallRecord,
        usage: CompletionTokenUsage,
        timing: ProviderCallTiming | None = None,
    ) -> None:
        self._settle_call(call, usage=usage, timing=timing, failure=None)

    def fail_call(
        self,
        *,
        call: ProposalCallRecord,
        failure: AIBuilderProviderFailure,
        timing: ProviderCallTiming | None = None,
    ) -> None:
        self._settle_call(
            call, usage=CompletionTokenUsage(), timing=timing, failure=failure
        )

    def _settle_call(
        self,
        call: ProposalCallRecord,
        *,
        usage: CompletionTokenUsage,
        timing: ProviderCallTiming | None,
        failure: AIBuilderProviderFailure | None,
    ) -> None:
        index = call.attempt - 1
        if index >= len(self.call_records) or self.call_records[index] != call:
            raise ValueError("Call record does not belong to this turn")
        if call.provider_failure_kind is not None:
            raise ValueError("A failed call record is final")
        self.call_records[index] = replace(
            call,
            usage=usage,
            provider_failure_kind=failure.kind if failure is not None else None,
            provider_status_class=(
                failure.status_class if failure is not None else None
            ),
            provider_turn_state=failure.turn_state if failure is not None else None,
            local_deadline=failure.local_deadline if failure is not None else None,
            first_chunk_ms=timing.first_chunk_ms if timing is not None else None,
            max_gap_ms=timing.max_gap_ms if timing is not None else None,
            provider_elapsed_ms=(
                timing.provider_elapsed_ms if timing is not None else None
            ),
        )

    def retry_call(
        self,
        *,
        failure: AIBuilderProviderFailure,
        timing: ProviderCallTiming | None = None,
        call: ProposalCallRecord | None = None,
    ) -> ProposalCallRecord:
        """Record a refused request as a failed call and begin its replacement.

        The refused call carries its own request's ``timing``. The replacement
        keeps the refused call's kind and budget; without ``call`` the
        attempt's pending call is the one refused.
        """
        refused = call if call is not None else self._pending_call
        if refused is None:
            raise ValueError("No provider call to retry")
        self.fail_call(call=refused, failure=failure, timing=timing)
        replacement = self.begin_call(
            call_kind=refused.call_kind, request_budget=refused.request_budget
        )
        if call is None:
            self._pending_call = replacement
        return replacement

    def start_attempt(
        self,
        *,
        counts_as_repair: bool,
        call_kind: ProposalCallKind | None = None,
        request_budget: AIBuilderResolvedRequestBudget | None = None,
    ) -> None:
        if self._attempt_started_ns is not None:
            self._complete_attempt(usage=None)
        self._attempt_started_ns = monotonic_ns()
        self._attempt_counts_as_repair = counts_as_repair
        self._pending_call = self.begin_call(
            call_kind=call_kind
            or ("proposal_repair" if counts_as_repair else "proposal_initial"),
            request_budget=request_budget,
        )
        if counts_as_repair:
            self.repair_attempts += 1

    def record_response(
        self,
        *,
        finish_reason: str | None,
        usage: CompletionTokenUsage,
        counts_as_repair: bool = False,
        timing: ProviderCallTiming | None = None,
    ) -> None:
        if self._attempt_started_ns is None:
            self.start_attempt(counts_as_repair=counts_as_repair)
        self._complete_attempt(usage=usage, timing=timing)
        self.finish_reason = finish_reason

    def fail_attempt(
        self,
        *,
        failure: AIBuilderProviderFailure,
        timing: ProviderCallTiming | None = None,
    ) -> None:
        """End the open attempt on a provider failure: the one terminal owner.

        The pending call is consumed here exactly once and recorded as failed
        with the failure's facts, and the attempt is closed in the same step,
        so nothing afterwards can complete that call again. With no open attempt
        there is nothing to fail: a recorded attempt is never rewritten.
        """

        if self._attempt_started_ns is None:
            raise ValueError("No open attempt to fail")
        pending, self._pending_call = self._pending_call, None
        if pending is not None:
            self.fail_call(call=pending, failure=failure, timing=timing)
        self.record_attempt_failure(
            failure_kind="provider_error", producers=frozenset()
        )

    def record_attempt_failure(
        self,
        *,
        failure_kind: ProposalAttemptFailureKind,
        producers: frozenset[FailureProducer],
        failure_codes: frozenset[str] = frozenset(),
    ) -> None:
        """Attribute the attempt's failure: a correctable kind names its owners."""

        if failure_kind in _CORRECTABLE_FAILURE_KINDS and not producers:
            raise ValueError(
                f"A {failure_kind} attempt failure names at least one producer"
            )
        if self._attempt_started_ns is not None:
            self._complete_attempt(usage=None)
        if not self.proposal_attempts:
            return
        safe_codes = tuple(
            code for code in sorted(failure_codes) if _FAILURE_CODE_RE.fullmatch(code)
        )
        self.proposal_attempts[-1] = self.proposal_attempts[-1].model_copy(
            update={
                "failure_kind": failure_kind,
                "failure_codes": safe_codes[:_MAX_ATTEMPT_FAILURE_CODES],
                "failure_code_count": len(safe_codes),
                "producers": tuple(sorted(producers)),
            }
        )

    def finalize_pending_attempt(self) -> None:
        self._complete_attempt(usage=None)

    def _complete_attempt(
        self,
        *,
        usage: CompletionTokenUsage | None,
        timing: ProviderCallTiming | None = None,
    ) -> None:
        started_ns = self._attempt_started_ns
        if started_ns is None:
            return
        elapsed_ms = max(0, (monotonic_ns() - started_ns) // 1_000_000)
        attempt_usage = usage or CompletionTokenUsage()
        self.proposal_attempts.append(
            ProposalAttemptTelemetryPayload(
                attempt=len(self.proposal_attempts) + 1,
                kind="repair" if self._attempt_counts_as_repair else "initial",
                elapsed_ms=elapsed_ms,
                prompt_tokens=attempt_usage.prompt_tokens,
                completion_tokens=attempt_usage.completion_tokens,
                total_tokens=attempt_usage.total_tokens,
                token_usage_source=attempt_usage.source,
                token_usage_estimated=attempt_usage.estimated,
            )
        )
        if self._pending_call is not None:
            self.complete_call(
                call=self._pending_call, usage=attempt_usage, timing=timing
            )
            self._pending_call = None
        self._attempt_started_ns = None
        self._attempt_counts_as_repair = False

    def record_first_attempt(
        self,
        *,
        tool_name: str,
        success: bool,
        failure_kind: ProposalFailureKind | None = None,
    ) -> bool:
        if self._attempt_started_ns is not None:
            self._complete_attempt(usage=None)
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

    def record_admission_normalization_hit(
        self,
        family: AdmissionNormalizerFamily,
    ) -> None:
        self.admission_normalization_hits[family] = (
            self.admission_normalization_hits.get(family, 0) + 1
        )

    def failed_turn_details(self) -> dict[str, JsonScalar]:
        """Content-free call evidence for a proposal turn that ended in an error.

        Reported for a streamed error event, a known provider rejection and an
        oversized planning state; an ambiguous provider outcome (timeout, 5xx,
        transport) is rebuilt by the router and does not carry it. The keys are
        ``FAILED_TURN_EVIDENCE_KEYS`` in that order; an absent figure has no key.

        ``turn_*_tokens`` sum every recorded call, auxiliary ones such as the
        slot classifier included, and a sum is published only when every call
        that reported counts reported that one, so an absent figure is never
        read as zero. ``calls_without_usage`` counts calls with no counts at all
        (an estimate counts as reported) and ``token_usage_source`` is
        ``litellm_estimate`` when any counted call was estimated. Both always
        precede the sums, so a published token sum always carries its source and
        missing-usage qualifier; under key pressure the sums are dropped.
        ``last_call_output_cap_tokens`` is the last call's; after a rejected
        later call ``last_response_finish_reason`` is an earlier call's.
        """
        if not self.call_records:
            return {}
        reported = [usage for usage in self.token_usages if usage.has_tokens]
        last_call_output_cap_tokens = next(
            (
                record.request_budget.provider_output_cap_tokens
                for record in reversed(self.call_records)
                if record.request_budget is not None
            ),
            None,
        )
        evidence: dict[FailedTurnEvidenceKey, JsonScalar] = {
            "last_response_finish_reason": _published_finish_reason(self.finish_reason),
            "last_call_output_cap_tokens": last_call_output_cap_tokens,
            "token_usage_source": combine_token_usage(reported).source,
            "calls_without_usage": len(self.call_records) - len(reported),
            "turn_reasoning_tokens": _summed_when_reported(
                usage.reasoning_tokens for usage in reported
            ),
            "turn_completion_tokens": _summed_when_reported(
                usage.completion_tokens for usage in reported
            ),
            "turn_prompt_tokens": _summed_when_reported(
                usage.prompt_tokens for usage in reported
            ),
            "llm_calls": self.llm_calls_made,
        }
        return {
            key: evidence[key]
            for key in FAILED_TURN_EVIDENCE_KEYS
            if evidence[key] is not None
        }

    def build_planner_telemetry(self, *, tool_call_count: int = 0) -> dict[str, Any]:
        if self._attempt_started_ns is not None:
            self._complete_attempt(usage=None)
        usage = combine_token_usage(self.token_usages)
        proposal_repair_reasons: list[str] | None = None
        proposal_repair_count: int | None = None
        if self.proposal_first_attempt_success is not None:
            proposal_repair_reasons = list(self.proposal_repair_reasons)
            # Dashboards query scalar metadata fields more easily than list length.
            proposal_repair_count = len(self.proposal_repair_reasons)

        telemetry = build_planner_telemetry(
            request_id=self.request_id,
            model=self.model,
            finish_reason=self.finish_reason,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            tool_call_count=tool_call_count,
            used_auxiliary_llm=any(
                record.call_kind == "slot_classification"
                for record in self.call_records
            ),
            auxiliary_llm_call_count=sum(
                record.call_kind == "slot_classification"
                for record in self.call_records
            ),
            token_usage_source=usage.source,
            token_usage_estimated=usage.estimated,
            outcome_kind="dispatched",
            wall_clock_ms=max(0, (monotonic_ns() - self._turn_started_ns) // 1_000_000),
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
        telemetry["proposal_attempts"] = [
            attempt.model_dump(mode="json", exclude_none=True)
            for attempt in self.proposal_attempts
        ]
        if self.admission_normalization_hits:
            telemetry["admission_normalization_hits"] = dict(
                self.admission_normalization_hits
            )
        telemetry["call_records"] = [
            _call_record_metadata(record).model_dump(mode="json", exclude_none=True)
            for record in self.call_records
        ]
        return telemetry


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

    @classmethod
    def from_preview(cls, preview: FlowAuthoringPreview) -> ChangesetCountSummary:
        return cls(
            steps_created=preview.steps_created,
            steps_updated=preview.steps_updated,
            steps_removed=preview.steps_removed,
            assistants_to_create=preview.assistants_to_create,
            assistants_to_update=preview.assistants_to_update,
        )


class MaterializerProgressSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: MaterializerProgressStage
    assistants_created: int = 0
    assistants_configured: int = 0
    assistants_updated: int = 0
    flow_created: bool = False
    flow_updated: bool = False


class ProposalFailedTurnTelemetryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event: Literal["ai_builder.proposal.failed_turn"] = (
        "ai_builder.proposal.failed_turn"
    )
    schema_version: int = PROPOSAL_TELEMETRY_SCHEMA_VERSION
    operation: Literal["failed_turn"] = "failed_turn"
    request_id: str
    session_id: str
    target_kind: str
    branch: ProposalFailedTurnBranch
    repair_attempts: int
    llm_calls: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    token_usage_source: str | None = None
    token_usage_estimated: bool = False
    final_failure_kind: ProposalTerminalFailureKind
    final_error_code: str
    provider_finish_reason: str | None = None
    proposal_attempts: tuple[ProposalAttemptTelemetryPayload, ...] = ()


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


def build_proposal_failed_turn_payload(
    *,
    usage_tracker: ProposalTurnTelemetry,
    session_id: UUID | str,
    branch: ProposalFailedTurnBranch,
    final_failure_kind: ProposalTerminalFailureKind,
    final_error_code: str,
) -> ProposalFailedTurnTelemetryPayload:
    usage_tracker.finalize_pending_attempt()
    usage = combine_token_usage(usage_tracker.token_usages)
    return ProposalFailedTurnTelemetryPayload(
        request_id=usage_tracker.request_id,
        session_id=str(session_id),
        target_kind=usage_tracker.target_kind.value,
        branch=branch,
        repair_attempts=usage_tracker.repair_attempts,
        llm_calls=usage_tracker.llm_calls_made,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        token_usage_source=usage.source,
        token_usage_estimated=usage.estimated,
        final_failure_kind=final_failure_kind,
        final_error_code=final_error_code,
        provider_finish_reason=usage_tracker.finish_reason,
        proposal_attempts=tuple(usage_tracker.proposal_attempts),
    )


def log_proposal_failed_turn(
    *,
    usage_tracker: ProposalTurnTelemetry,
    session_id: UUID | str,
    branch: ProposalFailedTurnBranch,
    final_failure_kind: ProposalTerminalFailureKind,
    final_error_code: str,
    event_logger: logging.Logger = logger,
) -> None:
    payload = build_proposal_failed_turn_payload(
        usage_tracker=usage_tracker,
        session_id=session_id,
        branch=branch,
        final_failure_kind=final_failure_kind,
        final_error_code=final_error_code,
    )
    event_logger.info(
        "ai_builder_proposal_failed_turn",
        extra={
            PROPOSAL_TELEMETRY_LOG_KEY: payload.model_dump(exclude_none=True),
        },
    )


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
