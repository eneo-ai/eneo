# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from datetime import timedelta

from eneo.database.database import sessionmanager
from eneo.main.logging import get_logger
from eneo.widgets.application.widget_limits import WidgetBudget
from eneo.widgets.domain.widget_policy import WidgetPolicy
from eneo.widgets.infrastructure.widget_usage_repo_impl import WidgetUsageRepoImpl

logger = get_logger(__name__)


async def purge_expired_widget_sessions() -> dict[str, int]:
    """Delete widget conversations older than each widget's retention.

    The only job that deletes widget conversations (the generic conversation
    retention leaves them alone). A widget's retention is held to its
    tenant's policy window as it stands tonight, not as it stood when the
    widget was saved. One transaction per widget so a failure on one
    tenant's widget never rolls back another's deletions.
    """
    async with sessionmanager.session() as session, session.begin():
        repo = WidgetUsageRepoImpl(session)
        targets = await repo.retention_targets()

    widgets_processed = 0
    sessions_deleted = 0
    errors = 0
    for target in targets:
        try:
            retention_days = WidgetPolicy.from_tenant(
                target.tenant_policy
            ).retention_days_for(target.retention_days)
            async with sessionmanager.session() as session, session.begin():
                repo = WidgetUsageRepoImpl(session)
                sessions_deleted += await repo.delete_sessions_before(
                    target.widget_id, repo.cutoff_for(retention_days)
                )
            widgets_processed += 1
        except Exception:
            errors += 1
            logger.exception(
                "Widget retention purge failed",
                extra={"widget_id": str(target.widget_id)},
            )

    # Accounting maintenance must never prevent conversation retention.
    try:
        async with sessionmanager.session() as session, session.begin():
            await WidgetUsageRepoImpl(session).prune_budget_receipts(
                WidgetBudget().today() - timedelta(days=7)
            )
    except Exception:
        errors += 1
        logger.exception("Widget budget receipt cleanup failed")

    summary = {
        "widgets_processed": widgets_processed,
        "sessions_deleted": sessions_deleted,
        "errors": errors,
    }
    logger.info("Widget retention purge completed", extra=summary)
    return summary
