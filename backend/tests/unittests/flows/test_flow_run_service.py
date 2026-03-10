from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
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
from intric.main.exceptions import BadRequestException, NotFoundException, UnauthorizedException


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
    )


def _flow(
    user,
    published_version: int | None = 1,
    metadata_json: dict | None = None,
) -> Flow:
    return Flow(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Flow",
        description="Flow description",
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=published_version,
        metadata_json=metadata_json,
        data_retention_days=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(1), _step(2)],
    )


def _run(user, flow_id) -> FlowRun:
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=flow_id,
        flow_version=1,
        user_id=user.id,
        tenant_id=user.tenant_id,
        status=FlowRunStatus.QUEUED,
        cancelled_at=None,
        input_payload_json={"input": "value"},
        output_payload_json=None,
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )


def _version(user, flow: Flow, version: int = 1) -> FlowVersion:
    return FlowVersion(
        flow_id=flow.id,
        version=version,
        tenant_id=user.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": str(step.id),
                    "step_order": step.step_order,
                    "assistant_id": str(step.assistant_id),
                }
                for step in flow.steps
            ]
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _form_schema_flow(user) -> Flow:
    return _flow(
        user=user,
        published_version=1,
        metadata_json={
            "form_schema": {
                "fields": [
                    {"name": "Namn på brukare", "type": "text", "required": True, "order": 1},
                    {"name": "Personnummer", "type": "text", "required": True, "order": 2},
                    {
                        "name": "Typ av insats",
                        "type": "multiselect",
                        "required": True,
                        "options": ["Hemtjänst", "Trygghetslarm"],
                        "order": 3,
                    },
                    {
                        "name": "Prioritet",
                        "type": "select",
                        "required": False,
                        "options": ["Låg", "Medel", "Hög"],
                        "order": 4,
                    },
                    {"name": "Mötesdatum", "type": "date", "required": False, "order": 5},
                    {"name": "Antal timmar", "type": "number", "required": False, "order": 6},
                ]
            }
        },
    )


@pytest.mark.asyncio
async def test_create_run_rejects_unpublished_flow(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=2,
    )
    flow_repo.get.return_value = _flow(user=user, published_version=None)

    with pytest.raises(BadRequestException) as exc_info:
        await service.create_run(flow_id=uuid4(), input_payload_json={"x": 1})
    assert exc_info.value.code == "flow_not_published"


@pytest.mark.asyncio
async def test_create_run_enforces_tenant_concurrency_limit(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=1,
    )
    flow = _flow(user=user, published_version=1)
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 1

    with pytest.raises(BadRequestException) as exc_info:
        await service.create_run(flow_id=flow.id, input_payload_json={"x": 1})
    assert exc_info.value.code == "flow_run_concurrency_limit_reached"


@pytest.mark.asyncio
async def test_create_run_creates_preseeded_run(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=2)
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=2)
    flow_run_repo.create.return_value = _run(user=user, flow_id=flow.id)

    created = await service.create_run(flow_id=flow.id, input_payload_json={"case": "123"})

    assert created.status == FlowRunStatus.QUEUED
    flow_run_repo.create.assert_awaited_once()
    kwargs = flow_run_repo.create.await_args.kwargs
    assert kwargs["flow_id"] == flow.id
    assert kwargs["flow_version"] == 2
    assert kwargs["tenant_id"] == user.tenant_id
    assert kwargs["preseed_steps"] == [
        {
            "step_id": flow.steps[0].id,
            "assistant_id": flow.steps[0].assistant_id,
            "step_order": flow.steps[0].step_order,
        },
        {
            "step_id": flow.steps[1].id,
            "assistant_id": flow.steps[1].assistant_id,
            "step_order": flow.steps[1].step_order,
        },
    ]


@pytest.mark.asyncio
async def test_create_run_dispatches_to_execution_backend(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    execution_backend = AsyncMock()
    flow = _flow(user=user, published_version=1)
    created_run = _run(user=user, flow_id=flow.id)
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        execution_backend=execution_backend,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    flow_run_repo.create.return_value = created_run

    result = await service.create_run(flow_id=flow.id, input_payload_json={"x": "y"})

    assert result.id == created_run.id
    execution_backend.dispatch.assert_awaited_once_with(
        run_id=created_run.id,
        flow_id=flow.id,
        tenant_id=user.tenant_id,
        user_id=user.id,
    )


@pytest.mark.asyncio
async def test_create_run_raises_if_dispatch_fails(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    execution_backend = AsyncMock()
    flow = _flow(user=user, published_version=1)
    created_run = _run(user=user, flow_id=flow.id)
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        execution_backend=execution_backend,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    flow_run_repo.create.return_value = created_run
    execution_backend.dispatch.side_effect = RuntimeError("broker unavailable")

    with patch("intric.flows.flow_run_service.logger") as logger_mock:
        with pytest.raises(RuntimeError, match="broker unavailable"):
            await service.create_run(flow_id=flow.id, input_payload_json={"x": "y"})

    logger_mock.exception.assert_called_once_with(
        "Failed to dispatch newly created flow run",
        extra={
            "run_id": str(created_run.id),
            "flow_id": str(flow.id),
            "tenant_id": str(user.tenant_id),
        },
    )
    flow_run_repo.update_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_rejects_missing_required_form_field(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _form_schema_flow(user)
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)

    with pytest.raises(
        BadRequestException, match="Missing required input field 'Personnummer'"
    ) as exc_info:
        await service.create_run(
            flow_id=flow.id,
            input_payload_json={
                "Namn på brukare": "Anna",
                "Typ av insats": ["Hemtjänst"],
            },
        )
    assert exc_info.value.code == "flow_input_required_field_missing"
    assert exc_info.value.context == {
        "field_name": "Personnummer",
        "field_type": "text",
    }


@pytest.mark.asyncio
async def test_create_run_rejects_invalid_select_option(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _form_schema_flow(user)
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)

    with pytest.raises(
        BadRequestException, match="must be one of the configured options"
    ) as exc_info:
        await service.create_run(
            flow_id=flow.id,
            input_payload_json={
                "Namn på brukare": "Anna",
                "Personnummer": "19121212-1212",
                "Typ av insats": ["Hemtjänst"],
                "Prioritet": "Akut",
            },
        )
    assert exc_info.value.code == "flow_input_invalid_option"
    assert exc_info.value.context == {
        "field_name": "Prioritet",
        "field_type": "select",
    }


@pytest.mark.asyncio
async def test_create_run_rejects_invalid_multiselect_shape(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _form_schema_flow(user)
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)

    with pytest.raises(BadRequestException, match="contains invalid option values") as exc_info:
        await service.create_run(
            flow_id=flow.id,
            input_payload_json={
                "Namn på brukare": "Anna",
                "Personnummer": "19121212-1212",
                "Typ av insats": ["Ogiltig"],
            },
        )
    assert exc_info.value.code == "flow_input_invalid_option"
    assert exc_info.value.context == {
        "field_name": "Typ av insats",
        "field_type": "multiselect",
    }


@pytest.mark.asyncio
async def test_create_run_normalizes_multiselect_number_and_date_fields(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _form_schema_flow(user)
    created_run = _run(user=user, flow_id=flow.id)
    flow_run_repo.create.return_value = created_run
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)

    await service.create_run(
        flow_id=flow.id,
        input_payload_json={
            "Namn på brukare": "Anna",
            "Personnummer": "19121212-1212",
            "Typ av insats": "Hemtjänst,Trygghetslarm",
            "Prioritet": "Hög",
            "Mötesdatum": "2026-03-03",
            "Antal timmar": "12",
        },
    )

    payload = flow_run_repo.create.await_args.kwargs["input_payload_json"]
    assert payload["Typ av insats"] == ["Hemtjänst", "Trygghetslarm"]
    assert payload["Antal timmar"] == 12
    assert payload["Mötesdatum"] == "2026-03-03"


@pytest.mark.asyncio
async def test_create_run_preserves_unknown_payload_fields_for_forward_compat(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _form_schema_flow(user)
    created_run = _run(user=user, flow_id=flow.id)
    flow_run_repo.create.return_value = created_run
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)

    await service.create_run(
        flow_id=flow.id,
        input_payload_json={
            "Namn på brukare": "Anna",
            "Personnummer": "19121212-1212",
            "Typ av insats": ["Hemtjänst"],
            "trace_id": "flow-consumer-abc123",
        },
    )

    payload = flow_run_repo.create.await_args.kwargs["input_payload_json"]
    assert payload["trace_id"] == "flow-consumer-abc123"


@pytest.mark.asyncio
async def test_create_run_rejects_stale_expected_flow_version(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=3)
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow

    with pytest.raises(BadRequestException) as exc_info:
        await service.create_run(
            flow_id=flow.id,
            expected_flow_version=2,
            input_payload_json={"x": "y"},
        )

    assert exc_info.value.code == "flow_run_stale_version"
    assert exc_info.value.context == {
        "expected_flow_version": 2,
        "published_flow_version": 3,
    }


@pytest.mark.asyncio
async def test_create_run_persists_expected_version_and_step_inputs(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    file_repo = AsyncMock()
    flow = _flow(user=user, published_version=2)
    runtime_step = flow.steps[0].model_copy(
        update={
            "input_config": {
                "runtime_input": {
                    "enabled": True,
                    "required": True,
                    "max_files": 2,
                    "input_format": "document",
                }
            }
        }
    )
    flow = flow.model_copy(update={"steps": [runtime_step, flow.steps[1]]})
    created_run = _run(user=user, flow_id=flow.id)
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        file_repo=file_repo,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_run_repo.create.return_value = created_run
    file_id = uuid4()
    file_repo.get_list_by_id_and_user.return_value = [
        SimpleNamespace(id=file_id, mimetype="application/pdf")
    ]
    flow_version_repo.get.return_value = FlowVersion(
        flow_id=flow.id,
        version=2,
        tenant_id=user.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": str(runtime_step.id),
                    "step_order": 1,
                    "assistant_id": str(runtime_step.assistant_id),
                    "input_source": "flow_input",
                    "input_type": "text",
                    "input_config": runtime_step.input_config,
                    "output_mode": "pass_through",
                    "output_type": "json",
                    "mcp_policy": "inherit",
                },
                {
                    "step_id": str(flow.steps[1].id),
                    "step_order": 2,
                    "assistant_id": str(flow.steps[1].assistant_id),
                    "input_source": "previous_step",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "json",
                    "mcp_policy": "inherit",
                },
            ]
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    await service.create_run(
        flow_id=flow.id,
        expected_flow_version=2,
        input_payload_json={"x": "y"},
        step_inputs={runtime_step.id: {"file_ids": [file_id]}},
    )

    payload = flow_run_repo.create.await_args.kwargs["input_payload_json"]
    assert payload["expected_flow_version"] == 2
    assert payload["step_inputs"] == {
        str(runtime_step.id): {"file_ids": [str(file_id)]}
    }


@pytest.mark.asyncio
async def test_create_run_rejects_duplicate_legacy_and_canonical_step_one_input(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    runtime_step = flow.steps[0].model_copy(
        update={"input_config": {"runtime_input": {"enabled": True, "max_files": 2}}}
    )
    flow = flow.model_copy(update={"steps": [runtime_step, flow.steps[1]]})
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_version_repo.get.return_value = FlowVersion(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": str(runtime_step.id),
                    "step_order": 1,
                    "assistant_id": str(runtime_step.assistant_id),
                    "input_source": "flow_input",
                    "input_type": "text",
                    "input_config": runtime_step.input_config,
                    "output_mode": "pass_through",
                    "output_type": "json",
                    "mcp_policy": "inherit",
                }
            ]
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.create_run(
            flow_id=flow.id,
            input_payload_json={"x": "y"},
            file_ids=[uuid4()],
            step_inputs={runtime_step.id: {"file_ids": [uuid4()]}},
        )

    assert exc_info.value.code == "flow_run_duplicate_step_input"


@pytest.mark.asyncio
async def test_create_run_rejects_runtime_step_input_mimetype(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    file_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    runtime_step = flow.steps[0].model_copy(
        update={
            "input_config": {
                "runtime_input": {
                    "enabled": True,
                    "required": True,
                    "max_files": 1,
                    "input_format": "audio",
                }
            }
        }
    )
    flow = flow.model_copy(update={"steps": [runtime_step, flow.steps[1]]})
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        file_repo=file_repo,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_version_repo.get.return_value = FlowVersion(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": str(runtime_step.id),
                    "step_order": 1,
                    "assistant_id": str(runtime_step.assistant_id),
                    "input_source": "flow_input",
                    "input_type": "text",
                    "input_config": runtime_step.input_config,
                    "output_mode": "pass_through",
                    "output_type": "json",
                    "mcp_policy": "inherit",
                }
            ]
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    file_id = uuid4()
    file_repo.get_list_by_id_and_user.return_value = [
        SimpleNamespace(id=file_id, mimetype="application/pdf")
    ]

    with pytest.raises(BadRequestException) as exc_info:
        await service.create_run(
            flow_id=flow.id,
            input_payload_json={"x": "y"},
            step_inputs={runtime_step.id: {"file_ids": [file_id]}},
        )

    assert exc_info.value.code == "flow_run_step_input_mimetype_rejected"
    assert exc_info.value.context == {
        "step_id": str(runtime_step.id),
        "file_id": str(file_id),
        "mimetype": "application/pdf",
    }


@pytest.mark.asyncio
async def test_list_runs_delegates_to_repo(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow_id = uuid4()
    expected = [_run(user=user, flow_id=flow_id)]
    flow_run_repo.list_runs.return_value = expected
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    result = await service.list_runs(flow_id=flow_id)

    assert result == expected
    flow_run_repo.list_runs.assert_awaited_once_with(
        tenant_id=user.tenant_id,
        flow_id=flow_id,
        limit=None,
        offset=None,
    )


@pytest.mark.asyncio
async def test_redispatch_stale_queued_runs_dispatches_with_backend(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    execution_backend = AsyncMock()
    flow_id = uuid4()
    stale_run = _run(user=user, flow_id=flow_id)
    flow_run_repo.list_stale_queued_runs.return_value = [stale_run]
    flow_run_repo.claim_stale_queued_run_for_redispatch.return_value = stale_run
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    count = await service.redispatch_stale_queued_runs(
        flow_id=flow_id,
        execution_backend=execution_backend,
    )

    assert count == 1
    flow_run_repo.list_stale_queued_runs.assert_awaited_once()
    kwargs = flow_run_repo.list_stale_queued_runs.await_args.kwargs
    assert kwargs["tenant_id"] == user.tenant_id
    assert kwargs["flow_id"] == flow_id
    assert kwargs["run_id"] is None
    assert kwargs["limit"] == 25
    assert isinstance(kwargs["stale_before"], datetime)
    claim_kwargs = flow_run_repo.claim_stale_queued_run_for_redispatch.await_args.kwargs
    assert claim_kwargs["run_id"] == stale_run.id
    assert claim_kwargs["tenant_id"] == user.tenant_id
    assert claim_kwargs["flow_id"] == flow_id
    assert isinstance(claim_kwargs["stale_before"], datetime)
    execution_backend.dispatch.assert_awaited_once_with(
        run_id=stale_run.id,
        flow_id=flow_id,
        tenant_id=user.tenant_id,
        user_id=user.id,
    )


@pytest.mark.asyncio
async def test_redispatch_stale_queued_runs_returns_zero_without_backend(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    count = await service.redispatch_stale_queued_runs(flow_id=uuid4())

    assert count == 0
    flow_run_repo.list_stale_queued_runs.assert_not_called()


@pytest.mark.asyncio
async def test_redispatch_stale_queued_runs_skips_runs_without_user_id(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    execution_backend = AsyncMock()
    flow_id = uuid4()
    missing_user_run = _run(user=user, flow_id=flow_id).model_copy(update={"user_id": None})
    dispatchable_run = _run(user=user, flow_id=flow_id)
    flow_run_repo.list_stale_queued_runs.return_value = [missing_user_run, dispatchable_run]
    flow_run_repo.claim_stale_queued_run_for_redispatch.side_effect = [missing_user_run, dispatchable_run]
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    count = await service.redispatch_stale_queued_runs(
        flow_id=flow_id,
        execution_backend=execution_backend,
    )

    assert count == 1
    assert flow_run_repo.claim_stale_queued_run_for_redispatch.await_count == 2
    execution_backend.dispatch.assert_awaited_once_with(
        run_id=dispatchable_run.id,
        flow_id=flow_id,
        tenant_id=user.tenant_id,
        user_id=user.id,
    )


@pytest.mark.asyncio
async def test_redispatch_stale_queued_runs_skips_when_claim_returns_none(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    execution_backend = AsyncMock()
    flow_id = uuid4()
    stale_run = _run(user=user, flow_id=flow_id)
    flow_run_repo.list_stale_queued_runs.return_value = [stale_run]
    flow_run_repo.claim_stale_queued_run_for_redispatch.return_value = None
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    count = await service.redispatch_stale_queued_runs(
        flow_id=flow_id,
        execution_backend=execution_backend,
    )

    assert count == 0
    execution_backend.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_redispatch_stale_queued_runs_continues_on_dispatch_failure(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    execution_backend = AsyncMock()
    flow_id = uuid4()
    failed_run = _run(user=user, flow_id=flow_id)
    succeeded_run = _run(user=user, flow_id=flow_id)
    flow_run_repo.list_stale_queued_runs.return_value = [failed_run, succeeded_run]
    flow_run_repo.claim_stale_queued_run_for_redispatch.side_effect = [failed_run, succeeded_run]
    execution_backend.dispatch.side_effect = [RuntimeError("broker down"), None]
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    count = await service.redispatch_stale_queued_runs(
        flow_id=flow_id,
        execution_backend=execution_backend,
    )

    assert count == 1
    assert execution_backend.dispatch.await_count == 2


@pytest.mark.asyncio
async def test_redispatch_stale_queued_runs_supports_run_scoped_filter(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    execution_backend = AsyncMock()
    flow_id = uuid4()
    stale_run = _run(user=user, flow_id=flow_id)
    flow_run_repo.list_stale_queued_runs.return_value = [stale_run]
    flow_run_repo.claim_stale_queued_run_for_redispatch.return_value = stale_run
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    count = await service.redispatch_stale_queued_runs(
        flow_id=flow_id,
        run_id=stale_run.id,
        limit=1,
        execution_backend=execution_backend,
    )

    assert count == 1
    kwargs = flow_run_repo.list_stale_queued_runs.await_args.kwargs
    assert kwargs["run_id"] == stale_run.id
    assert kwargs["limit"] == 1


@pytest.mark.asyncio
async def test_redispatch_stale_queued_runs_raises_on_run_scoped_dispatch_failure(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    execution_backend = AsyncMock()
    flow_id = uuid4()
    stale_run = _run(user=user, flow_id=flow_id)
    flow_run_repo.list_stale_queued_runs.return_value = [stale_run]
    flow_run_repo.claim_stale_queued_run_for_redispatch.return_value = stale_run
    execution_backend.dispatch.side_effect = RuntimeError("broker down")
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    with pytest.raises(RuntimeError, match="broker down"):
        await service.redispatch_stale_queued_runs(
            flow_id=flow_id,
            run_id=stale_run.id,
            limit=1,
            execution_backend=execution_backend,
        )

    execution_backend.dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_redispatch_stale_queued_runs_skips_unclaimable_runs(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    execution_backend = AsyncMock()
    flow_id = uuid4()
    stale_run = _run(user=user, flow_id=flow_id)
    flow_run_repo.list_stale_queued_runs.return_value = [stale_run]
    flow_run_repo.claim_stale_queued_run_for_redispatch.return_value = None
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    count = await service.redispatch_stale_queued_runs(
        flow_id=flow_id,
        execution_backend=execution_backend,
    )

    assert count == 0
    execution_backend.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_rejects_oversized_input_payload(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow = _flow(user=user, published_version=1)
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0

    with pytest.raises(BadRequestException, match="exceeds allowed size limit") as exc_info:
        await service.create_run(
            flow_id=flow.id,
            input_payload_json={"text": "x" * (2 * 1024 * 1024)},
        )
    assert exc_info.value.code == "flow_run_input_payload_too_large"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("definition_json", "message_fragment", "error_code", "error_context"),
    [
        ({}, "does not contain executable steps", "flow_version_no_executable_steps", None),
        (
            {"steps": []},
            "does not contain executable steps",
            "flow_version_no_executable_steps",
            None,
        ),
        (
            {"steps": ["bad-step"]},
            "Invalid flow version step definition",
            "flow_version_invalid_step_definition",
            None,
        ),
        (
            {"steps": [{"step_order": 0, "step_id": str(uuid4()), "assistant_id": str(uuid4())}]},
            "Invalid flow version step order",
            "flow_version_invalid_step_order",
            {"step_order": 0},
        ),
        (
            {"steps": [{"step_order": "abc", "step_id": str(uuid4()), "assistant_id": str(uuid4())}]},
            "Invalid flow version step order",
            "flow_version_invalid_step_order",
            {"step_order": "abc"},
        ),
        (
            {"steps": [{"step_order": True, "step_id": str(uuid4()), "assistant_id": str(uuid4())}]},
            "Invalid flow version step order",
            "flow_version_invalid_step_order",
            {"step_order": True},
        ),
        (
            {"steps": [{"step_order": 1, "step_id": "not-a-uuid", "assistant_id": str(uuid4())}]},
            "Invalid flow version step identifier",
            "flow_version_invalid_step_identifier",
            {"step_order": 1, "field": "step_id", "value": "not-a-uuid"},
        ),
        (
            {"steps": [{"step_order": 1, "step_id": str(uuid4()), "assistant_id": "bad-assistant-id"}]},
            "Invalid flow version step identifier",
            "flow_version_invalid_step_identifier",
            {"step_order": 1, "field": "assistant_id", "value": "bad-assistant-id"},
        ),
    ],
)
async def test_create_run_rejects_invalid_published_snapshot(
    user,
    definition_json,
    message_fragment,
    error_code,
    error_context,
):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow = _flow(user=user, published_version=1)
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = FlowVersion(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum="checksum",
        definition_json=definition_json,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    with pytest.raises(BadRequestException, match=message_fragment) as exc_info:
        await service.create_run(flow_id=flow.id, input_payload_json={"x": "y"})
    assert exc_info.value.code == error_code
    assert exc_info.value.context == error_context


@pytest.mark.asyncio
async def test_cancel_run_marks_pending_steps_cancelled(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    run = _run(user=user, flow_id=uuid4()).model_copy(update={"status": FlowRunStatus.RUNNING})
    cancelled_run = run.model_copy(update={"status": FlowRunStatus.CANCELLED})
    flow_run_repo.get.return_value = run
    flow_run_repo.cancel.return_value = cancelled_run
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    result = await service.cancel_run(run_id=run.id)

    assert result.status == FlowRunStatus.CANCELLED
    flow_run_repo.mark_pending_steps_cancelled.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
        error_message="Run cancelled by user.",
    )
    flow_run_repo.cancel.assert_awaited_once_with(run_id=run.id, tenant_id=user.tenant_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    (
        FlowRunStatus.COMPLETED,
        FlowRunStatus.FAILED,
        FlowRunStatus.CANCELLED,
    ),
)
async def test_cancel_run_is_noop_for_terminal_status(user, status):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    run = _run(user=user, flow_id=uuid4()).model_copy(update={"status": status})
    flow_run_repo.get.return_value = run
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    result = await service.cancel_run(run_id=run.id)

    assert result.status == status
    flow_run_repo.mark_pending_steps_cancelled.assert_not_awaited()
    flow_run_repo.cancel.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_resolves_missing_snapshot_identifiers_from_fallback_steps(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = FlowVersion(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {"step_order": 1},
                {
                    "step_order": 2,
                    "step_id": str(flow.steps[1].id),
                    "assistant_id": str(flow.steps[1].assistant_id),
                },
            ]
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    created_run = _run(user=user, flow_id=flow.id)
    flow_run_repo.create.return_value = created_run

    await service.create_run(flow_id=flow.id, input_payload_json={"x": "y"})

    preseed_steps = flow_run_repo.create.await_args.kwargs["preseed_steps"]
    assert preseed_steps[0]["step_order"] == 1
    assert preseed_steps[0]["step_id"] == flow.steps[0].id
    assert preseed_steps[0]["assistant_id"] == flow.steps[0].assistant_id
    assert preseed_steps[1]["step_order"] == 2
    assert preseed_steps[1]["step_id"] == flow.steps[1].id
    assert preseed_steps[1]["assistant_id"] == flow.steps[1].assistant_id


@pytest.mark.asyncio
async def test_create_run_rejects_missing_snapshot_identifiers_without_fallback(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1).model_copy(update={"steps": [_step(1)]})
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = FlowVersion(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_order": 2,
                    "step_id": None,
                    "assistant_id": None,
                }
            ]
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    with pytest.raises(BadRequestException, match="missing stable step identifiers") as exc_info:
        await service.create_run(flow_id=flow.id, input_payload_json={"x": "y"})
    assert exc_info.value.code == "flow_version_missing_step_identifiers"
    assert exc_info.value.context == {"step_order": 2}


@pytest.mark.asyncio
async def test_get_evidence_redacts_sensitive_values(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={
            "input_payload_json": {
                "text": "hello",
                "api_key": "sk-secret",
                "api-key": "sk-secret-hyphen",
                "api.token": "sk-secret-dot",
                "webhook_url": "https://alice:secret@example.org/hook?token=abc",
            }
        }
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = FlowVersion(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_order": 1,
                    "output_config": {
                        "url": "https://service.example.com/notify?api_key=hidden&x-api-key=hidden2",
                        "headers": {
                            "Authorization": "Bearer top-secret",
                            "X-Api-Key": "top-secret-hyphen",
                            "X-Trace": "ok",
                        },
                    },
                }
            ]
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    flow_run_repo.list_step_results.return_value = [
        SimpleNamespace(
            model_dump=lambda mode="json": {
                "step_order": 1,
                "input_payload_json": {
                    "text": "safe",
                    "token": "abc",
                    "x-api-key": "abc-2",
                    "auth.token": "abc-3",
                    "contract_validation": {
                        "schema_type_hint": "object",
                        "parse_attempted": True,
                        "parse_succeeded": False,
                        "candidate_type": "str",
                    },
                },
                "effective_prompt": "Authorization: Bearer xyz",
                "output_payload_json": {
                    "url": "https://bob:pw@example.org/path?client_secret=x&client.secret=z&api-key=y",
                },
            }
        )
    ]
    flow_run_repo.list_step_attempts.return_value = [
        SimpleNamespace(
            model_dump=lambda mode="json": {
                "attempt_no": 1,
                "error_message": "Bearer should-hide",
            }
        )
    ]

    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    evidence = await service.get_evidence(run_id=run.id)

    assert evidence["run"]["input_payload_json"]["api_key"] == "[REDACTED]"
    assert evidence["run"]["input_payload_json"]["api-key"] == "[REDACTED]"
    assert evidence["run"]["input_payload_json"]["api.token"] == "[REDACTED]"
    assert evidence["run"]["input_payload_json"]["webhook_url"] == "https://example.org/hook?token=%5BREDACTED%5D"
    assert (
        evidence["definition_snapshot"]["steps"][0]["output_config"]["headers"]["Authorization"]
        == "[REDACTED]"
    )
    assert evidence["definition_snapshot"]["steps"][0]["output_config"]["headers"]["X-Api-Key"] == "[REDACTED]"
    assert evidence["definition_snapshot"]["steps"][0]["output_config"]["url"] == (
        "https://service.example.com/notify?api_key=%5BREDACTED%5D&x-api-key=%5BREDACTED%5D"
    )
    assert evidence["step_results"][0]["input_payload_json"]["token"] == "[REDACTED]"
    assert evidence["step_results"][0]["input_payload_json"]["x-api-key"] == "[REDACTED]"
    assert evidence["step_results"][0]["input_payload_json"]["auth.token"] == "[REDACTED]"
    assert evidence["step_results"][0]["input_payload_json"]["contract_validation"] == {
        "schema_type_hint": "object",
        "parse_attempted": True,
        "parse_succeeded": False,
        "candidate_type": "str",
    }
    assert evidence["step_results"][0]["effective_prompt"] == "Authorization: Bearer [REDACTED]"
    assert evidence["step_results"][0]["output_payload_json"]["url"] == (
        "https://example.org/path?client_secret=%5BREDACTED%5D&client.secret=%5BREDACTED%5D&api-key=%5BREDACTED%5D"
    )
    assert evidence["step_attempts"][0]["error_message"] == "Bearer [REDACTED]"
    assert evidence["debug_export"]["schema_version"] == "eneo.flow.debug-export.v1"
    assert evidence["debug_export"]["definition"]["checksum"] == "checksum"
    assert evidence["debug_export"]["run"]["status"] == "queued"
    assert evidence["debug_export"]["steps"][0]["input"]["source"] is None
    assert evidence["debug_export"]["steps"][0]["mcp"]["tool_allowlist"] == []
    assert (
        evidence["debug_export"]["definition_snapshot"]["steps"][0]["output_config"]["headers"]["Authorization"]
        == "[REDACTED]"
    )


@pytest.mark.asyncio
async def test_get_evidence_includes_rag_metadata_in_debug_export(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    run = _run(user=user, flow_id=flow.id)
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = FlowVersion(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_order": 1,
                    "step_id": str(uuid4()),
                    "assistant_id": str(uuid4()),
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "text",
                    "mcp_policy": "inherit",
                }
            ]
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    flow_run_repo.list_step_results.return_value = [
        SimpleNamespace(
            step_order=1,
            input_payload_json={
                "text": "hello",
                "rag": {
                    "attempted": True,
                    "status": "success",
                    "version": 1,
                    "timeout_seconds": 30,
                    "include_info_blobs": False,
                    "chunks_retrieved": 5,
                    "raw_chunks_count": 5,
                    "deduped_chunks_count": 2,
                    "unique_sources": 2,
                    "source_ids": ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
                    "source_ids_short": ["aaaaaaaa"],
                    "error_code": None,
                    "retrieval_duration_ms": 87,
                    "retrieval_error_type": None,
                    "references_truncated": False,
                    "references": [
                        {
                            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                            "id_short": "aaaaaaaa",
                            "title": "Sundsvall source",
                            "hit_count": 2,
                            "best_score": 0.92,
                            "chunks": [
                                {
                                    "chunk_no": 1,
                                    "score": 0.92,
                                    "snippet": "Sundsvall redovisar positivt resultat.",
                                }
                            ],
                        }
                    ],
                },
            },
            model_dump=lambda mode="json": {
                "step_order": 1,
                "input_payload_json": {
                    "text": "hello",
                    "rag": {
                        "attempted": True,
                        "status": "success",
                        "version": 1,
                        "timeout_seconds": 30,
                        "include_info_blobs": False,
                        "chunks_retrieved": 5,
                        "raw_chunks_count": 5,
                        "deduped_chunks_count": 2,
                        "unique_sources": 2,
                        "source_ids": ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
                        "source_ids_short": ["aaaaaaaa"],
                        "error_code": None,
                        "retrieval_duration_ms": 87,
                        "retrieval_error_type": None,
                        "references_truncated": False,
                        "references": [
                            {
                                "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                                "id_short": "aaaaaaaa",
                                "title": "Sundsvall source",
                                "hit_count": 2,
                                "best_score": 0.92,
                                "chunks": [
                                    {
                                        "chunk_no": 1,
                                        "score": 0.92,
                                        "snippet": "Sundsvall redovisar positivt resultat.",
                                    }
                                ],
                            }
                        ],
                    },
                },
            },
        )
    ]
    flow_run_repo.list_step_attempts.return_value = []

    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    evidence = await service.get_evidence(run_id=run.id)

    assert evidence["debug_export"]["steps"][0]["rag"]["status"] == "success"
    assert evidence["debug_export"]["steps"][0]["rag"]["chunks_retrieved"] == 5
    assert evidence["debug_export"]["steps"][0]["rag"]["retrieval_duration_ms"] == 87
    assert evidence["debug_export"]["steps"][0]["rag"]["raw_chunks_count"] == 5
    assert evidence["debug_export"]["steps"][0]["rag"]["deduped_chunks_count"] == 2
    assert evidence["debug_export"]["steps"][0]["rag"]["references"][0]["title"] == "Sundsvall source"
    assert evidence["debug_export"]["steps"][0]["rag"]["references"][0]["chunks"][0]["chunk_no"] == 1
    assert evidence["debug_export"]["steps"][0]["rag"]["source_ids_short"] == ["aaaaaaaa"]


@pytest.mark.asyncio
async def test_get_evidence_sets_rag_to_null_when_metadata_missing(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    run = _run(user=user, flow_id=flow.id)
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = FlowVersion(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_order": 1,
                    "step_id": str(uuid4()),
                    "assistant_id": str(uuid4()),
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "text",
                    "mcp_policy": "inherit",
                }
            ]
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    flow_run_repo.list_step_results.return_value = [
        SimpleNamespace(
            step_order=1,
            input_payload_json={"text": "hello"},
            model_dump=lambda mode="json": {
                "step_order": 1,
                "input_payload_json": {"text": "hello"},
            },
        )
    ]
    flow_run_repo.list_step_attempts.return_value = []

    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    evidence = await service.get_evidence(run_id=run.id)

    assert evidence["debug_export"]["steps"][0]["rag"] is None


@pytest.mark.asyncio
async def test_get_evidence_ignores_rag_metadata_when_step_order_is_boolean(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    run = _run(user=user, flow_id=flow.id)
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = FlowVersion(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_order": 1,
                    "step_id": str(uuid4()),
                    "assistant_id": str(uuid4()),
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "text",
                    "mcp_policy": "inherit",
                }
            ]
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    flow_run_repo.list_step_results.return_value = [
        SimpleNamespace(
            step_order=True,
            input_payload_json={
                "text": "hello",
                "rag": {"status": "success", "chunks_retrieved": 1},
            },
            model_dump=lambda mode="json": {
                "step_order": True,
                "input_payload_json": {
                    "text": "hello",
                    "rag": {"status": "success", "chunks_retrieved": 1},
                },
            },
        )
    ]
    flow_run_repo.list_step_attempts.return_value = []

    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    evidence = await service.get_evidence(run_id=run.id)

    assert evidence["debug_export"]["steps"][0]["rag"] is None


@pytest.mark.asyncio
async def test_list_step_results_filters_by_run_and_flow(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
    )
    run = _run(user=user, flow_id=uuid4())
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = [
        SimpleNamespace(step_order=1),
        SimpleNamespace(step_order=2),
    ]

    results = await service.list_step_results(run_id=run.id, flow_id=run.flow_id)

    assert len(results) == 2
    flow_run_repo.get.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
        flow_id=run.flow_id,
    )
    flow_run_repo.list_step_results.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
    )


# ---------------------------------------------------------------------------
# get_run_artifact_file tests
# ---------------------------------------------------------------------------


def _step_result_with_artifacts(
    run, artifacts=None, generated_file_ids=None,
):
    payload = {}
    if artifacts is not None:
        payload["artifacts"] = artifacts
    if generated_file_ids is not None:
        payload["generated_file_ids"] = generated_file_ids
    return SimpleNamespace(
        id=uuid4(),
        flow_run_id=run.id,
        step_order=1,
        output_payload_json=payload,
    )


def _file(file_id, tenant_id, name="artifact.docx"):
    return SimpleNamespace(
        id=file_id,
        tenant_id=tenant_id,
        name=name,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size=1024,
    )


def _artifact_service(user, file_repo=None, step_results=None, run=None):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    if run is None:
        run = _run(user=user, flow_id=uuid4())
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = step_results or []
    return FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        file_repo=file_repo,
    ), run


@pytest.mark.asyncio
async def test_get_run_artifact_file_happy_path(user):
    """File found in step artifacts is returned."""
    file_id = uuid4()
    run = _run(user=user, flow_id=uuid4())
    file_repo = AsyncMock()
    file_obj = _file(file_id=file_id, tenant_id=user.tenant_id)
    file_repo.get_by_id.return_value = file_obj

    step_results = [_step_result_with_artifacts(
        run, artifacts=[{"file_id": str(file_id), "name": "out.docx"}],
    )]
    service, run = _artifact_service(
        user, file_repo=file_repo, step_results=step_results, run=run,
    )

    result = await service.get_run_artifact_file(
        run_id=run.id, flow_id=run.flow_id, file_id=file_id,
    )
    assert result.id == file_id
    file_repo.get_by_id.assert_awaited_once_with(file_id=file_id)


@pytest.mark.asyncio
async def test_get_run_artifact_file_from_generated_file_ids(user):
    """File found in generated_file_ids (not artifacts) is returned."""
    file_id = uuid4()
    run = _run(user=user, flow_id=uuid4())
    file_repo = AsyncMock()
    file_repo.get_by_id.return_value = _file(file_id=file_id, tenant_id=user.tenant_id)

    step_results = [_step_result_with_artifacts(
        run, generated_file_ids=[str(file_id)],
    )]
    service, run = _artifact_service(
        user, file_repo=file_repo, step_results=step_results, run=run,
    )

    result = await service.get_run_artifact_file(
        run_id=run.id, flow_id=run.flow_id, file_id=file_id,
    )
    assert result.id == file_id


@pytest.mark.asyncio
async def test_get_run_artifact_file_rejects_unknown_file_id(user):
    """NotFoundException when file_id is not in any step result."""
    file_id = uuid4()
    other_file_id = uuid4()
    run = _run(user=user, flow_id=uuid4())
    file_repo = AsyncMock()

    step_results = [_step_result_with_artifacts(
        run, artifacts=[{"file_id": str(other_file_id)}],
    )]
    service, run = _artifact_service(
        user, file_repo=file_repo, step_results=step_results, run=run,
    )

    with pytest.raises(NotFoundException) as exc_info:
        await service.get_run_artifact_file(
            run_id=run.id, flow_id=run.flow_id, file_id=file_id,
        )
    assert exc_info.value.code == "flow_run_artifact_not_found"
    file_repo.get_by_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_run_artifact_file_rejects_cross_tenant(user):
    """UnauthorizedException when file belongs to a different tenant."""
    file_id = uuid4()
    run = _run(user=user, flow_id=uuid4())
    file_repo = AsyncMock()
    file_repo.get_by_id.return_value = _file(
        file_id=file_id, tenant_id=uuid4(),  # different tenant
    )

    step_results = [_step_result_with_artifacts(
        run, artifacts=[{"file_id": str(file_id)}],
    )]
    service, run = _artifact_service(
        user, file_repo=file_repo, step_results=step_results, run=run,
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.get_run_artifact_file(
            run_id=run.id, flow_id=run.flow_id, file_id=file_id,
        )
    assert exc_info.value.code == "forbidden_action"


@pytest.mark.asyncio
async def test_get_run_artifact_file_empty_step_results(user):
    """NotFoundException when run has no step results at all."""
    file_id = uuid4()
    run = _run(user=user, flow_id=uuid4())
    file_repo = AsyncMock()

    service, run = _artifact_service(
        user, file_repo=file_repo, step_results=[], run=run,
    )

    with pytest.raises(NotFoundException) as exc_info:
        await service.get_run_artifact_file(
            run_id=run.id, flow_id=run.flow_id, file_id=file_id,
        )
    assert exc_info.value.code == "flow_run_artifact_not_found"


@pytest.mark.asyncio
async def test_get_run_artifact_file_no_file_repo(user):
    """BadRequestException when file_repo is None (e.g. celery worker context)."""
    service, run = _artifact_service(user, file_repo=None)

    with pytest.raises(BadRequestException) as exc_info:
        await service.get_run_artifact_file(
            run_id=run.id, flow_id=run.flow_id, file_id=uuid4(),
        )
    assert exc_info.value.code == "file_repo_unavailable"


@pytest.mark.asyncio
async def test_get_run_artifact_file_collects_from_multiple_steps(user):
    """Artifacts scattered across multiple step results are all collected."""
    file_id_a = uuid4()
    file_id_b = uuid4()
    run = _run(user=user, flow_id=uuid4())
    file_repo = AsyncMock()
    file_repo.get_by_id.return_value = _file(file_id=file_id_b, tenant_id=user.tenant_id)

    step_results = [
        _step_result_with_artifacts(run, artifacts=[{"file_id": str(file_id_a)}]),
        _step_result_with_artifacts(run, generated_file_ids=[str(file_id_b)]),
    ]
    service, run = _artifact_service(
        user, file_repo=file_repo, step_results=step_results, run=run,
    )

    # file_id_b from second step's generated_file_ids should be found
    result = await service.get_run_artifact_file(
        run_id=run.id, flow_id=run.flow_id, file_id=file_id_b,
    )
    assert result.id == file_id_b


@pytest.mark.asyncio
async def test_get_run_artifact_file_ignores_malformed_payloads(user):
    """Steps with non-dict output_payload_json or missing artifacts are skipped."""
    file_id = uuid4()
    run = _run(user=user, flow_id=uuid4())
    file_repo = AsyncMock()

    step_results = [
        SimpleNamespace(id=uuid4(), flow_run_id=run.id, step_order=1, output_payload_json=None),
        SimpleNamespace(id=uuid4(), flow_run_id=run.id, step_order=2, output_payload_json="not a dict"),
        SimpleNamespace(id=uuid4(), flow_run_id=run.id, step_order=3, output_payload_json={}),
    ]
    service, run = _artifact_service(
        user, file_repo=file_repo, step_results=step_results, run=run,
    )

    with pytest.raises(NotFoundException) as exc_info:
        await service.get_run_artifact_file(
            run_id=run.id, flow_id=run.flow_id, file_id=file_id,
        )
    assert exc_info.value.code == "flow_run_artifact_not_found"
