import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import TypeVar

from dependency_injector import providers
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import TypedDict

from intric.data_retention.infrastructure.data_retention_service import (
    RETENTION_BATCH_SIZE,
    FlowDebugRedactionCounts,
    FlowRunHistoryPurgeBlockedCounts,
    FlowRunHistoryPurgeCounts,
)
from intric.database.database import sessionmanager
from intric.main.container.container import Container
from intric.worker.worker import Worker

logger = logging.getLogger(__name__)
worker = Worker()
T = TypeVar("T")


class DeletedCounts(TypedDict):
    questions: int
    app_runs: int
    sessions: int
    flow_debug_rows: int
    flow_attempt_provenance: int
    flow_runs_purged: int
    flow_generated_files_deleted: int
    flow_webhook_deliveries_deleted: int
    flow_audit_outbox_rows_deleted: int
    flow_review_checkpoints_deleted: int
    flow_runs_skipped_undelivered_audit: int
    flow_runs_skipped_active_rerun: int
    flow_audit_outbox_delivered_rows: int
    total: int


class CleanupResults(TypedDict):
    start_time: str
    end_time: str
    duration_seconds: float
    deleted: DeletedCounts
    errors: list[str]
    success: bool


async def _run_cleanup_step(
    *,
    session: AsyncSession,
    results: CleanupResults,
    error_prefix: str,
    action: Callable[[], Awaitable[T]],
) -> T | None:
    try:
        async with session.begin():
            return await action()
    except Exception as e:
        error_msg = f"{error_prefix}: {e}"
        logger.error(error_msg, exc_info=True)
        results["errors"].append(error_msg)
        results["success"] = False
        return None


def _record_flow_run_history_purge_counts(
    deleted: DeletedCounts, counts: FlowRunHistoryPurgeCounts
) -> None:
    deleted["flow_runs_purged"] += counts.flow_runs_purged
    deleted["flow_generated_files_deleted"] += counts.flow_generated_files_deleted
    deleted["flow_webhook_deliveries_deleted"] += counts.flow_webhook_deliveries_deleted
    deleted["flow_audit_outbox_rows_deleted"] += counts.flow_audit_outbox_rows_deleted
    deleted["flow_review_checkpoints_deleted"] += counts.flow_review_checkpoints_deleted


def _record_flow_run_history_blocked_counts(
    deleted: DeletedCounts, counts: FlowRunHistoryPurgeBlockedCounts
) -> None:
    deleted["flow_runs_skipped_undelivered_audit"] = counts.skipped_undelivered_audit
    deleted["flow_runs_skipped_active_rerun"] = counts.skipped_active_rerun


def _record_flow_debug_redaction_counts(
    deleted: DeletedCounts, counts: FlowDebugRedactionCounts
) -> None:
    deleted["flow_debug_rows"] += counts.debug_step_results
    deleted["flow_attempt_provenance"] += counts.debug_step_attempts


@worker.cron_job(hour=3, minute=0)
async def cleanup_old_data(container: Container) -> CleanupResults:
    """
    Daily cleanup of old data based on retention policies.

    Uses explicit sessionmanager.session() to avoid nested transaction issues
    when cron wrapper already has a transaction open.

    Runs separate transactions for each deletion type to ensure partial
    success is possible if one type fails.

    Returns:
        Dictionary with deletion counts and any errors encountered
    """
    start_time = datetime.now(timezone.utc)

    results: CleanupResults = {
        "start_time": start_time.isoformat(),
        "deleted": {
            "questions": 0,
            "app_runs": 0,
            "sessions": 0,
            "flow_debug_rows": 0,
            "flow_attempt_provenance": 0,
            "flow_runs_purged": 0,
            "flow_generated_files_deleted": 0,
            "flow_webhook_deliveries_deleted": 0,
            "flow_audit_outbox_rows_deleted": 0,
            "flow_review_checkpoints_deleted": 0,
            "flow_runs_skipped_undelivered_audit": 0,
            "flow_runs_skipped_active_rerun": 0,
            "flow_audit_outbox_delivered_rows": 0,
            "total": 0,
        },
        "errors": [],
        "success": True,
        "end_time": "",
        "duration_seconds": 0.0,
    }

    logger.info("Starting data retention cleanup job")

    # Use fresh session to avoid nested transaction error from cron wrapper
    async with sessionmanager.session() as session:
        container.session.override(providers.Object(session))  # pyright: ignore[reportUnknownMemberType]  # dependency_injector provider stubs have partially unknown override()
        try:
            retention_service = container.data_retention_service()

            questions_count = await _run_cleanup_step(
                session=session,
                results=results,
                error_prefix="Failed to delete old questions",
                action=retention_service.delete_old_questions,
            )
            if questions_count is not None:
                results["deleted"]["questions"] = questions_count
                if questions_count > 0:
                    logger.info(
                        f"Deleted {questions_count} old questions based on retention policies"
                    )

            app_runs_count = await _run_cleanup_step(
                session=session,
                results=results,
                error_prefix="Failed to delete old app runs",
                action=retention_service.delete_old_app_runs,
            )
            if app_runs_count is not None:
                results["deleted"]["app_runs"] = app_runs_count
                if app_runs_count > 0:
                    logger.info(
                        f"Deleted {app_runs_count} old app runs based on retention policies"
                    )

            sessions_count = await _run_cleanup_step(
                session=session,
                results=results,
                error_prefix="Failed to delete old sessions",
                action=retention_service.delete_old_sessions,
            )
            if sessions_count is not None:
                results["deleted"]["sessions"] = sessions_count
                if sessions_count > 0:
                    logger.info(f"Deleted {sessions_count} orphaned sessions")

            flow_runtime_now = start_time
            flow_purge_drained = True
            while True:
                purge_counts = await _run_cleanup_step(
                    session=session,
                    results=results,
                    error_prefix="Failed to purge old Flow run history batch",
                    action=lambda: retention_service.purge_old_flow_run_history_batch(
                        now=flow_runtime_now,
                        limit=RETENTION_BATCH_SIZE,
                    ),
                )
                if purge_counts is None:
                    flow_purge_drained = False
                    break

                _record_flow_run_history_purge_counts(
                    results["deleted"],
                    purge_counts,
                )
                if purge_counts.flow_runs_purged == 0:
                    break

            if flow_purge_drained:
                blocked_counts = await _run_cleanup_step(
                    session=session,
                    results=results,
                    error_prefix="Failed to count blocked Flow run-history purge candidates",
                    action=lambda: retention_service.count_blocked_flow_run_history_purge_candidates(
                        now=flow_runtime_now,
                    ),
                )
                if blocked_counts is not None:
                    _record_flow_run_history_blocked_counts(
                        results["deleted"],
                        blocked_counts,
                    )

            redaction_counts = await _run_cleanup_step(
                session=session,
                results=results,
                error_prefix="Failed to redact old Flow debug evidence",
                action=lambda: retention_service.redact_old_flow_debug_evidence(
                    now=flow_runtime_now,
                ),
            )
            if redaction_counts is not None:
                _record_flow_debug_redaction_counts(
                    results["deleted"],
                    redaction_counts,
                )

            outbox_count = await _run_cleanup_step(
                session=session,
                results=results,
                error_prefix="Failed to delete delivered Flow audit outbox rows",
                action=retention_service.delete_old_delivered_flow_audit_outbox_rows,
            )
            if outbox_count is not None:
                results["deleted"]["flow_audit_outbox_delivered_rows"] = outbox_count
        finally:
            # Later worker calls must not inherit this job's scoped session.
            container.session.reset_override()

    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()

    results["end_time"] = end_time.isoformat()
    results["duration_seconds"] = duration
    results["deleted"]["total"] = (
        results["deleted"]["questions"]
        + results["deleted"]["app_runs"]
        + results["deleted"]["sessions"]
        + results["deleted"]["flow_debug_rows"]
        + results["deleted"]["flow_attempt_provenance"]
        + results["deleted"]["flow_runs_purged"]
        + results["deleted"]["flow_generated_files_deleted"]
        + results["deleted"]["flow_webhook_deliveries_deleted"]
        + results["deleted"]["flow_audit_outbox_rows_deleted"]
        + results["deleted"]["flow_review_checkpoints_deleted"]
        + results["deleted"]["flow_audit_outbox_delivered_rows"]
    )

    if results["success"]:
        logger.info(
            f"Data retention cleanup completed successfully: "
            f"deleted {results['deleted']['total']} records in {duration:.2f}s "
            f"(questions: {results['deleted']['questions']}, "
            f"app_runs: {results['deleted']['app_runs']}, "
            f"sessions: {results['deleted']['sessions']}, "
            f"flow_debug_rows: {results['deleted']['flow_debug_rows']}, "
            f"flow_attempt_provenance: {results['deleted']['flow_attempt_provenance']}, "
            f"flow_runs_purged: {results['deleted']['flow_runs_purged']}, "
            f"flow_generated_files_deleted: "
            f"{results['deleted']['flow_generated_files_deleted']}, "
            f"flow_webhook_deliveries_deleted: "
            f"{results['deleted']['flow_webhook_deliveries_deleted']}, "
            f"flow_audit_outbox_rows_deleted: "
            f"{results['deleted']['flow_audit_outbox_rows_deleted']}, "
            f"flow_review_checkpoints_deleted: "
            f"{results['deleted']['flow_review_checkpoints_deleted']}, "
            f"flow_runs_skipped_undelivered_audit: "
            f"{results['deleted']['flow_runs_skipped_undelivered_audit']}, "
            f"flow_runs_skipped_active_rerun: "
            f"{results['deleted']['flow_runs_skipped_active_rerun']}, "
            f"flow_audit_outbox_delivered_rows: "
            f"{results['deleted']['flow_audit_outbox_delivered_rows']})"
        )
    else:
        logger.warning(
            f"Data retention cleanup completed with errors: "
            f"deleted {results['deleted']['total']} records in {duration:.2f}s, "
            f"errors: {len(results['errors'])}"
        )

    return results
