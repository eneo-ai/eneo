from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.flows.application.stale_queued_redispatch import (
    StaleQueuedRedispatchDispatched,
    StaleQueuedRedispatchDispatchFailed,
    StaleQueuedRedispatchInvalidRequest,
    StaleQueuedRedispatchNotClaimed,
    redispatch_stale_queued_run,
)
from intric.flows.flow_run_dispatch_request import FlowRunUserDispatchRequest
from tests.unittests.flows.test_flow_router import _run


@pytest.mark.asyncio
async def test_redispatch_stale_queued_run_classifies_not_claimed():
    backend = MagicMock()
    backend.dispatch = AsyncMock()

    async def claim_run():
        return None

    result = await redispatch_stale_queued_run(
        claim_run=claim_run,
        backend=backend,
    )

    assert isinstance(result, StaleQueuedRedispatchNotClaimed)
    backend.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_redispatch_stale_queued_run_dispatches_claimed_run():
    backend = MagicMock()
    backend.dispatch = AsyncMock()
    flow_id = uuid4()
    tenant_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=tenant_id)

    async def claim_run():
        return run

    result = await redispatch_stale_queued_run(
        claim_run=claim_run,
        backend=backend,
    )

    assert result == StaleQueuedRedispatchDispatched(run=run)
    backend.dispatch.assert_awaited_once_with(
        request=FlowRunUserDispatchRequest(
            run_id=run.id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            principal_user_id=run.principal_user_id,
        )
    )


@pytest.mark.asyncio
async def test_redispatch_stale_queued_run_classifies_invalid_request():
    backend = MagicMock()
    backend.dispatch = AsyncMock()
    run = _run(flow_id=uuid4(), tenant_id=uuid4()).model_copy(
        update={"principal_type": None, "principal_user_id": None}
    )

    async def claim_run():
        return run

    result = await redispatch_stale_queued_run(
        claim_run=claim_run,
        backend=backend,
    )

    assert isinstance(result, StaleQueuedRedispatchInvalidRequest)
    assert result.run is run
    backend.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_redispatch_stale_queued_run_classifies_dispatch_failure():
    error = RuntimeError("broker down")
    backend = MagicMock()
    backend.dispatch = AsyncMock(side_effect=error)
    run = _run(flow_id=uuid4(), tenant_id=uuid4())

    async def claim_run():
        return run

    result = await redispatch_stale_queued_run(
        claim_run=claim_run,
        backend=backend,
    )

    assert result == StaleQueuedRedispatchDispatchFailed(run=run, error=error)
