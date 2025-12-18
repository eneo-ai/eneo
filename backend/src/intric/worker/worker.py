from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone
from functools import wraps
from typing import Callable
from uuid import UUID

import crochet
import sqlalchemy as sa
from arq.connections import RedisSettings
from arq.cron import cron
from dependency_injector import providers

from intric.database.database import AsyncSession, sessionmanager
from intric.jobs.task_models import ResourceTaskParams
from intric.main.config import get_settings
from intric.main.container.container import Container, SessionProxy
from intric.main.container.container_overrides import override_user
from intric.main.logging import get_logger
from intric.main.models import ChannelType, Status
from intric.server.dependencies import lifespan
from intric.worker.task_manager import TaskManager, WorkerConfig

logger = get_logger(__name__)


class Worker:
    """
    Worker class responsible for managing and executing functions, tasks, and cron jobs.

    Attributes:
        functions (list): List of registered functions.
        cron_jobs (list): List of registered cron jobs.
        redis_settings (RedisSettings): Redis settings for the worker.
        on_startup (callable): Function to call on startup.
        on_shutdown (callable): Function to call on shutdown.
        retry_jobs (bool): Flag to indicate if jobs should be retried.
        job_timeout (int): Timeout for jobs in seconds.
        max_jobs (int): Maximum number of jobs.
        expires_extra_ms (int): Extra expiration time in milliseconds.

    Methods:
        _create_container(session: AsyncSession) -> Container:
            Creates a dependency injection container with the given session.

        _override_user_if_required(container: Container, user_id: UUID):
            Overrides the user in the container if required.

        startup(ctx):
            Starts up the worker and sets up necessary configurations.

        shutdown(ctx):
            Shuts down the worker and performs cleanup.

        function(with_user: bool = True):
            Decorator to register a function with optional user context.

        task(with_user: bool = True):
            Decorator to register a task with optional user context.

        cron_job(**decorator_kwargs):
            Decorator to register a cron job with additional arguments.

        include_subworker(sub_worker: Worker):
            Includes functions and cron jobs from a sub-worker.
    """

    def __init__(self):
        settings = get_settings()
        self.functions = []
        self.cron_jobs = []
        self.redis_settings = RedisSettings(
            host=settings.redis_host, port=settings.redis_port
        )
        self.on_startup = self.startup
        self.on_shutdown = self.shutdown
        self.retry_jobs = False
        # Job timeout is a safety net - uses global env default as upper bound.
        # Per-tenant crawl timeouts are enforced by asyncio.wait_for() in crawler.py
        # which respects tenant-specific crawl_max_length settings.
        self.job_timeout = settings.crawl_max_length + 60 * 60  # crawl window + 1h buffer
        self.max_jobs = settings.worker_max_jobs
        self.expires_extra_ms = 604800000  # 1 week

        # ARQ v0.26+ features for improved job management
        # allow_abort_jobs: Enables job.abort() to cancel running/queued jobs
        # Why: Allows preemption of stale jobs without complex Compare-and-Swap SQL
        self.allow_abort_jobs = True

        # health_check_interval: How often to update worker health key in Redis
        self.health_check_interval = 60  # seconds (default is 3600)

        # job_completion_wait: Time to wait for jobs to complete on shutdown
        # Allows Scrapy/Twisted reactor cleanup via crochet
        self.job_completion_wait = 60  # seconds

        # ARQ lifecycle hooks for centralized job status management
        # These run for ALL job types, providing consistent state tracking
        self.on_job_start = self._on_job_start
        self.after_job_end = self._after_job_end

    async def _on_job_start(self, ctx: dict) -> None:
        """ARQ hook: Called before each job starts.

        Updates job status to IN_PROGRESS in the database.
        This centralizes status management that was previously scattered.

        Args:
            ctx: ARQ context containing job_id, job_try, enqueue_time
        """
        job_id = ctx.get("job_id")
        if not job_id:
            return

        try:
            # Import here to avoid circular import
            from intric.database.tables.job_table import Jobs

            async with sessionmanager.session() as session:
                async with session.begin():
                    # Use direct SQL to avoid session lifecycle issues
                    stmt = (
                        sa.update(Jobs)
                        .where(Jobs.id == UUID(job_id))
                        .values(
                            status=Status.IN_PROGRESS.value,
                            updated_at=datetime.now(timezone.utc),
                        )
                    )
                    await session.execute(stmt)

            logger.debug(
                "Job started (ARQ hook)",
                extra={"job_id": job_id, "job_try": ctx.get("job_try", 1)},
            )
        except Exception as exc:
            # Don't fail the job if status update fails
            logger.warning(
                "Failed to update job status on start",
                extra={"job_id": job_id, "error": str(exc)},
            )

    async def _after_job_end(self, ctx: dict) -> None:
        """ARQ hook: Called after each job ends AND result is recorded.

        This is the final hook in the job lifecycle. The job's actual status
        should already be set by the task itself (complete/failed), so we just
        log for observability. Could be extended to sync with external systems.

        Args:
            ctx: ARQ context containing job_id, result, and any exception
        """
        job_id = ctx.get("job_id")
        if not job_id:
            return

        # Log job completion for observability
        result = ctx.get("result")
        logger.debug(
            "Job ended (ARQ hook)",
            extra={
                "job_id": job_id,
                "job_try": ctx.get("job_try", 1),
                "success": result is not None and not isinstance(result, Exception),
            },
        )

    async def _create_container(
        self,
        session: AsyncSession,
        user_id: UUID | None = None,
    ) -> Container:
        container = Container(session=providers.Object(session))
        if user_id is not None:
            await self._override_user(container=container, user_id=user_id)
        return container

    async def _override_user(self, container: Container, user_id: UUID):
        user_repo = container.user_repo()
        user = await user_repo.get_user_by_id(id=user_id)
        override_user(container=container, user=user)

    def _get_kwargs(self, func: Callable, task_manager: TaskManager):
        sig = inspect.signature(func)
        parameters = {k for k in sig.parameters if k not in {"params", "container"}}
        kwargs = {}

        if "worker_config" in parameters:
            kwargs["worker_config"] = WorkerConfig(task_manager=task_manager)

        return kwargs

    async def startup(self, ctx):
        await lifespan.startup()
        crochet.setup()

        # Start crawl feeder as background task if enabled
        # Why: Meters job enqueue rate to prevent burst overload during scheduled crawls
        # Uses leader election to ensure only ONE feeder runs across all workers
        settings = get_settings()
        if settings.crawl_feeder_enabled:
            from intric.worker.crawl_feeder import CrawlFeeder

            try:
                # CrawlFeeder is now container-independent
                # Why: It manages its own DB sessions and Redis client to avoid
                # session lifecycle issues (session closing while feeder runs)
                feeder = CrawlFeeder()

                # Start feeder as background task
                # Why: Runs concurrently with worker jobs in same event loop
                task = asyncio.create_task(feeder.run_forever())

                # Store references for cleanup on shutdown
                # Why: Allows graceful cancellation and prevents GC
                ctx["feeder_task"] = task
                ctx["feeder"] = feeder  # Store feeder for proper stop() call

                logger.info(
                    "Started crawl feeder background task with leader election",
                    extra={"feeder_enabled": True},
                )
            except Exception as exc:
                logger.error(
                    f"Failed to start crawl feeder: {exc}. Continuing without feeder.",
                    extra={"feeder_enabled": False},
                )

    async def shutdown(self, ctx):
        # Stop feeder gracefully if running
        # Why: Prevents orphaned background tasks and closes Redis connection
        if "feeder" in ctx:
            feeder = ctx["feeder"]
            logger.info("Stopping crawl feeder background task")
            await feeder.stop()  # Gracefully stop and close Redis

        if "feeder_task" in ctx:
            task = ctx["feeder_task"]
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass  # Expected on cancellation

        await lifespan.shutdown()

    def function(self, with_user: bool = True):
        def decorator(func):
            @wraps(func)
            async def wrapper(*args):
                ctx, params = args[0], args[1]
                logger.debug(
                    f"Executing {func.__name__} with context {ctx} and params {params}"
                )

                async with sessionmanager.session() as session, session.begin():
                    user_id = params.user_id if with_user else None
                    container = await self._create_container(session, user_id=user_id)
                    return await func(ctx["job_id"], params, container=container)

            self.functions.append(wrapper)
            return wrapper

        return decorator

    def long_running_function(self, with_user: bool = True):
        """Decorator for long-running tasks (crawls, batch jobs).

        Unlike function(), this does NOT hold a database session for the entire
        task duration. Instead:

        1. BOOTSTRAP PHASE (~50ms): Short-lived session to look up user
        2. EXECUTION PHASE: Task runs with sessionless container
        3. DB OPERATIONS: Task uses Container.session_scope() for each DB op

        This prevents DB pool exhaustion for tasks that run minutes to hours.
        The task is responsible for managing its own DB sessions via session_scope().

        Example:
            @worker.long_running_function()
            async def crawl(job_id, params, container):
                # NO session held here - use session_scope for DB ops:
                async with container.session_scope() as session:
                    repo = container.some_repo(session=session)
                    await repo.update(...)
                # Session returned to pool immediately
        """
        def decorator(func):
            @wraps(func)
            async def wrapper(*args):
                ctx, params = args[0], args[1]
                logger.debug(
                    f"Executing long-running {func.__name__} with context {ctx}"
                )

                # PHASE 1: Bootstrap - short-lived session for user lookup only
                # Pattern: Query ORM → Convert to Pydantic INSIDE session → Return pure Python data
                # Why: Pydantic model is session-independent, safe to use after session closes
                user = None
                if with_user and hasattr(params, "user_id") and params.user_id:
                    async with sessionmanager.session() as session:
                        async with session.begin():
                            # Import here to avoid circular imports at module level
                            from sqlalchemy.orm import selectinload
                            from intric.database.tables.users_table import Users
                            from intric.database.tables.tenant_table import Tenants
                            from intric.users.user import UserInDB

                            # Query with ALL selectinload options (exact match with UsersRepository._get_options())
                            # CRITICAL: Every relationship field in UserInDB must be loaded here.
                            # Missing any relationship causes MissingGreenlet/DetachedInstanceError
                            # when Pydantic tries to validate (triggers lazy load in async context).
                            stmt = (
                                sa.select(Users)
                                .where(Users.id == params.user_id)
                                .where(Users.deleted_at.is_(None))  # Soft-delete safety
                                .options(
                                    selectinload(Users.roles),
                                    selectinload(Users.predefined_roles),
                                    selectinload(Users.tenant).selectinload(Tenants.modules),
                                    selectinload(Users.api_key),
                                    selectinload(Users.user_groups),
                                )
                            )
                            result = await session.execute(stmt)
                            user_row = result.scalar_one_or_none()
                            if user_row:
                                # Convert ORM → Pydantic INSIDE session (while relationships accessible)
                                # This creates a pure Python object with no ORM bindings.
                                # No expunge() needed - we're not using the ORM object after this.
                                user = UserInDB.model_validate(user_row)
                    # Session returned to pool HERE (~50ms total)
                    # `user` is now a Pydantic model - pure Python data, session-independent

                # PHASE 2: Create sessionless container with SessionProxy
                # Inject SessionProxy() instead of None. This allows dependencies (like JobRepo)
                # to be instantiated without failing type validation. The proxy delegates to
                # the ContextVar set by session_scope(), raising a clear error if accessed
                # outside a scope instead of cryptic "None is not AsyncSession" during DI.
                container = Container(session=providers.Object(SessionProxy()))

                # Override user if found during bootstrap
                if user is not None:
                    from intric.main.container.container_overrides import override_user
                    override_user(container=container, user=user)

                # PHASE 3: Execute task - NO session held
                # Task uses Container.session_scope() for DB operations
                logger.debug(
                    f"Starting long-running task {func.__name__} (sessionless)",
                    extra={"job_id": ctx.get("job_id")},
                )
                return await func(ctx["job_id"], params, container=container)

            self.functions.append(wrapper)
            return wrapper

        return decorator

    def task(
        self,
        with_user: bool = True,
        channel_type: ChannelType | None = None,
    ):
        def decorator(func):
            @wraps(func)
            async def wrapper(*args):
                ctx: dict = args[0]
                params: ResourceTaskParams = args[1]
                logger.debug(
                    f"Executing {func.__name__} with context {ctx} and params {params}"
                )

                async with sessionmanager.session() as session, session.begin():
                    user_id = params.user_id if with_user else None
                    container = await self._create_container(session, user_id=user_id)

                    task_manager = container.task_manager(
                        job_id=ctx["job_id"],
                        resource_id=params.id,
                        channel_type=channel_type,
                    )
                    optional_kwargs = self._get_kwargs(func, task_manager=task_manager)

                    async with task_manager.set_status_on_exception():
                        task_manager.result_location = await func(
                            params, container=container, **optional_kwargs
                        )

                    return task_manager.successful()

            self.functions.append(wrapper)
            return wrapper

        return decorator

    def cron_job(self, **decorator_kwargs):
        def decorator(func):
            @wraps(func)
            async def wrapper(*args):
                logger.debug(f"Executing {func.__name__}")

                async with sessionmanager.session() as session, session.begin():
                    container = await self._create_container(session)

                    return await func(container=container)

            self.cron_jobs.append(cron(wrapper, **decorator_kwargs))
            return wrapper

        return decorator

    def include_subworker(self, sub_worker: Worker):
        self.functions.extend(sub_worker.functions)
        self.cron_jobs.extend(sub_worker.cron_jobs)

        logger.debug(
            "Including functions from subworker: %s",
            [func.__name__ for func in sub_worker.functions],
        )
        logger.debug(
            "Including cron jobs from subworker: %s",
            sub_worker.cron_jobs,
        )
