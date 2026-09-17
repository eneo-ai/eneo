# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from eneo.database.database import sessionmanager
from eneo.main.logging import get_logger
from eneo.widgets.infrastructure.widget_usage_repo_impl import WidgetUsageRepoImpl

logger = get_logger(__name__)


async def purge_expired_widget_sessions() -> dict[str, int]:
    """Delete widget conversations older than each widget's retention.

    One transaction per widget so a failure on one tenant's widget never
    rolls back another's deletions.
    """
    async with sessionmanager.session() as session, session.begin():
        targets = await WidgetUsageRepoImpl(session).retention_targets()

    widgets_processed = 0
    sessions_deleted = 0
    errors = 0
    for widget_id, retention_days in targets:
        try:
            async with sessionmanager.session() as session, session.begin():
                repo = WidgetUsageRepoImpl(session)
                sessions_deleted += await repo.delete_sessions_before(
                    widget_id, repo.cutoff_for(retention_days)
                )
            widgets_processed += 1
        except Exception:
            errors += 1
            logger.exception(
                "Widget retention purge failed", extra={"widget_id": str(widget_id)}
            )

    summary = {
        "widgets_processed": widgets_processed,
        "sessions_deleted": sessions_deleted,
        "errors": errors,
    }
    logger.info("Widget retention purge completed", extra=summary)
    return summary
