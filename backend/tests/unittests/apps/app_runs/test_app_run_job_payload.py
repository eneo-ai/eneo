"""An App run job carries ids; the worker reads the prompt from the stored run."""

import inspect
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from eneo.ai_models.completion_models.completion_model import Completion
from eneo.apps.app_runs.api.app_run_models import AppRunParams
from eneo.apps.app_runs.api.app_run_worker import run_app
from eneo.apps.app_runs.app_run_service import AppRunService
from eneo.apps.apps.app_service import AppExecutionPlan, AppExecutionResult


def _service(user: MagicMock) -> AppRunService:
    return AppRunService(
        user=user,
        repo=AsyncMock(),
        factory=MagicMock(),
        app_service=AsyncMock(),
        job_service=AsyncMock(),
        file_service=AsyncMock(),
    )


async def test_queued_app_run_params_carry_no_prompt_text():
    """Mutants: the service puts the prompt into the queued job; the prompt is
    no longer stored on the App run, so the worker has nothing to read."""
    user = MagicMock(id=uuid4(), tenant_id=uuid4())
    service = _service(user)
    app = MagicMock(id=uuid4(), name="App")
    app.is_valid_input.return_value = True
    service.app_service.prepare_app_run.return_value = AppExecutionPlan(  # pyright: ignore[reportAttributeAccessIssue]
        app=app, skill_provenance=()
    )
    service.file_service.get_file_infos.return_value = []  # pyright: ignore[reportAttributeAccessIssue]
    service.repo.add.return_value = MagicMock(id=uuid4())  # pyright: ignore[reportAttributeAccessIssue]
    service.job_service.queue_job.return_value = MagicMock(id=uuid4())  # pyright: ignore[reportAttributeAccessIssue]

    await service.queue_app_run(app.id, file_ids=[], text="secret prompt")

    params = service.job_service.queue_job.call_args.kwargs["task_params"]  # pyright: ignore[reportAttributeAccessIssue]
    assert isinstance(params, AppRunParams)
    assert params.text is None
    assert "secret prompt" not in repr(params.model_dump())
    assert service.factory.create_app_run.call_args.kwargs["text"] == "secret prompt"  # pyright: ignore[reportAttributeAccessIssue]


async def test_worker_runs_the_stored_prompt_even_when_an_old_payload_has_text():
    """Mutants: the worker forwards the payload's text to the run; an old
    payload that still carries text no longer parses."""
    user = MagicMock(id=uuid4(), tenant_id=uuid4())
    service = _service(user)
    app_run = MagicMock(
        user_id=user.id, skill_provenance=(), input_text="stored prompt"
    )
    service.repo.get.return_value = app_run  # pyright: ignore[reportAttributeAccessIssue]
    service.app_service.run_app.return_value = AppExecutionResult(  # pyright: ignore[reportAttributeAccessIssue]
        response=MagicMock(
            completion=Completion(text="output"), total_token_count=1, usage=None
        ),
        skill_provenance=(),
    )
    app = MagicMock(id=uuid4(), space_id=uuid4())
    container = MagicMock()
    container.app_run_service.return_value = service
    container.app_service.return_value.get_app = AsyncMock(return_value=(app, None))
    container.space_service.return_value.get_space = AsyncMock(return_value=MagicMock())
    file_ids = [uuid4()]
    params = AppRunParams.model_validate(
        {
            "id": uuid4(),
            "user_id": user.id,
            "app_id": app.id,
            "file_ids": file_ids,
            "text": "stale payload text",
        }
    )

    await inspect.unwrap(run_app)(
        params, container=container, worker_config=MagicMock()
    )

    service.app_service.run_app.assert_awaited_once_with(  # pyright: ignore[reportAttributeAccessIssue]
        app.id, file_ids=file_ids, text="stored prompt", skill_provenance=()
    )
