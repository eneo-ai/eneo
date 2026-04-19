import logging
from datetime import datetime, timezone

from dependency_injector import providers
from typing_extensions import TypedDict

from intric.database.database import sessionmanager
from intric.main.container.container import Container
from intric.worker.worker import Worker

logger = logging.getLogger(__name__)
worker = Worker()


class DeletedCounts(TypedDict):
    questions: int
    app_runs: int
    sessions: int
    flow_debug_rows: int
    flow_attempt_provenance: int
    flow_artifact_rows: int
    flow_artifact_files: int
    flow_artifact_reconciliations: int
    total: int


class CleanupResults(TypedDict):
    start_time: str
    end_time: str
    duration_seconds: float
    deleted: DeletedCounts
    errors: list[str]
    success: bool


@worker.cron_job(hour=3, minute=0)  # Run daily at 3 AM
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
            "flow_artifact_rows": 0,
            "flow_artifact_files": 0,
            "flow_artifact_reconciliations": 0,
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
            data_retention_service = container.data_retention_service()

            # Delete old questions
            try:
                async with session.begin():
                    questions_count = (
                        await data_retention_service.delete_old_questions()
                    )
                    results["deleted"]["questions"] = questions_count
                    if questions_count > 0:
                        logger.info(
                            f"Deleted {questions_count} old questions based on retention policies"
                        )
            except Exception as e:
                error_msg = f"Failed to delete old questions: {str(e)}"
                logger.error(error_msg, exc_info=True)
                results["errors"].append(error_msg)
                results["success"] = False

            # Delete old app runs
            try:
                async with session.begin():
                    app_runs_count = await data_retention_service.delete_old_app_runs()
                    results["deleted"]["app_runs"] = app_runs_count
                    if app_runs_count > 0:
                        logger.info(
                            f"Deleted {app_runs_count} old app runs based on retention policies"
                        )
            except Exception as e:
                error_msg = f"Failed to delete old app runs: {str(e)}"
                logger.error(error_msg, exc_info=True)
                results["errors"].append(error_msg)
                results["success"] = False

            # Delete old orphaned sessions
            try:
                async with session.begin():
                    sessions_count = await data_retention_service.delete_old_sessions()
                    results["deleted"]["sessions"] = sessions_count
                    if sessions_count > 0:
                        logger.info(f"Deleted {sessions_count} orphaned sessions")
            except Exception as e:
                error_msg = f"Failed to delete old sessions: {str(e)}"
                logger.error(error_msg, exc_info=True)
                results["errors"].append(error_msg)
                results["success"] = False

            try:
                async with session.begin():
                    flow_runtime_counts = (
                        await data_retention_service.cleanup_old_flow_runtime_data()
                    )
                    results["deleted"]["flow_debug_rows"] = flow_runtime_counts[
                        "debug_step_results"
                    ]
                    results["deleted"]["flow_attempt_provenance"] = flow_runtime_counts[
                        "debug_step_attempts"
                    ]
                    results["deleted"]["flow_artifact_rows"] = flow_runtime_counts[
                        "generated_artifact_rows"
                    ]
                    results["deleted"]["flow_artifact_files"] = flow_runtime_counts[
                        "generated_artifact_files"
                    ]
                    results["deleted"]["flow_artifact_reconciliations"] = (
                        flow_runtime_counts["reconciled_artifact_references"]
                    )
            except Exception as e:
                error_msg = f"Failed to clean old flow runtime data: {str(e)}"
                logger.error(error_msg, exc_info=True)
                results["errors"].append(error_msg)
                results["success"] = False
        finally:
            # Always reset override, even on exception
            container.session.reset_override()

    # Calculate total and duration
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
        + results["deleted"]["flow_artifact_rows"]
        + results["deleted"]["flow_artifact_files"]
        + results["deleted"]["flow_artifact_reconciliations"]
    )

    # Log summary
    if results["success"]:
        logger.info(
            f"Data retention cleanup completed successfully: "
            f"deleted {results['deleted']['total']} records in {duration:.2f}s "
            f"(questions: {results['deleted']['questions']}, "
            f"app_runs: {results['deleted']['app_runs']}, "
            f"sessions: {results['deleted']['sessions']}, "
            f"flow_debug_rows: {results['deleted']['flow_debug_rows']}, "
            f"flow_attempt_provenance: {results['deleted']['flow_attempt_provenance']}, "
            f"flow_artifact_rows: {results['deleted']['flow_artifact_rows']}, "
            f"flow_artifact_files: {results['deleted']['flow_artifact_files']}, "
            f"flow_artifact_reconciliations: {results['deleted']['flow_artifact_reconciliations']})"
        )
    else:
        logger.warning(
            f"Data retention cleanup completed with errors: "
            f"deleted {results['deleted']['total']} records in {duration:.2f}s, "
            f"errors: {len(results['errors'])}"
        )

    return results
