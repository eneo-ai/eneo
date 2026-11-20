from collections.abc import Awaitable, Callable
from typing import cast
from uuid import UUID

from eneo.apps.app_runs.api.app_run_models import AppRunParams
from eneo.apps.app_runs.app_run_dispatch import claim_app_job, reconcile_app_runs
from eneo.database.database import AsyncSession
from eneo.jobs.job_manager import DURABLE_APP_FUNCTION
from eneo.main.container.container import Container
from eneo.main.logging import get_logger
from eneo.main.models import Channel, ChannelType, RedisMessage, Status
from eneo.worker.task_manager import WorkerConfig, publish_task_status
from eneo.worker.worker import Worker

worker = Worker()
logger = get_logger(__name__)


def _update_data(
    app_id: UUID | None, space_id: UUID | None, *, personal: bool
) -> dict[str, object]:
    return {"app_id": app_id, "space": {"id": space_id, "personal": personal}}


# A worker can die after a provider accepted the request. Reaping lets the
# user retry explicitly instead of ARQ repeating the provider call.
@worker.task(
    channel_type=ChannelType.APP_RUN_UPDATES,
    keep_result=0,
    max_tries=1,
    claim_before_run=claim_app_job,
    function_alias=DURABLE_APP_FUNCTION,
)
async def run_app(
    params: AppRunParams,
    container: Container,
    worker_config: WorkerConfig,
    checkpoint: Callable[[], Awaitable[None]],
):
    app_service = container.app_service(
        transcriber=container.transcriber(after_transcription_saved=checkpoint)
    )
    app_run_service = container.app_run_service(app_service=app_service)
    space_service = container.space_service()

    app, _ = await app_service.get_app(params.app_id)
    space = await space_service.get_space(app.space_id)

    worker_config.set_additional_data(
        _update_data(app.id, space.id, personal=space.is_personal())
    )

    await app_run_service.run_app(
        app_run_id=params.id,
        app_id=params.app_id,
        file_ids=params.file_ids,
    )


@worker.cron_job(manages_own_session=True, run_at_startup=True)
async def reconcile_app_run_jobs(container: Container) -> None:
    session = cast(AsyncSession, container.session())
    async with session.begin():
        failed_ids = await reconcile_app_runs(session)
        if not failed_ids:
            return

        targets = await container.app_run_repo().get_update_targets_for_jobs(failed_ids)

    logger.warning("Expired app runs failed", extra={"count": len(failed_ids)})
    for run_id, user_id, app_id, space_id, personal in targets:
        await publish_task_status(
            Channel(type=ChannelType.APP_RUN_UPDATES, user_id=user_id),
            RedisMessage(
                id=run_id,
                status=Status.FAILED,
                additional_data=_update_data(app_id, space_id, personal=personal),
            ),
        )
