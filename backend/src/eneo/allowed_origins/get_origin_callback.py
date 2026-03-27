from eneo.allowed_origins.allowed_origin_repo import AllowedOriginRepository
from eneo.database.database import sessionmanager
from eneo.main.logging import get_logger

logger = get_logger(__name__)


async def get_origin(origin: str):
    async with sessionmanager.session() as session, session.begin():
        repo = AllowedOriginRepository(session)
        origin = await repo.get_origin(origin)

        logger.debug(
            f"Origin attempted to be resolved from database, success = {origin is not None}"
        )

        return origin is not None
