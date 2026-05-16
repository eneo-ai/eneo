"""Terminal-zero-output crawl ownership.

A crawl that completes with no usable output — no pages returned, the
sitemap fetched but yielded nothing, the only successful work was
files that exceeded the download size limit, the crawl timed out
before collecting any pages — is still a typed terminal event. The
worker must:

  1. Log "Crawl produced no usable output" with the diagnostics shape
     operators already rely on.
  2. Commit one `TerminalEvent(outcome_code=...)` through
     `execute_with_recovery` so retries are bounded to the same
     recovery budget the rest of `crawl_task(...)` enjoys.
  3. Apply post-terminal effects (audit + circuit-breaker + slot
     release) with a `CrawlAuditPayload` whose counters are zero,
     EXCEPT the `files_too_large_skipped` counter which carries the
     only successful-ish work the crawler did before terminating
     (operators need this in the audit trail to explain "the crawl
     ended but we still spent download bandwidth").
  4. Acknowledge the terminal commit on the `TaskManager` so the
     orchestration's outer exception handler does not subsequently
     flip the job status.

This module owns those four steps so `crawl_task(...)` stays
orchestration-only. The previous inline implementation lived at
`worker/crawl_tasks.py:1005-1094` and tangled the recovery plumbing +
audit payload construction with the rest of the crawl_task body.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

from intric.main.logging import get_logger
from intric.main.models import Status
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.websites.domain.crawl_run import CrawlFileTooLargeSample, CrawlType
from intric.websites.domain.crawl_terminal import (
    CrawlRunTerminalUpdate,
    TerminalEvent,
    commit_terminal,
)
from intric.worker.crawl.audit import CrawlAuditPayload
from intric.worker.crawl.post_terminal_effects import (
    PostTerminalEffectInput,
    apply_post_terminal_effects,
)
from intric.worker.crawl.recovery import execute_with_recovery

if TYPE_CHECKING:
    from intric.audit.application.audit_service import AuditService
    from intric.worker.task_manager import TaskManager

logger = get_logger(__name__)


@dataclass(frozen=True)
class CommitZeroOutputTerminalInput:
    """Strongly-typed parameter bundle for `commit_zero_output_terminal(...)`.

    Grouping the inputs into a frozen dataclass keeps the call site at
    `crawl_task(...)` declarative — the caller assembles the inputs
    once and the no-output terminator policy is invoked with one
    typed argument instead of fourteen positional parameters.
    """

    crawl_run_id: UUID
    job_id: UUID
    website_id: UUID
    website_url: str
    website_name: str | None
    website_owner_id: UUID | None
    tenant_id: UUID
    crawl_type: CrawlType
    outcome_code: CrawlOutcomeCode
    failure_message: str
    crawl_termination_reason: str
    diagnostics_log_fields: dict[str, Any]
    files_too_large_skipped: int
    files_too_large_download_limit_bytes: int | None
    files_too_large_samples: tuple[CrawlFileTooLargeSample, ...]


async def commit_zero_output_terminal(
    input: CommitZeroOutputTerminalInput,
    *,
    audit_service: "AuditService",
    task_manager: "TaskManager",
) -> dict[str, str]:
    """Commit the typed terminal event + post-effects for a zero-output crawl.

    Returns the status dict the caller should return from
    `crawl_task(...)`. The dict shape is preserved from the previous
    inline implementation so the ARQ job result wire format does not
    change (`{"status": "failed", "outcome_code": <value>}`).
    """
    logger.warning(
        "Crawl produced no usable output",
        extra={
            "job_id": str(input.job_id),
            "website_id": str(input.website_id),
            "tenant_id": str(input.tenant_id),
            "crawl_type": input.crawl_type.value,
            "outcome_code": input.outcome_code.value,
            "termination_reason": input.crawl_termination_reason,
            "scrapy_diagnostics": input.diagnostics_log_fields,
        },
    )

    terminal_finished_at = datetime.now(timezone.utc)

    async def _do_commit(sess: Any) -> None:
        await commit_terminal(
            sess,
            TerminalEvent(
                crawl_run_id=input.crawl_run_id,
                job_id=input.job_id,
                job_status=Status.FAILED,
                outcome_code=input.outcome_code,
                finished_at=terminal_finished_at,
                result_location=input.failure_message,
                crawl_run_update=CrawlRunTerminalUpdate(
                    pages_crawled=0,
                    files_downloaded=0,
                    pages_failed=0,
                    files_failed=0,
                    pages_source_retained=0,
                    pages_hash_retained=0,
                    files_hash_retained=0,
                    files_too_large_skipped=input.files_too_large_skipped,
                    files_too_large_download_limit_bytes=(
                        input.files_too_large_download_limit_bytes
                    ),
                    files_too_large_samples=input.files_too_large_samples,
                    failure_summary=None,
                ),
            ),
        )

    await execute_with_recovery(
        operation_name="terminal_zero_output_commit",
        operation=_do_commit,
    )

    await apply_post_terminal_effects(
        PostTerminalEffectInput(
            recovery_executor=execute_with_recovery,
            audit_service=audit_service,
            audit_payload=CrawlAuditPayload(
                tenant_id=input.tenant_id,
                website_id=input.website_id,
                website_url=input.website_url,
                website_name=input.website_name,
                website_owner_id=input.website_owner_id,
                pages_crawled=0,
                pages_failed=0,
                pages_hash_retained=0,
                pages_source_retained=0,
                files_downloaded=0,
                files_failed=0,
                files_hash_retained=0,
                files_too_large_skipped=input.files_too_large_skipped,
                blobs_deleted=0,
                successful=False,
                outcome_code=input.outcome_code,
            ),
            circuit_breaker_operation_name="terminal_circuit_breaker_update",
        )
    )

    # Terminal zero-output crawls advance no website crawl timestamps,
    # so scheduled retries are not hidden.
    task_manager.acknowledge_terminal_commit(successful=False)
    return {
        "status": "failed",
        "outcome_code": input.outcome_code.value,
    }
