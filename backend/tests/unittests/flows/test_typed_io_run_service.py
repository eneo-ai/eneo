"""TDD tests for file_ids support in FlowRunService — RED phase."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.flows.flow import (
    Flow,
    FlowRun,
    FlowRunStatus,
    FlowStep,
    FlowVersion,
)
from intric.flows.flow_run_service import FlowRunService


def _flow_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.session = AsyncMock()
    repo.session.execute = AsyncMock()
    return repo


def _step(step_order: int = 1) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        user_description="Step",
        input_source="flow_input",
        input_type="text",
        output_mode="pass_through",
        output_type="json",
        mcp_policy="inherit",
        input_config={"runtime_input": {"enabled": True, "max_files": 2}},
    )


def _flow(user, published_version: int | None = 1) -> Flow:
    return Flow(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Flow",
        description="Flow description",
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=published_version,
        metadata_json=None,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(1)],
    )


def _version(user, flow: Flow) -> FlowVersion:
    return FlowVersion(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": str(step.id),
                    "step_order": step.step_order,
                    "assistant_id": str(step.assistant_id),
                    "input_source": step.input_source,
                    "input_type": step.input_type,
                    "input_config": step.input_config,
                    "output_mode": step.output_mode,
                    "output_type": step.output_type,
                    "mcp_policy": step.mcp_policy,
                }
                for step in flow.steps
            ]
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_create_run_stores_file_ids(user):
    """file_ids should be merged into input_payload_json."""
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user)
    version = _version(user, flow)

    flow_repo.get = AsyncMock(return_value=flow)
    flow_version_repo.get = AsyncMock(return_value=version)
    flow_run_repo.count_active_runs = AsyncMock(return_value=0)

    created_run = FlowRun(
        id=uuid4(),
        flow_id=flow.id,
        flow_version=1,
        user_id=user.id,
        tenant_id=user.tenant_id,
        status=FlowRunStatus.QUEUED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json=None,
        error_message=None,
        job_id=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    flow_run_repo.create = AsyncMock(return_value=created_run)

    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=10,
    )

    file_id_1 = uuid4()
    file_id_2 = uuid4()
    await service.create_run(
        flow_id=flow.id,
        input_payload_json={"text": "hello"},
        file_ids=[file_id_1, file_id_2],
    )

    # Verify file_ids were merged into the payload passed to repo.create
    create_kwargs = flow_run_repo.create.await_args.kwargs
    payload = create_kwargs["input_payload_json"]
    assert payload["file_ids"] == [str(file_id_1), str(file_id_2)]
    assert payload["expected_flow_version"] == 1
    assert payload["step_inputs"] == {
        str(flow.steps[0].id): {"file_ids": [str(file_id_1), str(file_id_2)]}
    }
    assert payload["text"] == "hello"


@pytest.mark.asyncio
async def test_create_run_no_file_ids(user):
    """Works without file_ids — payload unchanged."""
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user)
    version = _version(user, flow)

    flow_repo.get = AsyncMock(return_value=flow)
    flow_version_repo.get = AsyncMock(return_value=version)
    flow_run_repo.count_active_runs = AsyncMock(return_value=0)

    created_run = FlowRun(
        id=uuid4(),
        flow_id=flow.id,
        flow_version=1,
        user_id=user.id,
        tenant_id=user.tenant_id,
        status=FlowRunStatus.QUEUED,
        cancelled_at=None,
        input_payload_json={"text": "hello"},
        output_payload_json=None,
        error_message=None,
        job_id=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    flow_run_repo.create = AsyncMock(return_value=created_run)

    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=10,
    )

    await service.create_run(
        flow_id=flow.id,
        input_payload_json={"text": "hello"},
    )

    create_kwargs = flow_run_repo.create.await_args.kwargs
    payload = create_kwargs["input_payload_json"]
    assert payload == {"text": "hello", "expected_flow_version": 1}
    assert "file_ids" not in payload
