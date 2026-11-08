"""Background jobs carry ids, not content, and keep no results in Redis."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from arq.worker import Function, create_worker

from eneo.analysis.analysis import AnalysisJobStatus
from eneo.analysis.analysis_job_manager import AnalysisJobManager
from eneo.jobs.task_models import AnalyzeConversationInsightsTask, ResourceTaskParams
from eneo.worker.analysis_tasks import analyze_conversation_insights_task
from eneo.worker.arq import WorkerSettings
from eneo.worker.worker import Worker


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


async def test_insights_task_uses_the_job_records_question_not_the_payloads():
    """Mutants: the task reads the question from the queued payload; an old
    payload that still carries a question no longer parses."""
    redis = _FakeRedis()
    tenant_id = uuid4()
    job_id = uuid4()
    manager = AnalysisJobManager(redis)  # pyright: ignore[reportArgumentType]
    await manager.create_job(
        job_id=job_id,
        tenant_id=tenant_id,
        question="stored question",
        assistant_id=None,
        group_chat_id=None,
    )
    container = _insights_container(redis, tenant_id)

    await analyze_conversation_insights_task(
        job_id=job_id,
        params=_payload(question="stale payload question"),
        container=container,
    )

    service = container.analysis_service.return_value
    assert (
        service.generate_unified_analysis_answer.call_args.kwargs["question"]
        == "stored question"
    )
    job = await manager.get_job(tenant_id=tenant_id, job_id=job_id)
    assert job is not None and job.status == AnalysisJobStatus.COMPLETED


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
    manager = AnalysisJobManager(redis)  # pyright: ignore[reportArgumentType]
    await manager.create_job(
        job_id=job_id,
        tenant_id=tenant_id,
        question="",
        assistant_id=None,
        group_chat_id=None,
    )
    container = _insights_container(redis, tenant_id)

    with pytest.raises(ValueError):
        await analyze_conversation_insights_task(
            job_id=job_id, params=_payload(), container=container
        )

    container.analysis_service.return_value.generate_unified_analysis_answer.assert_not_called()
    job = await manager.get_job(tenant_id=tenant_id, job_id=job_id)
    assert job is not None and job.status == AnalysisJobStatus.FAILED
