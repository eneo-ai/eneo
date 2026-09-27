"""A dispatch that loses the claim to another dispatcher reports the run as not
claimed. The request's background dispatch and the maintenance sweep both
dispatch a newly queued run; whichever claims second must read the run back
inside a transaction, since the session does not begin one on its own."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from eneo.flows.application.flow_dispatch import (
    FlowRunDispatchNotClaimed,
    dispatch_flow_run_recoverably_after_commit,
)
from eneo.flows.enums import FlowRunStatus
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from tests.integration.flows.test_flow_runtime_health import (
    _create_published_flow,
    _create_run,
)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dispatch_of_a_run_claimed_elsewhere_reports_not_claimed(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        flow = await _create_published_flow(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        run = await _create_run(
            run_repo=FlowRunRepository(session=session),
            flow=flow,
            admin_user=admin_user,
            case="claimed-elsewhere",
        )

    # The other dispatcher (here: the sweep) claims the run first.
    async with db_container() as container:
        claimed = await FlowRunRepository(
            session=container.session()
        ).claim_queued_run_for_dispatch(
            run_id=run.id,
            tenant_id=run.tenant_id,
            expected_revision=run.revision,
            now=datetime.now(timezone.utc),
        )
        assert claimed is not None

    result = await dispatch_flow_run_recoverably_after_commit(
        run_id=run.id,
        tenant_id=run.tenant_id,
        expected_revision=run.revision,
    )

    assert isinstance(result, FlowRunDispatchNotClaimed)
    assert result.run.id == run.id
    assert result.run.status == FlowRunStatus.QUEUED
    assert result.run.dispatch_attempt_count == 1
