from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from eneo.authentication.auth_models import (
    ApiKeyPermission,
    ResourcePermissionLevel,
    ResourcePermissions,
)
from eneo.authentication.principal_types import PrincipalType
from eneo.files.file_models import FileType
from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.application.flow_run_evidence_service import FlowRunEvidenceService
from eneo.flows.application.flow_run_service import (
    FlowRunPageWithResultFilesAndTokenUsage,
    FlowRunService,
    FlowRunVersionedView,
    FlowRunWithResultFilesAndTokenUsage,
)
from eneo.flows.domain.flow import (
    Flow,
    FlowRun,
    FlowRunRerunInvalidatedStep,
    FlowRunRerunOperation,
    FlowRunStatus,
    FlowRunTokenUsage,
    FlowStep,
    FlowStepAttempt,
    FlowStepResult,
)
from eneo.flows.domain.flow import (
    FlowVersion as FlowVersionModel,
)
from eneo.flows.domain.flow_invariant_exceptions import FlowPersistedIdMissingError
from eneo.flows.domain.flow_run_exceptions import (
    FlowRunConcurrencyLimitReachedError,
    FlowRunNotFoundError,
)
from eneo.flows.domain.flow_run_input_revision import FlowRunInputRevisionNotRecorded
from eneo.flows.domain.run_step_input_exceptions import (
    FlowRunRuntimeUploadBindingRaceError,
)
from eneo.flows.domain.runtime_invariant_exceptions import (
    FlowPublishedDefinitionWithoutExecutableStepsError,
)
from eneo.flows.enums import (
    FlowRunLifecycleSource,
    FlowRunRerunInvalidationRole,
    FlowRunRerunOperationStatus,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
    RerunDependencyKind,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_run_input_envelope import build_initial_run_input_envelope
from eneo.flows.flow_run_provenance import FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION
from eneo.flows.flow_run_step_inputs import (
    FlowRunStepInputFiles,
    normalize_step_inputs_payload,
)
from eneo.flows.flow_run_step_result_file import FlowRunStepResultFile
from eneo.flows.infrastructure.flow_run_rerun_repo import (
    FlowRunRerunCommandResult,
    FlowRunRerunRepository,
)
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRepository,
)
from eneo.flows.principal import FlowPrincipal
from eneo.flows.published_definition import (
    FLOW_DEFINITION_SCHEMA_VERSION,
    FLOW_DEFINITION_STEPS_INVALID,
    FLOW_PUBLISHED_FORM_SCHEMA_INVALID,
    build_published_definition_json,
    published_definition_checksum,
)
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    ResourceGoneException,
    UnauthorizedException,
)
from eneo.roles.permissions import Permission


def _flow_repo() -> AsyncMock:
    return AsyncMock()


def _runtime_upload_repo(*bound_file_ids: UUID) -> AsyncMock:
    repo = AsyncMock()
    repo.list_bound_file_ids_for_owner.return_value = set(bound_file_ids)
    return repo


_FILE_REPO_UNSET = object()


def _file_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_list_by_id_for_owner.return_value = []
    return repo


def _flow_run_rerun_repo() -> AsyncMock:
    repo = AsyncMock(spec=FlowRunRerunRepository)
    repo.list_rerun_operations_for_run.return_value = []
    repo.list_rerun_invalidated_steps_for_run.return_value = []
    return repo


def _webhook_delivery_repo() -> AsyncMock:
    repo = AsyncMock(spec=FlowRunWebhookDeliveryRepository)
    repo.list_run_delivery_statuses.return_value = []
    return repo


def _flow_run_service(
    *,
    user,
    flow_repo,
    flow_run_repo,
    flow_version_repo,
    runtime_upload_repo,
    flow_run_review_checkpoint_repo=None,
    file_repo=_FILE_REPO_UNSET,
    flow_run_terminalizer=None,
    settings_service=None,
    access_policy=None,
    webhook_delivery_repo: FlowRunWebhookDeliveryRepository | None = None,
    max_concurrent_runs=None,
) -> FlowRunService:
    resolved_file_repo = _file_repo() if file_repo is _FILE_REPO_UNSET else file_repo
    if resolved_file_repo is None:
        raise AssertionError("FlowRunService tests must provide a file repository.")
    resolved_terminalizer = flow_run_terminalizer or AsyncMock()
    resolved_access_policy = access_policy or _access_policy(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
    )
    return FlowRunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=(
            flow_run_review_checkpoint_repo or AsyncMock()
        ),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=runtime_upload_repo,
        file_repo=resolved_file_repo,
        flow_run_terminalizer=resolved_terminalizer,
        settings_service=settings_service,
        access_policy=resolved_access_policy,
        webhook_delivery_repo=webhook_delivery_repo
        or AsyncMock(spec=FlowRunWebhookDeliveryRepository),
        max_concurrent_runs=max_concurrent_runs,
    )


def _access_policy(
    *,
    user,
    flow_repo,
    flow_run_repo,
    space_service=None,
    actor_manager=None,
) -> FlowRunAccessPolicy:
    return FlowRunAccessPolicy(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        space_service=space_service,
        actor_manager=actor_manager,
    )


def _step(step_order: int = 1) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        user_description="Step",
        input_source="flow_input" if step_order == 1 else "previous_step",
        input_type="text",
        output_mode="pass_through",
        output_type="json",
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
        tenant_id=user.tenant_id,
        trace_id=uuid4(),
        status=FlowRunStatus.QUEUED,
        cancelled_at=None,
        input_payload_json={"input": "value"},
        output_payload_json=None,
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
                service_principal_id=uuid4(),
                permission=ApiKeyPermission.WRITE,
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


def _published_flow_version(
    *,
    flow_id: UUID,
    version: int,
    tenant_id: UUID,
    definition_checksum: str | None,
    definition_json: dict[str, object],
    created_at: datetime,
    updated_at: datetime,
) -> FlowVersionModel:
    """Derive a valid fixture checksum unless a test supplies an explicit value."""
    if definition_checksum is None:
        definition_checksum = published_definition_checksum(definition_json)
    return FlowVersionModel(
        flow_id=flow_id,
        version=version,
        tenant_id=tenant_id,
        definition_checksum=definition_checksum,
        definition_json=definition_json,
        created_at=created_at,
        updated_at=updated_at,
    )


def _version(user, flow: Flow, version: int = 1) -> FlowVersionModel:
    return _published_flow_version(
        flow_id=flow.id,
        version=version,
        tenant_id=user.tenant_id,
        definition_checksum=None,
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
    }


def _runtime_version(user, flow: Flow, version: int = 1) -> FlowVersionModel:
    return _published_flow_version(
        flow_id=flow.id,
        version=version,
        tenant_id=user.tenant_id,
        definition_checksum=None,
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
        input_revision=FlowRunInputRevisionNotRecorded(status="not_recorded"),
        root_step_input_override_requested=False,
        root_step_input_override=None,
        requested_by_principal_type=PrincipalType.USER,
        requested_by_user_id=user.id,
        requested_by_service_id=None,
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
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
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
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=1,
    )
    flow = _flow(user=user, published_version=1)
    flow_repo.get.return_value = flow
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    flow_run_repo.count_active_runs.return_value = 1

    with pytest.raises(FlowRunConcurrencyLimitReachedError) as exc_info:
        await service.create_run(flow_id=flow.id, input_payload_json={"x": 1})
    assert exc_info.value.max_concurrent_runs == 1
    flow_run_repo.acquire_tenant_run_creation_lock.assert_awaited_once_with(
        tenant_id=user.tenant_id
    )
    flow_run_repo.count_active_runs.assert_awaited_once_with(tenant_id=user.tenant_id)
    flow_run_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_creates_preseeded_run(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=2)
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
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

    assert created.created is True
    assert created.run.status == FlowRunStatus.QUEUED
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
async def test_create_run_maps_runtime_upload_binding_race_to_public_error(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    step_id = uuid4()
    file_id = uuid4()
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.get_idempotent_run.return_value = None
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    flow_run_repo.create.side_effect = FlowRunRuntimeUploadBindingRaceError(
        step_id=step_id,
        file_ids=(file_id,),
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.create_run(flow_id=flow.id, input_payload_json={"x": "y"})

    assert exc_info.value.code == "flow_run_file_not_bound_to_flow"
    assert exc_info.value.context == {
        "step_id": str(step_id),
        "file_ids": [str(file_id)],
    }


@pytest.mark.asyncio
async def test_create_run_returns_created_run(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    created_run = _run(user=user, flow_id=flow.id)
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.get_idempotent_run.return_value = None
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    flow_run_repo.create.return_value = created_run

    result = await service.create_run(flow_id=flow.id, input_payload_json={"x": "y"})

    assert result.created is True
    assert result.run.id == created_run.id


@pytest.mark.asyncio
async def test_create_run_replays_existing_run_for_matching_idempotency_key(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    existing_run = _run(user=user, flow_id=flow.id)
    version = _version(user=user, flow=flow, version=1)
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
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

    assert result.run == existing_run
    assert result.created is False
    flow_run_repo.create.assert_not_awaited()
    flow_run_repo.get_idempotent_run.assert_awaited_once()


def test_create_run_idempotency_fingerprint_shape_is_stable(user):
    service = _flow_run_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=AsyncMock(),
        flow_version_repo=AsyncMock(),
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )
    payload = build_initial_run_input_envelope(
        normalized_inline_payload={"case_id": "A-123", "tags": ["one", "two"]},
        flow_version=7,
    )
    step_id = UUID("00000000-0000-0000-0000-000000000003")
    file_id_1 = UUID("00000000-0000-0000-0000-000000000004")
    file_id_2 = UUID("00000000-0000-0000-0000-000000000005")

    fingerprint = service._build_idempotency_fingerprint(
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        principal=FlowPrincipal(
            principal_type=PrincipalType.USER,
            principal_user_id=UUID("00000000-0000-0000-0000-000000000002"),
        ),
        flow_id=UUID("00000000-0000-0000-0000-000000000006"),
        flow_version=7,
        input_payload_json=payload,
        step_input_files=[
            {
                "step_id": step_id,
                "step_order": 1,
                "file_ids": [file_id_1, file_id_2],
            }
        ],
    )

    assert fingerprint == (
        "7c11e7738bb53084971053e6719133e2acb33a18c6a5ade511735406a8f21910"
    )


def test_create_run_idempotency_fingerprint_includes_ordered_step_files(user):
    service = _flow_run_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=AsyncMock(),
        flow_version_repo=AsyncMock(),
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )
    step_id = UUID("00000000-0000-0000-0000-000000000010")
    file_a = UUID("00000000-0000-0000-0000-000000000011")
    file_b = UUID("00000000-0000-0000-0000-000000000012")
    payload = {"case_id": "A-123", "expected_flow_version": 1}
    base_kwargs = {
        "tenant_id": user.tenant_id,
        "principal": service._principal(),
        "flow_id": UUID("00000000-0000-0000-0000-000000000013"),
        "flow_version": 1,
        "input_payload_json": payload,
    }

    first_order = service._build_idempotency_fingerprint(
        **base_kwargs,
        step_input_files=[
            {
                "step_id": step_id,
                "step_order": 1,
                "file_ids": [file_a, file_b],
            }
        ],
    )
    second_order = service._build_idempotency_fingerprint(
        **base_kwargs,
        step_input_files=[
            {
                "step_id": step_id,
                "step_order": 1,
                "file_ids": [file_b, file_a],
            }
        ],
    )
    no_files = service._build_idempotency_fingerprint(**base_kwargs)

    assert first_order != second_order
    assert first_order != no_files


def test_step_inputs_boundary_normalizes_file_ids():
    step_id = UUID("00000000-0000-0000-0000-000000000010")
    file_b = UUID("00000000-0000-0000-0000-000000000012")
    file_a = UUID("00000000-0000-0000-0000-000000000011")

    normalized = normalize_step_inputs_payload(
        {step_id: FlowRunStepInputFiles(file_ids=(file_b, file_a, file_b))}
    )

    assert normalized == {step_id: [file_b, file_a]}


@pytest.mark.asyncio
async def test_create_run_with_idempotency_key_creates_when_no_retained_row_exists(
    user,
):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    created_run = _run(user=user, flow_id=flow.id)
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
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

    assert result.run == created_run
    assert result.created is True
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
            "principal_type": PrincipalType.SERVICE_KEY,
            "principal_user_id": None,
            "principal_service_id": service_user.active_api_key.service_principal_id,
            "created_by_api_key_id": service_user.active_api_key.id,
            "runtime_service_permission": ApiKeyPermission.WRITE,
        }
    )
    service = _flow_run_service(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
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

    assert result.run == created_run
    assert result.created is True
    flow_run_repo.create.assert_awaited_once()
    kwargs = flow_run_repo.create.await_args.kwargs
    assert kwargs["principal_type"] == "service_key"
    assert kwargs["principal_user_id"] is None
    assert (
        kwargs["principal_service_id"]
        == service_user.active_api_key.service_principal_id
    )
    assert kwargs["created_by_api_key_id"] == service_user.active_api_key.id
    assert kwargs["runtime_service_permission"] == ApiKeyPermission.WRITE


@pytest.mark.asyncio
async def test_create_run_replays_idempotent_run_before_concurrency_limit(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    existing_run = _run(user=user, flow_id=flow.id)
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=0,
    )
    flow_repo.get.return_value = flow
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
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

    assert result.run == existing_run
    assert result.created is False
    flow_run_repo.count_active_runs.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_rejects_invalid_idempotency_key(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
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
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
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
async def test_create_run_rejects_missing_required_form_field(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _form_schema_flow(user)
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)

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
async def test_create_run_validates_against_published_metadata(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    draft_flow = _flow(user=user, published_version=1, metadata_json=None)
    published_metadata = {
        "form_schema": {
            "fields": [
                {"name": "case_id", "type": "text", "required": True, "order": 1}
            ]
        }
    }
    published_flow = draft_flow.model_copy(update={"metadata_json": published_metadata})
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = draft_flow
    flow_version_repo.get.return_value = _runtime_version(
        user=user, flow=published_flow
    )

    with pytest.raises(
        BadRequestException, match="Missing required input field 'case_id'"
    ) as exc_info:
        await service.create_run(flow_id=draft_flow.id, input_payload_json={})

    assert exc_info.value.code == "flow_input_required_field_missing"
    assert exc_info.value.context == {
        "field_name": "case_id",
        "field_type": "text",
    }
    flow_run_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_ignores_draft_only_form_fields(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    draft_flow = _flow(
        user=user,
        published_version=1,
        metadata_json={
            "form_schema": {
                "fields": [
                    {
                        "name": "draft_only",
                        "type": "text",
                        "required": True,
                        "order": 1,
                    }
                ]
            }
        },
    )
    published_flow = draft_flow.model_copy(update={"metadata_json": None})
    created_run = _run(user=user, flow_id=draft_flow.id)
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = draft_flow
    flow_run_repo.get_idempotent_run.return_value = None
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _runtime_version(
        user=user, flow=published_flow
    )
    flow_run_repo.create.return_value = created_run

    result = await service.create_run(flow_id=draft_flow.id, input_payload_json={})

    assert result.run == created_run
    assert result.created is True
    assert flow_run_repo.create.await_args.kwargs["input_payload_json"] == {
        "expected_flow_version": 1,
    }


@pytest.mark.parametrize(
    "metadata_json",
    [
        {"form_schema": {"fields": "not-a-list"}},
        {"form_schema": {"fields": [{"name": "case_id", "type": "unsupported"}]}},
        {"form_schema": {"fields": [{"type": "text"}]}},
    ],
)
@pytest.mark.asyncio
async def test_create_run_ignores_malformed_draft_metadata(
    user,
    metadata_json: dict[str, object],
):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1, metadata_json=metadata_json)
    created_run = _run(user=user, flow_id=flow.id)
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.get_idempotent_run.return_value = None
    flow_run_repo.count_active_runs.return_value = 0
    published_flow = flow.model_copy(update={"metadata_json": None})
    flow_version_repo.get.return_value = _runtime_version(
        user=user, flow=published_flow
    )
    flow_run_repo.create.return_value = created_run

    result = await service.create_run(flow_id=flow.id, input_payload_json={"x": "y"})

    assert result.run == created_run
    assert result.created is True
    assert flow_run_repo.create.await_args.kwargs["input_payload_json"] == {
        "x": "y",
        "expected_flow_version": 1,
    }


@pytest.mark.asyncio
async def test_create_run_rejects_malformed_published_form_schema_before_side_effects(
    user,
):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    draft_flow = _flow(user=user, published_version=1, metadata_json=None)
    published_flow = draft_flow.model_copy(
        update={
            "metadata_json": {
                "form_schema": {"fields": [{"name": "case_id", "type": "unsupported"}]}
            }
        }
    )
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = draft_flow
    flow_version_repo.get.return_value = _runtime_version(
        user=user, flow=published_flow
    )

    with pytest.raises(
        BadRequestException, match="Published flow form schema is invalid"
    ) as exc_info:
        await service.create_run(
            flow_id=draft_flow.id,
            input_payload_json={"case_id": "A-123"},
        )

    assert exc_info.value.code == FLOW_PUBLISHED_FORM_SCHEMA_INVALID
    flow_run_repo.acquire_tenant_run_creation_lock.assert_not_awaited()
    flow_run_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_rejects_invalid_select_option(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _form_schema_flow(user)
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)

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
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)

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
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)

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
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)

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
    flow = _flow(
        user=user,
        published_version=3,
        metadata_json={
            "form_schema": {
                "fields": [
                    {"name": "case_id", "type": "text", "required": True, "order": 1}
                ]
            }
        },
    )
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
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
    runtime_upload_repo = AsyncMock()
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
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=file_repo,
        runtime_upload_repo=runtime_upload_repo,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_run_repo.create.return_value = created_run
    file_id = uuid4()
    runtime_upload_repo.list_bound_file_ids_for_owner.return_value = {file_id}
    file_repo.get_list_by_id_for_owner.return_value = [
        SimpleNamespace(id=file_id, mimetype="application/pdf", size=1024)
    ]
    flow_version_repo.get.return_value = _published_flow_version(
        flow_id=flow.id,
        version=2,
        tenant_id=user.tenant_id,
        definition_checksum=None,
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
                },
                {
                    "step_id": str(flow.steps[1].id),
                    "step_order": 2,
                    "assistant_id": str(flow.steps[1].assistant_id),
                    "input_source": "previous_step",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "json",
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
        step_inputs={runtime_step.id: FlowRunStepInputFiles(file_ids=(file_id,))},
    )

    payload = flow_run_repo.create.await_args.kwargs["input_payload_json"]
    assert payload["expected_flow_version"] == 2
    assert "step_inputs" not in payload
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
    runtime_upload_repo = AsyncMock()
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
            "principal_type": PrincipalType.SERVICE_KEY,
            "principal_user_id": None,
            "principal_service_id": service_user.active_api_key.service_principal_id,
            "created_by_api_key_id": service_user.active_api_key.id,
            "runtime_service_permission": ApiKeyPermission.WRITE,
        }
    )
    service = _flow_run_service(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=file_repo,
        runtime_upload_repo=runtime_upload_repo,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_run_repo.create.return_value = created_run
    file_id = uuid4()
    runtime_upload_repo.list_bound_file_ids_for_owner.return_value = {file_id}
    file_repo.get_list_by_id_for_owner.return_value = [
        SimpleNamespace(id=file_id, mimetype="application/pdf", size=1024)
    ]
    flow_version_repo.get.return_value = _published_flow_version(
        flow_id=flow.id,
        version=2,
        tenant_id=user.tenant_id,
        definition_checksum=None,
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
        step_inputs={runtime_step.id: FlowRunStepInputFiles(file_ids=(file_id,))},
    )

    file_repo.get_list_by_id_for_owner.assert_awaited_once_with(
        ids=[file_id],
        owner_type="service_key",
        owner_user_id=None,
        owner_service_id=service_user.active_api_key.service_principal_id,
        tenant_id=service_user.tenant_id,
        include_transcription=False,
    )
    runtime_upload_repo.list_bound_file_ids_for_owner.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_run_rejects_runtime_step_input_mimetype(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    file_repo = AsyncMock()
    runtime_upload_repo = AsyncMock()
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
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=file_repo,
        runtime_upload_repo=runtime_upload_repo,
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_version_repo.get.return_value = _published_flow_version(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum=None,
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
                }
            ],
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    file_id = uuid4()
    runtime_upload_repo.list_bound_file_ids_for_owner.return_value = {file_id}
    file_repo.get_list_by_id_for_owner.return_value = [
        SimpleNamespace(id=file_id, mimetype="application/pdf", size=1024)
    ]

    with pytest.raises(BadRequestException) as exc_info:
        await service.create_run(
            flow_id=flow.id,
            input_payload_json={"x": "y"},
            step_inputs={runtime_step.id: FlowRunStepInputFiles(file_ids=(file_id,))},
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
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )

    result = await service.list_runs(flow_id=flow_id)

    assert result == expected
    flow_run_repo.list_runs.assert_awaited_once_with(
        tenant_id=user.tenant_id,
        flow_id=flow_id,
        statuses=None,
        principal_user_id=user.id,
        principal_service_id=None,
        limit=None,
        offset=None,
    )


@pytest.mark.asyncio
async def test_list_runs_delegates_status_filter_to_repo(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow_id = uuid4()
    statuses = [FlowRunStatus.COMPLETED]
    expected = [
        _run(user=user, flow_id=flow_id).model_copy(
            update={"status": FlowRunStatus.COMPLETED}
        )
    ]
    flow_run_repo.list_runs.return_value = expected
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )

    result = await service.list_runs(flow_id=flow_id, statuses=statuses)

    assert result == expected
    flow_run_repo.list_runs.assert_awaited_once_with(
        tenant_id=user.tenant_id,
        flow_id=flow_id,
        statuses=statuses,
        principal_user_id=user.id,
        principal_service_id=None,
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
    service = _flow_run_service(
        user=admin_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )

    result = await service.list_runs(flow_id=flow_id)

    assert result == expected
    flow_run_repo.list_runs.assert_awaited_once_with(
        tenant_id=admin_user.tenant_id,
        flow_id=flow_id,
        statuses=None,
        principal_user_id=None,
        principal_service_id=None,
        limit=None,
        offset=None,
    )


@pytest.mark.asyncio
async def test_list_runs_filters_service_key_runs_by_service_principal(user):
    service_user = _service_key_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow_id = uuid4()
    expected = [
        _run(user=user, flow_id=flow_id).model_copy(
            update={
                "principal_type": PrincipalType.SERVICE_KEY,
                "principal_user_id": None,
                "principal_service_id": service_user.active_api_key.service_principal_id,
                "created_by_api_key_id": service_user.active_api_key.id,
                "runtime_service_permission": ApiKeyPermission.WRITE,
            }
        )
    ]
    flow_run_repo.list_runs.return_value = expected
    service = _flow_run_service(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )

    result = await service.list_runs(flow_id=flow_id)

    assert result == expected
    flow_run_repo.list_runs.assert_awaited_once_with(
        tenant_id=service_user.tenant_id,
        flow_id=flow_id,
        statuses=None,
        principal_user_id=None,
        principal_service_id=service_user.active_api_key.service_principal_id,
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
    service = _flow_run_service(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        access_policy=_access_policy(
            user=service_user,
            flow_repo=flow_repo,
            flow_run_repo=flow_run_repo,
            space_service=space_service,
            actor_manager=actor_manager,
        ),
    )

    await service.list_runs(flow_id=flow.id)

    flow_run_repo.list_runs.assert_awaited_once_with(
        tenant_id=service_user.tenant_id,
        flow_id=flow.id,
        statuses=None,
        principal_user_id=None,
        principal_service_id=service_user.active_api_key.service_principal_id,
        limit=None,
        offset=None,
    )


@pytest.mark.asyncio
async def test_list_runs_with_result_files_and_token_usage_enriches_page(user):
    flow_run_repo = AsyncMock()
    flow_id = uuid4()
    run_with_file = _run(user=user, flow_id=flow_id)
    run_with_usage = _run(user=user, flow_id=flow_id)
    extra_run = _run(user=user, flow_id=flow_id)
    result_file = _result_file(user=user, run=run_with_file, file_id=uuid4())
    usage = FlowRunTokenUsage(
        num_tokens_input=12,
        num_tokens_output=5,
        num_tokens_total=17,
    )
    flow_run_repo.list_runs.return_value = [run_with_file, run_with_usage, extra_run]
    flow_run_repo.list_result_files_for_runs.return_value = [result_file]
    flow_run_repo.list_token_usage_for_runs.return_value = {run_with_usage.id: usage}
    service = _flow_run_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_version_repo=AsyncMock(),
        runtime_upload_repo=_runtime_upload_repo(),
    )

    page = await service.list_runs_with_result_files_and_token_usage(
        flow_id=flow_id,
        limit=2,
        offset=4,
    )

    assert isinstance(page, FlowRunPageWithResultFilesAndTokenUsage)
    assert page.has_more is True
    assert [item.run for item in page.items] == [run_with_file, run_with_usage]
    assert page.items[0].result_files == (result_file,)
    assert page.items[0].token_usage is None
    assert page.items[1].result_files == ()
    assert page.items[1].token_usage == usage
    flow_run_repo.list_runs.assert_awaited_once_with(
        tenant_id=user.tenant_id,
        flow_id=flow_id,
        statuses=None,
        principal_user_id=user.id,
        principal_service_id=None,
        limit=3,
        offset=4,
    )
    flow_run_repo.list_result_files_for_runs.assert_awaited_once_with(
        run_ids=[run_with_file.id, run_with_usage.id],
        tenant_id=user.tenant_id,
    )
    flow_run_repo.list_token_usage_for_runs.assert_awaited_once_with(
        run_ids=[run_with_file.id, run_with_usage.id],
        tenant_id=user.tenant_id,
    )


@pytest.mark.asyncio
async def test_get_run_detail_includes_tenant_scoped_webhook_deliveries(user):
    flow_run_repo = AsyncMock()
    webhook_delivery_repo = AsyncMock(spec=FlowRunWebhookDeliveryRepository)
    flow = _flow(user)
    run = _run(user=user, flow_id=flow.id)
    delivery = SimpleNamespace(id=uuid4(), delivery_status="pending")
    flow_run_repo.get.return_value = run
    flow_run_repo.list_result_files_for_runs.return_value = []
    flow_run_repo.list_token_usage_for_runs.return_value = {}
    webhook_delivery_repo.list_run_delivery_statuses.return_value = [delivery]
    service = _flow_run_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_version_repo=AsyncMock(),
        runtime_upload_repo=_runtime_upload_repo(),
        webhook_delivery_repo=webhook_delivery_repo,
    )

    detail = await service.get_run_detail_with_result_files_and_token_usage(
        flow_id=flow.id,
        run_id=run.id,
    )

    assert detail.run == run
    assert detail.webhook_deliveries == (delivery,)
    webhook_delivery_repo.list_run_delivery_statuses.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
    )


@pytest.mark.asyncio
async def test_list_runs_bulk_loads_each_historical_completed_version_once(user):
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user, published_version=2)
    version_one = _runtime_version(user, flow, version=1)
    text_flow = flow.model_copy(
        update={
            "steps": [
                flow.steps[0],
                flow.steps[1].model_copy(
                    update={"output_type": "text", "output_contract": None}
                ),
            ]
        },
        deep=True,
    )
    version_two = _runtime_version(user, text_flow, version=2)
    structured_run = _run(user=user, flow_id=flow.id).model_copy(
        update={
            "status": FlowRunStatus.COMPLETED,
            "flow_version": 1,
            "output_payload_json": {"structured": {"answer": "first"}},
        }
    )
    duplicate_version_run = _run(user=user, flow_id=flow.id).model_copy(
        update={
            "status": FlowRunStatus.COMPLETED,
            "flow_version": 1,
            "output_payload_json": {"structured": {"answer": "second"}},
        }
    )
    text_run = _run(user=user, flow_id=flow.id).model_copy(
        update={
            "status": FlowRunStatus.COMPLETED,
            "flow_version": 2,
            "output_payload_json": {"text": "current text"},
        }
    )
    flow_run_repo.list_runs.return_value = [
        structured_run,
        duplicate_version_run,
        text_run,
    ]
    flow_run_repo.list_result_files_for_runs.return_value = []
    flow_run_repo.list_token_usage_for_runs.return_value = {}
    flow_version_repo.get_many.return_value = {
        (flow.id, 1): version_one,
        (flow.id, 2): version_two,
    }
    service = _flow_run_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )

    page = await service.list_runs_with_result_files_and_token_usage(
        flow_id=flow.id,
        limit=3,
        offset=0,
    )

    assert [item.final_output.output_type for item in page.items] == [
        "json",
        "json",
        "text",
    ]
    flow_version_repo.get_many.assert_awaited_once_with(
        version_refs=((flow.id, 1), (flow.id, 2)),
        tenant_id=user.tenant_id,
    )


@pytest.mark.asyncio
async def test_list_runs_with_result_files_and_token_usage_exact_limit_has_no_more(
    user,
):
    flow_run_repo = AsyncMock()
    flow_id = uuid4()
    run_one = _run(user=user, flow_id=flow_id)
    run_two = _run(user=user, flow_id=flow_id)
    flow_run_repo.list_runs.return_value = [run_one, run_two]
    flow_run_repo.list_result_files_for_runs.return_value = []
    flow_run_repo.list_token_usage_for_runs.return_value = {}
    service = _flow_run_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_version_repo=AsyncMock(),
        runtime_upload_repo=_runtime_upload_repo(),
    )

    page = await service.list_runs_with_result_files_and_token_usage(
        flow_id=flow_id,
        limit=2,
        offset=0,
    )

    assert page.has_more is False
    assert [item.run for item in page.items] == [run_one, run_two]
    flow_run_repo.list_result_files_for_runs.assert_awaited_once_with(
        run_ids=[run_one.id, run_two.id],
        tenant_id=user.tenant_id,
    )
    flow_run_repo.list_token_usage_for_runs.assert_awaited_once_with(
        run_ids=[run_one.id, run_two.id],
        tenant_id=user.tenant_id,
    )


@pytest.mark.asyncio
async def test_list_runs_with_result_files_and_token_usage_empty_page_skips_enrichment(
    user,
):
    flow_run_repo = AsyncMock()
    flow_id = uuid4()
    flow_run_repo.list_runs.return_value = []
    service = _flow_run_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_version_repo=AsyncMock(),
        runtime_upload_repo=_runtime_upload_repo(),
    )

    page = await service.list_runs_with_result_files_and_token_usage(
        flow_id=flow_id,
        limit=20,
        offset=0,
    )

    assert page.items == ()
    assert page.has_more is False
    flow_run_repo.list_result_files_for_runs.assert_not_awaited()
    flow_run_repo.list_token_usage_for_runs.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_runs_with_result_files_and_token_usage_rejects_foreign_tenant_row(
    user,
):
    flow_run_repo = AsyncMock()
    flow_id = uuid4()
    foreign_run = _run(user=user, flow_id=flow_id).model_copy(
        update={"tenant_id": uuid4()}
    )
    flow_run_repo.list_runs.return_value = [foreign_run]
    service = _flow_run_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_version_repo=AsyncMock(),
        runtime_upload_repo=_runtime_upload_repo(),
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.list_runs_with_result_files_and_token_usage(
            flow_id=flow_id,
            limit=1,
            offset=0,
        )

    assert exc_info.value.code == "flow_run_access_denied"
    assert exc_info.value.context == {"auth_layer": "flow_run_argument"}
    flow_run_repo.list_result_files_for_runs.assert_not_awaited()
    flow_run_repo.list_token_usage_for_runs.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_run_with_result_files_and_token_usage_enriches_single_run(user):
    flow_run_repo = AsyncMock()
    flow_id = uuid4()
    run = _run(user=user, flow_id=flow_id)
    result_file = _result_file(user=user, run=run, file_id=uuid4())
    usage = FlowRunTokenUsage(
        num_tokens_input=20,
        num_tokens_output=8,
        num_tokens_total=28,
    )
    flow_run_repo.get.return_value = run
    flow_run_repo.list_result_files_for_runs.return_value = [result_file]
    flow_run_repo.list_token_usage_for_runs.return_value = {run.id: usage}
    service = _flow_run_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_version_repo=AsyncMock(),
        runtime_upload_repo=_runtime_upload_repo(),
    )

    view = await service.get_run_with_result_files_and_token_usage(
        flow_id=flow_id,
        run_id=run.id,
    )

    assert isinstance(view, FlowRunWithResultFilesAndTokenUsage)
    assert view.run == run
    assert view.result_files == (result_file,)
    assert view.token_usage == usage
    flow_run_repo.list_result_files_for_runs.assert_awaited_once_with(
        run_ids=[run.id],
        tenant_id=user.tenant_id,
    )
    flow_run_repo.list_token_usage_for_runs.assert_awaited_once_with(
        run_ids=[run.id],
        tenant_id=user.tenant_id,
    )


@pytest.mark.asyncio
async def test_get_evidence_rejects_service_key_even_for_own_run(user):
    service_user = _service_key_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    service = FlowRunEvidenceService(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
    )
    run = _run(user=user, flow_id=uuid4()).model_copy(
        update={
            "principal_type": PrincipalType.SERVICE_KEY,
            "principal_user_id": None,
            "principal_service_id": service_user.active_api_key.service_principal_id,
            "created_by_api_key_id": service_user.active_api_key.id,
            "runtime_service_permission": ApiKeyPermission.WRITE,
        }
    )
    flow_run_repo.get.return_value = run

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.get_redacted_evidence_bundle(run_id=run.id)

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
            "principal_type": PrincipalType.SERVICE_KEY,
            "principal_user_id": None,
            "principal_service_id": service_user.active_api_key.service_principal_id,
            "created_by_api_key_id": service_user.active_api_key.id,
            "runtime_service_permission": ApiKeyPermission.WRITE,
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
    service = FlowRunEvidenceService(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
    )

    evidence = (await service.get_redacted_evidence_bundle(run_id=run.id)).to_dict()

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
            "principal_type": PrincipalType.SERVICE_KEY,
            "principal_user_id": None,
            "principal_service_id": service_user.active_api_key.service_principal_id,
            "created_by_api_key_id": service_user.active_api_key.id,
            "runtime_service_permission": ApiKeyPermission.WRITE,
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
    service = FlowRunEvidenceService(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
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
            "principal_type": PrincipalType.SERVICE_KEY,
            "principal_user_id": None,
            "principal_service_id": service_user.active_api_key.service_principal_id,
            "created_by_api_key_id": service_user.active_api_key.id,
            "runtime_service_permission": ApiKeyPermission.WRITE,
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
    service = FlowRunEvidenceService(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
        access_policy=_access_policy(
            user=service_user,
            flow_repo=flow_repo,
            flow_run_repo=flow_run_repo,
            space_service=space_service,
            actor_manager=actor_manager,
        ),
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
    service = FlowRunEvidenceService(
        user=_trace_user(user),
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
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
    service = FlowRunEvidenceService(
        user=allowed_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
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
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
        access_policy=_access_policy(
            user=user,
            flow_repo=flow_repo,
            flow_run_repo=flow_run_repo,
            space_service=space_service,
            actor_manager=actor_manager,
        ),
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
    service = FlowRunEvidenceService(
        user=admin_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
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
    service = FlowRunEvidenceService(
        user=_trace_user(user),
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
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
    service = FlowRunEvidenceService(
        user=admin_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
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
            "principal_type": PrincipalType.SERVICE_KEY,
            "principal_user_id": None,
            "principal_service_id": service_user.active_api_key.service_principal_id,
            "created_by_api_key_id": service_user.active_api_key.id,
            "runtime_service_permission": ApiKeyPermission.WRITE,
        }
    )
    flow_run_repo.get.return_value = run
    service = _flow_run_service(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
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
    service = _flow_run_service(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        access_policy=_access_policy(
            user=service_user,
            flow_repo=flow_repo,
            flow_run_repo=flow_run_repo,
            space_service=space_service,
            actor_manager=actor_manager,
        ),
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
    service = _flow_run_service(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    other_service_principal_id = uuid4()
    run = _run(user=user, flow_id=uuid4()).model_copy(
        update={
            "principal_type": PrincipalType.SERVICE_KEY,
            "principal_user_id": None,
            "principal_service_id": other_service_principal_id,
            "created_by_api_key_id": uuid4(),
            "runtime_service_permission": ApiKeyPermission.WRITE,
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
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
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
    service = _flow_run_service(
        user=admin_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
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
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        access_policy=_access_policy(
            user=user,
            flow_repo=flow_repo,
            flow_run_repo=flow_run_repo,
            space_service=space_service,
            actor_manager=actor_manager,
        ),
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
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        access_policy=_access_policy(
            user=user,
            flow_repo=flow_repo,
            flow_run_repo=flow_run_repo,
            space_service=space_service,
            actor_manager=actor_manager,
        ),
    )

    result = await service.list_step_results(run_id=run.id, flow_id=run.flow_id)

    assert result == []


@pytest.mark.asyncio
async def test_get_run_versioned_view_loads_run_definition_and_results(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user)
    assert flow.id is not None
    run = _run(user=user, flow_id=flow.id)
    version = _runtime_version(user=user, flow=flow, version=run.flow_version)
    step_result = _step_result_record(run, step_order=1)
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = [step_result]
    flow_version_repo.get.return_value = version
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )

    result = await service.get_run_versioned_view(
        flow_id=run.flow_id,
        run_id=run.id,
    )

    assert isinstance(result, FlowRunVersionedView)
    assert result.published_definition.flow_id == run.flow_id
    assert result.published_definition.schema_version == FLOW_DEFINITION_SCHEMA_VERSION
    assert result.step_results == (step_result,)
    flow_run_repo.get.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
        flow_id=run.flow_id,
    )
    flow_version_repo.get.assert_awaited_once_with(
        flow_id=run.flow_id,
        version=run.flow_version,
        tenant_id=run.tenant_id,
    )
    flow_run_repo.list_step_results.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
    )


@pytest.mark.asyncio
async def test_get_run_versioned_view_rejects_checksum_drift_before_results(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user)
    assert flow.id is not None
    run = _run(user=user, flow_id=flow.id)
    version = _runtime_version(user=user, flow=flow, version=run.flow_version)
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = version.model_copy(
        update={"definition_checksum": "stored-checksum-does-not-match"}
    )
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )

    with pytest.raises(FlowBadRequestException) as exc_info:
        await service.get_run_versioned_view(flow_id=flow.id, run_id=run.id)

    assert exc_info.value.code is FlowApiErrorCode.DEFINITION_CHECKSUM_MISMATCH
    flow_run_repo.list_step_results.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_run_versioned_view_rejects_matching_checksum_invalid_runtime_step_before_results(
    user,
) -> None:
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user)
    assert flow.id is not None
    run = _run(user=user, flow_id=flow.id)
    invalid_definition = build_published_definition_json(
        flow_id=flow.id,
        name=flow.name,
        description=flow.description,
        metadata_json=flow.metadata_json,
        steps=[
            {
                **_published_runtime_step(step),
                "output_mode": "invalid_mode" if index == 0 else "pass_through",
            }
            for index, step in enumerate(flow.steps)
        ],
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _published_flow_version(
        flow_id=flow.id,
        version=run.flow_version,
        tenant_id=user.tenant_id,
        definition_checksum=None,
        definition_json=invalid_definition,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.get_run_versioned_view(flow_id=flow.id, run_id=run.id)

    assert exc_info.value.code == FLOW_DEFINITION_STEPS_INVALID
    flow_run_repo.list_step_results.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_run_versioned_view_rejects_empty_snapshot_before_results(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user)
    assert flow.id is not None
    run = _run(user=user, flow_id=flow.id)
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _published_flow_version(
        flow_id=flow.id,
        version=run.flow_version,
        tenant_id=user.tenant_id,
        definition_checksum=None,
        definition_json=build_published_definition_json(
            flow_id=flow.id,
            name=flow.name,
            description=flow.description,
            metadata_json=flow.metadata_json,
            steps=[],
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )

    with pytest.raises(FlowPublishedDefinitionWithoutExecutableStepsError) as exc_info:
        await service.get_run_versioned_view(flow_id=flow.id, run_id=run.id)

    assert exc_info.value.flow_id == flow.id
    assert exc_info.value.flow_version == run.flow_version
    flow_run_repo.list_step_results.assert_not_awaited()


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
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
        access_policy=_access_policy(
            user=user,
            flow_repo=flow_repo,
            flow_run_repo=flow_run_repo,
            space_service=space_service,
            actor_manager=actor_manager,
        ),
    )

    evidence = (await service.get_redacted_evidence_bundle(run_id=run.id)).to_dict()

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
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
        access_policy=_access_policy(
            user=user,
            flow_repo=flow_repo,
            flow_run_repo=flow_run_repo,
            space_service=space_service,
            actor_manager=actor_manager,
        ),
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
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
        access_policy=_access_policy(
            user=user,
            flow_repo=flow_repo,
            flow_run_repo=flow_run_repo,
            space_service=space_service,
            actor_manager=actor_manager,
        ),
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
    service = FlowRunEvidenceService(
        user=trace_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
        access_policy=_access_policy(
            user=trace_user,
            flow_repo=flow_repo,
            flow_run_repo=flow_run_repo,
            space_service=space_service,
            actor_manager=actor_manager,
        ),
    )

    export = await service.export_evidence_json(run_id=run.id, detail="raw")

    assert export["redaction"]["applied"] is False


@pytest.mark.asyncio
async def test_create_run_rejects_oversized_input_payload(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )
    flow = _flow(user=user, published_version=1)
    flow_repo.get.return_value = flow
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
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
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )
    flow = _flow(user=user, published_version=1)
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _published_flow_version(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum=None,
        definition_json=definition_json,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    with pytest.raises(BadRequestException, match=message_fragment) as exc_info:
        await service.create_run(flow_id=flow.id, input_payload_json={"x": "y"})
    assert exc_info.value.code == error_code
    assert exc_info.value.context == error_context
    flow_run_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_rejects_checksum_drift_before_creation_work(user) -> None:
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    version = _runtime_version(user=user, flow=flow, version=1)
    flow_repo.get.return_value = flow
    flow_version_repo.get.return_value = version.model_copy(
        update={"definition_checksum": "stored-checksum-does-not-match"}
    )
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )

    with pytest.raises(FlowBadRequestException) as exc_info:
        await service.create_run(flow_id=flow.id, input_payload_json={"x": "y"})

    assert exc_info.value.code is FlowApiErrorCode.DEFINITION_CHECKSUM_MISMATCH
    assert exc_info.value.context == {
        "expected_checksum": "stored-checksum-does-not-match",
        "current_checksum": published_definition_checksum(version.definition_json),
    }
    flow_run_repo.acquire_tenant_run_creation_lock.assert_not_awaited()
    flow_run_repo.count_active_runs.assert_not_awaited()
    flow_run_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_rejects_matching_checksum_invalid_runtime_step_before_creation_work(
    user,
) -> None:
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    invalid_definition = build_published_definition_json(
        flow_id=flow.id,
        name=flow.name,
        description=flow.description,
        metadata_json=flow.metadata_json,
        steps=[
            {
                **_published_runtime_step(step),
                "output_mode": "invalid_mode" if index == 0 else "pass_through",
            }
            for index, step in enumerate(flow.steps)
        ],
    )
    flow_repo.get.return_value = flow
    flow_version_repo.get.return_value = _published_flow_version(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum=None,
        definition_json=invalid_definition,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.create_run(flow_id=flow.id, input_payload_json={"x": "y"})

    assert exc_info.value.code == FLOW_DEFINITION_STEPS_INVALID
    flow_run_repo.acquire_tenant_run_creation_lock.assert_not_awaited()
    flow_run_repo.count_active_runs.assert_not_awaited()
    flow_run_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_rejects_published_snapshot_without_executable_steps_as_internal_invariant(
    user,
):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )
    flow = _flow(user=user, published_version=1)
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _published_flow_version(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum=None,
        definition_json={"schema_version": 1, "flow_id": str(flow.id), "steps": []},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    with pytest.raises(
        FlowPublishedDefinitionWithoutExecutableStepsError,
        match="does not contain executable steps",
    ) as exc_info:
        await service.create_run(flow_id=flow.id, input_payload_json={"x": "y"})

    assert exc_info.value.flow_id == flow.id
    assert exc_info.value.flow_version == 1
    flow_run_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_rejects_loaded_published_flow_without_id_as_internal_invariant(
    user,
):
    requested_flow_id = uuid4()
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )
    flow = _flow(user=user, published_version=1).model_copy(update={"id": None})
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _published_flow_version(
        flow_id=requested_flow_id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum=None,
        definition_json=build_published_definition_json(
            flow_id=requested_flow_id,
            name=flow.name,
            description=flow.description,
            metadata_json=flow.metadata_json,
            steps=[_published_runtime_step(_step(1))],
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    with pytest.raises(FlowPersistedIdMissingError):
        await service.create_run(
            flow_id=requested_flow_id,
            input_payload_json={"x": "y"},
        )

    flow_run_repo.create.assert_not_awaited()


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
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_terminalizer=terminalizer,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )

    result = await service.cancel_run(run_id=run.id, flow_id=run.flow_id)

    assert result.status == FlowRunStatus.CANCELLED
    flow_run_repo.get.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
        flow_id=run.flow_id,
    )
    terminalizer.terminalize_run.assert_awaited_once()
    terminal_kwargs = terminalizer.terminalize_run.await_args.kwargs
    assert terminal_kwargs["target_status"] == FlowRunStatus.CANCELLED
    assert terminal_kwargs["source"] == FlowRunLifecycleSource.USER_CANCEL
    assert terminal_kwargs["error"].code == FlowApiErrorCode.RUN_USER_CANCELLED.value
    assert terminal_kwargs["error"].message == "Run cancelled by user."


@pytest.mark.asyncio
async def test_cancel_run_translates_terminalizer_missing_run_race_to_public_not_found(
    user,
):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    run = _run(user=user, flow_id=uuid4()).model_copy(
        update={"status": FlowRunStatus.RUNNING}
    )
    flow_run_repo.get.return_value = run
    terminalizer = AsyncMock()
    terminalizer.terminalize_run.side_effect = FlowRunNotFoundError(
        run_id=run.id,
        tenant_id=user.tenant_id,
        flow_id=run.flow_id,
    )
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_terminalizer=terminalizer,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )

    with pytest.raises(NotFoundException) as exc_info:
        await service.cancel_run(run_id=run.id, flow_id=run.flow_id)

    assert exc_info.value.code is None
    terminalizer.terminalize_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_run_does_not_terminalize_flow_mismatch(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    terminalizer = AsyncMock()
    run_id = uuid4()
    flow_id = uuid4()
    flow_run_repo.get.side_effect = FlowRunNotFoundError(
        run_id=run_id,
        tenant_id=user.tenant_id,
        flow_id=flow_id,
    )
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_terminalizer=terminalizer,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )

    with pytest.raises(NotFoundException):
        await service.cancel_run(run_id=run_id, flow_id=flow_id)

    flow_run_repo.get.assert_awaited_once_with(
        run_id=run_id,
        tenant_id=user.tenant_id,
        flow_id=flow_id,
    )
    terminalizer.terminalize_run.assert_not_awaited()


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
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_terminalizer=terminalizer,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )

    result = await service.cancel_run(run_id=run.id, flow_id=run.flow_id)

    assert result.status == status
    flow_run_repo.get.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
        flow_id=run.flow_id,
    )
    terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("broken_order", "include_step_id"),
    (
        (1, False),
        (2, True),
    ),
)
async def test_create_run_rejects_missing_snapshot_identifiers_even_when_draft_could_repair(
    broken_order,
    include_step_id,
    user,
):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    draft_step = flow.steps[broken_order - 1]
    broken_step: dict[str, object] = {"step_order": broken_order}
    if include_step_id:
        broken_step["step_id"] = str(draft_step.id)
    published_steps: list[dict[str, object]] = [
        {
            "step_order": step.step_order,
            "step_id": str(step.id),
            "assistant_id": str(step.assistant_id),
        }
        for step in flow.steps
    ]
    published_steps[broken_order - 1] = broken_step
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _published_flow_version(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum=None,
        definition_json=_published_definition_json(
            flow,
            published_steps,
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    with pytest.raises(
        BadRequestException, match="missing stable step identifiers"
    ) as exc_info:
        await service.create_run(flow_id=flow.id, input_payload_json={"x": "y"})

    assert exc_info.value.code == "flow_version_missing_step_identifiers"
    assert exc_info.value.context == {"step_order": broken_order}
    flow_run_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_rejects_missing_snapshot_identifiers_without_fallback(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1).model_copy(
        update={"steps": [_step(1)]}
    )
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        max_concurrent_runs=5,
    )
    flow_repo.get.return_value = flow
    flow_run_repo.count_active_runs.return_value = 0
    flow_version_repo.get.return_value = _published_flow_version(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum=None,
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
    flow_version_repo.get.return_value = _published_flow_version(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum=None,
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
    flow_run_repo.list_current_step_input_file_metadata_by_step_result_id.return_value = {}
    flow_run_repo.list_step_attempts.return_value = [
        _step_attempt_record(
            run,
            step_order=1,
            error_message="Bearer should-hide",
        )
    ]

    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
    )

    evidence = (await service.get_redacted_evidence_bundle(run_id=run.id)).to_dict()

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
    assert evidence["debug_export"]["definition"]["checksum"] == (
        flow_version_repo.get.return_value.definition_checksum
    )
    assert evidence["debug_export"]["run"]["status"] == "queued"
    assert evidence["debug_export"]["steps"][0]["input"]["source"] is None
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
    flow_version_repo.get.return_value = _published_flow_version(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum=None,
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
    flow_run_repo.list_current_step_input_file_metadata_by_step_result_id.return_value = {}
    flow_run_repo.list_step_attempts.return_value = []

    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
    )

    evidence = (await service.get_redacted_evidence_bundle(run_id=run.id)).to_dict()

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
    flow_version_repo.get.return_value = _published_flow_version(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum=None,
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
    flow_run_repo.list_current_step_input_file_metadata_by_step_result_id.return_value = {}
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

    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
    )

    evidence = (await service.get_redacted_evidence_bundle(run_id=run.id)).to_dict()

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
    run_owner_user_id = uuid4()
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"principal_user_id": run_owner_user_id}
    )
    flow_repo.get.return_value = flow
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _published_flow_version(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum=None,
        definition_json=_published_definition_json(
            flow,
            [_published_runtime_step(flow.steps[0])],
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    access_policy = AsyncMock(spec=FlowRunAccessPolicy)

    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
        access_policy=access_policy,
    )

    redacted_export = await service.export_evidence_json(run_id=run.id, run=run)
    raw_export = await service.export_evidence_json(
        run_id=run.id,
        detail="raw",
        run=run,
        export_reason="government_audit_request",
    )

    assert set(redacted_export) == set(raw_export)
    assert set(redacted_export["manifest"]) == set(raw_export["manifest"])
    for export, hash_input in (
        (redacted_export, "redacted"),
        (raw_export, "raw"),
    ):
        assert export["schema_version"] == "flow-evidence-export.v11"
        assert export["manifest"]["schema_version"] == export["schema_version"]
        assert isinstance(export["manifest"]["app_version"], str)
        assert export["manifest"]["app_version"]
        assert export["manifest"]["content_hash"] == export["content_hash"]
        assert export["manifest"]["content_hash_input"] == hash_input
        assert export["manifest"]["exported_at"] == export["generated_at"]
        assert export["manifest"]["run_id"] == str(run.id)
        assert export["manifest"]["tenant_id"] == str(user.tenant_id)
        assert export["manifest"]["trace_id"] == str(run.trace_id)
        assert export["manifest"]["flow_id"] == str(flow.id)
        assert export["manifest"]["actor"] == {
            "type": "user",
            "user_id": str(user.id),
        }
        assert export["manifest"]["actor"]["user_id"] != str(run_owner_user_id)
        assert "exported_by_user_id" not in export["manifest"]
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
async def test_export_evidence_json_attributes_service_key_actor_to_key_id(user):
    service_user = _service_key_user(user)
    principal = FlowPrincipal.from_user(service_user)
    assert principal.actor_api_key_id is not None
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=service_user, published_version=1)
    run = _run(user=service_user, flow_id=flow.id)
    flow_version_repo.get.return_value = _published_flow_version(
        flow_id=flow.id,
        version=1,
        tenant_id=service_user.tenant_id,
        definition_checksum=None,
        definition_json=_published_definition_json(
            flow,
            [_published_runtime_step(flow.steps[0])],
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    access_policy = AsyncMock(spec=FlowRunAccessPolicy)
    service = FlowRunEvidenceService(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
        access_policy=access_policy,
    )

    export = await service.export_evidence_json(run_id=run.id, run=run)

    assert export["manifest"]["actor"] == {
        "type": "service_key",
        "key_id": str(principal.actor_api_key_id),
    }
    assert "user_id" not in export["manifest"]["actor"]
    assert "exported_by_user_id" not in export["manifest"]
    access_policy.ensure_can_access_run.assert_awaited_once_with(
        run,
        access_kind="evidence_export_redacted",
    )


@pytest.mark.asyncio
async def test_get_evidence_normalizes_attempt_provenance_payloads(user):
    user = _trace_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    run = _run(user=user, flow_id=flow.id)
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _published_flow_version(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum=None,
        definition_json=_published_definition_json(
            flow,
            [_published_runtime_step(flow.steps[0])],
        ),
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

    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
    )

    evidence = (await service.get_redacted_evidence_bundle(run_id=run.id)).to_dict()

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
    flow_version_repo.get.return_value = _published_flow_version(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum=None,
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
    flow_run_repo.list_current_step_input_file_metadata_by_step_result_id.return_value = {}
    flow_run_repo.list_step_attempts.return_value = []

    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
    )

    evidence = (await service.get_redacted_evidence_bundle(run_id=run.id)).to_dict()

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
    flow_version_repo.get.return_value = _published_flow_version(
        flow_id=flow.id,
        version=1,
        tenant_id=user.tenant_id,
        definition_checksum=None,
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
                }
            ],
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []

    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
    )

    evidence = (await service.get_redacted_evidence_bundle(run_id=run.id)).to_dict()

    assert evidence["debug_export"]["steps"][0]["rag"] is None


@pytest.mark.asyncio
async def test_list_step_results_filters_by_run_and_flow(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
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


@pytest.mark.asyncio
async def test_list_step_results_with_files_composes_per_step_views(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    service = _flow_run_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    run = _run(user=user, flow_id=uuid4())
    step_result_1 = _step_result_record(run, step_order=1)
    step_result_2 = _step_result_record(run, step_order=2)
    step_result_3 = _step_result_record(run, step_order=3)
    step_result_1_id = step_result_1.id
    step_result_2_id = step_result_2.id
    assert step_result_1_id is not None
    assert step_result_2_id is not None

    file_2 = _result_file(
        user=user,
        run=run,
        file_id=uuid4(),
        step_result_id=step_result_2_id,
        step_id=step_result_2.step_id,
        step_order=2,
    )
    file_1 = _result_file(
        user=user,
        run=run,
        file_id=uuid4(),
        step_result_id=step_result_1_id,
        step_id=step_result_1.step_id,
        step_order=1,
    )
    orphan_file = _result_file(
        user=user,
        run=run,
        file_id=uuid4(),
        step_result_id=uuid4(),
        step_id=uuid4(),
        step_order=3,
    )
    runtime_input_file_id = uuid4()
    orphan_runtime_input_file_id = uuid4()

    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = [
        step_result_1,
        step_result_2,
        step_result_3,
    ]
    flow_run_repo.list_result_files.return_value = [file_2, orphan_file, file_1]
    flow_run_repo.list_current_step_input_file_ids_by_step_result_id.return_value = {
        step_result_1_id: (runtime_input_file_id,),
        uuid4(): (orphan_runtime_input_file_id,),
    }

    result = await service.list_step_results_with_files(
        run_id=run.id,
        flow_id=run.flow_id,
    )

    assert tuple(item.step_result for item in result) == (
        step_result_1,
        step_result_2,
        step_result_3,
    )
    assert result[0].result_files == (file_1,)
    assert result[1].result_files == (file_2,)
    assert result[2].result_files == ()
    assert orphan_file not in result[0].result_files
    assert orphan_file not in result[1].result_files
    assert orphan_file not in result[2].result_files
    assert result[0].runtime_input_file_ids == (runtime_input_file_id,)
    assert result[1].runtime_input_file_ids == ()
    assert result[2].runtime_input_file_ids == ()
    flow_run_repo.get.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
        flow_id=run.flow_id,
    )
    flow_run_repo.list_current_step_input_file_ids_by_step_result_id.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
        step_results=[step_result_1, step_result_2, step_result_3],
    )


# ---------------------------------------------------------------------------
def _result_file(
    *,
    user,
    run,
    file_id,
    step_result_id=None,
    step_id=None,
    step_order=1,
    availability="available",
) -> FlowRunStepResultFile:
    resolved_step_id = step_id or uuid4()
    return FlowRunStepResultFile(
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=user.tenant_id,
        step_result_id=step_result_id or uuid4(),
        step_id=resolved_step_id,
        step_order=step_order,
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


def _artifact_service(user, *, file_repo, result_file=None, run=None):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    if run is None:
        run = _run(user=user, flow_id=uuid4())
    flow_run_repo.get.return_value = run
    flow_run_repo.get_result_file.return_value = result_file
    return FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=flow_version_repo,
        file_repo=file_repo,
        webhook_delivery_repo=_webhook_delivery_repo(),
    ), run


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
