"""The run-limit refusal of every route that creates a run."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, Response
from starlette.requests import Request

from eneo.flows.api import (
    flow_run_lifecycle_router,
    flow_run_retry_router,
    flow_transcript_regeneration_router,
)
from eneo.flows.api.flow_models import FlowRunCreateRequest
from eneo.flows.api.flow_transcript_regeneration_router import (
    FlowTranscriptRegenerationRequest,
)
from eneo.flows.domain.flow_run_exceptions import FlowRunConcurrencyLimitReachedError

EFFECTIVE_LIMIT = 3


def _request() -> Request:
    return Request({"type": "http", "headers": [], "state": {}})


@asynccontextmanager
async def _no_commit(_container):
    yield


def _refusing_container() -> MagicMock:
    refusal = FlowRunConcurrencyLimitReachedError(max_concurrent_runs=EFFECTIVE_LIMIT)
    container = MagicMock()
    container.flow_run_service.return_value.create_run = AsyncMock(side_effect=refusal)
    container.flow_transcript_regeneration_service.return_value.regenerate = AsyncMock(
        side_effect=refusal
    )
    return container


def _assert_refused(response, background_tasks: BackgroundTasks) -> None:
    body = json.loads(response.body)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert body["code"] == "flow_run_concurrency_limit_reached"
    assert body["context"] == {
        "max_concurrent_runs": EFFECTIVE_LIMIT,
        "retry_after_seconds": 60,
    }
    assert background_tasks.tasks == []


@pytest.fixture(autouse=True)
def _scope_and_commit(monkeypatch):
    for module in (
        flow_run_lifecycle_router,
        flow_run_retry_router,
        flow_transcript_regeneration_router,
    ):
        monkeypatch.setattr(
            module.flow_access_context, "enforce_flow_scope", AsyncMock()
        )
        monkeypatch.setattr(
            module, "commit_flow_runtime_write_before_response", _no_commit
        )


@pytest.mark.asyncio
async def test_create_refuses_with_the_effective_limit_and_dispatches_nothing():
    tasks = BackgroundTasks()

    response = await flow_run_lifecycle_router.create_flow_run(
        id=uuid4(),
        request=_request(),
        run_in=FlowRunCreateRequest(
            expected_flow_version=1, input_payload_json={"x": 1}
        ),
        background_tasks=tasks,
        idempotency_key=None,
        container=_refusing_container(),
    )

    _assert_refused(response, tasks)


@pytest.mark.asyncio
async def test_retry_refuses_with_the_effective_limit_and_dispatches_nothing(
    monkeypatch,
):
    refusal = FlowRunConcurrencyLimitReachedError(max_concurrent_runs=EFFECTIVE_LIMIT)
    service = MagicMock()
    service.return_value.retry_from_failed_step = AsyncMock(side_effect=refusal)
    monkeypatch.setattr(flow_run_retry_router, "FlowRunRetryService", service)
    tasks = BackgroundTasks()

    response = await flow_run_retry_router.retry_flow_run_from_failed_step(
        id=uuid4(),
        run_id=uuid4(),
        request=_request(),
        response=Response(),
        background_tasks=tasks,
        idempotency_key="k",
        container=MagicMock(),
    )

    _assert_refused(response, tasks)


@pytest.mark.asyncio
async def test_regeneration_refuses_with_the_effective_limit_and_dispatches_nothing():
    tasks = BackgroundTasks()

    response = await flow_transcript_regeneration_router.regenerate_flow_run_transcript(
        id=uuid4(),
        run_id=uuid4(),
        step_id=uuid4(),
        body=FlowTranscriptRegenerationRequest(
            expected_run_revision=1,
            expected_correction_revision=None,
            segments_hash="0" * 64,
        ),
        request=_request(),
        response=Response(),
        background_tasks=tasks,
        idempotency_key="k",
        container=_refusing_container(),
    )

    _assert_refused(response, tasks)
