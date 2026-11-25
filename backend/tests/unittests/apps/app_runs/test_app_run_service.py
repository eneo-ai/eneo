import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.ai_models.completion_models.completion_model import Completion
from eneo.apps.app_runs.api.app_run_models import AppRunParams
from eneo.apps.app_runs.app_run import AppRun
from eneo.apps.app_runs.app_run_factory import AppRunFactory
from eneo.apps.app_runs.app_run_service import AppRunService
from eneo.apps.apps.app_service import AppExecutionPlan, AppExecutionResult
from eneo.completion_models.infrastructure.context_builder import count_tokens
from eneo.jobs.job_models import JobInDb, Task
from eneo.jobs.job_service import JobService
from eneo.main.exceptions import UnauthorizedException
from eneo.main.models import Status
from eneo.skills.domain.skill import SkillExecutionReference
from tests.fixtures import TEST_USER


async def test_update_tokens_in_run():
    # Setup
    app_run_service = AppRunService(
        MagicMock(id=1), AsyncMock(), MagicMock(), AsyncMock(), AsyncMock(), AsyncMock()
    )

    app_run = MagicMock(user_id=1, skill_provenance=(), input_text="input")
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
    await app_run_service.run_app(app_id, app_run_id, file_ids)

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
    assert job_service.queue_job.call_args.kwargs["after_commit"] is True


def _service_with_real_job_service(
    session: AsyncSession, job_id
) -> tuple[AppRunService, MagicMock, AsyncMock]:
    app = MagicMock(id=uuid4())
    app.name = "Meeting transcription"
    app.is_valid_input.return_value = True
    persisted = MagicMock(id=uuid4())
    repo = AsyncMock()
    repo.add.return_value = persisted
    repo.update.return_value = persisted
    factory = MagicMock()
    factory.create_app_run.return_value = MagicMock(id=None)
    app_service = AsyncMock()
    app_service.prepare_app_run.return_value = AppExecutionPlan(
        app=app, skill_provenance=()
    )
    job_repo = MagicMock()
    job_repo.delegate.session = session
    job_repo.add_durable_job = AsyncMock(
        return_value=JobInDb(
            id=job_id,
            user_id=TEST_USER.id,
            task=Task.RUN_APP,
            name=app.name,
            status=Status.QUEUED,
        )
    )
    file_service = AsyncMock()
    file_service.get_file_infos.return_value = []
    service = AppRunService(
        user=TEST_USER,
        repo=repo,
        factory=factory,
        app_service=app_service,
        job_service=JobService(TEST_USER, job_repo),
        file_service=file_service,
    )
    return service, app, repo


async def test_queue_app_run_dispatches_only_after_commit(monkeypatch) -> None:
    enqueue = AsyncMock()
    monkeypatch.setattr("eneo.jobs.job_service.job_manager.enqueue", enqueue)
    session = AsyncSession()
    job_id = uuid4()
    file_ids = [uuid4()]
    service, app, repo = _service_with_real_job_service(session, job_id)

    async with session.begin():
        app_run = await service.queue_app_run(app.id, file_ids=file_ids, text="input")
        app_run.update.assert_called_once_with(job_id=job_id)
        repo.update.assert_awaited_once_with(app_run)
        enqueue.assert_not_awaited()
    await asyncio.sleep(0)
    await session.close()

    enqueue.assert_awaited_once_with(
        Task.RUN_APP,
        job_id,
        AppRunParams(
            id=app_run.id,
            user_id=TEST_USER.id,
            tenant_id=TEST_USER.tenant_id,
            file_ids=file_ids,
            app_id=app.id,
        ),
    )


async def test_queue_app_run_never_dispatches_on_rollback(monkeypatch) -> None:
    enqueue = AsyncMock()
    monkeypatch.setattr("eneo.jobs.job_service.job_manager.enqueue", enqueue)
    session = AsyncSession()
    service, app, _ = _service_with_real_job_service(session, uuid4())

    with pytest.raises(RuntimeError):
        async with session.begin():
            await service.queue_app_run(app.id, file_ids=[], text="input")
            raise RuntimeError("later router step failed")
    await asyncio.sleep(0)
    await session.close()

    enqueue.assert_not_awaited()


def _service_key_user(service_principal_id):
    """The made-up user a service key signs in as: its id is the key's id."""
    key = SimpleNamespace(
        id=uuid4(), ownership="service", service_principal_id=service_principal_id
    )
    return SimpleNamespace(id=key.id, tenant_id=uuid4(), active_api_key=key)


def _run(*, user_id=None, service_principal_id=None) -> AppRun:
    return AppRun(
        created_at=None,
        updated_at=None,
        id=uuid4(),
        job_id=None,
        app_id=uuid4(),
        user_id=user_id,
        tenant_id=uuid4(),
        input_files=[],
        input_text="input",
        output=None,
        user=None,
        num_tokens_input=None,
        num_tokens_output=None,
        skill_provenance=None,
        job=None,
        completion_model_id=uuid4(),
        service_principal_id=service_principal_id,
    )


def _service_reading(user, app_run: AppRun) -> AppRunService:
    repo = AsyncMock()
    repo.get.return_value = app_run
    return AppRunService(user, repo, MagicMock(), AsyncMock(), AsyncMock(), AsyncMock())


async def test_a_service_key_starts_a_run_that_its_principal_owns():
    principal_id = uuid4()
    user = _service_key_user(principal_id)
    app = MagicMock(id=uuid4(), completion_model=MagicMock(id=uuid4()))
    app.name = "Invoice reader"
    app.is_valid_input.return_value = True
    app_service = AsyncMock()
    app_service.prepare_app_run.return_value = AppExecutionPlan(
        app=app, skill_provenance=()
    )

    async def store(app_run: AppRun) -> AppRun:
        app_run.id = app_run.id or uuid4()
        return app_run

    repo = AsyncMock()
    repo.add.side_effect = store
    repo.update.side_effect = store
    job_service = AsyncMock()
    job_service.queue_job.return_value = MagicMock(id=uuid4())
    file_service = AsyncMock()
    file_service.get_file_infos.return_value = []
    service = AppRunService(
        user=user,
        repo=repo,
        factory=AppRunFactory(),
        app_service=app_service,
        job_service=job_service,
        file_service=file_service,
    )

    app_run = await service.queue_app_run(app.id, file_ids=[], text="input")

    assert app_run.user_id is None
    assert app_run.service_principal_id == principal_id
    params = job_service.queue_job.call_args.kwargs["task_params"]
    assert params.user_id is None
    assert params.service_principal_id == principal_id
    assert params.api_key_id == user.active_api_key.id
    assert params.tenant_id == user.tenant_id


async def test_a_service_key_reads_the_runs_of_its_principal_also_after_rotation():
    principal_id = uuid4()
    app_run = _run(service_principal_id=principal_id)

    for key_user in (_service_key_user(principal_id), _service_key_user(principal_id)):
        service = _service_reading(key_user, app_run)
        assert await service.get_app_run(app_run.id) is app_run


async def test_a_run_is_read_by_its_owner_only():
    person = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), active_api_key=None)
    principal_id = uuid4()
    persons_run = _run(user_id=person.id)
    services_run = _run(service_principal_id=principal_id)

    assert await _service_reading(person, persons_run).get_app_run(persons_run.id)
    for user, app_run in (
        (person, services_run),
        (_service_key_user(principal_id), persons_run),
        (_service_key_user(uuid4()), services_run),
        (person, _run()),
    ):
        with pytest.raises(UnauthorizedException):
            await _service_reading(user, app_run).get_app_run(app_run.id)


async def test_a_service_key_lists_the_runs_of_its_principal():
    principal_id = uuid4()
    user = _service_key_user(principal_id)
    repo = AsyncMock()
    service = AppRunService(
        user, repo, MagicMock(), AsyncMock(), AsyncMock(), AsyncMock()
    )
    app_id = uuid4()

    await service.get_app_runs(app_id)

    repo.get_for_app.assert_awaited_once_with(
        app_id=app_id, user_id=None, service_principal_id=principal_id
    )
