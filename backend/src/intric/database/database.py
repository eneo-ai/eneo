import contextlib
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from intric.main.logging import get_logger

logger = get_logger(__name__)


class DatabaseSessionManager:
    def __init__(self):
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None

    def init(self, host: str):
        # If already initialized, don't reinitialize (important for tests)
        if self._engine is not None:
            logger.debug("Database already initialized, skipping reinitialization")
            return

        self._engine = create_async_engine(host, pool_size=20, max_overflow=10)
        self._sessionmaker = async_sessionmaker(
            autocommit=False, bind=self._engine, autobegin=False
        )
        logger.debug(f"Database connected to {host}")

    async def close(self):
        if self._engine is None:
            logger.debug("DatabaseSessionManager already closed or not initialized")
            return
        await self._engine.dispose()
        self._engine = None
        self._sessionmaker = None
        logger.debug("DatabaseSessionManager closed")

    @contextlib.asynccontextmanager
    async def connect(self) -> AsyncIterator[AsyncConnection]:
        if self._engine is None:
            raise Exception("DatabaseSessionManager is not initialized")

        async with self._engine.begin() as connection:
            try:
                yield connection
            except Exception:
                await connection.rollback()
                raise

    @contextlib.asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        if self._sessionmaker is None:
            raise Exception("DatabaseSessionManager is not initialized")

        session = self._sessionmaker()
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


sessionmanager = DatabaseSessionManager()


async def get_session_with_transaction():
    async with sessionmanager.session() as session, session.begin():
        yield session


async def get_session():
    async with sessionmanager.session() as session:
        yield session
