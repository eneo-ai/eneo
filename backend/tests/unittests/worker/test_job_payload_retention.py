"""Background jobs carry ids, not content, and keep no results in Redis."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import orjson
import pytest
from arq.worker import Function, create_worker

from eneo.analysis.analysis import AnalysisJobStatus
from eneo.analysis.analysis_job_manager import AnalysisJobManager
from eneo.analysis.analysis_router import get_conversation_insight_job
from eneo.jobs.task_models import AnalyzeConversationInsightsTask, ResourceTaskParams
from eneo.main.exceptions import NotFoundException
from eneo.worker import analysis_tasks
from eneo.worker.analysis_tasks import analyze_conversation_insights_task
from eneo.worker.arq import WorkerSettings
from eneo.worker.worker import Worker
from tests.log_capture import chained_error, emitted, logged_errors


async def _noop_task(params: ResourceTaskParams, container: object) -> None:
    del params, container


def test_task_passes_keep_result_through_to_arq():
    """Mutant: Worker.task drops keep_result, so arq keeps the result for its
    default hour."""
    worker = Worker()
    worker.task(keep_result=0)(_noop_task)

    registered = worker.functions[-1]
    assert isinstance(registered, Function)
    assert registered.keep_result_s == 0


def test_task_without_keep_result_leaves_the_arq_default():
    """Mutant: Worker.task always wraps in arq's func with a fixed keep_result,
    changing the result lifetime of every existing task."""
    worker = Worker()
    worker.task()(_noop_task)

    assert not isinstance(worker.functions[-1], Function)


@pytest.mark.parametrize(
    "name", ["run_app", "analyze_conversation_insights", "log_audit_event"]
)
def test_content_bearing_tasks_keep_no_result(name: str):
    """Mutant: one of the tasks that handles prompts, analysis questions or
    audit details is registered without keep_result=0, so its result stays in
    Redis after the job ends."""
    functions = create_worker(WorkerSettings).functions

    assert functions[name].keep_result_s == 0


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def setex(self, key: str, ttl: object, value: bytes) -> None:
        del ttl
        self.store[key] = value

    def store_pre_retirement_job(
        self,
        tenant_id: UUID,
        job_id: UUID,
        assistant_id: UUID | None,
        group_chat_id: UUID | None,
    ) -> None:
        now = datetime.now(timezone.utc)
        self.store[f"analysis_insights:{tenant_id}:{job_id}"] = orjson.dumps(
            {
                "job_id": job_id,
                "tenant_id": tenant_id,
                "status": "queued",
                "question": "stored question",
                "assistant_id": assistant_id,
                "group_chat_id": group_chat_id,
                "created_at": now,
                "updated_at": now,
            }
        )


def _insights_container(redis: _FakeRedis, tenant_id: object) -> MagicMock:
    container = MagicMock()
    container.user.return_value = SimpleNamespace(tenant_id=tenant_id)
    container.redis_client.return_value = redis
    service = AsyncMock()
    service.generate_unified_analysis_answer.return_value = "answer"
    container.analysis_service.return_value = service
    return container


def _payload(**extra: object) -> AnalyzeConversationInsightsTask:
    now = datetime.now(timezone.utc).isoformat()
    return AnalyzeConversationInsightsTask.model_validate(
        {
            "user_id": uuid4(),
            "from_date": now,
            "to_date": now,
            "assistant_id": uuid4(),
            **extra,
        }
    )


async def test_insights_task_uses_the_stored_question_and_assistant():
    redis = _FakeRedis()
    tenant_id = uuid4()
    job_id = uuid4()
    container = _insights_container(redis, tenant_id)
    manager = AnalysisJobManager(container.redis_client())
    assistant_id = uuid4()
    await manager.create_job(
        job_id=job_id,
        tenant_id=tenant_id,
        question="stored question",
        assistant_id=assistant_id,
    )

    await analyze_conversation_insights_task(
        job_id=job_id,
        params=_payload(question="stale payload question"),
        container=container,
    )

    service = container.analysis_service.return_value
    arguments = service.generate_unified_analysis_answer.await_args.kwargs
    assert arguments["question"] == "stored question"
    assert arguments["assistant_id"] == assistant_id
    job = await manager.get_job(tenant_id=tenant_id, job_id=job_id)
    assert job is not None and job.status == AnalysisJobStatus.COMPLETED


async def test_pre_retirement_group_job_runs_and_can_be_polled_by_its_original_id():
    redis = _FakeRedis()
    tenant_id, job_id, group_id = uuid4(), uuid4(), uuid4()
    redis.store_pre_retirement_job(
        tenant_id, job_id, assistant_id=None, group_chat_id=group_id
    )
    container = _insights_container(redis, tenant_id)

    await analyze_conversation_insights_task(
        job_id=job_id,
        params=_payload(assistant_id=None, group_chat_id=group_id),
        container=container,
    )
    result = await get_conversation_insight_job(job_id=job_id, container=container)

    service = container.analysis_service.return_value
    assert (
        service.generate_unified_analysis_answer.await_args.kwargs["assistant_id"]
        == group_id
    )
    assert service.authorize_insight_job.await_args.args[0].assistant_id == group_id
    assert result.status == AnalysisJobStatus.COMPLETED and result.answer == "answer"


@pytest.mark.parametrize(
    ("assistant_id", "group_chat_id"),
    [(None, None), (UUID(int=1), UUID(int=2))],
    ids=["missing-target", "ambiguous-target"],
)
async def test_poll_hides_a_persisted_job_without_exactly_one_target(
    assistant_id: UUID | None, group_chat_id: UUID | None
):
    redis = _FakeRedis()
    tenant_id, job_id = uuid4(), uuid4()
    redis.store_pre_retirement_job(tenant_id, job_id, assistant_id, group_chat_id)
    container = _insights_container(redis, tenant_id)

    with pytest.raises(NotFoundException):
        await get_conversation_insight_job(job_id=job_id, container=container)

    container.analysis_service.return_value.authorize_insight_job.assert_not_awaited()


async def test_insights_task_fails_closed_without_a_job_record():
    """Mutant: a missing job record falls back to the payload's question or
    runs the analysis with no question."""
    redis = _FakeRedis()
    container = _insights_container(redis, uuid4())

    with pytest.raises(ValueError):
        await analyze_conversation_insights_task(
            job_id=uuid4(),
            params=_payload(question="stale payload question"),
            container=container,
        )

    container.analysis_service.return_value.generate_unified_analysis_answer.assert_not_called()


async def test_insights_task_fails_closed_when_the_record_has_no_question():
    """Mutant: an empty question in the record runs the analysis anyway
    instead of marking the job failed."""
    redis = _FakeRedis()
    tenant_id = uuid4()
    job_id = uuid4()
    container = _insights_container(redis, tenant_id)
    manager = AnalysisJobManager(container.redis_client())
    await manager.create_job(
        job_id=job_id,
        tenant_id=tenant_id,
        question="",
        assistant_id=uuid4(),
    )

    with pytest.raises(ValueError):
        await analyze_conversation_insights_task(
            job_id=job_id, params=_payload(), container=container
        )

    container.analysis_service.return_value.generate_unified_analysis_answer.assert_not_called()
    job = await manager.get_job(tenant_id=tenant_id, job_id=job_id)
    assert job is not None and job.status == AnalysisJobStatus.FAILED


async def test_a_failed_insights_job_logs_the_kind_of_error_not_its_text():
    """A provider's error can echo the questions it was given. Mutant: the
    job's failure is logged with its message or traceback."""
    redis = _FakeRedis()
    tenant_id = uuid4()
    job_id = uuid4()
    container = _insights_container(redis, tenant_id)
    manager = AnalysisJobManager(container.redis_client())
    await manager.create_job(
        job_id=job_id,
        tenant_id=tenant_id,
        question="stored question",
        assistant_id=uuid4(),
    )
    service = container.analysis_service.return_value
    service.generate_unified_analysis_answer.side_effect = chained_error()

    with emitted(analysis_tasks.logger) as records, pytest.raises(RuntimeError):
        await analyze_conversation_insights_task(
            job_id=job_id, params=_payload(), container=container
        )

    assert logged_errors(records), [record.getMessage() for record in records]
