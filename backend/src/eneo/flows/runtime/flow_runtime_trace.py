from __future__ import annotations

import asyncio
import logging
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode
from opentelemetry.util.types import AttributeValue

logger = logging.getLogger(__name__)

FLOW_RUN_EXECUTE_SPAN_NAME: Final = "flow.run.execute"
FLOW_STEP_EXECUTE_SPAN_NAME: Final = "flow.step.execute"

# These allowlists are the Flow runtime span PII boundary; adding a key changes
# what operational metadata can leave the runtime through tracing.
# `flow.run.trace_id` is the persisted FlowRuns correlation token exposed by the
# Flow API, evidence, and exports, not OpenTelemetry's protocol trace id.
FLOW_RUN_SPAN_ATTRIBUTE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "flow.run.id",
        "flow.run.trace_id",
        "flow.id",
        "flow.tenant.id",
        "flow.celery.task_id",
        "flow.celery.retry_count",
        "flow.run.result.status",
        "flow.run.result.reason",
    }
)
FLOW_STEP_SPAN_ATTRIBUTE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "flow.run.id",
        "flow.run.trace_id",
        "flow.id",
        "flow.tenant.id",
        "flow.step.id",
        "flow.step.order",
        "flow.step.attempt_no",
        "flow.step.input_type",
        "flow.step.output_type",
        "flow.step.output_mode",
        "flow.step.result.status",
    }
)

FLOW_RUN_RESULT_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "completed",
        "failed",
        "skipped",
        "cancelled",
        "running",
        "awaiting_review",
        "unclassified",
    }
)
FLOW_RUN_RESULT_REASONS: Final[frozenset[str]] = frozenset(
    {
        "assistant_snapshot_drift",
        "cancelled",
        "definition_checksum_mismatch",
        "flow_assistant_snapshot_drift",
        "flow_definition_checksum_mismatch",
        "flow_definition_invalid",
        "flow_deleted",
        "flow_step_execution_failed",
        "flow_step_missing",
        "invalid_flow_definition",
        "run_awaiting_review",
        "run_cancelled",
        "run_completed",
        "run_failed",
        "run_in_progress",
        "run_queued",
        "run_running",
        "run_terminal",
        "runtime_actor_invalid",
        "service_principal_disabled",
        "step_already_claimed",
        "step_missing",
        "tenant_not_found",
        "unclassified",
        "unhandled_exception",
        "unknown",
    }
)

FLOW_STEP_RESULT_STATUSES: Final[frozenset[str]] = frozenset(
    {"cancelled", "completed", "failed"}
)

_tracer = trace.get_tracer("eneo.flows.runtime")


@dataclass(slots=True)
class FlowRunSpanContext:
    span: Span
    _result_recorded: bool = False

    @property
    def has_result(self) -> bool:
        return self._result_recorded

    def set_run_trace_id(self, trace_id: UUID) -> None:
        # The run span starts before the run row is loaded so early failures trace.
        self.span.set_attribute("flow.run.trace_id", str(trace_id))

    def set_result_from_mapping(self, result: Mapping[str, object]) -> None:
        raw_status = result.get("status")
        status = raw_status if isinstance(raw_status, str) else "unclassified"
        raw_reason = result.get("reason")
        raw_error = result.get("error")
        reason: str | None = None
        if isinstance(raw_reason, str):
            reason = raw_reason
        elif isinstance(raw_error, str):
            reason = raw_error
        self.set_result(status=status, reason=reason)

    def set_result(self, *, status: str, reason: str | None = None) -> None:
        safe_status = _safe_run_status(status)
        self.span.set_attribute("flow.run.result.status", safe_status)
        safe_reason = _safe_run_reason(reason)
        if safe_reason is not None:
            self.span.set_attribute("flow.run.result.reason", safe_reason)
        if safe_status == "failed":
            self.span.set_status(Status(StatusCode.ERROR, safe_reason or safe_status))
        self._result_recorded = True


@dataclass(frozen=True, slots=True)
class FlowStepSpanContext:
    span: Span

    def set_result(self, *, status: str) -> None:
        safe_status = _safe_step_status(status)
        self.span.set_attribute("flow.step.result.status", safe_status)
        if safe_status == "failed":
            self.span.set_status(Status(StatusCode.ERROR, safe_status))


@contextmanager
def trace_flow_run(
    *,
    run_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    celery_task_id: str | None,
    retry_count: int,
) -> Generator[FlowRunSpanContext, None, None]:
    attributes = _flow_run_span_attributes(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        celery_task_id=celery_task_id,
        retry_count=retry_count,
    )
    with _tracer.start_as_current_span(
        FLOW_RUN_EXECUTE_SPAN_NAME, attributes=attributes
    ) as span:
        context = FlowRunSpanContext(span=span)
        try:
            yield context
        except asyncio.CancelledError:
            if not context.has_result:
                context.set_result(status="failed", reason="cancelled")
            raise
        except Exception:
            if not context.has_result:
                context.set_result(status="failed", reason="unhandled_exception")
            raise


@contextmanager
def trace_flow_step(
    *,
    run_id: UUID,
    run_trace_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    step_id: UUID,
    step_order: int,
    attempt_no: int,
    input_type: str,
    output_type: str,
    output_mode: str,
) -> Generator[FlowStepSpanContext, None, None]:
    attributes = _flow_step_span_attributes(
        run_id=run_id,
        run_trace_id=run_trace_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        step_id=step_id,
        step_order=step_order,
        attempt_no=attempt_no,
        input_type=input_type,
        output_type=output_type,
        output_mode=output_mode,
    )
    with _tracer.start_as_current_span(
        FLOW_STEP_EXECUTE_SPAN_NAME, attributes=attributes
    ) as span:
        context = FlowStepSpanContext(span=span)
        try:
            yield context
        except asyncio.CancelledError:
            context.set_result(status="cancelled")
            raise
        except Exception:
            context.set_result(status="failed")
            raise


def _flow_run_span_attributes(
    *,
    run_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    celery_task_id: str | None,
    retry_count: int,
) -> dict[str, AttributeValue]:
    attributes: dict[str, AttributeValue] = {
        "flow.run.id": str(run_id),
        "flow.id": str(flow_id),
        "flow.tenant.id": str(tenant_id),
        "flow.celery.retry_count": retry_count,
    }
    if celery_task_id is not None:
        attributes["flow.celery.task_id"] = celery_task_id
    _warn_for_unexpected_keys(attributes, FLOW_RUN_SPAN_ATTRIBUTE_KEYS)
    return attributes


def _flow_step_span_attributes(
    *,
    run_id: UUID,
    run_trace_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    step_id: UUID,
    step_order: int,
    attempt_no: int,
    input_type: str,
    output_type: str,
    output_mode: str,
) -> dict[str, AttributeValue]:
    attributes: dict[str, AttributeValue] = {
        "flow.run.id": str(run_id),
        "flow.run.trace_id": str(run_trace_id),
        "flow.id": str(flow_id),
        "flow.tenant.id": str(tenant_id),
        "flow.step.id": str(step_id),
        "flow.step.order": step_order,
        "flow.step.attempt_no": attempt_no,
        "flow.step.input_type": input_type,
        "flow.step.output_type": output_type,
        "flow.step.output_mode": output_mode,
    }
    _warn_for_unexpected_keys(attributes, FLOW_STEP_SPAN_ATTRIBUTE_KEYS)
    return attributes


def _safe_run_status(status: str) -> str:
    if status in FLOW_RUN_RESULT_STATUSES:
        return status
    logger.warning("flow_runtime_span_unclassified_result_status")
    return "unclassified"


def _safe_run_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    if reason in FLOW_RUN_RESULT_REASONS:
        return reason
    logger.warning("flow_runtime_span_unclassified_result_reason")
    return "unclassified"


def _safe_step_status(status: str) -> str:
    if status in FLOW_STEP_RESULT_STATUSES:
        return status
    logger.warning("flow_runtime_span_unclassified_step_status")
    return "failed"


def _warn_for_unexpected_keys(
    attributes: Mapping[str, AttributeValue],
    allowed_keys: frozenset[str],
) -> None:
    unexpected = set(attributes) - allowed_keys
    if unexpected:
        logger.warning("flow_runtime_span_unexpected_attribute_keys")
