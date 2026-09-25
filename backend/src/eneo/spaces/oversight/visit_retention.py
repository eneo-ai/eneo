# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.

from datetime import datetime, timedelta, timezone

from eneo.database.database import sessionmanager
from eneo.main.logging import get_logger
from eneo.spaces.oversight.domain import OVERSIGHT_VISIT_WINDOW_DAYS
from eneo.spaces.oversight.visit_repo import OversightVisitRepo

logger = get_logger(__name__)


async def purge_ended_oversight_visits() -> dict[str, int]:
    """Delete oversight visits that members no longer see: those that ended
    more than OVERSIGHT_VISIT_WINDOW_DAYS ago, in every tenant. The audit log
    keeps the join and the leave under its own retention."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=OVERSIGHT_VISIT_WINDOW_DAYS)
    async with sessionmanager.session() as session, session.begin():
        deleted = await OversightVisitRepo(session).delete_ended_before(cutoff)
    summary = {"visits_deleted": deleted}
    logger.info("Oversight visit purge completed", extra=summary)
    return summary
