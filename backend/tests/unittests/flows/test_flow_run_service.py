from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from intric.authentication.auth_models import (
    ResourcePermissionLevel,
    ResourcePermissions,
)
from intric.authentication.principal_types import PrincipalType
from intric.files.file_models import FileType
from intric.flows.application.flow_run_service import FlowRunService
from intric.flows.domain.flow import (
    FlowRunRerunInvalidatedStep,
    FlowRunRerunOperation,
    FlowRunReviewCheckpoint,
)
from intric.flows.enums import (
    FlowRunLifecycleSource,
    FlowRunRerunInvalidationRole,
    FlowRunRerunOperationStatus,
    FlowRunReviewCheckpointState,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
    RerunDependencyKind,
)
from intric.flows.flow import (
    Flow,
    FlowRun,
    FlowRunStatus,
    FlowStep,
    FlowStepAttempt,
    FlowStepResult,
    FlowVersion,
)
from intric.flows.flow_run_provenance import FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION
from intric.flows.flow_run_rerun_request import (
    FlowRunRerunRequestFingerprintInput,
    build_rerun_request_fingerprint,
)
from intric.flows.flow_run_step_result_file import FlowRunStepResultFile
from intric.flows.infrastructure.flow_run_repo import (
    FlowRunRerunCommandResult,
    FlowRunReviewCheckpointResumeResult,
)
from intric.flows.published_definition import (
    FLOW_DEFINITION_SCHEMA_VERSION,
    build_published_definition_json,
)
from intric.main.exceptions import (
    BadRequestException,
    NotFoundException,
    ResourceGoneException,
    UnauthorizedException,
)
from intric.roles.permissions import Permission


def _flow_repo() -> AsyncMock:
    return AsyncMock()


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
        principal_type="user",
        principal_user_id=user.id,
        user_id=user.id,
        tenant_id=user.tenant_id,
        trace_id=uuid4(),
        status=FlowRunStatus.QUEUED,
        cancelled_at=None,
        input_payload_json={"input": "value"},
        output_payload_json=None,
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )


def _service_key_user(user):
    return user.model_copy(
        update={
            "active_api_key": SimpleNamespace(
                id=uuid4(),
                ownership="service",
                resource_permissions=None,
            ),
        }
    )


def _trace_user(user):
    return user.model_copy(
        update={
            "permissions": {Permission.FLOWS_VIEW, Permission.FLOWS_TRACE},
            "roles": [
                SimpleNamespace(
                    permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_TRACE]
                )
            ],
        }
    )


def _published_definition_json(
    flow: Flow,
    steps: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
        "flow_id": str(flow.id),
        "steps": steps,
    }


def _step_result_record(
    run: FlowRun,
    *,
    step_order: int,
    input_payload_json: dict[str, object] | None = None,
    output_payload_json: dict[str, object] | None = None,
    effective_prompt: str | None = None,
    error_message: str | None = None,
) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        input_payload_json=input_payload_json,
        effective_prompt=effective_prompt,
        output_payload_json=output_payload_json,
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        error_message=error_message,
        flow_step_execution_hash=None,
        created_at=now,
        updated_at=now,
    )


def _step_attempt_record(
    run: FlowRun,
    *,
    step_order: int,
    attempt_no: int = 1,
    error_message: str | None = None,
    error_code: str | None = None,
    requested_model: str | None = None,
    response_model: str | None = None,
    provider: str | None = None,
    finish_reason: str | None = None,
    provider_response_id: str | None = None,
    num_tokens_input: int | None = None,
    num_tokens_output: int | None = None,
    provenance_json: dict[str, object] | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> FlowStepAttempt:
    now = datetime.now(timezone.utc)
    return FlowStepAttempt(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=step_order,
        attempt_no=attempt_no,
        celery_task_id=None,
        status=FlowStepAttemptStatus.COMPLETED,
        error_code=error_code,
        error_message=error_message,
        requested_model=requested_model,
        response_model=response_model,
        provider=provider,
        finish_reason=finish_reason,
        provider_response_id=provider_response_id,
        num_tokens_input=num_tokens_input,
        num_tokens_output=num_tokens_output,
        provenance_json=provenance_json,
        started_at=started_at or now,
        finished_at=finished_at,
        created_at=now,
        updated_at=now,
    )


def _version(user, flow: Flow, version: int = 1) -> FlowVersion:
    return FlowVersion(
        flow_id=flow.id,
        version=version,
        tenant_id=user.tenant_id,
        definition_checksum="checksum",
        definition_json=_published_definition_json(
            flow,
            [
                {
                    "step_id": str(step.id),
                    "step_order": step.step_order,
                    "assistant_id": str(step.assistant_id),
                }
                for step in flow.steps
            ],
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _published_runtime_step(step: FlowStep) -> dict[str, object]:
    def enum_or_string(value: object) -> object:
        return getattr(value, "value", value)

    return {
        "step_id": str(step.id),
        "assistant_id": str(step.assistant_id),
        "step_order": step.step_order,
        "user_description": step.user_description,
        "input_source": enum_or_string(step.input_source),
        "input_type": enum_or_string(step.input_type),
        "input_contract": step.input_contract,
        "input_bindings": step.input_bindings,
        "input_config": step.input_config,
        "output_mode": enum_or_string(step.output_mode),
        "output_type": enum_or_string(step.output_type),
        "output_contract": step.output_contract,
        "output_config": step.output_config,
        "output_classification_override": step.output_classification_override,
        "mcp_policy": enum_or_string(step.mcp_policy),
    }


def _runtime_version(user, flow: Flow, version: int = 1) -> FlowVersion:
    return FlowVersion(
        flow_id=flow.id,
        version=version,
        tenant_id=user.tenant_id,
        definition_checksum="checksum",
        definition_json=build_published_definition_json(
            flow_id=flow.id,
            name=flow.name,
            description=flow.description,
            metadata_json=flow.metadata_json,
            steps=[_published_runtime_step(step) for step in flow.steps],
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _rerun_command_result(
    *,
    user,
    run: FlowRun,
    rerun_step_id: UUID,
    invalidated_step_ids: list[UUID],
    created: bool = True,
) -> FlowRunRerunCommandResult:
    now = datetime.now(timezone.utc)
    operation_id = uuid4()
    operation = FlowRunRerunOperation(
        id=operation_id,
        tenant_id=user.tenant_id,
        flow_id=run.flow_id,
        flow_run_id=run.id,
        rerun_step_id=rerun_step_id,
        rerun_step_order=1,
        root_attempt_no=2,
        root_attempt_id=None,
        status=FlowRunRerunOperationStatus.QUEUED,
        request_fingerprint="fingerprint",
        expected_run_revision=run.revision,
        accepted_run_revision=run.revision,
        reason="Fix source",
        input_payload_json=None,
        step_inputs_json=None,
        requested_by_principal_type=PrincipalType.USER,
        requested_by_user_id=user.id,
        failure_code=None,
        failure_message=None,
        started_at=None,
        finished_at=None,
        created_at=now,
        updated_at=now,
    )
    invalidated_steps = tuple(
        FlowRunRerunInvalidatedStep(
            id=uuid4(),
            operation_id=operation_id,
            tenant_id=user.tenant_id,
            flow_id=run.flow_id,
            flow_run_id=run.id,
            step_id=step_id,
            step_order=index,
            invalidation_order=index,
            role=(
                FlowRunRerunInvalidationRole.ROOT
                if step_id == rerun_step_id
                else FlowRunRerunInvalidationRole.DOWNSTREAM
            ),
            dependency_sources_json=[]
            if step_id == rerun_step_id
            else [RerunDependencyKind.INPUT_SOURCE_PREVIOUS_STEP],
            prior_step_result_id=uuid4(),
            prior_attempt_id=uuid4(),
            new_attempt_no=None,
            new_attempt_id=None,
            created_at=now,
            updated_at=now,
        )
        for index, step_id in enumerate(invalidated_step_ids, start=1)
    )
    return FlowRunRerunCommandResult(
        operation=operation,
        run=run,
        invalidated_steps=invalidated_steps,
        created=created,
    )


def _review_checkpoint(
    user,
    run: FlowRun,
    *,
    state: FlowRunReviewCheckpointState = FlowRunReviewCheckpointState.AWAITING_REVIEW,
    revision: int = 1,
    resume_idempotency_key: str | None = None,
) -> FlowRunReviewCheckpoint:
    now = datetime.now(timezone.utc)
    return FlowRunReviewCheckpoint(
        id=uuid4(),
        tenant_id=user.tenant_id,
        flow_id=run.flow_id,
        flow_run_id=run.id,
        step_id=uuid4(),
        step_order=1,
        attempt_no=1,
        state=state,
        revision=revision,
        schema_version=1,
        original_payload_json={"text": "Draft"},
        current_payload_json={"text": "Draft"},
        requester_user_id=user.id,
        requester_principal_type=PrincipalType.USER,
        decided_by_user_id=None,
        decided_by_principal_type=None,
        next_step_ids_json=[],
        resume_idempotency_key=resume_idempotency_key,
        edited_at=None,
        approved_at=None,
        rejected_at=None,
        resumed_at=None,
        cancelled_at=None,
        created_at=now,
        updated_at=now,
    )


def _form_schema_flow(user) -> Flow:
    return _flow(
        user=user,
        published_version=1,
        metadata_json={
            "form_schema": {
                "fields": [
                    {
                        "name": "Namn på brukare",
                        "type": "text",
                        "required": True,
                        "order": 1,
                    },
                    {
                        "name": "Personnummer",
                        "type": "text",
                        "required": True,
                        "order": 2,
                    },
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
                    {
                        "name": "Mötesdatum",
                        "type": "date",
                        "required": False,
                        "order": 5,
                    },
                    {
                        "name": "Antal timmar",
                        "type": "number",
                        "required": False,
                        "order": 6,
                    },
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
    flow_run_repo.acquire_tenant_run_creation_lock.assert_awaited_once_with(
        tenant_id=user.tenant_id
    )


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
    flow_run_repo.get_idempotent_run.return_value = None
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=2)
    flow_run_repo.create.return_value = _run(user=user, flow_id=flow.id)

    created = await service.create_run(
        flow_id=flow.id, input_payload_json={"case": "123"}
    )

    assert created.status == FlowRunStatus.QUEUED
    flow_run_repo.acquire_tenant_run_creation_lock.assert_awaited_once_with(
        tenant_id=user.tenant_id
    )
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
async def test_create_run_returns_created_run_without_dispatching(user):
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
    flow_run_repo.get_idempotent_run.return_value = None
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    flow_run_repo.create.return_value = created_run

    result = await service.create_run(flow_id=flow.id, input_payload_json={"x": "y"})

    assert result.id == created_run.id
    execution_backend.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_replays_existing_run_for_matching_idempotency_key(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    existing_run = _run(user=user, flow_id=flow.id)
    version = _version(user=user, flow=flow, version=1)
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.get_idempotent_run.return_value = None
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = version
    flow_run_repo.get_idempotent_run.return_value = None

    payload = {"x": "y"}
    expected_fingerprint = service._build_idempotency_fingerprint(
        tenant_id=user.tenant_id,
        principal=service._principal(),
        flow_id=flow.id,
        flow_version=flow.published_version,
        input_payload_json={"x": "y", "expected_flow_version": 1},
    )
    flow_run_repo.get_idempotent_run.return_value = (
        existing_run,
        expected_fingerprint,
    )

    result = await service.create_run(
        flow_id=flow.id,
        input_payload_json=payload,
        idempotency_key="abc123",
    )

    assert result == existing_run
    flow_run_repo.create.assert_not_awaited()
    flow_run_repo.get_idempotent_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_run_with_idempotency_key_creates_when_no_retained_row_exists(
    user,
):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    created_run = _run(user=user, flow_id=flow.id)
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.get_idempotent_run.return_value = None
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    flow_run_repo.create.return_value = created_run

    result = await service.create_run(
        flow_id=flow.id,
        input_payload_json={"x": "y"},
        idempotency_key="abc123",
    )

    assert result == created_run
    flow_run_repo.get_idempotent_run.assert_awaited_once()
    flow_run_repo.count_active_runs.assert_awaited_once()
    flow_run_repo.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_run_persists_service_key_principal(user):
    service_user = _service_key_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=service_user, published_version=1)
    created_run = _run(user=user, flow_id=flow.id).model_copy(
        update={
            "user_id": None,
            "principal_type": "service_key",
            "principal_user_id": None,
            "principal_api_key_id": service_user.active_api_key.id,
        }
    )
    service = FlowRunService(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.get_idempotent_run.return_value = None
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _version(
        user=service_user, flow=flow, version=1
    )
    flow_run_repo.create.return_value = created_run

    result = await service.create_run(
        flow_id=flow.id,
        input_payload_json={"x": "y"},
        idempotency_key="svc-123",
    )

    assert result == created_run
    flow_run_repo.create.assert_awaited_once()
    kwargs = flow_run_repo.create.await_args.kwargs
    assert kwargs["user_id"] is None
    assert kwargs["principal_type"] == "service_key"
    assert kwargs["principal_user_id"] is None
    assert kwargs["principal_api_key_id"] == service_user.active_api_key.id


@pytest.mark.asyncio
async def test_create_run_replays_idempotent_run_before_concurrency_limit(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    existing_run = _run(user=user, flow_id=flow.id)
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=0,
    )
    flow_repo.get.return_value = flow
    expected_fingerprint = service._build_idempotency_fingerprint(
        tenant_id=user.tenant_id,
        principal=service._principal(),
        flow_id=flow.id,
        flow_version=flow.published_version,
        input_payload_json={"x": "y", "expected_flow_version": 1},
    )
    flow_run_repo.get_idempotent_run.return_value = (
        existing_run,
        expected_fingerprint,
    )

    result = await service.create_run(
        flow_id=flow.id,
        input_payload_json={"x": "y"},
        idempotency_key="abc123",
    )

    assert result == existing_run
    flow_run_repo.count_active_runs.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_rejects_invalid_idempotency_key(user):
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

    with pytest.raises(BadRequestException) as exc_info:
        await service.create_run(
            flow_id=flow.id,
            input_payload_json={"x": "y"},
            idempotency_key="x" * 256,
        )

    assert exc_info.value.code == "flow_run_invalid_idempotency_key"


@pytest.mark.asyncio
async def test_create_run_rejects_idempotency_key_replay_with_different_payload(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    existing_run = _run(user=user, flow_id=flow.id)
    version = _version(user=user, flow=flow, version=1)
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = version
    flow_run_repo.get_idempotent_run.return_value = (
        existing_run,
        "different-fingerprint",
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.create_run(
            flow_id=flow.id,
            input_payload_json={"x": "y"},
            idempotency_key="abc123",
        )

    assert exc_info.value.code == "flow_run_idempotency_conflict"
    flow_run_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_persists_even_when_execution_backend_is_configured(user):
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
    execution_backend.dispatch.assert_not_awaited()


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

    with pytest.raises(
        BadRequestException, match="contains invalid option values"
    ) as exc_info:
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
        definition_json=_published_definition_json(
            flow,
            [
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
            ],
        ),
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
    assert flow_run_repo.create.await_args.kwargs["step_input_files"] == [
        {
            "step_id": runtime_step.id,
            "step_order": 1,
            "file_ids": [file_id],
        }
    ]
    flow_version_repo.get.assert_awaited_once_with(
        flow_id=flow.id,
        version=2,
        tenant_id=user.tenant_id,
    )


@pytest.mark.asyncio
async def test_create_run_validates_service_key_step_inputs_by_principal_owner(user):
    service_user = _service_key_user(user)
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
    created_run = _run(user=user, flow_id=flow.id).model_copy(
        update={
            "user_id": None,
            "principal_type": "service_key",
            "principal_user_id": None,
            "principal_api_key_id": service_user.active_api_key.id,
        }
    )
    service = FlowRunService(
        user=service_user,
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
    file_repo.get_list_by_id_for_owner.return_value = [
        SimpleNamespace(id=file_id, mimetype="application/pdf")
    ]
    flow_version_repo.get.return_value = FlowVersion(
        flow_id=flow.id,
        version=2,
        tenant_id=user.tenant_id,
        definition_checksum="checksum",
        definition_json=_published_definition_json(
            flow,
            [
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
            ],
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    await service.create_run(
        flow_id=flow.id,
        expected_flow_version=2,
        input_payload_json={"x": "y"},
        step_inputs={runtime_step.id: {"file_ids": [file_id]}},
    )

    file_repo.get_list_by_id_for_owner.assert_awaited_once_with(
        ids=[file_id],
        owner_type="service_key",
        owner_user_id=None,
        owner_api_key_id=service_user.active_api_key.id,
        include_transcription=False,
    )
    file_repo.get_list_by_id_and_user.assert_not_called()


@pytest.mark.asyncio
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
        definition_json=_published_definition_json(
            flow,
            [
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
            ],
        ),
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
async def test_rerun_step_builds_repository_command(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    file_repo = AsyncMock()
    flow = _flow(user=user, published_version=3)
    root_step = flow.steps[0].model_copy(
        update={
            "input_config": {
                "runtime_input": {
                    "enabled": True,
                    "required": False,
                    "max_files": 5,
                    "input_format": "document",
                }
            }
        }
    )
    downstream_step = flow.steps[1].model_copy(update={"input_source": "previous_step"})
    flow = flow.model_copy(update={"steps": [root_step, downstream_step]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={
            "flow_version": 3,
            "revision": 7,
            "status": FlowRunStatus.COMPLETED,
        }
    )
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        file_repo=file_repo,
        max_concurrent_runs=5,
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(
        user=user, flow=flow, version=3
    )
    prior_root_attempt_id = uuid4()
    flow_run_repo.get_latest_completed_attempt_id_for_step.return_value = (
        prior_root_attempt_id
    )
    expected_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id, downstream_step.id],
    )
    flow_run_repo.accept_or_replay_rerun_operation.return_value = expected_result
    file_a_id = uuid4()
    file_b_id = uuid4()
    expected_file_ids = sorted({file_a_id, file_b_id}, key=str)
    file_repo.get_list_by_id_and_user.return_value = [
        SimpleNamespace(id=file_id, mimetype="application/pdf")
        for file_id in expected_file_ids
    ]

    result = await service.rerun_step(
        flow_id=flow.id,
        run_id=run.id,
        rerun_step_id=root_step.id,
        expected_run_revision=7,
        reason="  Corrected source  ",
        input_payload_json={"case_id": "A-123"},
        step_inputs={root_step.id: {"file_ids": [file_b_id, file_a_id, file_b_id]}},
    )

    assert result == expected_result
    flow_run_repo.get.assert_awaited_once_with(
        run_id=run.id,
        flow_id=flow.id,
        tenant_id=user.tenant_id,
    )
    flow_version_repo.get.assert_awaited_once_with(
        flow_id=flow.id,
        version=3,
        tenant_id=user.tenant_id,
    )
    flow_run_repo.get_latest_completed_attempt_id_for_step.assert_awaited_once_with(
        run_id=run.id,
        flow_id=flow.id,
        tenant_id=user.tenant_id,
        step_id=root_step.id,
    )
    file_repo.get_list_by_id_and_user.assert_awaited_once_with(
        ids=expected_file_ids,
        user_id=user.id,
        include_transcription=False,
    )
    expected_fingerprint = build_rerun_request_fingerprint(
        FlowRunRerunRequestFingerprintInput(
            tenant_id=user.tenant_id,
            requested_by_user_id=user.id,
            flow_id=flow.id,
            flow_run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=7,
            prior_root_attempt_id=prior_root_attempt_id,
            input_payload_json={"case_id": "A-123"},
            root_step_inputs={root_step.id: expected_file_ids},
        )
    )
    kwargs = flow_run_repo.accept_or_replay_rerun_operation.await_args.kwargs
    assert kwargs["tenant_id"] == user.tenant_id
    assert kwargs["flow_id"] == flow.id
    assert kwargs["flow_run_id"] == run.id
    assert kwargs["rerun_step_id"] == root_step.id
    assert kwargs["rerun_step_order"] == root_step.step_order
    assert kwargs["request_fingerprint"] == expected_fingerprint
    assert kwargs["expected_run_revision"] == 7
    assert kwargs["reason"] == "Corrected source"
    assert kwargs["input_payload_json"] == {"case_id": "A-123"}
    assert kwargs["step_inputs_json"] == {
        str(root_step.id): {"file_ids": [str(file_id) for file_id in expected_file_ids]}
    }
    assert kwargs["requested_by_user_id"] == user.id
    invalidated_steps = kwargs["invalidated_steps"]
    assert [
        (step.step_id, step.step_order, step.dependency_kinds)
        for step in invalidated_steps
    ] == [
        (root_step.id, root_step.step_order, ()),
        (
            downstream_step.id,
            downstream_step.step_order,
            (RerunDependencyKind.INPUT_SOURCE_PREVIOUS_STEP,),
        ),
    ]


@pytest.mark.asyncio
async def test_rerun_step_preserves_empty_root_step_inputs(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    root_step = flow.steps[0].model_copy(
        update={
            "input_config": {
                "runtime_input": {
                    "enabled": True,
                    "required": False,
                    "max_files": 5,
                    "input_format": "document",
                }
            }
        }
    )
    flow = flow.model_copy(update={"steps": [root_step]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 3}
    )
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_repo.get_latest_completed_attempt_id_for_step.return_value = None
    expected_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id],
    )
    flow_run_repo.accept_or_replay_rerun_operation.return_value = expected_result

    result = await service.rerun_step(
        flow_id=flow.id,
        run_id=run.id,
        rerun_step_id=root_step.id,
        expected_run_revision=3,
        reason="Refresh answer",
        step_inputs={root_step.id: {"file_ids": []}},
    )

    assert result == expected_result
    expected_fingerprint = build_rerun_request_fingerprint(
        FlowRunRerunRequestFingerprintInput(
            tenant_id=user.tenant_id,
            requested_by_user_id=user.id,
            flow_id=flow.id,
            flow_run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=3,
            prior_root_attempt_id=None,
            input_payload_json=None,
            root_step_inputs={root_step.id: []},
        )
    )
    kwargs = flow_run_repo.accept_or_replay_rerun_operation.await_args.kwargs
    assert kwargs["request_fingerprint"] == expected_fingerprint
    assert kwargs["step_inputs_json"] == {str(root_step.id): {"file_ids": []}}


@pytest.mark.asyncio
async def test_rerun_step_fingerprint_uses_none_without_completed_root_attempt(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 4}
    )
    root_step = flow.steps[0]
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_repo.get_latest_completed_attempt_id_for_step.return_value = None
    expected_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id],
    )
    flow_run_repo.accept_or_replay_rerun_operation.return_value = expected_result

    result = await service.rerun_step(
        flow_id=flow.id,
        run_id=run.id,
        rerun_step_id=root_step.id,
        expected_run_revision=4,
        reason="Refresh answer",
    )

    assert result == expected_result
    expected_fingerprint = build_rerun_request_fingerprint(
        FlowRunRerunRequestFingerprintInput(
            tenant_id=user.tenant_id,
            requested_by_user_id=user.id,
            flow_id=flow.id,
            flow_run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=4,
            prior_root_attempt_id=None,
            input_payload_json=None,
            root_step_inputs=None,
        )
    )
    kwargs = flow_run_repo.accept_or_replay_rerun_operation.await_args.kwargs
    assert kwargs["request_fingerprint"] == expected_fingerprint
    assert kwargs["input_payload_json"] is None
    assert kwargs["step_inputs_json"] is None


@pytest.mark.asyncio
async def test_rerun_step_returns_repository_replay_result(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    root_step = flow.steps[0]
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 2}
    )
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_repo.get_latest_completed_attempt_id_for_step.return_value = uuid4()
    replayed_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id],
        created=False,
    )
    flow_run_repo.accept_or_replay_rerun_operation.return_value = replayed_result

    result = await service.rerun_step(
        flow_id=flow.id,
        run_id=run.id,
        rerun_step_id=root_step.id,
        expected_run_revision=2,
        reason="Refresh answer",
    )

    assert result == replayed_result
    assert result.created is False


@pytest.mark.asyncio
async def test_rerun_step_rejects_empty_reason(user):
    service = FlowRunService(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=AsyncMock(),
        flow_version_repo=AsyncMock(),
        max_concurrent_runs=5,
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=uuid4(),
            run_id=uuid4(),
            rerun_step_id=uuid4(),
            expected_run_revision=1,
            reason="  \n\t  ",
        )

    assert exc_info.value.code == "flow_run_rerun_reason_required"
    service.flow_run_repo.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_rejects_too_long_reason(user):
    flow_run_repo = AsyncMock()
    service = FlowRunService(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_version_repo=AsyncMock(),
        max_concurrent_runs=5,
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=uuid4(),
            run_id=uuid4(),
            rerun_step_id=uuid4(),
            expected_run_revision=1,
            reason="x" * 1025,
        )

    assert exc_info.value.code == "flow_run_rerun_reason_too_long"
    assert exc_info.value.context == {"max_length": 1024}
    flow_run_repo.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_accepts_max_length_reason(user):
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    root_step = flow.steps[0]
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 1}
    )
    service = FlowRunService(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_repo.get_latest_completed_attempt_id_for_step.return_value = None
    expected_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id],
    )
    flow_run_repo.accept_or_replay_rerun_operation.return_value = expected_result
    reason = "x" * 1024

    result = await service.rerun_step(
        flow_id=flow.id,
        run_id=run.id,
        rerun_step_id=root_step.id,
        expected_run_revision=1,
        reason=reason,
    )

    assert result == expected_result
    kwargs = flow_run_repo.accept_or_replay_rerun_operation.await_args.kwargs
    assert kwargs["reason"] == reason


@pytest.mark.asyncio
async def test_rerun_step_rejects_missing_published_root_step(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED}
    )
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=uuid4(),
            expected_run_revision=1,
            reason="Refresh answer",
        )

    assert exc_info.value.code == "flow_run_rerun_step_not_found"
    flow_run_repo.get_latest_completed_attempt_id_for_step.assert_not_awaited()
    flow_run_repo.accept_or_replay_rerun_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_rejects_downstream_step_inputs(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    root_step = flow.steps[0]
    downstream_step = flow.steps[1].model_copy(update={"input_source": "previous_step"})
    flow = flow.model_copy(update={"steps": [root_step, downstream_step]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED}
    )
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=1,
            reason="Refresh answer",
            step_inputs={downstream_step.id: {"file_ids": []}},
        )

    assert exc_info.value.code == "flow_run_rerun_step_inputs_invalid"
    assert exc_info.value.context == {"step_ids": [str(downstream_step.id)]}
    flow_run_repo.get_latest_completed_attempt_id_for_step.assert_not_awaited()
    flow_run_repo.accept_or_replay_rerun_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_omitted_payload_does_not_require_form_fields(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _form_schema_flow(user)
    root_step = flow.steps[0]
    downstream_step = flow.steps[1].model_copy(update={"input_source": "previous_step"})
    flow = flow.model_copy(update={"steps": [root_step, downstream_step]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED}
    )
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_repo.get_latest_completed_attempt_id_for_step.return_value = None
    expected_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id, downstream_step.id],
    )
    flow_run_repo.accept_or_replay_rerun_operation.return_value = expected_result

    result = await service.rerun_step(
        flow_id=flow.id,
        run_id=run.id,
        rerun_step_id=root_step.id,
        expected_run_revision=1,
        reason="Refresh answer",
    )

    assert result == expected_result
    assert (
        flow_run_repo.accept_or_replay_rerun_operation.await_args.kwargs[
            "input_payload_json"
        ]
        is None
    )


@pytest.mark.asyncio
async def test_rerun_step_rejects_empty_payload_missing_required_form_field(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _form_schema_flow(user)
    root_step = flow.steps[0]
    downstream_step = flow.steps[1].model_copy(update={"input_source": "previous_step"})
    flow = flow.model_copy(update={"steps": [root_step, downstream_step]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED}
    )
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=1,
            reason="Refresh answer",
            input_payload_json={},
        )

    assert exc_info.value.code == "flow_input_required_field_missing"
    assert exc_info.value.context == {
        "field_name": "Namn på brukare",
        "field_type": "text",
    }
    flow_run_repo.get_latest_completed_attempt_id_for_step.assert_not_awaited()
    flow_run_repo.accept_or_replay_rerun_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_rejects_malformed_published_form_schema(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _form_schema_flow(user).model_copy(
        update={
            "metadata_json": {
                "form_schema": {"fields": [{"name": "case_id", "type": "unsupported"}]}
            }
        }
    )
    root_step = flow.steps[0]
    downstream_step = flow.steps[1].model_copy(update={"input_source": "previous_step"})
    flow = flow.model_copy(update={"steps": [root_step, downstream_step]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED}
    )
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)

    with pytest.raises(
        BadRequestException, match="metadata_json.form_schema.fields\\[0\\].type"
    ) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=1,
            reason="Refresh answer",
            input_payload_json={"case_id": "A-123"},
        )

    assert exc_info.value.code is None
    flow_run_repo.get_latest_completed_attempt_id_for_step.assert_not_awaited()
    flow_run_repo.accept_or_replay_rerun_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_rejects_reserved_payload_keys(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    root_step = flow.steps[0]
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED}
    )
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=1,
            reason="Refresh answer",
            input_payload_json={"expected_flow_version": 1},
        )

    assert exc_info.value.code == "flow_run_reserved_input_payload_key"
    flow_run_repo.get_latest_completed_attempt_id_for_step.assert_not_awaited()
    flow_run_repo.accept_or_replay_rerun_operation.assert_not_awaited()


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
        user_id=user.id,
        principal_api_key_id=None,
        limit=None,
        offset=None,
    )


@pytest.mark.asyncio
async def test_list_runs_allows_tenant_admin_to_see_all_runs(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow_id = uuid4()
    expected = [_run(user=user, flow_id=flow_id)]
    flow_run_repo.list_runs.return_value = expected
    admin_user = user.model_copy(
        update={"roles": [SimpleNamespace(permissions=[Permission.ADMIN])]}
    )
    service = FlowRunService(
        user=admin_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    result = await service.list_runs(flow_id=flow_id)

    assert result == expected
    flow_run_repo.list_runs.assert_awaited_once_with(
        tenant_id=admin_user.tenant_id,
        flow_id=flow_id,
        user_id=None,
        principal_api_key_id=None,
        limit=None,
        offset=None,
    )


@pytest.mark.asyncio
async def test_list_runs_filters_service_key_runs_by_api_key(user):
    service_user = _service_key_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow_id = uuid4()
    expected = [
        _run(user=user, flow_id=flow_id).model_copy(
            update={
                "user_id": None,
                "principal_type": "service_key",
                "principal_user_id": None,
                "principal_api_key_id": service_user.active_api_key.id,
            }
        )
    ]
    flow_run_repo.list_runs.return_value = expected
    service = FlowRunService(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    result = await service.list_runs(flow_id=flow_id)

    assert result == expected
    flow_run_repo.list_runs.assert_awaited_once_with(
        tenant_id=service_user.tenant_id,
        flow_id=flow_id,
        user_id=None,
        principal_api_key_id=service_user.active_api_key.id,
        limit=None,
        offset=None,
    )


@pytest.mark.asyncio
async def test_list_runs_keeps_service_keys_scoped_even_with_space_admin_role(user):
    service_user = _service_key_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    space_service = AsyncMock()
    actor_manager = MagicMock()
    actor = SimpleNamespace(get_current_role=lambda: "admin")
    actor_manager.get_space_actor_from_space.return_value = actor
    flow = _flow(user=user)
    flow_run_repo.list_runs.return_value = []
    flow_repo.get.return_value = flow
    space_service.get_space.return_value = SimpleNamespace(id=flow.space_id)
    service = FlowRunService(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        space_service=space_service,
        actor_manager=actor_manager,
    )

    await service.list_runs(flow_id=flow.id)

    flow_run_repo.list_runs.assert_awaited_once_with(
        tenant_id=service_user.tenant_id,
        flow_id=flow.id,
        user_id=None,
        principal_api_key_id=service_user.active_api_key.id,
        limit=None,
        offset=None,
    )


@pytest.mark.asyncio
async def test_get_evidence_rejects_service_key_even_for_own_run(user):
    service_user = _service_key_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    service = FlowRunService(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
    )
    run = _run(user=user, flow_id=uuid4()).model_copy(
        update={
            "user_id": None,
            "principal_type": "service_key",
            "principal_user_id": None,
            "principal_api_key_id": service_user.active_api_key.id,
        }
    )
    flow_run_repo.get.return_value = run

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.get_evidence(run_id=run.id)

    assert exc_info.value.code == "flow_run_evidence_forbidden"


@pytest.mark.asyncio
async def test_get_evidence_allows_service_key_with_view_capability(user):
    service_user = _service_key_user(user)
    service_user.active_api_key.resource_permissions = ResourcePermissions(
        flow_evidence=ResourcePermissionLevel.READ
    )
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    run = _run(user=user, flow_id=uuid4()).model_copy(
        update={
            "user_id": None,
            "principal_type": "service_key",
            "principal_user_id": None,
            "principal_api_key_id": service_user.active_api_key.id,
        }
    )
    flow = _flow(user=user).model_copy(update={"id": run.flow_id})
    version = _version(user=user, flow=flow, version=1)
    flow_repo.get.return_value = flow
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    flow_version_repo.get.return_value = version.model_copy(
        update={"flow_id": run.flow_id}
    )
    service = FlowRunService(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
    )

    evidence = await service.get_evidence(run_id=run.id)

    assert evidence["run"]["id"] == str(run.id)


@pytest.mark.asyncio
async def test_export_evidence_json_allows_service_key_redacted_export_with_write_capability(
    user,
):
    service_user = _service_key_user(user)
    service_user.active_api_key.resource_permissions = ResourcePermissions(
        flow_evidence=ResourcePermissionLevel.WRITE
    )
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    run = _run(user=user, flow_id=uuid4()).model_copy(
        update={
            "user_id": None,
            "principal_type": "service_key",
            "principal_user_id": None,
            "principal_api_key_id": service_user.active_api_key.id,
        }
    )
    flow = _flow(user=user).model_copy(update={"id": run.flow_id})
    version = _version(user=user, flow=flow, version=1)
    flow_repo.get.return_value = flow
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    flow_version_repo.get.return_value = version.model_copy(
        update={"flow_id": run.flow_id}
    )
    service = FlowRunService(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
    )

    export = await service.export_evidence_json(run_id=run.id, detail="redacted")

    assert export["redaction"]["applied"] is True


@pytest.mark.asyncio
async def test_export_evidence_json_rejects_service_key_raw_export_in_classification3_by_default(
    user,
):
    service_user = _service_key_user(user)
    service_user.active_api_key.resource_permissions = ResourcePermissions(
        flow_evidence=ResourcePermissionLevel.ADMIN
    )
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    space_service = AsyncMock()
    actor_manager = MagicMock()
    actor_manager.get_space_actor_from_space.return_value = SimpleNamespace(
        get_current_role=lambda: "admin"
    )
    flow = _flow(user=user)
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={
            "user_id": None,
            "principal_type": "service_key",
            "principal_user_id": None,
            "principal_api_key_id": service_user.active_api_key.id,
        }
    )
    version = _version(user=user, flow=flow, version=1)
    flow_repo.get.return_value = flow
    space_service.get_space.return_value = SimpleNamespace(
        id=flow.space_id,
        security_classification=SimpleNamespace(security_level=3),
    )
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    flow_version_repo.get.return_value = version
    service = FlowRunService(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        space_service=space_service,
        actor_manager=actor_manager,
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.export_evidence_json(run_id=run.id, detail="raw")

    assert exc_info.value.code == "flow_run_evidence_raw_export_forbidden"


@pytest.mark.asyncio
async def test_export_evidence_json_rejects_sensitive_flow_redacted_export_by_default(
    user,
):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    sensitive_flow = _flow(
        user=user,
        metadata_json={"care_data_policy": {"sensitive": True}},
    )
    run = _run(user=user, flow_id=sensitive_flow.id)
    flow_run_repo.get.return_value = run
    flow_repo.get.return_value = sensitive_flow
    service = FlowRunService(
        user=_trace_user(user),
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.export_evidence_json(run_id=run.id, detail="redacted")

    assert exc_info.value.code == "flow_run_evidence_forbidden"


@pytest.mark.asyncio
async def test_export_evidence_json_allows_sensitive_flow_redacted_export_when_policy_enabled(
    user,
):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    sensitive_flow = _flow(
        user=user,
        metadata_json={"care_data_policy": {"sensitive": True}},
    )
    run = _run(user=user, flow_id=sensitive_flow.id)
    version = _version(user=user, flow=sensitive_flow, version=1)
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    flow_repo.get.return_value = sensitive_flow
    flow_version_repo.get.return_value = version
    allowed_user = _trace_user(
        user.model_copy(
            update={
                "tenant": SimpleNamespace(
                    flow_settings={
                        "evidence_policy": {"allow_sensitive_flow_exports": True}
                    }
                )
            }
        )
    )
    service = FlowRunService(
        user=allowed_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
    )

    export = await service.export_evidence_json(run_id=run.id, detail="redacted")

    assert export["redaction"]["applied"] is True


@pytest.mark.asyncio
async def test_export_evidence_json_rejects_sensitive_flow_redacted_export_for_space_admin_by_default(
    user,
):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    space_service = AsyncMock()
    actor_manager = MagicMock()
    actor_manager.get_space_actor_from_space.return_value = SimpleNamespace(
        get_current_role=lambda: "admin"
    )
    sensitive_flow = _flow(
        user=user,
        metadata_json={"care_data_policy": {"sensitive": True}},
    )
    run = _run(
        user=SimpleNamespace(id=uuid4(), tenant_id=user.tenant_id),
        flow_id=sensitive_flow.id,
    )
    flow_run_repo.get.return_value = run
    flow_repo.get.return_value = sensitive_flow
    space_service.get_space.return_value = SimpleNamespace(id=sensitive_flow.space_id)
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        space_service=space_service,
        actor_manager=actor_manager,
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.export_evidence_json(run_id=run.id, detail="redacted")

    assert exc_info.value.code == "flow_run_evidence_forbidden"


@pytest.mark.asyncio
async def test_export_evidence_json_rejects_sensitive_flow_redacted_export_for_tenant_admin_by_default(
    user,
):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    admin_user = user.model_copy(
        update={
            "roles": [SimpleNamespace(permissions=[Permission.ADMIN])],
            "tenant": SimpleNamespace(flow_settings={}),
        }
    )
    sensitive_flow = _flow(
        user=user,
        metadata_json={"care_data_policy": {"sensitive": True}},
    )
    run = _run(
        user=SimpleNamespace(id=uuid4(), tenant_id=user.tenant_id),
        flow_id=sensitive_flow.id,
    )
    flow_run_repo.get.return_value = run
    flow_repo.get.return_value = sensitive_flow
    service = FlowRunService(
        user=admin_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.export_evidence_json(run_id=run.id, detail="redacted")

    assert exc_info.value.code == "flow_run_evidence_forbidden"


@pytest.mark.asyncio
async def test_export_evidence_json_rechecks_sensitive_policy_when_run_is_injected(
    user,
):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    sensitive_flow = _flow(
        user=user,
        metadata_json={"care_data_policy": {"sensitive": True}},
    )
    run = _run(user=user, flow_id=sensitive_flow.id)
    version = _version(user=user, flow=sensitive_flow, version=1)
    flow_repo.get.return_value = sensitive_flow
    flow_version_repo.get.return_value = version
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    service = FlowRunService(
        user=_trace_user(user),
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.export_evidence_json(
            run_id=run.id,
            detail="redacted",
            run=run,
        )

    assert exc_info.value.code == "flow_run_evidence_forbidden"


@pytest.mark.asyncio
async def test_export_evidence_json_rejects_cross_tenant_injected_run_for_tenant_admin(
    user,
):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    admin_user = user.model_copy(
        update={"roles": [SimpleNamespace(permissions=[Permission.ADMIN])]}
    )
    flow = _flow(user=user)
    run = _run(user=user, flow_id=flow.id).model_copy(update={"tenant_id": uuid4()})
    version = _version(user=user, flow=flow, version=1)
    flow_version_repo.get.return_value = version
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    service = FlowRunService(
        user=admin_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.export_evidence_json(
            run_id=run.id,
            detail="redacted",
            run=run,
        )

    assert exc_info.value.code == "flow_run_access_denied"


@pytest.mark.asyncio
async def test_service_key_unknown_access_kind_fails_closed(user):
    service_user = _service_key_user(user)
    service_user.active_api_key.resource_permissions = ResourcePermissions(
        flow_evidence=ResourcePermissionLevel.ADMIN
    )
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    run = _run(user=user, flow_id=uuid4()).model_copy(
        update={
            "user_id": None,
            "principal_type": "service_key",
            "principal_user_id": None,
            "principal_api_key_id": service_user.active_api_key.id,
        }
    )
    flow_run_repo.get.return_value = run
    service = FlowRunService(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.get_run(
            run_id=run.id,
            flow_id=run.flow_id,
            access_kind=cast(object, "unknown_access_kind"),
        )

    assert exc_info.value.code == "flow_run_access_denied"


@pytest.mark.asyncio
async def test_get_run_rejects_other_service_key_run_even_with_space_admin_role(user):
    service_user = _service_key_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    space_service = AsyncMock()
    actor_manager = MagicMock()
    actor = SimpleNamespace(get_current_role=lambda: "admin")
    actor_manager.get_space_actor_from_space.return_value = actor
    flow = _flow(user=user)
    other_user = SimpleNamespace(id=uuid4(), tenant_id=user.tenant_id)
    run = _run(user=other_user, flow_id=flow.id)
    flow_run_repo.get.return_value = run
    flow_repo.get.return_value = flow
    space_service.get_space.return_value = SimpleNamespace(id=flow.space_id)
    service = FlowRunService(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        space_service=space_service,
        actor_manager=actor_manager,
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.get_run(run_id=run.id, flow_id=run.flow_id)

    assert exc_info.value.code == "flow_run_access_denied"


@pytest.mark.asyncio
async def test_get_run_rejects_service_key_for_other_principals_run(user):
    service_user = _service_key_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    service = FlowRunService(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
    )
    other_key_id = uuid4()
    run = _run(user=user, flow_id=uuid4()).model_copy(
        update={
            "user_id": None,
            "principal_type": "service_key",
            "principal_user_id": None,
            "principal_api_key_id": other_key_id,
        }
    )
    flow_run_repo.get.return_value = run

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.get_run(run_id=run.id, flow_id=run.flow_id)

    assert exc_info.value.code == "flow_run_access_denied"


@pytest.mark.asyncio
async def test_get_run_rejects_other_users_run_for_non_admin(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
    )
    other_user = SimpleNamespace(id=uuid4(), tenant_id=user.tenant_id)
    run = _run(user=other_user, flow_id=uuid4())
    flow_run_repo.get.return_value = run

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.get_run(run_id=run.id, flow_id=run.flow_id)

    assert exc_info.value.code == "flow_run_access_denied"


@pytest.mark.asyncio
async def test_get_run_allows_other_users_run_for_tenant_admin(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    admin_user = user.model_copy(
        update={"roles": [SimpleNamespace(permissions=[Permission.ADMIN])]}
    )
    service = FlowRunService(
        user=admin_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
    )
    other_user = SimpleNamespace(id=uuid4(), tenant_id=user.tenant_id)
    run = _run(user=other_user, flow_id=uuid4())
    flow_run_repo.get.return_value = run

    result = await service.get_run(run_id=run.id, flow_id=run.flow_id)

    assert result == run


@pytest.mark.asyncio
async def test_get_run_allows_space_admin_to_view_other_users_run_status(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    space_service = AsyncMock()
    actor_manager = MagicMock()
    actor = SimpleNamespace(get_current_role=lambda: "admin")
    actor_manager.get_space_actor_from_space.return_value = actor
    flow = _flow(user=user)
    other_user = SimpleNamespace(id=uuid4(), tenant_id=user.tenant_id)
    run = _run(user=other_user, flow_id=flow.id)
    flow_run_repo.get.return_value = run
    flow_repo.get.return_value = flow
    space_service.get_space.return_value = SimpleNamespace(id=flow.space_id)
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        space_service=space_service,
        actor_manager=actor_manager,
    )

    result = await service.get_run(run_id=run.id, flow_id=run.flow_id)

    assert result == run


@pytest.mark.asyncio
async def test_list_step_results_allows_space_admin_for_other_users_run_content(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    space_service = AsyncMock()
    actor_manager = MagicMock()
    actor = SimpleNamespace(get_current_role=lambda: "admin")
    actor_manager.get_space_actor_from_space.return_value = actor
    flow = _flow(user=user)
    other_user = SimpleNamespace(id=uuid4(), tenant_id=user.tenant_id)
    run = _run(user=other_user, flow_id=flow.id)
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = []
    flow_repo.get.return_value = flow
    space_service.get_space.return_value = SimpleNamespace(id=flow.space_id)
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        space_service=space_service,
        actor_manager=actor_manager,
    )

    result = await service.list_step_results(run_id=run.id, flow_id=run.flow_id)

    assert result == []


@pytest.mark.asyncio
async def test_get_evidence_allows_space_admin_for_other_users_run(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    space_service = AsyncMock()
    actor_manager = MagicMock()
    actor = SimpleNamespace(get_current_role=lambda: "admin")
    actor_manager.get_space_actor_from_space.return_value = actor
    flow = _flow(user=user)
    other_user = SimpleNamespace(id=uuid4(), tenant_id=user.tenant_id)
    run = _run(user=other_user, flow_id=flow.id)
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    flow_repo.get.return_value = flow
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    space_service.get_space.return_value = SimpleNamespace(id=flow.space_id)
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        space_service=space_service,
        actor_manager=actor_manager,
    )

    evidence = await service.get_evidence(run_id=run.id)

    assert evidence["run"]["id"] == str(run.id)


@pytest.mark.asyncio
async def test_export_evidence_json_rejects_space_admin_raw_export_in_classification3_by_default(
    user,
):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    space_service = AsyncMock()
    actor_manager = MagicMock()
    actor = SimpleNamespace(get_current_role=lambda: "admin")
    actor_manager.get_space_actor_from_space.return_value = actor
    flow = _flow(user=user)
    other_user = SimpleNamespace(id=uuid4(), tenant_id=user.tenant_id)
    run = _run(user=other_user, flow_id=flow.id)
    flow_run_repo.get.return_value = run
    flow_repo.get.return_value = flow
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    space_service.get_space.return_value = SimpleNamespace(
        id=flow.space_id,
        security_classification=SimpleNamespace(security_level=3),
    )
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        space_service=space_service,
        actor_manager=actor_manager,
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.export_evidence_json(run_id=run.id, detail="raw")

    assert exc_info.value.code == "flow_run_evidence_raw_export_forbidden"


@pytest.mark.asyncio
async def test_export_evidence_json_allows_space_owner_raw_export_in_classification3(
    user,
):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    space_service = AsyncMock()
    actor_manager = MagicMock()
    actor = SimpleNamespace(get_current_role=lambda: "owner")
    actor_manager.get_space_actor_from_space.return_value = actor
    flow = _flow(user=user)
    other_user = SimpleNamespace(id=uuid4(), tenant_id=user.tenant_id)
    run = _run(user=other_user, flow_id=flow.id)
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    flow_repo.get.return_value = flow
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    space_service.get_space.return_value = SimpleNamespace(
        id=flow.space_id,
        security_classification=SimpleNamespace(security_level=3),
    )
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        space_service=space_service,
        actor_manager=actor_manager,
    )

    export = await service.export_evidence_json(run_id=run.id, detail="raw")

    assert export["redaction"]["applied"] is False


@pytest.mark.asyncio
async def test_export_evidence_json_allows_run_owner_raw_export_in_classification3_when_policy_enabled(
    user,
):
    trace_user = _trace_user(user)
    trace_user.tenant = trace_user.tenant.model_copy(
        update={
            "flow_settings": {
                "evidence_policy": {
                    "classification_3": {"allow_run_owner_raw_export": True}
                }
            }
        }
    )
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    space_service = AsyncMock()
    actor_manager = MagicMock()
    actor_manager.get_space_actor_from_space.return_value = SimpleNamespace(
        get_current_role=lambda: "viewer"
    )
    flow = _flow(user=trace_user)
    run = _run(user=trace_user, flow_id=flow.id)
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    flow_repo.get.return_value = flow
    flow_version_repo.get.return_value = _version(user=trace_user, flow=flow, version=1)
    space_service.get_space.return_value = SimpleNamespace(
        id=flow.space_id,
        security_classification=SimpleNamespace(security_level=3),
    )
    service = FlowRunService(
        user=trace_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        space_service=space_service,
        actor_manager=actor_manager,
    )

    export = await service.export_evidence_json(run_id=run.id, detail="raw")

    assert export["redaction"]["applied"] is False


def test_build_dispatch_request_uses_run_identity(user):
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

    dispatch_request = service.build_dispatch_request(run)

    assert dispatch_request == {
        "run_id": run.id,
        "flow_id": run.flow_id,
        "tenant_id": run.tenant_id,
        "user_id": run.user_id,
    }


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
    missing_user_run = _run(user=user, flow_id=flow_id).model_copy(
        update={
            "user_id": None,
            "principal_type": None,
            "principal_user_id": None,
        }
    )
    dispatchable_run = _run(user=user, flow_id=flow_id)
    flow_run_repo.list_stale_queued_runs.return_value = [
        missing_user_run,
        dispatchable_run,
    ]
    flow_run_repo.claim_stale_queued_run_for_redispatch.side_effect = [
        missing_user_run,
        dispatchable_run,
    ]
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
    flow_run_repo.claim_stale_queued_run_for_redispatch.side_effect = [
        failed_run,
        succeeded_run,
    ]
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
async def test_reconcile_stale_running_runs_marks_stale_runs_failed(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow_id = uuid4()
    stale_run = _run(user=user, flow_id=flow_id).model_copy(
        update={"status": FlowRunStatus.RUNNING}
    )
    flow_run_repo.list_stale_running_runs.return_value = [stale_run]
    terminalizer = AsyncMock()
    terminalizer.terminalize_stale_running_run.return_value = SimpleNamespace(
        did_transition=True
    )
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_terminalizer=terminalizer,
        flow_version_repo=flow_version_repo,
        queued_redispatch_after_seconds=30,
    )

    count = await service.reconcile_stale_running_runs(limit=10)

    assert count == 1
    flow_run_repo.list_stale_running_runs.assert_awaited_once()
    terminalizer.terminalize_stale_running_run.assert_awaited_once()
    terminal_kwargs = terminalizer.terminalize_stale_running_run.await_args.kwargs
    assert terminal_kwargs["error_code"] == "flow_worker_stalled"
    assert terminal_kwargs["error_message"] == (
        "flow_worker_stalled: Flow run exceeded the execution timeout and was reconciled as failed."
    )


@pytest.mark.asyncio
async def test_reconcile_stale_running_runs_skips_already_reconciled_runs(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow_id = uuid4()
    stale_run = _run(user=user, flow_id=flow_id).model_copy(
        update={"status": FlowRunStatus.RUNNING}
    )
    flow_run_repo.list_stale_running_runs.return_value = [stale_run]
    terminalizer = AsyncMock()
    terminalizer.terminalize_stale_running_run.return_value = SimpleNamespace(
        did_transition=False
    )
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_terminalizer=terminalizer,
        flow_version_repo=flow_version_repo,
    )

    count = await service.reconcile_stale_running_runs(limit=10)

    assert count == 0
    terminalizer.terminalize_stale_running_run.assert_awaited_once()


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

    with pytest.raises(
        BadRequestException, match="exceeds allowed size limit"
    ) as exc_info:
        await service.create_run(
            flow_id=flow.id,
            input_payload_json={"text": "x" * (2 * 1024 * 1024)},
        )
    assert exc_info.value.code == "flow_run_input_payload_too_large"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("definition_json", "message_fragment", "error_code", "error_context"),
    [
        (
            {},
            "missing schema_version",
            "flow_definition_schema_version_missing",
            None,
        ),
        (
            {"schema_version": 1, "flow_id": str(uuid4()), "steps": []},
            "does not contain executable steps",
            "flow_version_no_executable_steps",
            None,
        ),
        (
            {"schema_version": 1, "flow_id": str(uuid4()), "steps": ["bad-step"]},
            "Invalid step definition",
            "flow_definition_steps_invalid",
            None,
        ),
        (
            {
                "schema_version": 1,
                "flow_id": str(uuid4()),
                "steps": [
                    {
                        "step_order": 0,
                        "step_id": str(uuid4()),
                        "assistant_id": str(uuid4()),
                    }
                ],
            },
            "Invalid flow version step order",
            "flow_version_invalid_step_order",
            {"step_order": 0},
        ),
        (
            {
                "schema_version": 1,
                "flow_id": str(uuid4()),
                "steps": [
                    {
                        "step_order": "abc",
                        "step_id": str(uuid4()),
                        "assistant_id": str(uuid4()),
                    }
                ],
            },
            "Invalid flow version step order",
            "flow_version_invalid_step_order",
            {"step_order": "abc"},
        ),
        (
            {
                "schema_version": 1,
                "flow_id": str(uuid4()),
                "steps": [
                    {
                        "step_order": True,
                        "step_id": str(uuid4()),
                        "assistant_id": str(uuid4()),
                    }
                ],
            },
            "Invalid flow version step order",
            "flow_version_invalid_step_order",
            {"step_order": True},
        ),
        (
            {
                "schema_version": 1,
                "flow_id": str(uuid4()),
                "steps": [
                    {
                        "step_order": 1,
                        "step_id": "not-a-uuid",
                        "assistant_id": str(uuid4()),
                    }
                ],
            },
            "Invalid flow version step identifier",
            "flow_version_invalid_step_identifier",
            {"step_order": 1, "field": "step_id", "value": "not-a-uuid"},
        ),
        (
            {
                "schema_version": 1,
                "flow_id": str(uuid4()),
                "steps": [
                    {
                        "step_order": 1,
                        "step_id": str(uuid4()),
                        "assistant_id": "bad-assistant-id",
                    }
                ],
            },
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
@pytest.mark.parametrize(
    "method_name",
    [
        "edit_review_checkpoint",
        "approve_review_checkpoint",
        "reject_review_checkpoint",
        "resume_review_checkpoint",
    ],
)
async def test_review_mutations_reject_service_key_principals(user, method_name):
    service_user = _service_key_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    service = FlowRunService(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )
    method = getattr(service, method_name)
    kwargs = {
        "flow_id": uuid4(),
        "run_id": uuid4(),
        "checkpoint_id": uuid4(),
        "expected_checkpoint_revision": 1,
    }
    if method_name == "edit_review_checkpoint":
        kwargs["current_payload_json"] = {"text": "Edited"}
    if method_name == "reject_review_checkpoint":
        kwargs["reason"] = "Reject the draft."
    if method_name == "resume_review_checkpoint":
        kwargs["idempotency_key"] = "resume-key"

    with pytest.raises(UnauthorizedException) as exc_info:
        await method(**kwargs)

    assert exc_info.value.code == "flow_service_key_principal_not_supported"
    assert exc_info.value.context["auth_layer"] == "service_key_principal"
    flow_run_repo.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_review_checkpoint_requires_idempotency_key(user):
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

    with pytest.raises(BadRequestException) as exc_info:
        await service.resume_review_checkpoint(
            flow_id=uuid4(),
            run_id=uuid4(),
            checkpoint_id=uuid4(),
            expected_checkpoint_revision=1,
            idempotency_key=" ",
        )

    assert exc_info.value.code == "flow_review_idempotency_key_required"
    flow_run_repo.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_reject_review_checkpoint_requires_reason(user):
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

    with pytest.raises(BadRequestException) as exc_info:
        await service.reject_review_checkpoint(
            flow_id=uuid4(),
            run_id=uuid4(),
            checkpoint_id=uuid4(),
            expected_checkpoint_revision=1,
            reason=" ",
        )

    assert exc_info.value.code == "flow_review_reject_reason_required"
    flow_run_repo.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_reject_review_checkpoint_terminalizes_run_with_review_source(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    terminalizer = AsyncMock()
    run = _run(user=user, flow_id=uuid4()).model_copy(
        update={"status": FlowRunStatus.AWAITING_REVIEW}
    )
    checkpoint = _review_checkpoint(user, run)
    flow_run_repo.get.return_value = run
    flow_run_repo.reject_review_checkpoint.return_value = checkpoint
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_terminalizer=terminalizer,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    result = await service.reject_review_checkpoint(
        flow_id=run.flow_id,
        run_id=run.id,
        checkpoint_id=checkpoint.id,
        expected_checkpoint_revision=checkpoint.revision,
        reason="Reject the draft.",
    )

    assert result == checkpoint
    flow_run_repo.reject_review_checkpoint.assert_awaited_once()
    terminalizer.terminalize_run.assert_awaited_once()
    terminal_kwargs = terminalizer.terminalize_run.await_args.kwargs
    assert terminal_kwargs["run_id"] == run.id
    assert terminal_kwargs["target_status"] == FlowRunStatus.CANCELLED
    assert terminal_kwargs["source"] == FlowRunLifecycleSource.REVIEW_REJECTED
    assert terminal_kwargs["error_code"] == "flow_review_rejected"
    assert terminal_kwargs["error_message"] == "Reject the draft."


@pytest.mark.asyncio
async def test_resume_review_checkpoint_normalizes_idempotency_key(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    run = _run(user=user, flow_id=uuid4()).model_copy(
        update={"status": FlowRunStatus.AWAITING_REVIEW}
    )
    checkpoint = _review_checkpoint(
        user,
        run,
        state=FlowRunReviewCheckpointState.RESUMED,
        revision=2,
        resume_idempotency_key="resume-key",
    )
    flow_run_repo.get.return_value = run
    flow_run_repo.resume_review_checkpoint.return_value = (
        FlowRunReviewCheckpointResumeResult(
            checkpoint=checkpoint,
            run=run,
            accepted=False,
        )
    )
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    result = await service.resume_review_checkpoint(
        flow_id=run.flow_id,
        run_id=run.id,
        checkpoint_id=checkpoint.id,
        expected_checkpoint_revision=1,
        idempotency_key=" resume-key ",
    )

    assert result.accepted is False
    resume_kwargs = flow_run_repo.resume_review_checkpoint.await_args.kwargs
    assert resume_kwargs["resume_idempotency_key"] == "resume-key"


@pytest.mark.asyncio
async def test_cancel_run_marks_pending_steps_cancelled(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    run = _run(user=user, flow_id=uuid4()).model_copy(
        update={"status": FlowRunStatus.RUNNING}
    )
    cancelled_run = run.model_copy(update={"status": FlowRunStatus.CANCELLED})
    flow_run_repo.get.return_value = run
    terminalizer = AsyncMock()
    terminalizer.terminalize_run.return_value = SimpleNamespace(run=cancelled_run)
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_terminalizer=terminalizer,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    result = await service.cancel_run(run_id=run.id)

    assert result.status == FlowRunStatus.CANCELLED
    terminalizer.terminalize_run.assert_awaited_once()
    terminal_kwargs = terminalizer.terminalize_run.await_args.kwargs
    assert terminal_kwargs["target_status"] == FlowRunStatus.CANCELLED
    assert terminal_kwargs["source"] == FlowRunLifecycleSource.USER_CANCEL
    assert terminal_kwargs["error_code"] == "user_cancelled"
    assert terminal_kwargs["error_message"] == "Run cancelled by user."


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
    terminalizer = AsyncMock()
    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_terminalizer=terminalizer,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    result = await service.cancel_run(run_id=run.id)

    assert result.status == status
    terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_resolves_missing_snapshot_identifiers_from_fallback_steps(
    user,
):
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
        definition_json=_published_definition_json(
            flow,
            [
                {"step_order": 1},
                {
                    "step_order": 2,
                    "step_id": str(flow.steps[1].id),
                    "assistant_id": str(flow.steps[1].assistant_id),
                },
            ],
        ),
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
    flow = _flow(user=user, published_version=1).model_copy(
        update={"steps": [_step(1)]}
    )
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
        definition_json=_published_definition_json(
            flow,
            [
                {
                    "step_order": 2,
                    "step_id": None,
                    "assistant_id": None,
                }
            ],
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    with pytest.raises(
        BadRequestException, match="missing stable step identifiers"
    ) as exc_info:
        await service.create_run(flow_id=flow.id, input_payload_json={"x": "y"})
    assert exc_info.value.code == "flow_version_missing_step_identifiers"
    assert exc_info.value.context == {"step_order": 2}


@pytest.mark.asyncio
async def test_get_evidence_redacts_sensitive_values(user):
    user = _trace_user(user)
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
        definition_json=_published_definition_json(
            flow,
            [
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
            ],
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    flow_run_repo.list_step_results.return_value = [
        _step_result_record(
            run,
            step_order=1,
            input_payload_json={
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
            effective_prompt="Authorization: Bearer xyz",
            output_payload_json={
                "url": "https://bob:pw@example.org/path?client_secret=x&client.secret=z&api-key=y",
            },
        )
    ]
    flow_run_repo.list_step_attempts.return_value = [
        _step_attempt_record(
            run,
            step_order=1,
            error_message="Bearer should-hide",
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
    assert (
        evidence["run"]["input_payload_json"]["webhook_url"]
        == "https://example.org/hook?token=%5BREDACTED%5D"
    )
    assert (
        evidence["definition_snapshot"]["steps"][0]["output_config"]["headers"][
            "Authorization"
        ]
        == "[REDACTED]"
    )
    assert (
        evidence["definition_snapshot"]["steps"][0]["output_config"]["headers"][
            "X-Api-Key"
        ]
        == "[REDACTED]"
    )
    assert evidence["definition_snapshot"]["steps"][0]["output_config"]["url"] == (
        "https://service.example.com/notify?api_key=%5BREDACTED%5D&x-api-key=%5BREDACTED%5D"
    )
    assert evidence["step_results"][0]["input_payload_json"]["token"] == "[REDACTED]"
    assert (
        evidence["step_results"][0]["input_payload_json"]["x-api-key"] == "[REDACTED]"
    )
    assert (
        evidence["step_results"][0]["input_payload_json"]["auth.token"] == "[REDACTED]"
    )
    assert evidence["step_results"][0]["input_payload_json"]["contract_validation"] == {
        "schema_type_hint": "object",
        "parse_attempted": True,
        "parse_succeeded": False,
        "candidate_type": "str",
    }
    assert (
        evidence["step_results"][0]["effective_prompt"]
        == "Authorization: Bearer [REDACTED]"
    )
    assert evidence["step_results"][0]["output_payload_json"]["url"] == (
        "https://example.org/path?client_secret=%5BREDACTED%5D&client.secret=%5BREDACTED%5D&api-key=%5BREDACTED%5D"
    )
    assert evidence["step_attempts"][0]["error_message"] == "Bearer [REDACTED]"
    assert evidence["debug_export"]["schema_version"] == "eneo.flow.debug-export.v2"
    assert evidence["debug_export"]["definition"]["checksum"] == "checksum"
    assert evidence["debug_export"]["run"]["status"] == "queued"
    assert evidence["debug_export"]["steps"][0]["input"]["source"] is None
    assert evidence["debug_export"]["steps"][0]["mcp"]["servers"] == []
    assert evidence["debug_export"]["steps"][0]["mcp"]["tools_enabled"] == []
    assert (
        evidence["debug_export"]["definition_snapshot"]["steps"][0]["output_config"][
            "headers"
        ]["Authorization"]
        == "[REDACTED]"
    )


@pytest.mark.asyncio
async def test_get_evidence_includes_rag_metadata_in_debug_export(user):
    user = _trace_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    run = _run(user=user, flow_id=flow.id)
    flow_repo.get.return_value = flow
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = FlowVersion(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum="checksum",
        definition_json=_published_definition_json(
            flow,
            [
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
            ],
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    flow_run_repo.list_step_results.return_value = [
        _step_result_record(
            run,
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
                            "matched_chunk_count": 2,
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
    assert (
        evidence["debug_export"]["steps"][0]["rag"]["references"][0]["title"]
        == "Sundsvall source"
    )
    assert (
        evidence["debug_export"]["steps"][0]["rag"]["references"][0]["chunks"][0][
            "chunk_no"
        ]
        == 1
    )
    assert evidence["debug_export"]["steps"][0]["rag"]["source_ids_short"] == [
        "aaaaaaaa"
    ]


@pytest.mark.asyncio
async def test_get_evidence_includes_trace_id_and_attempts_in_debug_export(user):
    user = _trace_user(user)
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
        definition_json=_published_definition_json(
            flow,
            [
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
            ],
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    flow_run_repo.list_step_results.return_value = [
        _step_result_record(
            run,
            step_order=1,
            input_payload_json={"text": "hello"},
        )
    ]
    flow_run_repo.list_step_attempts.return_value = [
        _step_attempt_record(
            run,
            step_order=1,
            attempt_no=2,
            started_at=datetime(2026, 3, 20, 12, 0, 0, tzinfo=timezone.utc),
            finished_at=datetime(2026, 3, 20, 12, 0, 5, tzinfo=timezone.utc),
            requested_model="gpt-4.1",
            response_model="gpt-4.1-mini",
            provider="openai",
            finish_reason="stop",
            provider_response_id="resp-123",
            num_tokens_input=11,
            num_tokens_output=13,
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

    assert evidence["debug_export"]["schema_version"] == "eneo.flow.debug-export.v2"
    assert evidence["debug_export"]["run"]["trace_id"] == str(run.trace_id)
    assert evidence["debug_export"]["steps"][0]["attempts"][0]["attempt_no"] == 2
    assert evidence["debug_export"]["steps"][0]["attempts"][0]["duration_ms"] == 5000
    assert (
        evidence["debug_export"]["steps"][0]["attempts"][0]["response_model"]
        == "gpt-4.1-mini"
    )


@pytest.mark.asyncio
async def test_export_evidence_json_hashes_returned_bundle_and_manifest_by_detail(user):
    user = _trace_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    run = _run(user=user, flow_id=flow.id)
    flow_repo.get.return_value = flow
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = FlowVersion(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum="checksum",
        definition_json=_published_definition_json(flow, []),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []

    service = FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        max_concurrent_runs=5,
    )

    redacted_export = await service.export_evidence_json(run_id=run.id)
    raw_export = await service.export_evidence_json(
        run_id=run.id,
        detail="raw",
        export_reason="government_audit_request",
    )

    assert set(redacted_export) == set(raw_export)
    assert set(redacted_export["manifest"]) == set(raw_export["manifest"])
    for export, hash_input in (
        (redacted_export, "redacted"),
        (raw_export, "raw"),
    ):
        assert export["schema_version"] == "flow-evidence-export.v5"
        assert export["manifest"]["schema_version"] == export["schema_version"]
        assert export["manifest"]["content_hash"] == export["content_hash"]
        assert export["manifest"]["content_hash_input"] == hash_input
        assert export["manifest"]["exported_at"] == export["generated_at"]
        assert export["manifest"]["run_id"] == str(run.id)
        assert export["manifest"]["tenant_id"] == str(user.tenant_id)
        assert export["manifest"]["trace_id"] == str(run.trace_id)
        assert export["manifest"]["flow_id"] == str(flow.id)
        assert export["manifest"]["exported_by_user_id"] == str(user.id)
        assert export["manifest"]["redaction_applied"] == export["redaction"]["applied"]
        assert (
            export["manifest"]["masked_fields_count"]
            == export["redaction"]["masked_fields_count"]
        )
        serialized_bundle = json.dumps(
            export["bundle"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        assert export["content_hash"] == hashlib.sha256(serialized_bundle).hexdigest()

    assert redacted_export["manifest"]["export_reason"] == "support_debug"
    assert raw_export["manifest"]["export_reason"] == "government_audit_request"


@pytest.mark.asyncio
async def test_get_evidence_normalizes_attempt_provenance_payloads(user):
    user = _trace_user(user)
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
        definition_json=_published_definition_json(flow, []),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = [
        _step_attempt_record(
            run,
            step_order=1,
            provenance_json={
                "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
                "llm": {
                    "effective_prompt": "Bearer secret " + ("x" * 20000),
                    "tool_calls": {"result": "y" * 20000},
                },
            },
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

    llm_provenance = evidence["step_attempts"][0]["provenance_json"]["llm"]
    assert llm_provenance["effective_prompt"]["truncated"] is True
    assert llm_provenance["effective_prompt"]["sha256"] is not None
    assert llm_provenance["tool_calls"]["truncated"] is True


@pytest.mark.asyncio
async def test_get_evidence_sets_rag_to_null_when_metadata_missing(user):
    user = _trace_user(user)
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
        definition_json=_published_definition_json(
            flow,
            [
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
            ],
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    flow_run_repo.list_step_results.return_value = [
        _step_result_record(
            run,
            step_order=1,
            input_payload_json={"text": "hello"},
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
    user = _trace_user(user)
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
        definition_json=_published_definition_json(
            flow,
            [
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
            ],
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    flow_run_repo.list_step_results.return_value = []
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
def _result_file(
    *,
    user,
    run,
    file_id,
    availability="available",
) -> FlowRunStepResultFile:
    step_id = uuid4()
    return FlowRunStepResultFile(
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=user.tenant_id,
        step_result_id=uuid4(),
        step_id=step_id,
        step_order=1,
        attempt_no=1,
        file_id=file_id,
        ordinal=0,
        source="declared_artifact",
        name="artifact.docx",
        checksum="artifact-checksum",
        size=1024,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_type=FileType.DOCUMENT,
        availability=availability,
    )


def _file(
    file_id,
    tenant_id,
    name="artifact.docx",
    *,
    text="artifact text",
    blob=None,
):
    return SimpleNamespace(
        id=file_id,
        tenant_id=tenant_id,
        name=name,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size=1024,
        text=text,
        blob=blob,
    )


def _artifact_service(user, file_repo=None, result_file=None, run=None):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    if run is None:
        run = _run(user=user, flow_id=uuid4())
    flow_run_repo.get.return_value = run
    flow_run_repo.get_result_file.return_value = result_file
    return FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        file_repo=file_repo,
    ), run


@pytest.mark.asyncio
async def test_list_result_files_for_runs_rejects_foreign_tenant_run(user):
    flow_run_repo = AsyncMock()
    service = FlowRunService(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_version_repo=AsyncMock(),
    )
    foreign_run = _run(user=user, flow_id=uuid4()).model_copy(
        update={"tenant_id": uuid4()}
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.list_result_files_for_runs(runs=[foreign_run])

    assert exc_info.value.code == "flow_run_access_denied"
    assert exc_info.value.context == {"auth_layer": "flow_run_argument"}
    flow_run_repo.list_result_files_for_runs.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_run_artifact_file_uses_result_file_row(user):
    file_id = uuid4()
    run = _run(user=user, flow_id=uuid4())
    file_repo = AsyncMock()
    file_obj = _file(file_id=file_id, tenant_id=user.tenant_id)
    file_repo.get_by_id.return_value = file_obj
    service, run = _artifact_service(
        user,
        file_repo=file_repo,
        result_file=_result_file(user=user, run=run, file_id=file_id),
        run=run,
    )

    result = await service.get_run_artifact_file(
        run_id=run.id,
        flow_id=run.flow_id,
        file_id=file_id,
    )
    assert result.id == file_id
    service.flow_run_repo.get_result_file.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
        file_id=file_id,
    )
    file_repo.get_by_id.assert_awaited_once_with(file_id=file_id)


@pytest.mark.asyncio
async def test_get_run_artifact_file_ignores_payload_artifacts_without_result_file_row(
    user,
):
    file_id = uuid4()
    run = _run(user=user, flow_id=uuid4())
    file_repo = AsyncMock()
    service, run = _artifact_service(
        user,
        file_repo=file_repo,
        run=run,
    )
    service.flow_run_repo.list_step_results.return_value = [
        SimpleNamespace(
            id=uuid4(),
            flow_run_id=run.id,
            step_order=1,
            output_payload_json={"artifacts": [{"file_id": str(file_id)}]},
        )
    ]

    with pytest.raises(NotFoundException) as exc_info:
        await service.get_run_artifact_file(
            run_id=run.id,
            flow_id=run.flow_id,
            file_id=file_id,
        )
    assert exc_info.value.code == "flow_run_artifact_not_found"
    service.flow_run_repo.list_step_results.assert_not_awaited()
    file_repo.get_by_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_run_artifact_file_rejects_unknown_file_id(user):
    file_id = uuid4()
    run = _run(user=user, flow_id=uuid4())
    file_repo = AsyncMock()
    service, run = _artifact_service(
        user,
        file_repo=file_repo,
        run=run,
    )

    with pytest.raises(NotFoundException) as exc_info:
        await service.get_run_artifact_file(
            run_id=run.id,
            flow_id=run.flow_id,
            file_id=file_id,
        )
    assert exc_info.value.code == "flow_run_artifact_not_found"
    file_repo.get_by_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_run_artifact_file_rejects_content_purged_row(user):
    file_id = uuid4()
    run = _run(user=user, flow_id=uuid4())
    file_repo = AsyncMock()
    service, run = _artifact_service(
        user,
        file_repo=file_repo,
        result_file=_result_file(
            user=user,
            run=run,
            file_id=file_id,
            availability="content_purged",
        ),
        run=run,
    )

    with pytest.raises(ResourceGoneException) as exc_info:
        await service.get_run_artifact_file(
            run_id=run.id,
            flow_id=run.flow_id,
            file_id=file_id,
        )
    assert exc_info.value.code == "flow_run_artifact_content_unavailable"
    file_repo.get_by_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_run_artifact_file_rechecks_file_content_before_signing(user):
    file_id = uuid4()
    run = _run(user=user, flow_id=uuid4())
    file_repo = AsyncMock()
    file_repo.get_by_id.return_value = _file(
        file_id=file_id,
        tenant_id=user.tenant_id,
        text=None,
        blob=None,
    )
    service, run = _artifact_service(
        user,
        file_repo=file_repo,
        result_file=_result_file(user=user, run=run, file_id=file_id),
        run=run,
    )

    with pytest.raises(ResourceGoneException) as exc_info:
        await service.get_run_artifact_file(
            run_id=run.id,
            flow_id=run.flow_id,
            file_id=file_id,
        )
    assert exc_info.value.code == "flow_run_artifact_content_unavailable"


@pytest.mark.asyncio
async def test_get_run_artifact_file_rejects_cross_tenant(user):
    file_id = uuid4()
    run = _run(user=user, flow_id=uuid4())
    file_repo = AsyncMock()
    file_repo.get_by_id.return_value = _file(
        file_id=file_id,
        tenant_id=uuid4(),
    )
    service, run = _artifact_service(
        user,
        file_repo=file_repo,
        result_file=_result_file(user=user, run=run, file_id=file_id),
        run=run,
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.get_run_artifact_file(
            run_id=run.id,
            flow_id=run.flow_id,
            file_id=file_id,
        )
    assert exc_info.value.code == "forbidden_action"


@pytest.mark.asyncio
async def test_get_run_artifact_file_missing_result_file_row(user):
    file_id = uuid4()
    run = _run(user=user, flow_id=uuid4())
    file_repo = AsyncMock()

    service, run = _artifact_service(
        user,
        file_repo=file_repo,
        run=run,
    )

    with pytest.raises(NotFoundException) as exc_info:
        await service.get_run_artifact_file(
            run_id=run.id,
            flow_id=run.flow_id,
            file_id=file_id,
        )
    assert exc_info.value.code == "flow_run_artifact_not_found"


@pytest.mark.asyncio
async def test_get_run_artifact_file_no_file_repo(user):
    service, run = _artifact_service(user, file_repo=None)

    with pytest.raises(BadRequestException) as exc_info:
        await service.get_run_artifact_file(
            run_id=run.id,
            flow_id=run.flow_id,
            file_id=uuid4(),
        )
    assert exc_info.value.code == "file_repo_unavailable"
