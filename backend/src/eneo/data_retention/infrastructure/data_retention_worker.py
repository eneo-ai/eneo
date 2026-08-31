import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import TypeVar

from dependency_injector import providers
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import TypedDict

from eneo.database.database import sessionmanager
from eneo.main.container.container import Container
from eneo.worker.worker import Worker

logger = logging.getLogger(__name__)
worker = Worker()
T = TypeVar("T")


class DeletedCounts(TypedDict):
    questions: int
    app_runs: int
    sessions: int
    builder_client_errors: int
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
        error_msg = f"{error_prefix}: {type(e).__name__}"
        logger.error(error_msg)
        results["errors"].append(error_msg)
        results["success"] = False
        return None


@worker.cron_job(hour=3, minute=0)
async def cleanup_old_data(container: Container) -> CleanupResults:
    """Run the daily cleanup for non-Flow retention policies.

    Flow-owned data is deliberately excluded. Flow retention settings determine
    purge eligibility, but deletion requires a separate administrator action.

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
            "builder_client_errors": 0,
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

            while True:
                client_errors_batch = await _run_cleanup_step(
                    session=session,
                    results=results,
                    error_prefix="Failed to delete expired Builder client errors",
                    action=(
                        lambda: retention_service.delete_expired_builder_client_errors_batch(
                            now=start_time,
                        )
                    ),
                )
                if not client_errors_batch:
                    break
                results["deleted"]["builder_client_errors"] += client_errors_batch
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
        + results["deleted"]["builder_client_errors"]
    )

    if results["success"]:
        logger.info(
            f"Data retention cleanup completed successfully: "
            f"deleted {results['deleted']['total']} records in {duration:.2f}s "
            f"(questions: {results['deleted']['questions']}, "
            f"app_runs: {results['deleted']['app_runs']}, "
            f"sessions: {results['deleted']['sessions']}, "
            f"builder_client_errors: {results['deleted']['builder_client_errors']})"
        )
    else:
        logger.warning(
            f"Data retention cleanup completed with errors: "
            f"deleted {results['deleted']['total']} records in {duration:.2f}s, "
            f"errors: {len(results['errors'])}"
        )

    return results
