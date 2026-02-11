from urllib.parse import urlparse

from intric.allowed_origins.allowed_origin_repo import AllowedOriginRepository
from intric.allowed_origins.origin_matching import origin_matches_pattern
from intric.database.database import sessionmanager
from intric.main.logging import get_logger

logger = get_logger(__name__)


async def get_origin(origin: str):
    parsed = urlparse(origin)
    if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        return True

    async with sessionmanager.session() as session, session.begin():
        repo = AllowedOriginRepository(session)
        allowed_origins = await repo.get_all()
        matches = any(origin_matches_pattern(origin, entry.url) for entry in allowed_origins)

        logger.debug(
            f"Origin attempted to be resolved from database, success = {matches}"
        )

        return matches
