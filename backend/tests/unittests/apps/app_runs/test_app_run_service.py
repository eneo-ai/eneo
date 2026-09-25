from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from eneo.ai_models.completion_models.completion_model import Completion
from eneo.apps.app_runs.app_run_service import AppRunService
from eneo.apps.apps.app_service import AppExecutionPlan, AppExecutionResult
from eneo.completion_models.infrastructure.context_builder import count_tokens
from eneo.skills.domain.skill import SkillExecutionReference


async def test_update_tokens_in_run():
    # Setup
    app_run_service = AppRunService(
        MagicMock(id=1), AsyncMock(), MagicMock(), AsyncMock(), AsyncMock(), AsyncMock()
    )

    app_run = MagicMock(user_id=1, skill_provenance=())
    app_run_service.repo.get.return_value = app_run

    completion = Completion(text="This is the output!")
    response = MagicMock(completion=completion, total_token_count=10, usage=None)
    app_run_service.app_service.run_app.return_value = AppExecutionResult(
        response=response,
        skill_provenance=(),
    )

    app_id = uuid4()
    app_run_id = uuid4()
    file_ids = [uuid4()]

    # Execute
    await app_run_service.run_app(app_id, app_run_id, file_ids, "input")

    # Assert
    num_tokens_output = count_tokens(completion.text)
    app_run.update.assert_called_once_with(
        output=completion.text,
        num_tokens_input=10,
        num_tokens_output=num_tokens_output,
        skill_provenance=(),
    )
    app_run_service.app_service.run_app.assert_awaited_once_with(
        app_id,
        file_ids=file_ids,
        text="input",
        skill_provenance=(),
    )


async def test_queue_app_run_persists_selected_skill_revisions_before_job():
    reference = SkillExecutionReference(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        revision_number=2,
        content_digest="a" * 64,
        position=0,
    )
    app = MagicMock(id=uuid4(), name="App")
    app.is_valid_input.return_value = True
    user = MagicMock(id=uuid4(), tenant_id=uuid4())
    repo = AsyncMock()
    factory = MagicMock()
    app_service = AsyncMock()
    app_service.prepare_app_run.return_value = AppExecutionPlan(
        app=app,
        skill_provenance=(reference,),
    )
    draft = MagicMock(id=None)
    persisted = MagicMock(id=uuid4())
    factory.create_app_run.return_value = draft
    repo.add.return_value = persisted
    repo.update.return_value = persisted
    job_service = AsyncMock()
    job_service.queue_job.return_value = MagicMock(id=uuid4())
    file_service = AsyncMock()
    file_service.get_file_infos.return_value = []
    service = AppRunService(
        user=user,
        repo=repo,
        factory=factory,
        app_service=app_service,
        job_service=job_service,
        file_service=file_service,
    )

    await service.queue_app_run(app.id, file_ids=[], text="input")

    assert factory.create_app_run.call_args.kwargs["skill_provenance"] == (reference,)
    repo.add.assert_awaited_once_with(draft)
    job_service.queue_job.assert_awaited_once()
