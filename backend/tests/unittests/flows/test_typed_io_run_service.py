"""FlowRunService step input contract tests."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.authentication.principal_types import PrincipalType
from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.application.flow_run_service import FlowRunService
from eneo.flows.domain.flow import (
    Flow,
    FlowRun,
    FlowRunStatus,
    FlowStep,
    FlowVersion,
)
from eneo.flows.flow_run_input_envelope import FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS
from eneo.flows.flow_run_step_inputs import FlowRunStepInputFiles
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRepository,
)
from eneo.flows.published_definition import (
    FLOW_DEFINITION_SCHEMA_VERSION,
    published_definition_checksum,
)
from eneo.main.exceptions import BadRequestException


def _flow_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.session = AsyncMock()
    repo.session.execute = AsyncMock()
    return repo


def _runtime_upload_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.list_bound_file_ids_for_owner.return_value = set()
    return repo


_FILE_REPO_UNSET = object()


def _file_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_list_by_id_for_owner.return_value = []
    return repo


def _flow_run_service(
    *,
    user,
    flow_repo,
    flow_run_repo,
    flow_version_repo,
    runtime_upload_repo,
    file_repo=_FILE_REPO_UNSET,
    max_concurrent_runs=None,
) -> FlowRunService:
    resolved_file_repo = _file_repo() if file_repo is _FILE_REPO_UNSET else file_repo
    if resolved_file_repo is None:
        raise AssertionError("FlowRunService tests must provide a file repository.")
    return FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=runtime_upload_repo,
        file_repo=resolved_file_repo,
        flow_run_terminalizer=AsyncMock(),
        webhook_delivery_repo=AsyncMock(spec=FlowRunWebhookDeliveryRepository),
        access_policy=FlowRunAccessPolicy(
            user=user,
            flow_repo=flow_repo,
            flow_run_repo=flow_run_repo,
        ),
        max_concurrent_runs=max_concurrent_runs,
    )


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
    definition_json = {
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
            }
            for step in flow.steps
        ],
    }
    return FlowVersion(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum=published_definition_checksum(definition_json),
        definition_json=definition_json,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("reserved_key", sorted(FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS))
async def test_create_run_rejects_reserved_input_payload_keys(user, reserved_key: str):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user)
    flow_repo.get = AsyncMock(return_value=flow)
    flow_version_repo.get = AsyncMock(return_value=_version(user, flow))

    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
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
async def test_create_run_stores_step_inputs_as_execution_file_rows(user):
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
        principal_type=PrincipalType.USER,
        principal_user_id=user.id,
        tenant_id=user.tenant_id,
        trace_id=uuid4(),
        status=FlowRunStatus.QUEUED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json=None,
        job_id=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    flow_run_repo.create = AsyncMock(return_value=created_run)
    file_repo = _file_repo()
    runtime_upload_repo = _runtime_upload_repo()

    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=runtime_upload_repo,
        file_repo=file_repo,
        max_concurrent_runs=10,
    )

    file_id_1 = uuid4()
    file_id_2 = uuid4()
    runtime_upload_repo.list_bound_file_ids_for_owner.return_value = {
        file_id_1,
        file_id_2,
    }
    file_repo.get_list_by_id_for_owner.return_value = [
        SimpleNamespace(id=file_id, mimetype="application/pdf", size=1024)
        for file_id in (file_id_2, file_id_1)
    ]
    await service.create_run(
        flow_id=flow.id,
        input_payload_json={"text": "hello"},
        step_inputs={
            flow.steps[0].id: FlowRunStepInputFiles(file_ids=(file_id_2, file_id_1))
        },
    )

    create_kwargs = flow_run_repo.create.await_args.kwargs
    payload = create_kwargs["input_payload_json"]
    assert payload["expected_flow_version"] == 1
    assert "step_inputs" not in payload
    assert payload["text"] == "hello"
    assert create_kwargs["step_input_files"] == [
        {
            "step_id": flow.steps[0].id,
            "step_order": 1,
            "file_ids": [file_id_2, file_id_1],
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
        principal_type=PrincipalType.USER,
        principal_user_id=user.id,
        tenant_id=user.tenant_id,
        trace_id=uuid4(),
        status=FlowRunStatus.QUEUED,
        cancelled_at=None,
        input_payload_json={"text": "hello"},
        output_payload_json=None,
        job_id=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    flow_run_repo.create = AsyncMock(return_value=created_run)

    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
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
