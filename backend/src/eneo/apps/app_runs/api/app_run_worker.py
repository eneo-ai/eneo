from eneo.apps.app_runs.api.app_run_models import AppRunParams
from eneo.main.container.container import Container
from eneo.main.models import ChannelType
from eneo.worker.task_manager import WorkerConfig
from eneo.worker.worker import Worker

worker = Worker()


@worker.task(channel_type=ChannelType.APP_RUN_UPDATES)
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
        text=params.text,
    )
