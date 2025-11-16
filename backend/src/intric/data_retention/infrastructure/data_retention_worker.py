import logging
from datetime import datetime, timezone
from typing import Dict, Any

from intric.main.container.container import Container
from intric.worker.worker import Worker

logger = logging.getLogger(__name__)
worker = Worker()


@worker.cron_job(hour=3, minute=0)  # Run daily at 3 AM
async def cleanup_old_data(container: Container) -> Dict[str, Any]:
    """
    Daily cleanup of old data based on retention policies.

    Runs separate transactions for each deletion type to ensure partial
    success is possible if one type fails.

    Returns:
        Dictionary with deletion counts and any errors encountered
    """
    data_retention_service = container.data_retention_service()
    start_time = datetime.now(timezone.utc)

    results = {
        "start_time": start_time.isoformat(),
        "deleted": {
            "questions": 0,
            "app_runs": 0,
            "sessions": 0
        },
        "errors": [],
        "success": True
    }

    logger.info("Starting data retention cleanup job")

    # Delete old questions
    try:
        async with container.session().begin():
            questions_count = await data_retention_service.delete_old_questions()
            results["deleted"]["questions"] = questions_count
            if questions_count > 0:
                logger.info(f"Deleted {questions_count} old questions based on retention policies")
    except Exception as e:
        error_msg = f"Failed to delete old questions: {str(e)}"
        logger.error(error_msg, exc_info=True)
        results["errors"].append(error_msg)
        results["success"] = False

    # Delete old app runs
    try:
        async with container.session().begin():
            app_runs_count = await data_retention_service.delete_old_app_runs()
            results["deleted"]["app_runs"] = app_runs_count
            if app_runs_count > 0:
                logger.info(f"Deleted {app_runs_count} old app runs based on retention policies")
    except Exception as e:
        error_msg = f"Failed to delete old app runs: {str(e)}"
        logger.error(error_msg, exc_info=True)
        results["errors"].append(error_msg)
        results["success"] = False

    # Delete old orphaned sessions
    try:
        async with container.session().begin():
            sessions_count = await data_retention_service.delete_old_sessions()
            results["deleted"]["sessions"] = sessions_count
            if sessions_count > 0:
                logger.info(f"Deleted {sessions_count} orphaned sessions")
    except Exception as e:
        error_msg = f"Failed to delete old sessions: {str(e)}"
        logger.error(error_msg, exc_info=True)
        results["errors"].append(error_msg)
        results["success"] = False

    # Calculate total and duration
    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()

    results["end_time"] = end_time.isoformat()
    results["duration_seconds"] = duration
    results["deleted"]["total"] = sum(results["deleted"].values())

    # Log summary
    if results["success"]:
        logger.info(
            f"Data retention cleanup completed successfully: "
            f"deleted {results['deleted']['total']} records in {duration:.2f}s "
            f"(questions: {results['deleted']['questions']}, "
            f"app_runs: {results['deleted']['app_runs']}, "
            f"sessions: {results['deleted']['sessions']})"
        )
    else:
        logger.warning(
            f"Data retention cleanup completed with errors: "
            f"deleted {results['deleted']['total']} records in {duration:.2f}s, "
            f"errors: {len(results['errors'])}"
        )

    return results
