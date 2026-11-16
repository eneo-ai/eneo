"""A queued insights job keeps its question in the job record, not the queue."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.analysis import analysis_router
from eneo.analysis.analysis import AskAnalysis
from eneo.analysis.analysis_router import ask_unified_questions_about_questions


async def test_queued_insights_job_carries_no_question(
    monkeypatch: pytest.MonkeyPatch,
):
    """Mutants: the router puts the question into the queued payload; the
    question is no longer stored in the job record the task reads."""
    enqueue = AsyncMock()
    monkeypatch.setattr(analysis_router.job_manager, "enqueue", enqueue)
    create_job = AsyncMock()
    monkeypatch.setattr(analysis_router.AnalysisJobManager, "create_job", create_job)
    service = AsyncMock()
    service.should_queue_unified_analysis_job.return_value = True
    container = MagicMock()
    container.user.return_value = MagicMock(id=uuid4(), tenant_id=uuid4())
    container.analysis_service.return_value = service

    await ask_unified_questions_about_questions(
        ask_analysis=AskAnalysis(question="secret question", stream=False),
        container=container,
        assistant_id=uuid4(),
    )

    params = enqueue.call_args.kwargs["params"]
    assert params.question is None
    assert "secret question" not in repr(params.model_dump())
    assert create_job.call_args.kwargs["question"] == "secret question"
