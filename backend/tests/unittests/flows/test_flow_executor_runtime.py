from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import intric.flows.runtime.executor as executor_module
import intric.flows.runtime.flow_runtime_trace as flow_runtime_trace
from intric.authentication.auth_models import (
    ApiKeyPermission,
    ApiKeyScopeType,
    ServicePrincipalInDB,
    ServicePrincipalState,
)
from intric.authentication.principal_types import PrincipalType
from intric.flows.assistant_execution_snapshot import (
    build_assistant_execution_snapshot,
    stable_hash,
)
from intric.flows.domain.flow import (
    FlowRun,
    FlowRunRerunInvalidatedStep,
    FlowRunRerunOperation,
    FlowRunStatus,
    FlowStepAttempt,
    FlowStepAttemptStatus,
    FlowStepResult,
    FlowStepResultStatus,
    RerunStepInputOverride,
)
from intric.flows.domain.flow import (
    FlowVersion as FlowVersionModel,
)
from intric.flows.domain.rerun_exceptions import (
    FlowRunRerunAttemptLineageConflictError,
    FlowRunRerunMultipleActiveOperationsError,
)
from intric.flows.domain.review_checkpoint_exceptions import (
    FlowReviewCheckpointRunNotRunningError,
    FlowReviewCheckpointStepResultIncompleteError,
    FlowReviewMultipleActiveCheckpointsError,
    FlowReviewOpenBlockedByActiveCheckpointError,
)
from intric.flows.enums import (
    FlowRunLifecycleSource,
    FlowRunRerunInvalidationRole,
    FlowRunRerunOperationStatus,
)
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.flows.flow_run_error import FlowRunError
from intric.flows.flow_run_provenance import (
    AttemptStartProvenance,
    ModelParameterSnapshot,
)
from intric.flows.flow_runtime_policy import FlowRuntimePolicy
from intric.flows.infrastructure.flow_run_rerun_repo import (
    FlowRunActiveRerunOperation,
    FlowRunRerunRepository,
)
from intric.flows.published_definition import FLOW_DEFINITION_SCHEMA_VERSION
from intric.flows.runtime.document_rendering.limits import DocumentRenderLimits
from intric.flows.runtime.executor import (
    FlowRunExecutor,
    FlowRunExecutorConfig,
    RunExecutionState,
    RuntimeStep,
    StepExecutionOutput,
    StepInputValue,
)
from intric.flows.runtime.flow_run_actor import FlowRunActor
from intric.flows.runtime.output_runtime import TypedOutputProcessingResult
from intric.flows.runtime.step_execution_result import (
    StepExecutionResult,
    WebhookDeliveryIntent,
    WebhookPayloadRef,
)
from intric.main.exceptions import BadRequestException, TypedIOValidationException

_DEFAULT_SNAPSHOT_MODEL_ID = UUID("00000000-0000-0000-0000-000000000001")
_DEFAULT_SNAPSHOT_PROMPT = "Execute this flow step."


@pytest.fixture
def captured_flow_spans(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        flow_runtime_trace, "_tracer", provider.get_tracer("test.flows")
    )
    yield exporter
    exporter.clear()


def _run(*, status: FlowRunStatus, user) -> FlowRun:
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        principal_type=PrincipalType.USER,
        principal_user_id=user.id,
        tenant_id=user.tenant_id,
        trace_id=uuid4(),
        status=status,
        cancelled_at=None,
        input_payload_json={"text": "hello"},
        output_payload_json=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )


def _default_snapshot_assistant(assistant_id: UUID | str) -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID(str(assistant_id)),
        origin="flow_managed",
        prompt=SimpleNamespace(text=_DEFAULT_SNAPSHOT_PROMPT),
        completion_model=SimpleNamespace(
            id=_DEFAULT_SNAPSHOT_MODEL_ID,
            name="gpt-5.4-nano",
            nickname="Nano",
            litellm_model_name="openai/gpt-5.4-nano",
        ),
        completion_model_kwargs={"temperature": 0.2},
        collections=[],
        websites=[],
        integration_knowledge_list=[],
        mcp_servers=[],
    )


def _definition_step_with_default_snapshot(step: object) -> object:
    if not isinstance(step, dict):
        return step
    normalized = dict(step)
    if "assistant_snapshot" in normalized:
        return normalized
    assistant_id = normalized.get("assistant_id")
    if assistant_id is None:
        return normalized
    snapshot = build_assistant_execution_snapshot(
        assistant=_default_snapshot_assistant(str(assistant_id)),
        mcp_server_entities=[],
    )
    if snapshot is not None:
        normalized["assistant_snapshot"] = snapshot
    return normalized


def FlowVersion(
    *,
    flow_id,
    version,
    tenant_id,
    definition_checksum,
    definition_json,
    created_at,
    updated_at,
) -> FlowVersionModel:
    """Build canonical versions unless a test intentionally passes a bad checksum."""
    if definition_checksum == "checksum":
        if isinstance(definition_json.get("steps"), list):
            schema_version_provided = "schema_version" in definition_json
            steps = definition_json["steps"]
            if not schema_version_provided:
                steps = [_definition_step_with_default_snapshot(step) for step in steps]
            definition_json = {
                "schema_version": definition_json.get(
                    "schema_version", FLOW_DEFINITION_SCHEMA_VERSION
                ),
                "flow_id": definition_json.get("flow_id", str(flow_id)),
                "name": definition_json.get("name", "Test flow"),
                "description": definition_json.get("description"),
                "metadata_json": definition_json.get("metadata_json"),
                "steps": steps,
            }
        definition_checksum = stable_hash(definition_json)
    return FlowVersionModel(
        flow_id=flow_id,
        version=version,
        tenant_id=tenant_id,
        definition_checksum=definition_checksum,
        definition_json=definition_json,
        created_at=created_at,
        updated_at=updated_at,
    )


def _claimed_step_result(
    *, run_id, flow_id, tenant_id, step_id, assistant_id
) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        step_id=step_id,
        step_order=1,
        assistant_id=assistant_id,
        input_payload_json=None,
        effective_prompt=None,
        output_payload_json=None,
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.RUNNING,
        flow_step_execution_hash=None,
        created_at=now,
        updated_at=now,
    )


def _started_step_attempt(
    *,
    run_id,
    flow_id,
    tenant_id,
    step_id,
    step_order: int,
    attempt_no: int = 1,
) -> FlowStepAttempt:
    now = datetime.now(timezone.utc)
    return FlowStepAttempt(
        id=uuid4(),
        flow_run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        step_id=step_id,
        step_order=step_order,
        attempt_no=attempt_no,
        rerun_operation_id=None,
        predecessor_attempt_id=None,
        superseded_by_attempt_id=None,
        celery_task_id="task-1",
        status=FlowStepAttemptStatus.STARTED,
        error_code=None,
        requested_model=None,
        response_model=None,
        provider=None,
        finish_reason=None,
        provider_response_id=None,
        num_tokens_input=None,
        num_tokens_output=None,
        provenance_json=None,
        input_payload_json=None,
        output_payload_json=None,
        flow_step_execution_hash=None,
        started_at=now,
        finished_at=None,
        created_at=now,
        updated_at=now,
    )


def _step_result(output: StepExecutionOutput) -> StepExecutionResult:
    return StepExecutionResult(output=output)


def _minimal_step_execution_output() -> StepExecutionOutput:
    return StepExecutionOutput(
        input_text="hello",
        source_text="hello",
        input_source="flow_input",
        used_question_binding=False,
        full_text="answer",
        persisted_text="answer",
        generated_file_ids=[],
        tool_calls_metadata=None,
        num_tokens_input=1,
        num_tokens_output=2,
        effective_prompt="Prompt",
        model_parameters_json={"temperature": 0.2},
    )


def _typed_output_result() -> TypedOutputProcessingResult:
    return TypedOutputProcessingResult(
        structured_output=None,
        artifacts=None,
        diagnostics=[],
    )


def _webhook_step_result(
    output: StepExecutionOutput,
    *,
    run_id: UUID,
    step_id: UUID,
    step_order: int = 1,
    attempt_no: int = 1,
) -> StepExecutionResult:
    return StepExecutionResult(
        output=output,
        delivery_intents=(
            WebhookDeliveryIntent(
                flow_run_id=run_id,
                step_id=step_id,
                step_order=step_order,
                attempt_no=attempt_no,
                idempotency_key=f"{run_id}:{step_id}:{attempt_no}:webhook",
                payload=WebhookPayloadRef(
                    value=f"flow_run:{run_id}:step:{step_id}:attempt:{attempt_no}"
                ),
            ),
        ),
    )


def _run_get_mock(*runs: FlowRun) -> AsyncMock:
    sequence = list(runs)

    async def _get(*args, **kwargs):
        if sequence:
            if len(sequence) == 1:
                return sequence[0]
            return sequence.pop(0)
        raise AssertionError("Flow run get mock exhausted without fallback run")

    return AsyncMock(side_effect=_get)


def _service_principal(user) -> ServicePrincipalInDB:
    return ServicePrincipalInDB(
        id=uuid4(),
        tenant_id=user.tenant_id,
        display_name="Runtime service principal",
        description=None,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        state=ServicePrincipalState.ACTIVE,
        created_by_user_id=user.id,
    )


def _service_run(user, service_principal: ServicePrincipalInDB, *, api_key_id: UUID):
    return SimpleNamespace(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=user.tenant_id,
        principal_type=PrincipalType.SERVICE_KEY.value,
        principal_user_id=None,
        principal_service_id=service_principal.id,
        created_by_api_key_id=api_key_id,
        runtime_service_permission=ApiKeyPermission.WRITE,
    )


def _build_executor(user, *, runtime_actor: FlowRunActor | None = None):
    flow_repo = AsyncMock()
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow_run_review_checkpoint_repo = AsyncMock()
    space_repo = AsyncMock()

    async def _create_or_get_attempt_started(**kwargs):
        return _started_step_attempt(
            run_id=kwargs["run_id"],
            flow_id=kwargs["flow_id"],
            tenant_id=kwargs["tenant_id"],
            step_id=kwargs["step_id"],
            step_order=kwargs["step_order"],
            attempt_no=kwargs["attempt_no"],
        )

    async def _get_space_by_assistant(*, assistant_id):
        assistant = _default_snapshot_assistant(assistant_id)
        return SimpleNamespace(
            id=uuid4(),
            default_assistant=None,
            assistants=[assistant],
            get_assistant=lambda assistant_id: assistant,
        )

    flow_run_repo.allocate_next_attempt_no = AsyncMock(return_value=1)
    flow_run_rerun_repo.get_active_rerun_operation = AsyncMock(return_value=None)
    flow_run_repo.list_step_input_file_ids = AsyncMock(return_value=[])
    flow_run_repo.copy_step_input_files_from_predecessor_attempt = AsyncMock()
    flow_run_rerun_repo.link_rerun_invalidated_step_attempt = AsyncMock()
    flow_run_rerun_repo.mark_rerun_operation_running = AsyncMock()
    flow_run_repo.create_or_get_attempt_started = AsyncMock(
        side_effect=_create_or_get_attempt_started
    )
    space_repo.get_space_by_assistant = AsyncMock(side_effect=_get_space_by_assistant)
    completion_service = AsyncMock()
    file_repo = AsyncMock()
    template_asset_repo = AsyncMock()
    encryption_service = AsyncMock()
    flow_run_terminalizer = SimpleNamespace()

    async def _terminalize_run(**kwargs):
        return SimpleNamespace(
            run=SimpleNamespace(status=kwargs["target_status"]),
            did_transition=True,
            target_status=kwargs["target_status"],
            source=kwargs["source"],
            audit_outbox_id=uuid4(),
        )

    flow_run_terminalizer.terminalize_run = AsyncMock(side_effect=_terminalize_run)
    executor = FlowRunExecutor(
        runtime_actor=runtime_actor or FlowRunActor.from_user(user=user),
        session=session,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_run_review_checkpoint_repo=flow_run_review_checkpoint_repo,
        flow_version_repo=flow_version_repo,
        space_repo=space_repo,
        completion_service=completion_service,
        file_repo=file_repo,
        template_asset_repo=template_asset_repo,
        encryption_service=encryption_service,
        flow_run_terminalizer=flow_run_terminalizer,
        max_inline_text_bytes=1024 * 1024,
    )
    return executor, flow_repo, flow_run_repo, flow_version_repo


def test_executor_derives_service_principal_owner_from_runtime_actor(user):
    service_principal = _service_principal(user)
    api_key_id = uuid4()
    actor = FlowRunActor.from_service_principal_run(
        run=_service_run(user, service_principal, api_key_id=api_key_id),
        service_principal=service_principal,
    )

    executor, *_ = _build_executor(user, runtime_actor=actor)

    assert executor.runtime_actor is actor
    assert executor.principal is actor.principal
    assert executor._template_fill_runtime_deps().principal.file_owner_fields() == {
        "owner_type": PrincipalType.SERVICE_KEY.value,
        "owner_user_id": None,
        "owner_service_id": service_principal.id,
    }


def _empty_execution_state() -> RunExecutionState:
    return RunExecutionState(
        completed_by_order={},
        prior_results=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )


def _active_rerun_operation(
    *,
    user,
    run: FlowRun,
    step: RuntimeStep,
    role: FlowRunRerunInvalidationRole,
    root_step_input_override: RerunStepInputOverride | None,
    root_step_input_override_requested: bool | None = None,
    root_attempt_no: int = 3,
    prior_attempt_id: UUID | None = None,
) -> tuple[FlowRunActiveRerunOperation, FlowRunRerunInvalidatedStep]:
    now = datetime.now(timezone.utc)
    operation = FlowRunRerunOperation(
        id=uuid4(),
        tenant_id=run.tenant_id,
        flow_id=run.flow_id,
        flow_run_id=run.id,
        rerun_step_id=step.step_id,
        rerun_step_order=step.step_order,
        root_attempt_no=root_attempt_no,
        root_attempt_id=None,
        status=FlowRunRerunOperationStatus.QUEUED,
        request_fingerprint="rerun-fingerprint",
        expected_run_revision=1,
        accepted_run_revision=2,
        reason="rerun",
        input_payload_json=None,
        root_step_input_override_requested=(
            root_step_input_override is not None
            if root_step_input_override_requested is None
            else root_step_input_override_requested
        ),
        root_step_input_override=root_step_input_override,
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
    invalidated_step = FlowRunRerunInvalidatedStep(
        id=uuid4(),
        operation_id=operation.id,
        tenant_id=run.tenant_id,
        flow_id=run.flow_id,
        flow_run_id=run.id,
        step_id=step.step_id,
        step_order=step.step_order,
        invalidation_order=1,
        role=role,
        dependency_sources_json=[],
        prior_step_result_id=uuid4(),
        prior_attempt_id=prior_attempt_id,
        new_attempt_no=None,
        new_attempt_id=None,
        created_at=now,
        updated_at=now,
    )
    return (
        FlowRunActiveRerunOperation(
            operation=operation,
            invalidated_steps=(invalidated_step,),
        ),
        invalidated_step,
    )


@pytest.mark.asyncio
async def test_flow_is_active_delegates_to_flow_repo(user):
    executor, flow_repo, _, _ = _build_executor(user)
    flow_id = uuid4()
    tenant_id = uuid4()
    flow_repo.is_active = AsyncMock(return_value=True)

    active = await executor._flow_is_active(flow_id=flow_id, tenant_id=tenant_id)

    assert active is True
    flow_repo.is_active.assert_awaited_once_with(flow_id=flow_id, tenant_id=tenant_id)


@pytest.mark.asyncio
async def test_start_step_attempt_skips_file_copy_for_root_rerun_file_override(user):
    executor, _, flow_run_repo, _ = _build_executor(user)
    flow_run_rerun_repo = executor.flow_run_rerun_repo
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _step_for_execute_step()
    prior_attempt_id = uuid4()
    active_operation, invalidated_step = _active_rerun_operation(
        user=user,
        run=run,
        step=step,
        role=FlowRunRerunInvalidationRole.ROOT,
        root_step_input_override=RerunStepInputOverride(
            step_id=step.step_id,
            file_ids=(),
        ),
        root_step_input_override_requested=True,
        prior_attempt_id=prior_attempt_id,
    )

    started = await executor._start_step_attempt(
        run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step=step,
        celery_task_id="rerun-root",
        active_rerun_operation=active_operation,
        active_rerun_invalidated_step=invalidated_step,
    )

    assert started.attempt_no == active_operation.operation.root_attempt_no
    flow_run_repo.copy_step_input_files_from_predecessor_attempt.assert_not_awaited()
    flow_run_rerun_repo.link_rerun_invalidated_step_attempt.assert_awaited_once_with(
        operation_id=active_operation.operation.id,
        tenant_id=run.tenant_id,
        step_id=step.step_id,
        new_attempt_no=started.attempt_no,
        new_attempt_id=started.id,
    )
    flow_run_rerun_repo.mark_rerun_operation_running.assert_awaited_once_with(
        operation_id=active_operation.operation.id,
        tenant_id=run.tenant_id,
        root_attempt_id=started.id,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "role",
        "root_step_input_override",
        "root_step_input_override_requested",
        "allocated_attempt_no",
        "expected_mark_running",
    ),
    [
        (FlowRunRerunInvalidationRole.ROOT, None, False, 3, True),
        (
            FlowRunRerunInvalidationRole.DOWNSTREAM,
            "override",
            True,
            4,
            False,
        ),
    ],
)
async def test_start_step_attempt_copies_file_rows_for_rerun_inherited_inputs(
    user,
    role: FlowRunRerunInvalidationRole,
    root_step_input_override: str | None,
    root_step_input_override_requested: bool,
    allocated_attempt_no: int,
    expected_mark_running: bool,
):
    executor, _, flow_run_repo, _ = _build_executor(user)
    flow_run_rerun_repo = executor.flow_run_rerun_repo
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _step_for_execute_step()
    prior_attempt_id = uuid4()
    flow_run_repo.allocate_next_attempt_no = AsyncMock(
        return_value=allocated_attempt_no
    )
    active_operation, invalidated_step = _active_rerun_operation(
        user=user,
        run=run,
        step=step,
        role=role,
        root_step_input_override=(
            RerunStepInputOverride(step_id=step.step_id, file_ids=())
            if root_step_input_override is not None
            else None
        ),
        root_step_input_override_requested=root_step_input_override_requested,
        root_attempt_no=3,
        prior_attempt_id=prior_attempt_id,
    )

    started = await executor._start_step_attempt(
        run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step=step,
        celery_task_id="rerun-inherited",
        active_rerun_operation=active_operation,
        active_rerun_invalidated_step=invalidated_step,
    )

    assert started.attempt_no == allocated_attempt_no
    flow_run_repo.copy_step_input_files_from_predecessor_attempt.assert_awaited_once_with(
        run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=step.step_id,
        step_order=step.step_order,
        predecessor_attempt_id=prior_attempt_id,
        target_attempt_no=started.attempt_no,
    )
    flow_run_rerun_repo.link_rerun_invalidated_step_attempt.assert_awaited_once()
    if expected_mark_running:
        flow_run_rerun_repo.mark_rerun_operation_running.assert_awaited_once()
    else:
        flow_run_rerun_repo.mark_rerun_operation_running.assert_not_awaited()


def test_executor_accepts_grouped_config(user):
    flow_repo = AsyncMock()
    session = AsyncMock()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow_run_review_checkpoint_repo = AsyncMock()
    space_repo = AsyncMock()
    completion_service = AsyncMock()
    file_repo = AsyncMock()
    template_asset_repo = AsyncMock()
    encryption_service = AsyncMock()
    config = FlowRunExecutorConfig(
        max_inline_text_bytes=2048,
        max_audio_files=7,
        max_generic_files=3,
        http_request_timeout_seconds=11.0,
        http_max_timeout_seconds=22.0,
        http_allow_private_networks=True,
        rag_retrieval_timeout_seconds=44.0,
        rag_max_reference_sources=12,
        rag_max_chunks_per_source=6,
        document_render_limits=DocumentRenderLimits(max_source_chars=123),
        runtime_policy=FlowRuntimePolicy(
            default_step_timeout_seconds=70,
            max_step_timeout_seconds=100,
            hard_ceiling_seconds=100,
        ),
    )

    executor = FlowRunExecutor(
        runtime_actor=FlowRunActor.from_user(user=user),
        session=session,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_run_review_checkpoint_repo=flow_run_review_checkpoint_repo,
        flow_version_repo=flow_version_repo,
        space_repo=space_repo,
        completion_service=completion_service,
        file_repo=file_repo,
        template_asset_repo=template_asset_repo,
        encryption_service=encryption_service,
        flow_run_terminalizer=AsyncMock(),
        config=config,
    )

    assert executor.max_inline_text_bytes == 2048
    assert executor.max_audio_files == 7
    assert executor.max_generic_files == 3
    assert executor.http_request_timeout_seconds == 11.0
    assert executor.http_max_timeout_seconds == 22.0
    assert executor.http_allow_private_networks is True
    assert executor.rag_retrieval_timeout_seconds == 44.0
    assert executor.rag_max_reference_sources == 12
    assert executor.rag_max_chunks_per_source == 6
    assert executor.document_render_service.limits.max_source_chars == 123
    assert (
        executor._step_deadline_seconds(
            RuntimeStep(
                step_id=uuid4(),
                step_order=1,
                assistant_id=uuid4(),
                user_description=None,
                input_source="flow_input",
                input_bindings=None,
                input_config=None,
                output_mode="pass_through",
                output_config=None,
            )
        )
        == 70.0
    )


def _assistant_for_execute_step(*, has_knowledge: bool):
    model_kwargs = MagicMock()
    model_kwargs.model_dump.return_value = {}
    assistant = MagicMock()
    assistant.has_knowledge.return_value = has_knowledge
    assistant.collections = [MagicMock()] if has_knowledge else []
    assistant.websites = []
    assistant.integration_knowledge_list = []
    assistant.get_prompt_text.return_value = ""
    assistant.completion_model_kwargs = model_kwargs
    assistant.completion_model = SimpleNamespace(
        id=uuid4(), name="gpt-4o-mini", provider_type="openai"
    )
    assistant.get_response = AsyncMock(
        return_value=SimpleNamespace(
            completion="answer",
            total_token_count=42,
        )
    )
    return assistant


def _attempt_start_provenance() -> AttemptStartProvenance:
    return AttemptStartProvenance(
        requested_model="openai/gpt-5.4-nano",
        provider="openai",
        deadline_at=datetime.now(timezone.utc),
        resolved_timeout_seconds=1200,
        effective_prompt_length=42,
        input_text_length=12,
        input_tokens_estimate=3,
        model_parameter_snapshot=ModelParameterSnapshot(reasoning_effort="high"),
    )


@pytest.mark.asyncio
async def test_webhook_enqueue_keeps_completed_step_evidence(user):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    async def _get_run(*args, **kwargs):
        if flow_run_repo.get.await_count == 1:
            return queued_run
        return running_run

    flow_run_repo.get = AsyncMock(side_effect=_get_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "http_post",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        return_value=_webhook_step_result(
            StepExecutionOutput(
                input_text="hello",
                source_text="hello",
                input_source="flow_input",
                used_question_binding=False,
                full_text="result",
                persisted_text="result",
                generated_file_ids=[],
                tool_calls_metadata=None,
                num_tokens_input=10,
                num_tokens_output=11,
                effective_prompt="prompt",
                model_parameters_json={"temperature": 0.2},
                contract_validation={
                    "schema_type_hint": "object",
                    "parse_attempted": True,
                    "parse_succeeded": True,
                    "candidate_type": "dict",
                },
                transcription_metadata={
                    "model": "kb-whisper-large",
                    "language": "sv",
                    "files_count": 1,
                    "elapsed_ms": 1200,
                },
            ),
            run_id=queued_run.id,
            step_id=step_id,
        )
    )
    executor.webhook_delivery_repo.insert_pending_delivery = AsyncMock(
        return_value=uuid4()
    )

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "running"}
    assert flow_repo.save_step_result.await_count == 1
    saved = flow_repo.save_step_result.await_args_list[0].args[1]
    assert saved.status == FlowStepResultStatus.COMPLETED
    assert saved.input_payload_json == {
        "text": "hello",
        "source_text": "hello",
        "input_source": "flow_input",
        "used_question_binding": False,
        "transcription": {
            "model": "kb-whisper-large",
            "language": "sv",
            "files_count": 1,
            "elapsed_ms": 1200,
        },
        "contract_validation": {
            "schema_type_hint": "object",
            "parse_attempted": True,
            "parse_succeeded": True,
            "candidate_type": "dict",
        },
    }
    executor.webhook_delivery_repo.insert_pending_delivery.assert_awaited_once()
    executor.flow_run_terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_webhook_step_enqueues_delivery_and_leaves_run_running(user):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    lifecycle_events: list[str] = []
    create_attempt = flow_run_repo.create_or_get_attempt_started.side_effect

    async def _create_attempt_in_order(**kwargs):
        lifecycle_events.append("attempt_started")
        return await create_attempt(**kwargs)

    async def _save_step_result_in_order(*args, **kwargs):
        lifecycle_events.append("step_result_saved")
        return args[1]

    async def _finish_attempt_in_order(**kwargs):
        lifecycle_events.append("attempt_finished")

    async def _insert_delivery_in_order(**kwargs):
        lifecycle_events.append("delivery_inserted")
        return uuid4()

    flow_run_repo.create_or_get_attempt_started = AsyncMock(
        side_effect=_create_attempt_in_order
    )
    flow_repo.save_step_result = AsyncMock(side_effect=_save_step_result_in_order)
    flow_run_repo.finish_attempt = AsyncMock(side_effect=_finish_attempt_in_order)
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "http_post",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        return_value=_webhook_step_result(
            StepExecutionOutput(
                input_text="hello",
                source_text="hello",
                input_source="flow_input",
                used_question_binding=False,
                full_text="result",
                persisted_text="result",
                generated_file_ids=[],
                tool_calls_metadata=None,
                num_tokens_input=10,
                num_tokens_output=11,
                effective_prompt="prompt",
                model_parameters_json={"temperature": 0.2},
            ),
            run_id=queued_run.id,
            step_id=step_id,
        )
    )
    executor.webhook_delivery_repo.insert_pending_delivery = AsyncMock(
        side_effect=_insert_delivery_in_order
    )

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "running"}
    assert flow_repo.save_step_result.await_count == 1
    saved = flow_repo.save_step_result.await_args_list[0].args[1]
    assert saved.status == FlowStepResultStatus.COMPLETED
    assert saved.output_payload_json["webhook_delivered"] is False
    call_kwargs = (
        executor.webhook_delivery_repo.insert_pending_delivery.await_args.kwargs
    )
    assert call_kwargs["flow_id"] == queued_run.flow_id
    assert call_kwargs["tenant_id"] == user.tenant_id
    assert call_kwargs["intent"].flow_run_id == queued_run.id
    assert call_kwargs["intent"].step_id == step_id
    assert lifecycle_events == [
        "attempt_started",
        "step_result_saved",
        "attempt_finished",
        "delivery_inserted",
    ]
    executor.flow_run_terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_persists_distinct_model_parameters_for_each_step(user):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    first_step_id = uuid4()
    second_step_id = uuid4()
    first_assistant_id = uuid4()
    second_assistant_id = uuid4()
    first_claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=first_step_id,
        assistant_id=first_assistant_id,
    )
    second_claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=second_step_id,
        assistant_id=second_assistant_id,
    ).model_copy(update={"step_order": 2})

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(
        side_effect=[first_claimed, second_claimed]
    )
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(first_step_id),
                        "step_order": 1,
                        "assistant_id": str(first_assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    },
                    {
                        "step_id": str(second_step_id),
                        "step_order": 2,
                        "assistant_id": str(second_assistant_id),
                        "input_source": "previous_step",
                        "output_mode": "pass_through",
                    },
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        side_effect=[
            _step_result(
                StepExecutionOutput(
                    input_text="hello",
                    source_text="hello",
                    input_source="flow_input",
                    used_question_binding=False,
                    full_text="step-one",
                    persisted_text="step-one",
                    generated_file_ids=[],
                    tool_calls_metadata=None,
                    num_tokens_input=10,
                    num_tokens_output=11,
                    effective_prompt="prompt-one",
                    model_parameters_json={
                        "model_id": str(uuid4()),
                        "model_name": "claude-haiku-4-5",
                        "provider": "anthropic",
                    },
                )
            ),
            _step_result(
                StepExecutionOutput(
                    input_text="step-one",
                    source_text="step-one",
                    input_source="previous_step",
                    used_question_binding=False,
                    full_text="step-two",
                    persisted_text="step-two",
                    generated_file_ids=[],
                    tool_calls_metadata=None,
                    num_tokens_input=12,
                    num_tokens_output=13,
                    effective_prompt="prompt-two",
                    model_parameters_json={
                        "model_id": str(uuid4()),
                        "model_name": "gpt-4o-mini",
                        "provider": "openai",
                    },
                )
            ),
        ]
    )

    async def _list_step_results(*args, **kwargs):
        return [call.args[1] for call in flow_repo.save_step_result.await_args_list]

    flow_run_repo.list_step_results = AsyncMock(side_effect=_list_step_results)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "completed"}
    assert flow_repo.save_step_result.await_count == 2
    first_saved = flow_repo.save_step_result.await_args_list[0].args[1]
    second_saved = flow_repo.save_step_result.await_args_list[1].args[1]
    assert first_saved.model_parameters_json == {
        "model_id": first_saved.model_parameters_json["model_id"],
        "model_name": "claude-haiku-4-5",
        "provider": "anthropic",
    }
    assert second_saved.model_parameters_json == {
        "model_id": second_saved.model_parameters_json["model_id"],
        "model_name": "gpt-4o-mini",
        "provider": "openai",
    }


@pytest.mark.asyncio
async def test_duplicate_worker_exits_when_step_already_claimed(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    running_step = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=None)
    flow_run_repo.get_step_result = AsyncMock(return_value=running_step)
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "skipped", "reason": "step_already_claimed"}


@pytest.mark.asyncio
async def test_execute_skips_when_run_claim_fails(user):
    executor, _, flow_run_repo, _ = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=False)
    executor._execute_step = AsyncMock()

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "skipped", "reason": "run_running"}
    executor._execute_step.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_short_circuits_terminal_run_without_lifecycle_writes(user):
    executor, _, flow_run_repo, _ = _build_executor(user)
    completed_run = _run(status=FlowRunStatus.COMPLETED, user=user)

    flow_run_repo.get = AsyncMock(return_value=completed_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock()
    flow_run_repo.claim_step_result = AsyncMock()

    result = await executor.execute(
        run_id=completed_run.id,
        flow_id=completed_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "skipped", "reason": "run_terminal"}
    flow_run_repo.mark_running_if_claimable.assert_not_awaited()
    flow_run_repo.claim_step_result.assert_not_awaited()
    executor.flow_run_terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_cancels_when_flow_deleted_before_step_execution(user):
    executor, _, flow_run_repo, _ = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)

    flow_run_repo.get = AsyncMock(return_value=queued_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    executor._flow_is_active = AsyncMock(return_value=False)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "cancelled", "reason": "flow_deleted"}
    executor.flow_run_terminalizer.terminalize_run.assert_awaited_once()
    assert (
        executor.flow_run_terminalizer.terminalize_run.await_args.kwargs["source"]
        == FlowRunLifecycleSource.FLOW_DELETED
    )


@pytest.mark.asyncio
async def test_step_execution_failure_marks_attempt_and_run_failed(user):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(side_effect=RuntimeError("llm boom"))

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result["status"] == "failed"
    assert result["error"] == FlowApiErrorCode.STEP_EXECUTION_FAILED.value
    flow_run_repo.finish_attempt.assert_awaited_once()
    finish_kwargs = flow_run_repo.finish_attempt.await_args.kwargs
    assert finish_kwargs["status"] == FlowStepAttemptStatus.FAILED
    assert finish_kwargs["error_code"] == FlowApiErrorCode.STEP_EXECUTION_FAILED.value
    assert finish_kwargs["error_message"] == "Flow step 1 execution failed."
    executor.flow_run_terminalizer.terminalize_run.assert_awaited_once()
    update_kwargs = executor.flow_run_terminalizer.terminalize_run.await_args.kwargs
    assert update_kwargs["error"].message == "Flow step 1 execution failed."
    saved_result = flow_repo.save_step_result.await_args.args[1]
    assert saved_result.status == FlowStepResultStatus.FAILED
    assert saved_result.error_message == "Flow step 1 execution failed."


@pytest.mark.asyncio
async def test_attempt_start_failure_after_claim_marks_run_and_step_failed(user):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.create_or_get_attempt_started = AsyncMock(
        side_effect=RuntimeError("db write failed")
    )
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {
        "status": "failed",
        "error": FlowApiErrorCode.STEP_EXECUTION_FAILED.value,
    }
    flow_run_repo.finish_attempt.assert_not_awaited()
    saved_result = flow_repo.save_step_result.await_args.args[1]
    assert saved_result.status == FlowStepResultStatus.FAILED
    assert saved_result.error_message == "Flow step 1 execution failed."
    assert (
        executor.flow_run_terminalizer.terminalize_run.await_args.kwargs[
            "target_status"
        ]
        == FlowRunStatus.FAILED
    )


@pytest.mark.asyncio
async def test_execute_terminalizes_multiple_active_rerun_operations(
    user,
    caplog,
):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    flow_run_rerun_repo = executor.flow_run_rerun_repo
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    failed_run = queued_run.model_copy(
        update={
            "status": FlowRunStatus.FAILED,
            "error": FlowRunError.from_source(
                FlowRunLifecycleSource.EXECUTOR_FAILED,
                code=FlowApiErrorCode.RUN_RERUN_MULTIPLE_ACTIVE_OPERATIONS_INVARIANT,
                message="Rerun failed because multiple active rerun operations exist.",
            ),
        }
    )
    step_id = uuid4()
    assistant_id = uuid4()

    flow_run_repo.get = _run_get_mock(queued_run, failed_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.list_step_results = AsyncMock(return_value=[])
    flow_run_rerun_repo.get_active_rerun_operation = AsyncMock(
        side_effect=FlowRunRerunMultipleActiveOperationsError(flow_run_id=queued_run.id)
    )
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    with caplog.at_level(logging.CRITICAL, logger="intric.flows.runtime.executor"):
        result = await executor.execute(
            run_id=queued_run.id,
            flow_id=queued_run.flow_id,
            tenant_id=user.tenant_id,
            celery_task_id="task-1",
            retry_count=0,
        )

    assert result == {
        "status": "failed",
        "error": "Rerun failed because multiple active rerun operations exist.",
    }
    flow_repo.save_step_result.assert_not_awaited()
    flow_run_repo.claim_step_result.assert_not_awaited()
    executor.session.rollback.assert_awaited_once()
    terminalize_kwargs = (
        executor.flow_run_terminalizer.terminalize_run.await_args.kwargs
    )
    assert terminalize_kwargs["target_status"] == FlowRunStatus.FAILED
    run_error = terminalize_kwargs["error"]
    assert run_error.code == "flow_run_rerun_multiple_active_operations_invariant"
    assert (
        run_error.message
        == "Rerun failed because multiple active rerun operations exist."
    )
    assert "flow_executor.rerun_multiple_active_operations_terminalized_failed" in (
        caplog.text
    )


@pytest.mark.asyncio
async def test_rerun_lineage_conflict_uses_specific_run_error_after_claim(user):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    flow_run_rerun_repo = executor.flow_run_rerun_repo
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step = _runtime_step(step_order=1, input_source="flow_input")
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step.step_id,
        assistant_id=step.assistant_id,
    )
    active_operation, _ = _active_rerun_operation(
        user=user,
        run=queued_run,
        step=step,
        role=FlowRunRerunInvalidationRole.ROOT,
        root_step_input_override=None,
        root_step_input_override_requested=False,
        prior_attempt_id=uuid4(),
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.list_step_results = AsyncMock(return_value=[])
    flow_run_rerun_repo.get_active_rerun_operation = AsyncMock(
        return_value=active_operation
    )
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_rerun_repo.link_rerun_invalidated_step_attempt = AsyncMock(
        side_effect=FlowRunRerunAttemptLineageConflictError(
            operation_id=active_operation.operation.id,
            step_id=step.step_id,
            new_attempt_id=uuid4(),
        )
    )
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step.step_id),
                        "step_order": step.step_order,
                        "assistant_id": str(step.assistant_id),
                        "input_source": step.input_source,
                        "output_mode": step.output_mode,
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {
        "status": "failed",
        "error": FlowApiErrorCode.STEP_EXECUTION_FAILED.value,
    }
    flow_run_repo.finish_attempt.assert_not_awaited()
    flow_run_rerun_repo.mark_rerun_operation_running.assert_not_awaited()
    saved_result = flow_repo.save_step_result.await_args.args[1]
    assert saved_result.status == FlowStepResultStatus.FAILED
    assert saved_result.error_message == "Flow step 1 execution failed."
    terminalize_kwargs = (
        executor.flow_run_terminalizer.terminalize_run.await_args.kwargs
    )
    run_error = terminalize_kwargs["error"]
    assert run_error.code == "flow_run_rerun_attempt_lineage_conflict_invariant"
    assert (
        run_error.message
        == "Rerun failed because the invalidated step is already linked to another attempt."
    )
    assert run_error.step_order == 1


@pytest.mark.asyncio
async def test_typed_validation_failure_persists_input_context_for_export(user):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    typed_exc = TypedIOValidationException(
        "Step 1 input: 'not json' is not of type 'object'",
        code="typed_io_contract_violation",
    )
    typed_exc.input_payload_json = {
        "text": "not json",
        "source_text": "not json",
        "input_source": "flow_input",
        "contract_validation": {
            "schema_type_hint": "object",
            "parse_attempted": True,
            "parse_succeeded": False,
            "candidate_type": "str",
        },
    }
    typed_exc.effective_prompt = "Categorize this"
    executor._execute_step = AsyncMock(side_effect=typed_exc)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result["status"] == "failed"
    finish_kwargs = flow_run_repo.finish_attempt.await_args.kwargs
    assert finish_kwargs["status"] == FlowStepAttemptStatus.FAILED
    assert finish_kwargs["error_code"] == "typed_io_contract_violation"
    saved_result = flow_repo.save_step_result.await_args.args[1]
    assert saved_result.status == FlowStepResultStatus.FAILED
    assert saved_result.input_payload_json == typed_exc.input_payload_json
    assert saved_result.effective_prompt == "Categorize this"


@pytest.mark.asyncio
async def test_typed_validation_failure_persists_model_telemetry(user):
    """flow_step_attempts must record requested_model/provider on typed failure.

    The flow_llm_request_timeout path (per-step LLM timeout) raises a typed
    exception. Without telemetry plumbed through finish_attempt, the
    persisted row shows requested_model=null/provider=null — making it
    impossible to triage which model wedged the run after the fact.
    """
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    typed_exc = TypedIOValidationException(
        "Step 1: LLM request exceeded 600s timeout.",
        code="flow_llm_request_timeout",
    )
    setattr(typed_exc, "requested_model", "openai/gpt-5.4-nano")
    setattr(typed_exc, "provider", "openai")
    executor._execute_step = AsyncMock(side_effect=typed_exc)

    await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    finish_kwargs = flow_run_repo.finish_attempt.await_args.kwargs
    assert finish_kwargs["requested_model"] == "openai/gpt-5.4-nano"
    assert finish_kwargs["provider"] == "openai"


@pytest.mark.asyncio
async def test_typed_validation_failure_partial_typed_exc_falls_back_field_independently(
    user,
):
    """Each telemetry field falls back from state independently.

    `_handle_typed_step_failure` reads `requested_model` and `provider`
    from the typed exception's attached attributes and falls back to
    `state.assistant_cache` for the assistant we just tried. The
    fallback must apply per-field — if only `provider` is attached
    (e.g. the timeout fired before the LLM client returned a model
    name), the persisted attempt row must still get `requested_model`
    from the assistant cache rather than null.
    """
    executor, flow_repo, flow_run_repo, _ = _build_executor(user)
    flow_run_repo.finish_attempt = AsyncMock()
    flow_repo.save_step_result = AsyncMock()
    executor._terminalize_run = AsyncMock()
    executor._rollback = AsyncMock()

    step_id = uuid4()
    assistant_id = uuid4()
    run_id = uuid4()
    flow_id = uuid4()
    claimed = _claimed_step_result(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )
    step = RuntimeStep(
        step_id=step_id,
        step_order=1,
        assistant_id=assistant_id,
        user_description=None,
        input_source="flow_input",
        input_bindings=None,
        input_config=None,
        output_mode="pass_through",
        output_config=None,
        output_type="text",
    )

    state = _empty_execution_state()
    state.assistant_cache[assistant_id] = SimpleNamespace(
        completion_model=SimpleNamespace(
            litellm_model_name="openai/gpt-5.4-nano",
            name="gpt-5.4-nano",
            provider_type="openai",
        )
    )

    typed_exc = TypedIOValidationException(
        "Step 1: LLM request exceeded 600s timeout.",
        code="flow_llm_request_timeout",
    )
    setattr(typed_exc, "provider", "openai")

    await executor._handle_typed_step_failure(
        run_id=run_id,
        tenant_id=user.tenant_id,
        step=step,
        attempt_no=1,
        claimed=claimed,
        typed_exc=typed_exc,
        failed_input_payload=None,
        state=state,
    )

    finish_kwargs = flow_run_repo.finish_attempt.await_args.kwargs
    assert finish_kwargs["requested_model"] == "openai/gpt-5.4-nano", (
        "requested_model was None on typed_exc, so must fall back to "
        "state.assistant_cache. Without per-field fallback the column "
        "stays null and triage of stuck runs becomes impossible."
    )
    assert finish_kwargs["provider"] == "openai"


@pytest.mark.asyncio
async def test_typed_validation_failure_terminalizes_with_bounded_public_error(user):
    executor, flow_repo, flow_run_repo, _ = _build_executor(user)
    flow_run_repo.finish_attempt = AsyncMock()
    flow_repo.save_step_result = AsyncMock()
    executor._terminalize_run = AsyncMock()
    executor._rollback = AsyncMock()

    step = _step_for_execute_step(step_order=3)
    run_id = uuid4()
    flow_id = uuid4()
    claimed = _claimed_step_result(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=user.tenant_id,
        step_id=step.step_id,
        assistant_id=step.assistant_id,
    )
    raw_source_excerpt = "SECRET_SOURCE_MATERIAL"
    typed_exc = TypedIOValidationException(
        "Step 3 input: "
        + raw_source_excerpt
        + (" x" * 5000)
        + " is not of type 'object'",
        code="typed_io_contract_violation",
    )

    await executor._handle_typed_step_failure(
        run_id=run_id,
        tenant_id=user.tenant_id,
        step=step,
        attempt_no=1,
        claimed=claimed,
        typed_exc=typed_exc,
        failed_input_payload={"text": raw_source_excerpt},
        state=_empty_execution_state(),
    )

    executor._terminalize_run.assert_awaited_once()
    terminal_error = executor._terminalize_run.await_args.kwargs["error"]
    assert isinstance(terminal_error, FlowRunError)
    assert terminal_error.code == "typed_io_contract_violation"
    assert terminal_error.step_order == 3
    assert len(terminal_error.message) <= 4096
    assert raw_source_excerpt not in terminal_error.message
    assert "flow_task_failure" not in terminal_error.message


@pytest.mark.asyncio
async def test_typed_validation_failure_unknown_code_uses_cataloged_fallback(user):
    executor, flow_repo, flow_run_repo, _ = _build_executor(user)
    flow_run_repo.finish_attempt = AsyncMock()
    flow_repo.save_step_result = AsyncMock()
    executor._terminalize_run = AsyncMock()
    executor._rollback = AsyncMock()

    step = _step_for_execute_step(step_order=2)
    run_id = uuid4()
    flow_id = uuid4()
    claimed = _claimed_step_result(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=user.tenant_id,
        step_id=step.step_id,
        assistant_id=step.assistant_id,
    )
    typed_exc = TypedIOValidationException(
        "Step 2 failed with an uncataloged typed IO code.",
        code="typed_io_private_unregistered",
    )

    await executor._handle_typed_step_failure(
        run_id=run_id,
        tenant_id=user.tenant_id,
        step=step,
        attempt_no=1,
        claimed=claimed,
        typed_exc=typed_exc,
        failed_input_payload=None,
        state=_empty_execution_state(),
    )

    fallback_code = FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED.value
    finish_kwargs = flow_run_repo.finish_attempt.await_args.kwargs
    assert finish_kwargs["error_code"] == fallback_code
    saved_result = flow_repo.save_step_result.await_args.args[1]
    assert saved_result.error_code == fallback_code
    terminal_error = executor._terminalize_run.await_args.kwargs["error"]
    assert terminal_error.code == fallback_code


@pytest.mark.asyncio
async def test_cancelled_step_retains_attempt_start_provenance(user):
    executor, _, flow_run_repo, _ = _build_executor(user)
    flow_run_repo.finish_attempt = AsyncMock()
    executor._rollback = AsyncMock()
    executor._commit = AsyncMock()
    step = _step_for_execute_step()
    state = _empty_execution_state()
    attempt_start = _attempt_start_provenance()
    state.attempt_start_by_step[step.step_id] = attempt_start

    result = await executor._handle_cancelled_step(
        run_id=uuid4(),
        tenant_id=user.tenant_id,
        step=step,
        attempt_no=1,
        state=state,
    )

    assert result == {"status": "skipped", "reason": "run_cancelled"}
    finish_kwargs = flow_run_repo.finish_attempt.await_args.kwargs
    assert finish_kwargs["status"] == FlowStepAttemptStatus.CANCELLED
    assert finish_kwargs["requested_model"] == "openai/gpt-5.4-nano"
    assert finish_kwargs["provider"] == "openai"
    assert (
        finish_kwargs["provenance_json"]["attempt_start"]["requested_model"]
        == "openai/gpt-5.4-nano"
    )
    assert "deadline_at" in finish_kwargs["provenance_json"]["attempt_start"]


@pytest.mark.asyncio
async def test_llm_timeout_failure_retains_attempt_start_provenance(user):
    executor, flow_repo, flow_run_repo, _ = _build_executor(user)
    flow_run_repo.finish_attempt = AsyncMock()
    flow_repo.save_step_result = AsyncMock()
    executor._terminalize_run = AsyncMock()
    executor._rollback = AsyncMock()
    step = _step_for_execute_step()
    state = _empty_execution_state()
    attempt_start = _attempt_start_provenance()
    state.attempt_start_by_step[step.step_id] = attempt_start
    claimed = _claimed_step_result(
        run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=user.tenant_id,
        step_id=step.step_id,
        assistant_id=step.assistant_id,
    )
    typed_exc = TypedIOValidationException(
        "Step 1: LLM request exceeded 1200s timeout.",
        code="flow_llm_request_timeout",
    )

    await executor._handle_typed_step_failure(
        run_id=claimed.flow_run_id,
        tenant_id=user.tenant_id,
        step=step,
        attempt_no=1,
        claimed=claimed,
        typed_exc=typed_exc,
        failed_input_payload=None,
        state=state,
    )

    finish_kwargs = flow_run_repo.finish_attempt.await_args.kwargs
    assert finish_kwargs["error_code"] == "flow_llm_request_timeout"
    assert finish_kwargs["requested_model"] == "openai/gpt-5.4-nano"
    assert finish_kwargs["provider"] == "openai"
    persisted_attempt_start = finish_kwargs["provenance_json"]["attempt_start"]
    assert persisted_attempt_start["resolved_timeout_seconds"] == 1200
    assert (
        persisted_attempt_start["deadline_at"]
        == attempt_start.model_dump(mode="json")["deadline_at"]
    )


@pytest.mark.asyncio
async def test_typed_validation_failure_without_attached_context_uses_fallback_payload(
    user,
):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        side_effect=TypedIOValidationException(
            "Step 1 output: expected object",
            code="typed_io_contract_violation",
        )
    )

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result["status"] == "failed"
    finish_kwargs = flow_run_repo.finish_attempt.await_args.kwargs
    assert finish_kwargs["status"] == FlowStepAttemptStatus.FAILED
    assert finish_kwargs["error_code"] == "typed_io_contract_violation"
    saved_result = flow_repo.save_step_result.await_args.args[1]
    assert saved_result.status == FlowStepResultStatus.FAILED
    assert saved_result.input_payload_json == {
        "text": "",
        "source_text": "",
        "input_source": "flow_input",
        "used_question_binding": False,
    }


@pytest.mark.asyncio
async def test_apply_output_cap_persists_file_when_over_limit(user):
    executor, _, _, _ = _build_executor(user)
    executor.max_inline_text_bytes = 5
    file_id = uuid4()
    executor.file_repo.add = AsyncMock(return_value=SimpleNamespace(id=file_id))
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = SimpleNamespace(step_order=1)
    long_text = "abcdefghi"

    persisted_text, file_ids = await executor._apply_output_cap(
        text=long_text,
        run=run,
        step=step,
    )

    assert persisted_text == long_text[:4096]
    assert file_ids == [file_id]
    executor.file_repo.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_output_cap_handles_utf8_byte_limit(user):
    executor, _, _, _ = _build_executor(user)
    executor.max_inline_text_bytes = 5
    file_id = uuid4()
    executor.file_repo.add = AsyncMock(return_value=SimpleNamespace(id=file_id))
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = SimpleNamespace(step_order=1)
    utf8_text = "ååå"  # 6 bytes in UTF-8, exceeds 5-byte cap.

    persisted_text, file_ids = await executor._apply_output_cap(
        text=utf8_text,
        run=run,
        step=step,
    )

    assert persisted_text == utf8_text[:4096]
    assert file_ids == [file_id]
    create_arg = executor.file_repo.add.await_args.args[0]
    assert create_arg.owner_type == PrincipalType.USER
    assert create_arg.owner_user_id == user.id


@pytest.mark.asyncio
async def test_execute_marks_run_completed_with_last_completed_output_payload(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    existing = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    ).model_copy(
        update={
            "status": FlowStepResultStatus.COMPLETED,
            "output_payload_json": {"text": "final"},
        },
        deep=True,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=None)
    flow_run_repo.get_step_result = AsyncMock(return_value=existing)
    flow_run_repo.list_step_results = AsyncMock(return_value=[existing])
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "completed"}
    executor.flow_run_terminalizer.terminalize_run.assert_awaited_once()
    kwargs = executor.flow_run_terminalizer.terminalize_run.await_args.kwargs
    assert kwargs["target_status"] == FlowRunStatus.COMPLETED
    assert kwargs["output_payload_json"] == {"text": "final"}


@pytest.mark.asyncio
async def test_execute_returns_cancelled_when_any_step_result_cancelled(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    existing = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    ).model_copy(
        update={"status": FlowStepResultStatus.COMPLETED},
        deep=True,
    )
    cancelled_result = existing.model_copy(
        update={
            "status": FlowStepResultStatus.CANCELLED,
            "error_message": "cancelled by policy",
        },
        deep=True,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=None)
    flow_run_repo.get_step_result = AsyncMock(return_value=existing)
    flow_run_repo.list_step_results = AsyncMock(return_value=[cancelled_result])
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "cancelled"}
    executor.flow_run_terminalizer.terminalize_run.assert_awaited_once()
    assert (
        executor.flow_run_terminalizer.terminalize_run.await_args.kwargs[
            "target_status"
        ]
        == FlowRunStatus.CANCELLED
    )


@pytest.mark.asyncio
async def test_execute_returns_run_in_progress_when_pending_results_exist(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    existing = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    ).model_copy(
        update={"status": FlowStepResultStatus.COMPLETED},
        deep=True,
    )
    pending_result = existing.model_copy(
        update={"status": FlowStepResultStatus.PENDING},
        deep=True,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=None)
    flow_run_repo.get_step_result = AsyncMock(return_value=existing)
    flow_run_repo.list_step_results = AsyncMock(return_value=[pending_result])
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "skipped", "reason": "run_in_progress"}
    executor.flow_run_terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_uses_persisted_next_attempt_no_for_attempt_lifecycle(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )
    completed = claimed.model_copy(
        update={
            "status": FlowStepResultStatus.COMPLETED,
            "output_payload_json": {"text": "done"},
        },
        deep=True,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.allocate_next_attempt_no = AsyncMock(return_value=7)
    flow_run_repo.finish_attempt = AsyncMock()
    flow_run_repo.list_step_results = AsyncMock(side_effect=[[], [completed]])
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        return_value=_step_result(
            StepExecutionOutput(
                input_text="hello",
                source_text="hello",
                input_source="flow_input",
                used_question_binding=False,
                full_text="done",
                persisted_text="done",
                generated_file_ids=[],
                tool_calls_metadata=None,
                num_tokens_input=10,
                num_tokens_output=10,
                effective_prompt="prompt",
                model_parameters_json={},
            )
        )
    )

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=2,
    )

    assert result == {"status": "completed"}
    assert (
        flow_run_repo.create_or_get_attempt_started.await_args.kwargs["attempt_no"] == 7
    )
    assert flow_run_repo.finish_attempt.await_args.kwargs["attempt_no"] == 7


@pytest.mark.asyncio
async def test_execute_stops_before_claiming_later_steps_when_run_becomes_cancelled(
    user,
):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    cancelled_run = queued_run.model_copy(update={"status": FlowRunStatus.CANCELLED})
    step_id_1 = uuid4()
    step_id_2 = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id_1,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, cancelled_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id_1),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    },
                    {
                        "step_id": str(step_id_2),
                        "step_order": 2,
                        "assistant_id": str(assistant_id),
                        "input_source": "previous_step",
                        "output_mode": "pass_through",
                    },
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        return_value=_step_result(
            StepExecutionOutput(
                input_text="hello",
                source_text="hello",
                input_source="flow_input",
                used_question_binding=False,
                full_text="step-one",
                persisted_text="step-one",
                generated_file_ids=[],
                tool_calls_metadata=None,
                num_tokens_input=10,
                num_tokens_output=10,
                effective_prompt="prompt",
                model_parameters_json={},
            )
        )
    )

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "skipped", "reason": "run_cancelled"}
    assert flow_run_repo.claim_step_result.await_count == 1
    assert flow_run_repo.create_or_get_attempt_started.await_count == 1


@pytest.mark.asyncio
async def test_execute_does_not_persist_step_after_run_cancelled_during_execution(user):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    cancelled_run = queued_run.model_copy(update={"status": FlowRunStatus.CANCELLED})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = AsyncMock(
        side_effect=[queued_run, running_run, cancelled_run, cancelled_run]
    )
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.finish_attempt = AsyncMock()
    flow_repo.save_step_result = AsyncMock(return_value=None)
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        return_value=_step_result(
            StepExecutionOutput(
                input_text="hello",
                source_text="hello",
                input_source="flow_input",
                used_question_binding=False,
                full_text="result",
                persisted_text="result",
                generated_file_ids=[],
                tool_calls_metadata=None,
                num_tokens_input=10,
                num_tokens_output=10,
                effective_prompt="prompt",
                model_parameters_json={},
            )
        )
    )

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "skipped", "reason": "run_cancelled"}
    flow_repo.save_step_result.assert_awaited_once()
    flow_run_repo.finish_attempt.assert_not_awaited()
    executor.flow_run_terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_returns_terminal_outcome_when_review_open_loses_run_race(
    user,
    caplog,
):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    failed_run = queued_run.model_copy(
        update={
            "status": FlowRunStatus.FAILED,
            "error": FlowRunError.from_source(
                FlowRunLifecycleSource.EXECUTOR_FAILED,
                code=FlowApiErrorCode.RUN_TASK_FAILURE,
                message="Run was terminalized as failed.",
            ),
        }
    )
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )
    completed = claimed.model_copy(
        update={
            "status": FlowStepResultStatus.COMPLETED,
            "output_payload_json": {"text": "done"},
        },
        deep=True,
    )

    flow_run_repo.get = AsyncMock(
        side_effect=[queued_run, running_run, running_run, failed_run]
    )
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.finish_attempt = AsyncMock()
    executor.flow_run_review_checkpoint_repo.open_review_checkpoint_for_completed_step = AsyncMock(
        side_effect=FlowReviewCheckpointRunNotRunningError(
            status=FlowRunStatus.FAILED.value
        )
    )
    flow_repo.save_step_result = AsyncMock(return_value=completed)
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                        "review_policy": {"mode": "view"},
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        return_value=_step_result(
            StepExecutionOutput(
                input_text="hello",
                source_text="hello",
                input_source="flow_input",
                used_question_binding=False,
                full_text="done",
                persisted_text="done",
                generated_file_ids=[],
                tool_calls_metadata=None,
                num_tokens_input=10,
                num_tokens_output=10,
                effective_prompt="prompt",
                model_parameters_json={},
            )
        )
    )

    with caplog.at_level(logging.INFO, logger="intric.flows.runtime.executor"):
        result = await executor.execute(
            run_id=queued_run.id,
            flow_id=queued_run.flow_id,
            tenant_id=user.tenant_id,
            celery_task_id="task-1",
            retry_count=0,
        )

    assert result == {"status": "failed", "error": "Run was terminalized as failed."}
    executor.flow_run_review_checkpoint_repo.open_review_checkpoint_for_completed_step.assert_awaited_once()
    executor.session.rollback.assert_awaited_once()
    assert "flow_executor.review_open_skipped_run_terminal" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("review_open_error", "expected_code", "expected_message"),
    [
        (
            FlowReviewOpenBlockedByActiveCheckpointError(active_checkpoint_id=uuid4()),
            FlowApiErrorCode.REVIEW_OPEN_ACTIVE_CONFLICT_INVARIANT,
            "Review checkpoint opening failed because another checkpoint is active.",
        ),
        (
            FlowReviewCheckpointStepResultIncompleteError(
                step_id=uuid4(), attempt_no=1
            ),
            FlowApiErrorCode.REVIEW_OPEN_STEP_RESULT_INCOMPLETE_INVARIANT,
            "Review checkpoint opening failed because the completed step result was unavailable.",
        ),
        (
            FlowReviewMultipleActiveCheckpointsError(),
            FlowApiErrorCode.REVIEW_OPEN_MULTIPLE_ACTIVE_CHECKPOINTS_INVARIANT,
            "Review checkpoint opening failed because multiple checkpoints are active.",
        ),
    ],
)
async def test_execute_terminalizes_review_open_invariant_errors(
    user,
    caplog,
    review_open_error,
    expected_code,
    expected_message,
):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    failed_run = queued_run.model_copy(
        update={
            "status": FlowRunStatus.FAILED,
            "error": FlowRunError.from_source(
                FlowRunLifecycleSource.EXECUTOR_FAILED,
                code=expected_code,
                message=expected_message,
                step_id=step_id,
                step_order=1,
            ),
        }
    )
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )
    completed = claimed.model_copy(
        update={
            "status": FlowStepResultStatus.COMPLETED,
            "output_payload_json": {"text": "done"},
        },
        deep=True,
    )
    flow_run_repo.get = AsyncMock(
        side_effect=[queued_run, running_run, running_run, failed_run]
    )
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.finish_attempt = AsyncMock()
    executor._terminalize_run = AsyncMock()
    executor.flow_run_review_checkpoint_repo.open_review_checkpoint_for_completed_step = AsyncMock(
        side_effect=review_open_error
    )
    flow_repo.save_step_result = AsyncMock(return_value=completed)
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                        "review_policy": {"mode": "view"},
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        return_value=_step_result(
            StepExecutionOutput(
                input_text="hello",
                source_text="hello",
                input_source="flow_input",
                used_question_binding=False,
                full_text="done",
                persisted_text="done",
                generated_file_ids=[],
                tool_calls_metadata=None,
                num_tokens_input=10,
                num_tokens_output=10,
                effective_prompt="prompt",
                model_parameters_json={},
            )
        )
    )

    with caplog.at_level(logging.INFO, logger="intric.flows.runtime.executor"):
        result = await executor.execute(
            run_id=queued_run.id,
            flow_id=queued_run.flow_id,
            tenant_id=user.tenant_id,
            celery_task_id="task-1",
            retry_count=0,
        )

    assert result == {"status": "failed", "error": expected_message}
    executor.flow_run_review_checkpoint_repo.open_review_checkpoint_for_completed_step.assert_awaited_once()
    executor.session.rollback.assert_awaited_once()
    executor._terminalize_run.assert_awaited_once()
    terminalize_kwargs = executor._terminalize_run.await_args.kwargs
    assert terminalize_kwargs["target_status"] == FlowRunStatus.FAILED
    assert terminalize_kwargs["source"] == FlowRunLifecycleSource.EXECUTOR_FAILED
    terminal_error = terminalize_kwargs["error"]
    assert isinstance(terminal_error, FlowRunError)
    assert terminal_error.code == expected_code
    assert terminal_error.message == expected_message
    assert terminal_error.step_id == step_id
    assert terminal_error.step_order == 1
    if isinstance(review_open_error, FlowReviewMultipleActiveCheckpointsError):
        assert (
            "flow_executor.review_open_multiple_active_terminalized_failed"
            in caplog.text
        )
    else:
        assert "flow_executor.review_open_terminalized_failed" in caplog.text


@pytest.mark.asyncio
async def test_execute_appends_completed_handoff_and_continues_with_next_step(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id_1 = uuid4()
    step_id_2 = uuid4()
    assistant_id = uuid4()
    existing_completed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id_1,
        assistant_id=assistant_id,
    ).model_copy(
        update={
            "status": FlowStepResultStatus.COMPLETED,
            "output_payload_json": {"text": "from-step-1"},
        },
        deep=True,
    )
    claimed_second = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id_2,
        assistant_id=assistant_id,
    )
    completed_second = claimed_second.model_copy(
        update={
            "step_order": 2,
            "status": FlowStepResultStatus.COMPLETED,
            "output_payload_json": {"text": "from-step-2"},
        },
        deep=True,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(side_effect=[None, claimed_second])
    flow_run_repo.get_step_result = AsyncMock(return_value=existing_completed)
    flow_run_repo.finish_attempt = AsyncMock()
    flow_run_repo.list_step_results = AsyncMock(side_effect=[[], [completed_second]])
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id_1),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    },
                    {
                        "step_id": str(step_id_2),
                        "step_order": 2,
                        "assistant_id": str(assistant_id),
                        "input_source": "previous_step",
                        "output_mode": "pass_through",
                    },
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        return_value=_step_result(
            StepExecutionOutput(
                input_text="from-step-1",
                source_text="from-step-1",
                input_source="previous_step",
                used_question_binding=False,
                full_text="from-step-2",
                persisted_text="from-step-2",
                generated_file_ids=[],
                tool_calls_metadata=None,
                num_tokens_input=10,
                num_tokens_output=10,
                effective_prompt="prompt",
                model_parameters_json={},
            )
        )
    )

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "completed"}
    flow_run_repo.create_or_get_attempt_started.assert_awaited_once()
    assert (
        flow_run_repo.create_or_get_attempt_started.await_args.kwargs["step_id"]
        == step_id_2
    )
    executor._execute_step.assert_awaited_once()
    assert (
        executor._execute_step.await_args.kwargs["state"].completed_by_order[1]
        == existing_completed
    )


@pytest.mark.asyncio
async def test_execute_cancels_when_flow_deleted_after_first_step_and_keeps_completed_evidence(
    user,
):
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id_1 = uuid4()
    step_id_2 = uuid4()
    assistant_id = uuid4()
    claimed_first = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id_1,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed_first)
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id_1),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    },
                    {
                        "step_id": str(step_id_2),
                        "step_order": 2,
                        "assistant_id": str(assistant_id),
                        "input_source": "previous_step",
                        "output_mode": "pass_through",
                    },
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(side_effect=[True, True, False])
    executor._execute_step = AsyncMock(
        return_value=_step_result(
            StepExecutionOutput(
                input_text="hello",
                source_text="hello",
                input_source="flow_input",
                used_question_binding=False,
                full_text="step-one",
                persisted_text="step-one",
                generated_file_ids=[],
                tool_calls_metadata=None,
                num_tokens_input=10,
                num_tokens_output=10,
                effective_prompt="prompt",
                model_parameters_json={},
            )
        )
    )

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "cancelled", "reason": "flow_deleted"}
    assert flow_repo.save_step_result.await_count >= 1
    first_saved = flow_repo.save_step_result.await_args_list[0].args[1]
    assert first_saved.status == FlowStepResultStatus.COMPLETED
    update_kwargs = executor.flow_run_terminalizer.terminalize_run.await_args.kwargs
    assert update_kwargs["target_status"] == FlowRunStatus.CANCELLED
    assert update_kwargs["source"] == FlowRunLifecycleSource.FLOW_DELETED
    assert update_kwargs["error"].message == "Flow was deleted during execution."


def _runtime_step(
    *,
    step_order: int,
    input_source: str,
    input_bindings: dict[str, object] | None = None,
) -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        user_description=None,
        input_source=input_source,
        input_bindings=input_bindings,
        input_config=None,
        output_mode="pass_through",
        output_config=None,
    )


def _completed_step_result(
    *,
    run_id,
    flow_id,
    tenant_id,
    step_order: int,
    text: str,
) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        input_payload_json={"text": f"input-{step_order}"},
        effective_prompt="prompt",
        output_payload_json={"text": text},
        model_parameters_json={},
        num_tokens_input=1,
        num_tokens_output=1,
        status=FlowStepResultStatus.COMPLETED,
        flow_step_execution_hash="hash",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_resolve_step_input_question_binding_overrides_source_text(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text="HELLO WORLD",
        )
    ]
    step = _runtime_step(
        step_order=2,
        input_source="previous_step",
        input_bindings={"question": "Summarize: {{step_1.output.text}}"},
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, prior)

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=prior,
    )

    assert resolved.text == "Summarize: HELLO WORLD"
    assert resolved.used_question_binding is True


@pytest.mark.asyncio
async def test_resolve_step_input_explicit_question_binding_is_resolved(
    user,
):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    prior = [
        _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text="HELLO WORLD",
        )
    ]
    step = _runtime_step(
        step_order=2,
        input_source="previous_step",
        input_bindings={
            "question": "Du ska alltid konvertera texten till stora bokstäver"
        },
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, prior)

    resolved = await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=prior,
    )

    assert resolved.text == "Du ska alltid konvertera texten till stora bokstäver"
    assert resolved.used_question_binding is True


@pytest.mark.asyncio
async def test_resolve_step_input_runtime_question_binding_must_consume_runtime_input(
    user,
):
    executor, _, _, _ = _build_executor(user)
    file_id = uuid4()
    executor.file_repo.get_list_by_id_for_owner = AsyncMock(
        return_value=[SimpleNamespace(id=file_id, text="runtime file text")]
    )
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = RuntimeStep(
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        user_description=None,
        input_source="flow_input",
        input_type="document",
        input_bindings={"question": "Use uploaded context"},
        input_config={"runtime_input": {"enabled": True, "input_format": "document"}},
        output_mode="pass_through",
        output_config=None,
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    with pytest.raises(TypedIOValidationException) as exc_info:
        await executor._resolve_step_input(
            step=step,
            context=context,
            run=run,
            prior_results=[],
            requested_file_ids=[file_id],
        )

    assert exc_info.value.code == "flow_runtime_input_not_consumed"


@pytest.mark.asyncio
async def test_resolve_step_input_raises_for_unknown_source(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _runtime_step(step_order=1, input_source="unknown_source")

    with pytest.raises(BadRequestException, match="Unsupported input source"):
        await executor._resolve_step_input(
            step=step,
            context={},
            run=run,
            prior_results=[],
        )


@pytest.mark.asyncio
async def test_execute_fails_run_when_claimed_step_result_missing(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=None)
    flow_run_repo.get_step_result = AsyncMock(return_value=None)
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {
        "status": "failed",
        "error": FlowApiErrorCode.STEP_MISSING.value,
    }
    executor.flow_run_terminalizer.terminalize_run.assert_awaited_once()
    assert (
        executor.flow_run_terminalizer.terminalize_run.await_args.kwargs[
            "target_status"
        ]
        == FlowRunStatus.FAILED
    )


@pytest.mark.asyncio
async def test_execute_fails_run_when_definition_snapshot_is_invalid(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)

    flow_run_repo.get = AsyncMock(return_value=queued_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    definition_json = {
        "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
        "flow_id": str(queued_run.flow_id),
        "name": "Test flow",
        "description": None,
        "metadata_json": None,
        "steps": [
            {
                "step_id": str(uuid4()),
                "step_order": 1,
                "assistant_id": str(uuid4()),
                "input_source": "flow_input",
                "output_mode": "invalid_mode",
            }
        ],
    }
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum=stable_hash(definition_json),
            definition_json=definition_json,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {
        "status": "failed",
        "error": FlowApiErrorCode.DEFINITION_STEPS_INVALID.value,
    }
    executor.flow_run_terminalizer.terminalize_run.assert_awaited_once()
    assert (
        executor.flow_run_terminalizer.terminalize_run.await_args.kwargs[
            "target_status"
        ]
        == FlowRunStatus.FAILED
    )
    run_error = executor.flow_run_terminalizer.terminalize_run.await_args.kwargs[
        "error"
    ]
    assert run_error.code == FlowApiErrorCode.DEFINITION_STEPS_INVALID.value
    assert run_error.source == FlowRunLifecycleSource.INVALID_FLOW_DEFINITION


@pytest.mark.asyncio
async def test_execute_terminalizes_definition_without_executable_steps(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)

    flow_run_repo.get = AsyncMock(return_value=queued_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    definition_json = {
        "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
        "flow_id": str(queued_run.flow_id),
        "name": "Test flow",
        "description": None,
        "metadata_json": None,
        "steps": [],
    }
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum=stable_hash(definition_json),
            definition_json=definition_json,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {
        "status": "failed",
        "error": "flow_definition_no_executable_steps",
    }
    executor.flow_run_terminalizer.terminalize_run.assert_awaited_once()
    assert (
        executor.flow_run_terminalizer.terminalize_run.await_args.kwargs[
            "target_status"
        ]
        == FlowRunStatus.FAILED
    )
    run_error = executor.flow_run_terminalizer.terminalize_run.await_args.kwargs[
        "error"
    ]
    assert run_error.code == "flow_definition_no_executable_steps"
    assert run_error.source == FlowRunLifecycleSource.INVALID_FLOW_DEFINITION
    flow_run_repo.create_or_get_attempt_started.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_rejects_question_binding_input_contract_before_step_execution(
    user,
):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)

    flow_run_repo.get = AsyncMock(return_value=queued_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(uuid4()),
                        "step_order": 1,
                        "assistant_id": str(uuid4()),
                        "input_source": "flow_input",
                        "output_type": "json",
                        "output_mode": "pass_through",
                    },
                    {
                        "step_id": str(uuid4()),
                        "step_order": 2,
                        "assistant_id": str(uuid4()),
                        "input_source": "previous_step",
                        "input_type": "text",
                        "input_bindings": {
                            "question": (
                                "{{ step_1.output.structured }}\n\n"
                                "Källmaterial: {{ step_1.output.text }}"
                            )
                        },
                        "input_contract": {
                            "type": "object",
                            "properties": {"title": {"type": "string"}},
                        },
                        "output_mode": "pass_through",
                    },
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {
        "status": "failed",
        "error": FlowApiErrorCode.INPUT_CONTRACT_INAPPLICABLE.value,
    }
    flow_run_repo.create_or_get_attempt_started.assert_not_awaited()
    run_error = executor.flow_run_terminalizer.terminalize_run.await_args.kwargs[
        "error"
    ]
    assert run_error.code == FlowApiErrorCode.INPUT_CONTRACT_INAPPLICABLE.value
    assert run_error.source == FlowRunLifecycleSource.INVALID_FLOW_DEFINITION
    assert run_error.step_order == 2


def test_run_error_from_bad_request_sanitizes_context(user) -> None:
    executor, _, _, _ = _build_executor(user)

    error = executor._run_error_from_bad_request(
        BadRequestException(
            "Step review_policy is invalid.",
            code="flow_review_policy_invalid",
            context={
                "step_order": 3,
                "step_description": "Analysera bakgrund",
                "secret_token": "must not leak",
            },
        ),
        source=FlowRunLifecycleSource.INVALID_FLOW_DEFINITION,
        default_code=FlowApiErrorCode.DEFINITION_INVALID,
    )

    assert error.code == FlowApiErrorCode.REVIEW_POLICY_INVALID.value
    assert error.step_order == 3
    assert error.details is not None
    assert error.details.model_dump(exclude_none=True) == {
        "step_description": "Analysera bakgrund"
    }


def test_run_error_from_bad_request_falls_back_and_logs_uncataloged_code(
    user, caplog
) -> None:
    executor, _, _, _ = _build_executor(user)

    with caplog.at_level(logging.WARNING):
        error = executor._run_error_from_bad_request(
            BadRequestException(
                "Definition parser returned a private code.",
                code="flow_private_parser_code",
            ),
            source=FlowRunLifecycleSource.INVALID_FLOW_DEFINITION,
            default_code=FlowApiErrorCode.DEFINITION_INVALID,
        )

    assert error.code == FlowApiErrorCode.DEFINITION_INVALID.value
    assert "flow_executor.bad_request_uncataloged_code" in caplog.text
    assert "flow_private_parser_code" in caplog.text


# --- RunExecutionState ---


def test_run_execution_state_append_completed():
    """append_completed tracks results and builds accumulated text."""
    now = datetime.now(timezone.utc)
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    result = FlowStepResult(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json={},
        effective_prompt="",
        output_payload_json={"text": "hello"},
        model_parameters_json={},
        num_tokens_input=1,
        num_tokens_output=1,
        status=FlowStepResultStatus.COMPLETED,
        flow_step_execution_hash="h",
        created_at=now,
        updated_at=now,
    )
    state.append_completed(result)

    assert 1 in state.completed_by_order
    assert len(state.prior_results) == 1
    accumulated_text = state.all_previous_text_before(2)
    assert "<step_1_output>" in accumulated_text
    assert "hello" in accumulated_text


def test_run_execution_state_all_previous_text_before_accumulates():
    """Multiple appends build up ordered all_previous text before a step."""
    now = datetime.now(timezone.utc)
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    for order, text in [(1, "first"), (2, "second")]:
        result = FlowStepResult(
            id=uuid4(),
            flow_run_id=uuid4(),
            flow_id=uuid4(),
            tenant_id=uuid4(),
            step_id=uuid4(),
            step_order=order,
            assistant_id=uuid4(),
            input_payload_json={},
            effective_prompt="",
            output_payload_json={"text": text},
            model_parameters_json={},
            num_tokens_input=1,
            num_tokens_output=1,
            status=FlowStepResultStatus.COMPLETED,
            flow_step_execution_hash="h",
            created_at=now,
            updated_at=now,
        )
        state.append_completed(result)

    accumulated_text = state.all_previous_text_before(3)
    assert "<step_1_output>" in accumulated_text
    assert "<step_2_output>" in accumulated_text
    assert "first" in accumulated_text
    assert "second" in accumulated_text


# --- Assistant cache ---


@pytest.mark.asyncio
async def test_assistant_cache_hit(user):
    """Same assistant ID loaded twice — get_space_by_assistant called once."""
    executor, _, _, _ = _build_executor(user)
    assistant_id = uuid4()
    mock_assistant = SimpleNamespace(id=assistant_id)
    mock_space = SimpleNamespace(
        id=uuid4(),
        default_assistant=None,
        assistants=[mock_assistant],
        get_assistant=lambda assistant_id: mock_assistant,
    )
    executor.space_repo.get_space_by_assistant = AsyncMock(return_value=mock_space)

    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )

    result1 = await executor._load_assistant(assistant_id, state)
    result2 = await executor._load_assistant(assistant_id, state)

    assert result1 is result2
    assert executor.space_repo.get_space_by_assistant.call_count == 1


def _security_assistant(assistant_id: UUID, *, model_level: int = 3) -> SimpleNamespace:
    return SimpleNamespace(
        id=assistant_id,
        completion_model=SimpleNamespace(
            security_classification=SimpleNamespace(security_level=model_level)
        ),
        collections=[],
        websites=[],
        integration_knowledge_list=[],
        mcp_servers=[],
    )


def _security_space(
    *,
    space_id: UUID,
    assistants: list[SimpleNamespace],
    security_level: int,
) -> SimpleNamespace:
    assistants_by_id = {assistant.id: assistant for assistant in assistants}
    return SimpleNamespace(
        id=space_id,
        default_assistant=None,
        assistants=assistants,
        security_classification=SimpleNamespace(security_level=security_level),
        get_assistant=lambda assistant_id: assistants_by_id[assistant_id],
    )


def _security_step(
    *,
    step_order: int,
    assistant_id: UUID,
    input_source: str = "flow_input",
) -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=assistant_id,
        user_description=f"Step {step_order}",
        input_source=input_source,
        input_bindings=None,
        input_config=None,
        output_mode="pass_through",
        output_config=None,
    )


async def _validate_security_steps(
    executor: FlowRunExecutor,
    state: RunExecutionState,
    steps: list[RuntimeStep],
) -> dict[int, int | None]:
    levels: dict[int, int | None] = {}
    for step in steps:
        levels[step.step_order] = await executor._validate_runtime_step_security(
            step=step,
            state=state,
            prior_output_levels_by_order=levels,
        )
    return levels


@pytest.mark.asyncio
async def test_runtime_step_security_reuses_space_for_same_space_assistants(user):
    executor, _, _, _ = _build_executor(user)
    assistant_one = _security_assistant(uuid4())
    assistant_two = _security_assistant(uuid4())
    space = _security_space(
        space_id=uuid4(),
        assistants=[assistant_one, assistant_two],
        security_level=1,
    )
    executor.space_repo.get_space_by_assistant = AsyncMock(return_value=space)
    state = _empty_execution_state()

    levels = await _validate_security_steps(
        executor=executor,
        state=state,
        steps=[
            _security_step(step_order=1, assistant_id=assistant_one.id),
            _security_step(step_order=2, assistant_id=assistant_two.id),
            _security_step(
                step_order=3,
                assistant_id=assistant_one.id,
                input_source="previous_step",
            ),
        ],
    )

    assert levels == {1: 1, 2: 1, 3: 1}
    assert state.assistant_cache[assistant_one.id] is assistant_one
    assert state.assistant_cache[assistant_two.id] is assistant_two
    assert executor.space_repo.get_space_by_assistant.await_count == 1


@pytest.mark.asyncio
async def test_runtime_step_security_keeps_distinct_space_hydration(user):
    executor, _, _, _ = _build_executor(user)
    assistant_one = _security_assistant(uuid4())
    assistant_two = _security_assistant(uuid4())
    space_by_assistant_id = {
        assistant_one.id: _security_space(
            space_id=uuid4(),
            assistants=[assistant_one],
            security_level=1,
        ),
        assistant_two.id: _security_space(
            space_id=uuid4(),
            assistants=[assistant_two],
            security_level=2,
        ),
    }

    async def _get_space_by_assistant(*, assistant_id: UUID):
        return space_by_assistant_id[assistant_id]

    executor.space_repo.get_space_by_assistant = AsyncMock(
        side_effect=_get_space_by_assistant
    )
    state = _empty_execution_state()

    levels = await _validate_security_steps(
        executor=executor,
        state=state,
        steps=[
            _security_step(step_order=1, assistant_id=assistant_one.id),
            _security_step(step_order=2, assistant_id=assistant_two.id),
        ],
    )

    assert levels == {1: 1, 2: 2}
    assert state.assistant_cache[assistant_one.id] is assistant_one
    assert state.assistant_cache[assistant_two.id] is assistant_two
    assert executor.space_repo.get_space_by_assistant.await_count == 2


def _step_for_execute_step(*, step_order: int = 1) -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        user_description=None,
        input_source="flow_input",
        input_bindings=None,
        input_config=None,
        output_mode="pass_through",
        output_config=None,
        output_type="text",
        input_type="text",
    )


def _assistant_for_snapshot(
    *,
    assistant_id,
    model_id,
    prompt: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=assistant_id,
        origin="flow_managed",
        prompt=SimpleNamespace(text=prompt),
        completion_model=SimpleNamespace(
            id=model_id,
            name="gpt-5.4-nano",
            nickname="Nano",
            litellm_model_name="openai/gpt-5.4-nano",
        ),
        completion_model_kwargs={"temperature": 0.2},
        collections=[],
        websites=[],
        integration_knowledge_list=[],
        mcp_servers=[],
    )


@pytest.mark.asyncio
async def test_execute_step_records_flow_step_span(user, captured_flow_spans):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _step_for_execute_step(step_order=2)

    class _Handler:
        async def execute(self, **_kwargs):
            return _step_result(_minimal_step_execution_output())

    executor._build_step_handler = MagicMock(return_value=_Handler())

    result = await executor._execute_step(
        step=step,
        run=run,
        state=_empty_execution_state(),
        attempt_no=3,
    )

    assert result.output.full_text == "answer"
    span = captured_flow_spans.get_finished_spans()[0]
    assert span.name == flow_runtime_trace.FLOW_STEP_EXECUTE_SPAN_NAME
    assert set(span.attributes) <= flow_runtime_trace.FLOW_STEP_SPAN_ATTRIBUTE_KEYS
    assert span.attributes["flow.run.id"] == str(run.id)
    assert span.attributes["flow.run.trace_id"] == str(run.trace_id)
    assert span.attributes["flow.id"] == str(run.flow_id)
    assert span.attributes["flow.tenant.id"] == str(run.tenant_id)
    assert span.attributes["flow.step.id"] == str(step.step_id)
    assert span.attributes["flow.step.order"] == 2
    assert span.attributes["flow.step.attempt_no"] == 3
    assert span.attributes["flow.step.result.status"] == "completed"


@pytest.mark.asyncio
async def test_execute_step_marks_flow_step_span_failed(user, captured_flow_spans):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _step_for_execute_step()

    class _Handler:
        async def execute(self, **_kwargs):
            raise RuntimeError("provider failed")

    executor._build_step_handler = MagicMock(return_value=_Handler())

    with pytest.raises(RuntimeError, match="provider failed"):
        await executor._execute_step(
            step=step,
            run=run,
            state=_empty_execution_state(),
            attempt_no=1,
        )

    span = captured_flow_spans.get_finished_spans()[0]
    assert span.name == flow_runtime_trace.FLOW_STEP_EXECUTE_SPAN_NAME
    assert span.attributes["flow.step.result.status"] == "failed"
    assert span.status.status_code.name == "ERROR"


@pytest.mark.asyncio
async def test_validate_assistant_snapshots_accepts_matching_execution_surface(user):
    executor, _, _, _ = _build_executor(user)
    assistant_id = uuid4()
    model_id = uuid4()
    assistant = _assistant_for_snapshot(
        assistant_id=assistant_id,
        model_id=model_id,
        prompt="Summarize the case.",
    )
    snapshot = build_assistant_execution_snapshot(
        assistant=assistant,
        mcp_server_entities=[],
    )
    assert snapshot is not None
    step = replace(
        _step_for_execute_step(),
        assistant_id=assistant_id,
        assistant_snapshot=snapshot,
    )
    state = _empty_execution_state()
    executor._load_assistant = AsyncMock(return_value=assistant)

    await executor._validate_assistant_snapshots(
        steps=[step],
        state=state,
        run_id=uuid4(),
    )

    executor._load_assistant.assert_awaited_once_with(assistant_id, state)


@pytest.mark.asyncio
async def test_validate_assistant_snapshots_rejects_prompt_drift(user):
    executor, _, _, _ = _build_executor(user)
    assistant_id = uuid4()
    model_id = uuid4()
    published_assistant = _assistant_for_snapshot(
        assistant_id=assistant_id,
        model_id=model_id,
        prompt="Summarize the case.",
    )
    current_assistant = _assistant_for_snapshot(
        assistant_id=assistant_id,
        model_id=model_id,
        prompt="Summarize the case and make recommendations.",
    )
    snapshot = build_assistant_execution_snapshot(
        assistant=published_assistant,
        mcp_server_entities=[],
    )
    assert snapshot is not None
    step = replace(
        _step_for_execute_step(),
        assistant_id=assistant_id,
        assistant_snapshot=snapshot,
    )
    executor._load_assistant = AsyncMock(return_value=current_assistant)

    with pytest.raises(BadRequestException, match="changed after publish"):
        await executor._validate_assistant_snapshots(
            steps=[step],
            state=_empty_execution_state(),
            run_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_validate_assistant_snapshots_skips_legacy_steps_without_snapshot(user):
    executor, _, _, _ = _build_executor(user)
    executor._load_assistant = AsyncMock()

    await executor._validate_assistant_snapshots(
        steps=[_step_for_execute_step()],
        state=_empty_execution_state(),
        run_id=uuid4(),
    )

    executor._load_assistant.assert_not_awaited()


@pytest.mark.asyncio
async def test_validate_assistant_snapshots_requires_schema_versioned_snapshots(user):
    executor, _, _, _ = _build_executor(user)
    executor._load_assistant = AsyncMock()

    with pytest.raises(BadRequestException, match="snapshot is missing"):
        await executor._validate_assistant_snapshots(
            steps=[_step_for_execute_step()],
            state=_empty_execution_state(),
            run_id=uuid4(),
            require_snapshots=True,
        )

    executor._load_assistant.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_step_records_attempt_start_before_llm_dispatch(user):
    executor, _, flow_run_repo, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _step_for_execute_step()
    state = _empty_execution_state()
    assistant = _assistant_for_execute_step(has_knowledge=False)
    assistant.get_prompt_text.return_value = "Prompt"
    flow_run_repo.record_attempt_start_provenance = AsyncMock()

    async def _get_response(**_kwargs):
        flow_run_repo.record_attempt_start_provenance.assert_awaited_once()
        return SimpleNamespace(completion="answer", total_token_count=42)

    assistant.get_response = AsyncMock(side_effect=_get_response)
    executor._load_assistant = AsyncMock(return_value=assistant)
    executor._resolve_step_input = AsyncMock(
        return_value=StepInputValue(
            text="hello", source_text="hello", input_source="flow_input"
        )
    )
    executor._process_typed_output = AsyncMock(return_value=_typed_output_result())
    executor._apply_output_cap = AsyncMock(return_value=("answer", []))
    executor._commit = AsyncMock()

    await executor._execute_step(step=step, run=run, state=state, attempt_no=1)

    record_kwargs = flow_run_repo.record_attempt_start_provenance.await_args.kwargs
    attempt_start = record_kwargs["attempt_start"]
    assert attempt_start.requested_model == "gpt-4o-mini"
    assert attempt_start.provider == "openai"
    assert attempt_start.resolved_timeout_seconds == 600
    assert attempt_start.input_text_length == 5
    assert attempt_start.effective_prompt_length >= 5
    assert state.attempt_start_by_step[step.step_id] == attempt_start


@pytest.mark.asyncio
async def test_execute_step_uses_rag_chunks_when_knowledge_present(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _step_for_execute_step()
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    assistant = _assistant_for_execute_step(has_knowledge=True)
    executor._load_assistant = AsyncMock(return_value=assistant)
    executor._resolve_step_input = AsyncMock(
        return_value=StepInputValue(
            text="hello", source_text="hello", input_source="flow_input"
        )
    )
    executor._process_typed_output = AsyncMock(return_value=_typed_output_result())
    executor._apply_output_cap = AsyncMock(return_value=("answer", []))
    executor._commit = AsyncMock()
    source_id = uuid4()
    chunks = [
        SimpleNamespace(
            info_blob_id=source_id,
            info_blob_title="Finance update",
            chunk_no=1,
            score=0.91,
            text="Sundsvalls kommun redovisar ett positivt resultat för 2025.",
        ),
        SimpleNamespace(
            info_blob_id=source_id,
            info_blob_title="Finance update",
            chunk_no=2,
            score=0.77,
            text="I november låg prognosen på lägre nivå men utfallet förbättrades.",
        ),
    ]
    executor.references_service = AsyncMock()
    executor.references_service.get_references = AsyncMock(
        return_value=SimpleNamespace(chunks=chunks, no_duplicate_chunks=[chunks[0]])
    )

    output = (
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    ).output

    executor.references_service.get_references.assert_awaited_once()
    rag_kwargs = executor.references_service.get_references.await_args.kwargs
    assert rag_kwargs["version"] == 1
    assert rag_kwargs["include_info_blobs"] is False
    assert assistant.get_response.await_args.kwargs["info_blob_chunks"] == chunks
    assert output.rag_metadata is not None
    assert output.rag_metadata["status"] == "success"
    assert output.rag_metadata["chunks_retrieved"] == 2
    assert output.rag_metadata["raw_chunks_count"] == 2
    assert output.rag_metadata["deduped_chunks_count"] == 1
    assert output.rag_metadata["attempted"] is True
    assert output.rag_metadata["retrieval_duration_ms"] is not None
    assert output.rag_metadata["retrieval_error_type"] is None
    assert output.rag_metadata["references_truncated"] is False
    assert len(output.rag_metadata["references"]) == 1
    assert output.rag_metadata["references"][0]["id"] == str(source_id)
    assert output.rag_metadata["references"][0]["matched_chunk_count"] == 2
    assert output.rag_metadata["references"][0]["best_score"] == pytest.approx(0.91)
    assert len(output.rag_metadata["references"][0]["chunks"]) == 2


@pytest.mark.asyncio
async def test_execute_step_skips_rag_when_assistant_has_no_knowledge(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _step_for_execute_step()
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    assistant = _assistant_for_execute_step(has_knowledge=False)
    executor._load_assistant = AsyncMock(return_value=assistant)
    executor._resolve_step_input = AsyncMock(
        return_value=StepInputValue(
            text="hello", source_text="hello", input_source="flow_input"
        )
    )
    executor._process_typed_output = AsyncMock(return_value=_typed_output_result())
    executor._apply_output_cap = AsyncMock(return_value=("answer", []))
    executor._commit = AsyncMock()
    executor.references_service = AsyncMock()
    executor.references_service.get_references = AsyncMock()

    output = (
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    ).output

    executor.references_service.get_references.assert_not_awaited()
    assert assistant.get_response.await_args.kwargs["info_blob_chunks"] == []
    assert output.rag_metadata is not None
    assert output.rag_metadata["status"] == "skipped_no_knowledge"
    assert output.rag_metadata["attempted"] is False


@pytest.mark.asyncio
async def test_execute_step_rag_timeout_appends_diagnostic_and_continues(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _step_for_execute_step()
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    assistant = _assistant_for_execute_step(has_knowledge=True)
    executor._load_assistant = AsyncMock(return_value=assistant)
    executor._resolve_step_input = AsyncMock(
        return_value=StepInputValue(
            text="hello", source_text="hello", input_source="flow_input"
        )
    )
    executor._process_typed_output = AsyncMock(return_value=_typed_output_result())
    executor._apply_output_cap = AsyncMock(return_value=("answer", []))
    executor._commit = AsyncMock()
    executor.references_service = AsyncMock()
    executor.references_service.get_references = AsyncMock(
        side_effect=asyncio.TimeoutError()
    )

    output = (
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    ).output

    assert assistant.get_response.await_args.kwargs["info_blob_chunks"] == []
    assert output.rag_metadata is not None
    assert output.rag_metadata["status"] == "timeout"
    assert output.rag_metadata["error_code"] == "rag_retrieval_timeout"
    assert output.rag_metadata["retrieval_error_type"] == "TimeoutError"
    assert any(d.code == "rag_retrieval_timeout" for d in output.diagnostics)


@pytest.mark.asyncio
async def test_execute_step_rag_failure_appends_diagnostic_and_continues(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _step_for_execute_step()
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    assistant = _assistant_for_execute_step(has_knowledge=True)
    executor._load_assistant = AsyncMock(return_value=assistant)
    executor._resolve_step_input = AsyncMock(
        return_value=StepInputValue(
            text="hello", source_text="hello", input_source="flow_input"
        )
    )
    executor._process_typed_output = AsyncMock(return_value=_typed_output_result())
    executor._apply_output_cap = AsyncMock(return_value=("answer", []))
    executor._commit = AsyncMock()
    executor.references_service = AsyncMock()
    executor.references_service.get_references = AsyncMock(
        side_effect=RuntimeError("boom")
    )

    output = (
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    ).output

    assert assistant.get_response.await_args.kwargs["info_blob_chunks"] == []
    assert output.rag_metadata is not None
    assert output.rag_metadata["status"] == "error"
    assert output.rag_metadata["error_code"] == "rag_retrieval_failed"
    assert output.rag_metadata["retrieval_error_type"] == "RuntimeError"
    assert any(d.code == "rag_retrieval_failed" for d in output.diagnostics)


@pytest.mark.asyncio
async def test_execute_step_skips_rag_when_input_is_whitespace(user):
    executor, _, _, _ = _build_executor(user)
    run = _run(status=FlowRunStatus.RUNNING, user=user)
    step = _step_for_execute_step()
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    assistant = _assistant_for_execute_step(has_knowledge=True)
    executor._load_assistant = AsyncMock(return_value=assistant)
    executor._resolve_step_input = AsyncMock(
        return_value=StepInputValue(
            text="   ", source_text="   ", input_source="flow_input"
        )
    )
    executor._process_typed_output = AsyncMock(return_value=_typed_output_result())
    executor._apply_output_cap = AsyncMock(return_value=("answer", []))
    executor._commit = AsyncMock()
    executor.references_service = AsyncMock()
    executor.references_service.get_references = AsyncMock()

    output = (
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    ).output

    executor.references_service.get_references.assert_not_awaited()
    assert output.rag_metadata is not None
    assert output.rag_metadata["status"] == "skipped_no_input"
    assert output.rag_metadata["attempted"] is False


@pytest.mark.asyncio
async def test_retrieve_rag_chunks_caps_sources_and_chunks(user):
    executor, _, _, _ = _build_executor(user)
    assistant = _assistant_for_execute_step(has_knowledge=True)
    executor.references_service = AsyncMock()

    chunks = []
    for source_index in range(27):
        source_id = uuid4()
        for chunk_index in range(7):
            chunks.append(
                SimpleNamespace(
                    info_blob_id=source_id,
                    info_blob_title=f"Source {source_index}",
                    chunk_no=chunk_index + 1,
                    score=1.0 - (chunk_index * 0.01),
                    text=f"Chunk {chunk_index} from source {source_index} " * 8,
                )
            )

    executor.references_service.get_references = AsyncMock(
        return_value=SimpleNamespace(chunks=chunks, no_duplicate_chunks=chunks[:27])
    )

    _, metadata, diagnostics = await executor._retrieve_rag_chunks(
        assistant=assistant,
        question="what happened?",
        run_id=uuid4(),
        step_order=1,
    )

    assert diagnostics == []
    assert metadata["status"] == "success"
    assert metadata["references_truncated"] is True
    assert len(metadata["references"]) == 25
    assert metadata["raw_chunks_count"] == len(chunks)
    assert metadata["deduped_chunks_count"] == 27
    assert all(len(reference["chunks"]) <= 5 for reference in metadata["references"])


# --- Prior results bootstrap ---


@pytest.mark.asyncio
async def test_prior_results_bootstrap_once(user):
    """list_step_results called exactly once at bootstrap, not per step."""
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id_1, step_id_2 = uuid4(), uuid4()
    assistant_id = uuid4()

    claimed_1 = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id_1,
        assistant_id=assistant_id,
    )
    claimed_2 = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id_2,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(side_effect=[claimed_1, claimed_2])
    flow_run_repo.finish_attempt = AsyncMock()
    # Bootstrap call returns empty (fresh run), final call returns all completed
    completed_1 = claimed_1.model_copy(
        update={
            "status": FlowStepResultStatus.COMPLETED,
            "output_payload_json": {"text": "out1"},
        },
        deep=True,
    )
    completed_2 = claimed_2.model_copy(
        update={
            "step_order": 2,
            "status": FlowStepResultStatus.COMPLETED,
            "output_payload_json": {"text": "out2"},
        },
        deep=True,
    )
    flow_run_repo.list_step_results = AsyncMock(
        side_effect=[
            [],  # bootstrap
            [completed_1, completed_2],  # final check
        ]
    )
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id_1),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    },
                    {
                        "step_id": str(step_id_2),
                        "step_order": 2,
                        "assistant_id": str(assistant_id),
                        "input_source": "previous_step",
                        "output_mode": "pass_through",
                    },
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        return_value=_step_result(
            StepExecutionOutput(
                input_text="hello",
                source_text="hello",
                input_source="flow_input",
                used_question_binding=False,
                full_text="result",
                persisted_text="result",
                generated_file_ids=[],
                tool_calls_metadata=None,
                num_tokens_input=10,
                num_tokens_output=11,
                effective_prompt="prompt",
                model_parameters_json={"temperature": 0.2},
            )
        )
    )

    await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    # list_step_results: 1 bootstrap + 1 final = 2 total (NOT per-step)
    assert flow_run_repo.list_step_results.call_count == 2


@pytest.mark.asyncio
async def test_execute_fails_before_claim_when_assistant_snapshot_drifted(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    assistant_id = uuid4()
    model_id = uuid4()
    published_assistant = _assistant_for_snapshot(
        assistant_id=assistant_id,
        model_id=model_id,
        prompt="Summarize the case.",
    )
    current_assistant = _assistant_for_snapshot(
        assistant_id=assistant_id,
        model_id=model_id,
        prompt="Summarize the case and include recommendations.",
    )
    snapshot = build_assistant_execution_snapshot(
        assistant=published_assistant,
        mcp_server_entities=[],
    )
    assert snapshot is not None
    step_id = uuid4()

    flow_run_repo.get = AsyncMock(return_value=queued_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.list_step_results = AsyncMock(return_value=[])
    flow_run_repo.claim_step_result = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                        "assistant_snapshot": snapshot,
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._load_assistant = AsyncMock(return_value=current_assistant)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {
        "status": "failed",
        "error": FlowApiErrorCode.ASSISTANT_SNAPSHOT_DRIFT.value,
    }
    flow_run_repo.claim_step_result.assert_not_awaited()
    executor.flow_run_terminalizer.terminalize_run.assert_awaited_once()
    assert (
        executor.flow_run_terminalizer.terminalize_run.await_args.kwargs[
            "target_status"
        ]
        == FlowRunStatus.FAILED
    )


@pytest.mark.asyncio
async def test_execute_fails_before_parse_when_definition_checksum_drifted(
    user, monkeypatch
):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    step_id = uuid4()
    assistant_id = uuid4()

    flow_run_repo.get = AsyncMock(return_value=queued_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.list_step_results = AsyncMock()
    flow_run_repo.claim_step_result = AsyncMock()
    parse_published_runtime_steps = MagicMock()
    monkeypatch.setattr(
        executor_module,
        "parse_published_runtime_steps",
        parse_published_runtime_steps,
    )
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum=stable_hash({"steps": []}),
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {
        "status": "failed",
        "error": FlowApiErrorCode.DEFINITION_CHECKSUM_MISMATCH.value,
    }
    parse_published_runtime_steps.assert_not_called()
    flow_run_repo.list_step_results.assert_not_awaited()
    flow_run_repo.claim_step_result.assert_not_awaited()
    executor.flow_run_terminalizer.terminalize_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_fails_before_claim_when_schema_versioned_snapshot_missing(user):
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    step_id = uuid4()
    assistant_id = uuid4()

    flow_run_repo.get = AsyncMock(return_value=queued_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.list_step_results = AsyncMock(return_value=[])
    flow_run_repo.claim_step_result = AsyncMock()
    executor._load_assistant = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "schema_version": 1,
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ],
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {
        "status": "failed",
        "error": FlowApiErrorCode.ASSISTANT_SNAPSHOT_DRIFT.value,
    }
    executor._load_assistant.assert_not_awaited()
    flow_run_repo.claim_step_result.assert_not_awaited()
    executor.flow_run_terminalizer.terminalize_run.assert_awaited_once()


# --- File cache ---


@pytest.mark.asyncio
async def test_file_cache_hit(user):
    executor, _, _, _ = _build_executor(user)
    step_id = uuid4()
    file_id = uuid4()
    fake_file = SimpleNamespace(id=file_id, text="doc text")
    executor.file_repo.get_list_by_id_for_owner = AsyncMock(return_value=[fake_file])

    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )

    run = _run(status=FlowRunStatus.RUNNING, user=user)
    run = run.model_copy(
        update={
            "input_payload_json": {
                "text": "x",
            }
        }
    )
    step = RuntimeStep(
        step_id=step_id,
        step_order=1,
        assistant_id=uuid4(),
        user_description=None,
        input_source="flow_input",
        input_bindings=None,
        input_config={"runtime_input": True},
        output_mode="pass_through",
        output_config=None,
        input_type="document",
    )
    context = executor.variable_resolver.build_context(run.input_payload_json, [])

    await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
        state=state,
        requested_file_ids=[file_id],
    )
    await executor._resolve_step_input(
        step=step,
        context=context,
        run=run,
        prior_results=[],
        state=state,
        requested_file_ids=[file_id],
    )

    assert executor.file_repo.get_list_by_id_for_owner.call_count == 1


def _make_audit_service():
    audit_service = AsyncMock()
    audit_service.log_async = AsyncMock(return_value=None)
    return audit_service


@pytest.mark.asyncio
async def test_execute_audits_completed_run_terminal_state(user):
    audit_service = _make_audit_service()
    executor, flow_repo, flow_run_repo, flow_version_repo = _build_executor(user)
    executor.audit_service = audit_service
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )
    completed_result = claimed.model_copy(
        update={
            "status": FlowStepResultStatus.COMPLETED,
            "output_payload_json": {"text": "done"},
        },
        deep=True,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.finish_attempt = AsyncMock()
    flow_run_repo.list_step_results = AsyncMock(return_value=[completed_result])
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(
        return_value=_step_result(
            StepExecutionOutput(
                input_text="hello",
                source_text="hello",
                input_source="flow_input",
                used_question_binding=False,
                full_text="done",
                persisted_text="done",
                generated_file_ids=[],
                tool_calls_metadata=None,
                num_tokens_input=10,
                num_tokens_output=10,
                effective_prompt="prompt",
                model_parameters_json={},
            )
        )
    )

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "completed"}
    audit_service.log_async.assert_not_awaited()
    terminal_kwargs = executor.flow_run_terminalizer.terminalize_run.await_args.kwargs
    assert terminal_kwargs["target_status"] == FlowRunStatus.COMPLETED
    assert terminal_kwargs["source"] == FlowRunLifecycleSource.EXECUTOR_COMPLETED


@pytest.mark.asyncio
async def test_execute_audits_failed_run_terminal_state(user):
    audit_service = _make_audit_service()
    executor, _, flow_run_repo, flow_version_repo = _build_executor(user)
    executor.audit_service = audit_service
    queued_run = _run(status=FlowRunStatus.QUEUED, user=user)
    running_run = queued_run.model_copy(update={"status": FlowRunStatus.RUNNING})
    step_id = uuid4()
    assistant_id = uuid4()
    claimed = _claimed_step_result(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        step_id=step_id,
        assistant_id=assistant_id,
    )

    flow_run_repo.get = _run_get_mock(queued_run, running_run, running_run)
    flow_run_repo.mark_running_if_claimable = AsyncMock(return_value=True)
    flow_run_repo.claim_step_result = AsyncMock(return_value=claimed)
    flow_run_repo.finish_attempt = AsyncMock()
    flow_version_repo.get = AsyncMock(
        return_value=FlowVersion(
            flow_id=queued_run.flow_id,
            version=queued_run.flow_version,
            tenant_id=user.tenant_id,
            definition_checksum="checksum",
            definition_json={
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(assistant_id),
                        "input_source": "flow_input",
                        "output_mode": "pass_through",
                    }
                ]
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    executor._flow_is_active = AsyncMock(return_value=True)
    executor._execute_step = AsyncMock(side_effect=RuntimeError("boom"))

    result = await executor.execute(
        run_id=queued_run.id,
        flow_id=queued_run.flow_id,
        tenant_id=user.tenant_id,
        celery_task_id="task-1",
        retry_count=0,
    )

    assert result == {
        "status": "failed",
        "error": FlowApiErrorCode.STEP_EXECUTION_FAILED.value,
    }
    audit_service.log_async.assert_not_awaited()
    terminal_kwargs = executor.flow_run_terminalizer.terminalize_run.await_args.kwargs
    assert terminal_kwargs["target_status"] == FlowRunStatus.FAILED
    assert terminal_kwargs["source"] == FlowRunLifecycleSource.EXECUTOR_FAILED


@pytest.mark.asyncio
async def test_validate_runtime_step_security_rejects_write_down(user):
    executor, _, _, _ = _build_executor(user)
    assistant_id = uuid4()
    space = SimpleNamespace(
        id=uuid4(),
        default_assistant=None,
        assistants=[],
        security_classification=SimpleNamespace(security_level=1),
    )
    assistant = SimpleNamespace(
        completion_model=SimpleNamespace(
            security_classification=SimpleNamespace(security_level=3)
        ),
        collections=[],
        websites=[],
        integration_knowledge_list=[],
        mcp_servers=[],
    )
    executor.space_repo.get_space_by_assistant = AsyncMock(return_value=space)
    executor._load_assistant = AsyncMock(return_value=assistant)
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    step = RuntimeStep(
        step_id=uuid4(),
        step_order=2,
        assistant_id=assistant_id,
        user_description="Step 2",
        input_source="previous_step",
        input_bindings=None,
        input_config=None,
        output_mode="pass_through",
        output_config=None,
        output_classification_override=1,
    )

    with pytest.raises(BadRequestException, match="output classification override"):
        await executor._validate_runtime_step_security(
            step=step,
            state=state,
            prior_output_levels_by_order={1: 3},
        )
