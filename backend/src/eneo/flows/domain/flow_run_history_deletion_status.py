"""Status of the scheduled deletion of Flow run history (content-free).

Ids, counts, timestamps and typed codes only: no run, Flow or Space names.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from eneo.data_retention.domain.retention import RetentionErrorCode, RetentionJobOutcome


class RetentionExecutionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: RetentionJobOutcome = Field(
        description=(
            "running, succeeded, partial (budget spent, resumes next night), failed, "
            "superseded (a later execution took over) or skipped (emergency switch "
            "or a claim that timed out)."
        )
    )
    started_at: datetime
    finished_at: datetime | None
    counts: dict[str, int] = Field(
        description="What the execution deleted or recorded, by `<step>.<count>`."
    )
    blocked: dict[str, int] = Field(
        description="What it left in place and why, by `<step>.<reason>`."
    )
    error_code: RetentionErrorCode | None


class RetentionTaskStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(description="Registered task, for example flows.housekeeping.")
    enabled: bool = Field(
        description=(
            "False when the deployment's emergency switch turned the task off "
            "(health flag GALLRING_DISABLED); each suppressed run is audited."
        )
    )
    stale: bool = Field(
        description=(
            "The task is enabled and has no completed execution within twice the "
            "daily cadence (health flag GALLRING_JOB_STALE); a task that never ran "
            "is not stale, and a task the switch turned off never is (it raises "
            "GALLRING_DISABLED)."
        )
    )
    last_completed_at: datetime | None = Field(
        description="End of the newest succeeded or partial execution."
    )
    last_execution: RetentionExecutionStatus | None = Field(
        description="The newest execution of any outcome, or null if it never ran."
    )


class FlowRunHistoryOverdueStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    count: int = Field(
        ge=0,
        description=(
            "Terminal runs under auto_delete still stored more than the overdue "
            "window after their deadline, capped; legal holds excluded."
        ),
    )
    complete: bool = Field(description="Whether the cap covered every overdue run.")
    oldest_due_at: datetime | None = Field(
        description="Deletion deadline of the oldest overdue run."
    )
    undelivered_audit: int = Field(
        ge=0,
        description="Overdue runs waiting for their audit events to be delivered.",
    )
    unresolved_webhook: int = Field(
        ge=0, description="Overdue runs with a webhook delivery still pending."
    )
    not_yet_deleted: int = Field(
        ge=0,
        description=(
            "Overdue runs without a blocker of their own: the nightly task has not "
            "reached them (see the flows.history execution)."
        ),
    )
    held: int = Field(
        ge=0,
        description=(
            "Runs past the same deadline and overdue window but kept by an "
            "active legal hold; counted apart up to the result cap."
        ),
    )


class FlowRunHistoryReceiptStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    unfinished: int = Field(
        ge=0,
        description=(
            "Run deletions started and not yet finished (resumed nightly, or "
            "paused by a legal hold)."
        ),
    )
    oldest_unfinished_started_at: datetime | None
    oldest_physical_pending_completed_at: datetime | None = Field(
        description=(
            "Oldest finished run deletion whose stored file content is not yet "
            "confirmed gone."
        )
    )


class FlowRunHistoryDeletionStatus(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "example": {
                "auto_delete_available": True,
                "overdue_window_days": 1,
                "tasks": [
                    {
                        "name": "flows.housekeeping",
                        "enabled": True,
                        "stale": False,
                        "last_completed_at": "2026-10-05T03:41:00Z",
                        "last_execution": {
                            "outcome": "succeeded",
                            "started_at": "2026-10-05T03:30:00Z",
                            "finished_at": "2026-10-05T03:41:00Z",
                            "counts": {"abandoned_uploads.files_deleted": 12},
                            "blocked": {"abandoned_uploads.held": 1},
                            "error_code": None,
                        },
                    }
                ],
                "overdue": {
                    "count": 2,
                    "complete": True,
                    "oldest_due_at": "2026-10-02T09:00:00Z",
                    "undelivered_audit": 1,
                    "unresolved_webhook": 0,
                    "not_yet_deleted": 1,
                    "held": 3,
                },
                "receipts": {
                    "unfinished": 0,
                    "oldest_unfinished_started_at": None,
                    "oldest_physical_pending_completed_at": None,
                },
            }
        },
    )

    auto_delete_available: bool = Field(
        description="Whether this deployment accepts auto_delete policies."
    )
    overdue_window_days: int = Field(
        description=(
            "Operator setting GALLRING_OVERDUE_WINDOW_DAYS: how long past its "
            "deadline a due run may stay before it is overdue."
        )
    )
    tasks: list[RetentionTaskStatus] = Field(
        description="Every registered nightly gallring task, in run order."
    )
    overdue: FlowRunHistoryOverdueStatus = Field(
        description="Live, capped count over the caller's Organization."
    )
    receipts: FlowRunHistoryReceiptStatus


class FlowRetentionStatusUnavailableError(Exception):
    """Status reads failed; a partial count must never look healthy."""

    code = "retention_status_unavailable"

    def __init__(self) -> None:
        super().__init__("Retention status is temporarily unavailable. Retry shortly.")
