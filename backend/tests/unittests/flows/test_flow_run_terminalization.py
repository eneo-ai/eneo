from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.flows.application.flow_run_terminalization import (
    FlowRunTerminalizationInvariantError,
    FlowRunTerminalizer,
)
from eneo.flows.domain.flow import FlowRunStatus
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import FlowRunError


@pytest.mark.asyncio
async def test_terminalize_run_rejects_error_source_drift_before_writing() -> None:
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock()
    audit_outbox_repo = AsyncMock()
    review_checkpoint_repo = AsyncMock()
    terminalizer = FlowRunTerminalizer(
        flow_run_repo,
        flow_run_rerun_repo,
        audit_outbox_repo,
        review_checkpoint_repo,
    )

    with pytest.raises(FlowRunTerminalizationInvariantError):
        await terminalizer.terminalize_run(
            run_id=uuid4(),
            tenant_id=uuid4(),
            target_status=FlowRunStatus.FAILED,
            source=FlowRunLifecycleSource.EXECUTOR_FAILED,
            error=FlowRunError.from_source(
                FlowRunLifecycleSource.USER_CANCEL,
                code=FlowApiErrorCode.RUN_USER_CANCELLED,
                message="Run cancelled by user.",
            ),
        )

    flow_run_repo.get.assert_not_awaited()
    flow_run_repo.terminalize_run_status.assert_not_awaited()
