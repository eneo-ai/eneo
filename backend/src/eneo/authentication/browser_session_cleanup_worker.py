"""Nightly deletion of expired browser sessions.

An expired session admits nothing (``BrowserSessionService.admit`` checks the
expiry), so its row only takes space until this job deletes it.
"""

from eneo.main.container.container import Container
from eneo.main.logging import get_logger
from eneo.worker.worker import Worker

logger = get_logger(__name__)
worker = Worker()


@worker.cron_job(hour=0, minute=30)  # Daily at 00:30 UTC
async def delete_expired_browser_sessions(container: Container) -> int:
    deleted = await container.browser_session_service().delete_expired()
    logger.info("Deleted expired browser sessions", extra={"deleted": deleted})
    return deleted
