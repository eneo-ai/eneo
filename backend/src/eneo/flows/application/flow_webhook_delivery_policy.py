from __future__ import annotations

from dataclasses import dataclass

from eneo.audit.domain.constants import MAX_ERROR_MESSAGE_LENGTH
from eneo.flows.flow_run_redaction import redact_string
from eneo.main.config import get_settings
from eneo.tasks.contracts import TaskCapacityClass, TaskEnqueueRequest
from eneo.tasks.routing import FLOW_DRAIN_WEBHOOK_OUTBOX_TASK

# The outbox cron requests an outbox job at this cadence, and a job claims new
# waves only during its first interval.
FLOW_WEBHOOK_DELIVERY_INTERVAL_SECONDS = 30
FLOW_WEBHOOK_DELIVERY_BATCH_SIZE = 50
# Bounds simultaneous outbound requests of one outbox job. Every request for the
# job carries one fixed task key, so one job runs at a time across maintenance
# processes.
#
# Delivery is at-least-once. A claim whose outcome is unknown when it expires is
# redelivered under the same idempotency key, so receivers must deduplicate on
# that key.
FLOW_WEBHOOK_DELIVERY_CONCURRENCY = 10
FLOW_WEBHOOK_MAX_ATTEMPTS = 5
FLOW_WEBHOOK_RETRY_BACKOFF_SECONDS = (30, 120, 300, 900)

assert FLOW_WEBHOOK_DELIVERY_CONCURRENCY <= FLOW_WEBHOOK_DELIVERY_BATCH_SIZE
assert len(FLOW_WEBHOOK_RETRY_BACKOFF_SECONDS) == FLOW_WEBHOOK_MAX_ATTEMPTS - 1
# How long a due delivery may wait for a claim before runtime health reports a
# backlog.
FLOW_WEBHOOK_OUTBOX_BACKLOG_GRACE_SECONDS = 300


@dataclass(frozen=True, slots=True)
class FlowWebhookDeliveryBudget:
    """The time arithmetic of one webhook outbox job.

    One delivery reads its run (preparation), sends one request bounded by the
    maximum request timeout, and audits the call and records the outcome
    (persistence). The job stops claiming once its remaining time no longer
    covers that worst case. Everything the job does, claims included, is cut at
    the hard stop (the finish margin after the job deadline), and ARQ's timeout
    leaves a cancel margin after that, so the job stops itself before ARQ
    cancels it. A claim outlives the job that made it, so a live delivery is
    never reclaimed by another job."""

    max_request_timeout_seconds: float
    preparation_margin_seconds: float = 15
    persistence_margin_seconds: float = 15
    finish_margin_seconds: float = 10
    cancel_margin_seconds: float = 5
    claim_window_seconds: float = FLOW_WEBHOOK_DELIVERY_INTERVAL_SECONDS

    @property
    def per_delivery_worst_case_seconds(self) -> float:
        return (
            self.preparation_margin_seconds
            + self.max_request_timeout_seconds
            + self.persistence_margin_seconds
        )

    @property
    def job_deadline_seconds(self) -> float:
        return self.per_delivery_worst_case_seconds + self.claim_window_seconds

    @property
    def hard_stop_seconds(self) -> float:
        return self.job_deadline_seconds + self.finish_margin_seconds

    @property
    def job_timeout_seconds(self) -> float:
        return self.hard_stop_seconds + self.cancel_margin_seconds

    @property
    def claim_ttl_seconds(self) -> float:
        return self.job_timeout_seconds

    def deadline(self, *, started_at: float) -> FlowWebhookDeliveryDeadline:
        return FlowWebhookDeliveryDeadline(
            budget=self, ends_at=started_at + self.job_deadline_seconds
        )


@dataclass(frozen=True, slots=True)
class FlowWebhookDeliveryDeadline:
    """One job's deadline on the event-loop clock (``loop.time()``).

    Sends end a persistence margin before ``ends_at``; the outbound audit after
    a send waits at most until ``ends_at``, so recording the outcome has at
    least the finish margin before ``hard_stop_at``."""

    budget: FlowWebhookDeliveryBudget
    ends_at: float

    @property
    def sends_end_at(self) -> float:
        return self.ends_at - self.budget.persistence_margin_seconds

    @property
    def hard_stop_at(self) -> float:
        return self.ends_at + self.budget.finish_margin_seconds

    def allows_new_wave(self, now: float) -> bool:
        return self.ends_at - now >= self.budget.per_delivery_worst_case_seconds


def flow_webhook_delivery_budget() -> FlowWebhookDeliveryBudget:
    return FlowWebhookDeliveryBudget(
        max_request_timeout_seconds=get_settings().flow_http_max_timeout_seconds
    )


def flow_webhook_delivery_request() -> TaskEnqueueRequest:
    """The request for one webhook outbox job.

    A run sends it once its deliveries are committed, and the outbox cron sends
    it every interval. The task runtime takes no second job under the fixed key
    while one is queued or running, so concurrent requests share one job; an
    ended job leaves the key free, so the next request starts a new one."""
    return TaskEnqueueRequest(
        task_name=FLOW_DRAIN_WEBHOOK_OUTBOX_TASK,
        capacity_class=TaskCapacityClass.MAINTENANCE,
        idempotency_key=FLOW_DRAIN_WEBHOOK_OUTBOX_TASK,
        payload={},
    )


# What a run needs, after its delivery request, to return before its
# invocation ends.
FLOW_WEBHOOK_DELIVERY_REQUEST_RETURN_MARGIN_SECONDS = 1.0


def flow_webhook_delivery_request_timeout_seconds(
    *, invocation_remaining_seconds: float | None = None
) -> float:
    """How long a run waits for its delivery request: as long as opening a
    connection to the task broker may take, and never so long that the run's
    invocation ends first. A broker that holds the request longer neither
    holds the run's execution slot nor fails its task; at zero or less the run
    sends no request."""
    timeout = float(get_settings().redis_conn_timeout)
    if invocation_remaining_seconds is None:
        return timeout
    return min(
        timeout,
        invocation_remaining_seconds
        - FLOW_WEBHOOK_DELIVERY_REQUEST_RETURN_MARGIN_SECONDS,
    )


def flow_webhook_retry_delay_seconds(*, failed_attempt_no: int) -> int | None:
    if failed_attempt_no < 1:
        raise ValueError("failed_attempt_no must be at least 1")
    if failed_attempt_no >= FLOW_WEBHOOK_MAX_ATTEMPTS:
        return None
    return FLOW_WEBHOOK_RETRY_BACKOFF_SECONDS[failed_attempt_no - 1]


def sanitize_webhook_delivery_error(error: Exception) -> str:
    message = " ".join(str(error).split())
    if not message:
        message = error.__class__.__name__
    message = redact_string(message, key=None)
    return f"{error.__class__.__name__}: {message}"[:MAX_ERROR_MESSAGE_LENGTH]
