import contextlib
import os
import time
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.inspection import inspect

from intric.main.config import get_settings
from intric.main.logging import get_logger

logger = get_logger(__name__)


class SafeAsyncSession(AsyncSession):
    """AsyncSession subclass that tolerates refresh() on non-ORM objects."""

    async def refresh(self, instance, attribute_names=None, with_for_update=None):  # type: ignore[override]
        state = inspect(instance, raiseerr=False)
        if state is None:
            logger.debug(
                "SafeAsyncSession.refresh skipped unmapped instance",
                extra={"instance_type": type(instance).__name__},
            )
            return None

        return await super().refresh(
            instance,
            attribute_names=attribute_names,
            with_for_update=with_for_update,
        )


class DatabaseSessionManager:
    def __init__(self):
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None
        self._pool_events_registered: bool = False  # Guard against double event registration

    def init(self, host: str):
        # If already initialized, don't reinitialize (important for tests)
        if self._engine is not None:
            logger.debug("Database already initialized, skipping reinitialization")
            return

        settings = get_settings()

        # Build connection URL with application_name for pg_stat_activity attribution
        # Why: Makes it easy to identify which connections belong to which worker in PostgreSQL
        worker_name = os.getenv("WORKER_NAME", f"intric-{os.getpid()}")
        connect_args = {"server_settings": {"application_name": worker_name}}

        # Build kwargs dict - conditionally include pool_recycle only when enabled
        # Why: Omitting the kwarg is safest across SQLAlchemy versions (avoids None pitfall)
        kwargs = dict(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_pool_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_pre_ping=settings.db_pool_pre_ping,
            connect_args=connect_args,
        )
        if settings.db_pool_recycle and settings.db_pool_recycle > 0:
            kwargs["pool_recycle"] = settings.db_pool_recycle

        self._engine = create_async_engine(host, **kwargs)

        # Singleton engine verification logging
        # Why: Ensures only ONE engine exists per process (multiple engines = pool multiplication)
        logger.info(
            "Database engine initialized",
            extra={
                "engine_id": id(self._engine),
                "pool_id": id(self._engine.sync_engine.pool),
                "pid": os.getpid(),
                "pool_size": settings.db_pool_size,
                "max_overflow": settings.db_pool_max_overflow,
                "application_name": worker_name,
            },
        )

        # Pool checkout duration logging (behind feature flag)
        # Why: Proves "hour-long holds" during pool exhaustion debugging
        # IMPORTANT: Use sync_engine.pool for async engines (async wraps sync internally)
        # Guard against double-registration in case of DI lifecycle oddities
        if settings.db_pool_debug and not self._pool_events_registered:
            sync_pool = self._engine.sync_engine.pool

            @event.listens_for(sync_pool, "checkout")
            def receive_checkout(dbapi_connection, connection_record, connection_proxy):
                connection_record.info["checkout_time"] = time.time()
                connection_record.info["checkout_pid"] = os.getpid()

            @event.listens_for(sync_pool, "checkin")
            def receive_checkin(dbapi_connection, connection_record):
                checkout_time = connection_record.info.get("checkout_time")
                if checkout_time:
                    duration = time.time() - checkout_time
                    if duration > 60:  # Log if held > 60 seconds
                        logger.warning(
                            f"Connection held for {duration:.1f}s",
                            extra={"pid": connection_record.info.get("checkout_pid")},
                        )

            self._pool_events_registered = True
            logger.info("Pool checkout duration logging enabled (DB_POOL_DEBUG=true)")

        self._sessionmaker = async_sessionmaker(
            autocommit=False,
            bind=self._engine,
            autobegin=False,
            class_=SafeAsyncSession,
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

    def create_session(self) -> AsyncSession:
        """Create a raw AsyncSession without context manager wrapper.

        WARNING: The caller is responsible for closing this session!
        Useful for manual recovery workflows where context managers are not viable.

        This avoids the orphaned async generator bug that occurs when using
        `await sessionmanager.session().__aenter__()` - that pattern creates
        an unreferenced context manager that GC may finalize at arbitrary times,
        causing spurious session.close() calls during active operations.
        """
        if self._sessionmaker is None:
            raise Exception("DatabaseSessionManager is not initialized")
        return self._sessionmaker()

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
