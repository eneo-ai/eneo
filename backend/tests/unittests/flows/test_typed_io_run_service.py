"""FlowRunService step input contract tests."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.flows.application.flow_run_service import FlowRunService
from intric.flows.flow import (
    Flow,
    FlowRun,
    FlowRunStatus,
    FlowStep,
    FlowVersion,
)
from intric.flows.published_definition import FLOW_DEFINITION_SCHEMA_VERSION
from intric.main.exceptions import BadRequestException


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
            "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
            "flow_id": str(flow.id),
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
@pytest.mark.parametrize(
    "reserved_key", ["expected_flow_version", "file_ids", "step_inputs"]
)
async def test_create_run_rejects_reserved_input_payload_keys(user, reserved_key: str):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user)
    flow_repo.get = AsyncMock(return_value=flow)

    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=10,
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.create_run(
            flow_id=flow.id,
            input_payload_json={reserved_key: "value"},
        )

    assert exc_info.value.code == "flow_run_reserved_input_payload_key"
    assert exc_info.value.context == {"keys": [reserved_key]}
    flow_run_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_stores_step_inputs_without_top_level_file_ids(user):
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
        trace_id=uuid4(),
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
        step_inputs={flow.steps[0].id: {"file_ids": [file_id_2, file_id_1]}},
    )

    create_kwargs = flow_run_repo.create.await_args.kwargs
    payload = create_kwargs["input_payload_json"]
    assert payload["expected_flow_version"] == 1
    assert payload["step_inputs"] == {
        str(flow.steps[0].id): {
            "file_ids": sorted([str(file_id_1), str(file_id_2)])
        }
    }
    assert payload["text"] == "hello"
    assert create_kwargs["step_input_files"] == [
        {
            "step_id": flow.steps[0].id,
            "step_order": 1,
            "file_ids": sorted([file_id_1, file_id_2], key=str),
        }
    ]


@pytest.mark.asyncio
async def test_create_run_without_step_inputs_preserves_inline_payload(user):
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
        trace_id=uuid4(),
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
