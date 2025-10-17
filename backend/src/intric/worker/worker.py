from __future__ import annotations

import inspect
from functools import wraps
from typing import Callable
from uuid import UUID

import crochet
from arq.connections import RedisSettings
from arq.cron import cron
from dependency_injector import providers

from intric.database.database import AsyncSession, sessionmanager
from intric.jobs.task_models import ResourceTaskParams
from intric.main.config import get_settings
from intric.main.container.container import Container
from intric.main.container.container_overrides import override_user
from intric.main.logging import get_logger
from intric.main.models import ChannelType
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
        self.job_timeout = settings.crawl_max_length + 60 * 60  # crawl window + 1h buffer
        self.max_jobs = settings.worker_max_jobs
        self.expires_extra_ms = 604800000  # 1 week

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

    async def shutdown(self, ctx):
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

                async with sessionmanager.session() as session:
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
