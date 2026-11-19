from datetime import datetime, timedelta, timezone
from typing import cast

import sqlalchemy as sa

from eneo.apps.app_runs.api.app_run_models import AppRunParams
from eneo.database.database import AsyncSession
from eneo.database.tables.app_table import AppRuns, Apps
from eneo.database.tables.spaces_table import Spaces
from eneo.jobs.job_models import JobFailureCode, Task
from eneo.main.container.container import Container
from eneo.main.logging import get_logger
from eneo.main.models import Channel, ChannelType, RedisMessage, Status
from eneo.worker.task_manager import WorkerConfig, publish_task_status
from eneo.worker.worker import Worker

worker = Worker()
logger = get_logger(__name__)

# This is a queue wait budget. A running task holds its job row lock and is
# skipped even if a long transcription exceeds the budget.
APP_RUN_QUEUE_TIMEOUT = timedelta(hours=2)
APP_RUN_REAPER_BATCH_SIZE = 50


@worker.task(channel_type=ChannelType.APP_RUN_UPDATES, keep_result=0)
async def run_app(
    params: AppRunParams, container: Container, worker_config: WorkerConfig
):
    app_run_service = container.app_run_service()
    app_service = container.app_service()
    space_service = container.space_service()

    app, _ = await app_service.get_app(params.app_id)
    space = await space_service.get_space(app.space_id)

    additional_data = {
        "app_id": app.id,
        "space": {"id": space.id, "personal": space.is_personal()},
    }
    worker_config.set_additional_data(additional_data)

    await app_run_service.run_app(
        app_run_id=params.id,
        app_id=params.app_id,
        file_ids=params.file_ids,
    )


@worker.cron_job(manages_own_session=True, run_at_startup=True)
async def fail_expired_app_runs(container: Container) -> None:
    session = cast(AsyncSession, container.session())
    async with session.begin():
        failed_ids = await container.job_repo().mark_stale_jobs_failed(
            tasks=[Task.RUN_APP.value],
            stale_before=datetime.now(timezone.utc) - APP_RUN_QUEUE_TIMEOUT,
            limit=APP_RUN_REAPER_BATCH_SIZE,
            failure_code=JobFailureCode.PROCESSING_INTERRUPTED,
        )
        if not failed_ids:
            return

        targets = (
            (
                await session.execute(
                    sa.select(
                        AppRuns.id,
                        AppRuns.user_id,
                        AppRuns.app_id,
                        Spaces.id,
                        Spaces.user_id.is_not(None),
                    )
                    .join(Apps, Apps.id == AppRuns.app_id)
                    .join(Spaces, Spaces.id == Apps.space_id)
                    .where(AppRuns.job_id.in_(failed_ids))
                )
            )
            .tuples()
            .all()
        )

    logger.warning("Expired app runs failed", extra={"count": len(failed_ids)})
    for run_id, user_id, app_id, space_id, personal in targets:
        await publish_task_status(
            Channel(type=ChannelType.APP_RUN_UPDATES, user_id=user_id),
            RedisMessage(
                id=run_id,
                status=Status.FAILED,
                additional_data={
                    "app_id": app_id,
                    "space": {"id": space_id, "personal": personal},
                },
            ),
        )
