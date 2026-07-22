from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
from types import SimpleNamespace
from unittest.mock import (
    AsyncMock,
    MagicMock,
)
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.authentication.auth_dependencies import ScopeFilter
from eneo.database.tables.flow_tables import FlowOutboxDeliveryStatus
from eneo.flows.api import flow_access_context as flow_access_context_module
from eneo.flows.api import flow_run_lifecycle_router as lifecycle_router_module
from eneo.flows.api import flow_run_review_router as review_router_module
from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.api.flow_models import (
    FlowFinalOutputContractPublic,
    FlowOutputDelivery,
    FlowRunCreateRequest,
    FlowRunRedispatchRequest,
    FlowRunReviewCheckpointResumeRequest,
    FlowRunStepRerunRequest,
)
from eneo.flows.api.flow_run_lifecycle_router import (
    cancel_flow_run,
    create_flow_run,
    get_flow_run,
    list_flow_runs,
    redispatch_flow_run,
)
from eneo.flows.api.flow_run_rerun_router import rerun_flow_run_step
from eneo.flows.api.flow_run_review_router import resume_flow_run_review_checkpoint
from eneo.flows.api.flow_run_steps_router import (
    get_flow_graph,
    list_flow_run_steps,
)
from eneo.flows.application.flow_dispatch import (
    FlowRunDispatchAccepted,
    FlowRunDispatchExhaustionGenerationConflictError,
    FlowRunDispatchFailed,
    FlowRunDispatchNotClaimed,
    dispatch_flow_run_recoverably_after_commit,
)
from eneo.flows.application.flow_run_service import (
    CreateRunResult,
    FlowRunDetailView,
    FlowRunPageWithResultFilesAndTokenUsage,
    FlowRunVersionedView,
    FlowRunWithResultFilesAndTokenUsage,
)
from eneo.flows.domain.flow import (
    FlowRunStatus,
    FlowStepResult,
)
from eneo.flows.domain.runtime_invariant_exceptions import (
    FlowPublishedDefinitionWithoutExecutableStepsError,
)
from eneo.flows.enums import (
    FlowOutputMode,
    FlowOutputType,
    FlowRunRerunOperationStatus,
    FlowStepResultStatus,
)
from eneo.flows.flow_run_step_inputs import FlowRunStepInputFiles
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRead,
)
from eneo.flows.published_definition import (
    FLOW_DEFINITION_SCHEMA_VERSION,
    parse_published_definition,
)
from eneo.main.exceptions import (
    BadRequestException,
    ConflictException,
    InternalServerException,
    NotFoundException,
)
from eneo.roles.permissions import Permission
from tests.unittests.flows.test_flow_router import (
    _enable_explicit_transaction,
    _enable_space_access,
    _flow,
    _RecordingBackgroundTasks,
    _rerun_result,
    _result_file,
    _review_checkpoint,
    _run,
    _service_key,
)


@pytest.mark.asyncio
async def test_get_flow_graph_uses_run_version_snapshot_when_run_id_supplied():
    container = MagicMock()
    flow_service = AsyncMock()
    flow_run_service = AsyncMock()
    container.flow_service.return_value = flow_service
    container.flow_run_service.return_value = flow_run_service
    _enable_space_access(container)

    flow_id = uuid4()
    live_flow = _flow(flow_id)
    run = _run(flow_id=flow_id, tenant_id=live_flow.tenant_id)
    snapshot_step_id = uuid4()
    flow_service.get_flow.return_value = live_flow
    definition_json = {
        "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
        "flow_id": str(flow_id),
        "steps": [
            {
                "step_id": str(snapshot_step_id),
                "step_order": 1,
                "assistant_id": str(uuid4()),
                "user_description": "Snapshot step",
                "input_source": "flow_input",
                "input_type": "text",
                "output_mode": "pass_through",
                "output_type": "json",
            }
        ],
    }
    flow_run_service.get_run_versioned_view.return_value = FlowRunVersionedView(
        published_definition=parse_published_definition(
            definition_json,
            flow_version=run.flow_version,
        ),
        step_results=(
            FlowStepResult(
                id=uuid4(),
                flow_run_id=run.id,
                flow_id=flow_id,
                tenant_id=run.tenant_id,
                step_id=snapshot_step_id,
                step_order=1,
                num_tokens_input=5,
                num_tokens_output=9,
                status=FlowStepResultStatus.COMPLETED,
                error_message=None,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ),
        ),
    )

    graph = await get_flow_graph(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        run_id=run.id,
        container=container,
    )

    llm_nodes = [node for node in graph.nodes if node.type == "llm"]
    assert len(llm_nodes) == 1
    assert llm_nodes[0].id == str(snapshot_step_id)
    assert llm_nodes[0].label == "Snapshot step"
    # enforce_flow_scope now always loads the flow for space membership checks,
    # but the graph should still be built from the version snapshot, not live flow.
    flow_run_service.get_run_versioned_view.assert_awaited_once_with(
        flow_id=flow_id,
        run_id=run.id,
    )
    flow_run_service.get_run.assert_not_awaited()
    flow_run_service.list_step_results.assert_not_awaited()
    container.flow_version_repo.assert_not_called()


@pytest.mark.asyncio
async def test_get_flow_graph_rejects_run_snapshot_without_executable_steps():
    container = MagicMock()
    flow_service = AsyncMock()
    flow_run_service = AsyncMock()
    container.flow_service.return_value = flow_service
    container.flow_run_service.return_value = flow_run_service
    _enable_space_access(container)

    flow_id = uuid4()
    live_flow = _flow(flow_id)
    run = _run(flow_id=flow_id, tenant_id=live_flow.tenant_id)
    flow_service.get_flow.return_value = live_flow
    flow_run_service.get_run_versioned_view.side_effect = (
        FlowPublishedDefinitionWithoutExecutableStepsError(
            flow_id=flow_id,
            flow_version=run.flow_version,
        )
    )

    with pytest.raises(FlowPublishedDefinitionWithoutExecutableStepsError) as exc_info:
        await get_flow_graph(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            run_id=run.id,
            container=container,
        )

    assert exc_info.value.flow_id == flow_id
    assert exc_info.value.flow_version == run.flow_version
    flow_run_service.get_run_versioned_view.assert_awaited_once_with(
        flow_id=flow_id,
        run_id=run.id,
    )
    flow_run_service.list_step_results.assert_not_awaited()
    container.flow_version_repo.assert_not_called()


@pytest.mark.asyncio
async def test_get_flow_graph_uses_live_flow_when_run_id_missing():
    container = MagicMock()
    flow_service = AsyncMock()
    container.flow_service.return_value = flow_service
    container.flow_run_service.return_value = AsyncMock()
    _enable_space_access(container)

    flow_id = uuid4()
    live_flow = _flow(flow_id)
    flow_service.get_flow.return_value = live_flow

    graph = await get_flow_graph(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        run_id=None,
        container=container,
    )

    llm_nodes = [node for node in graph.nodes if node.type == "llm"]
    assert len(llm_nodes) == 1
    assert llm_nodes[0].label == "Step 1"
    container.flow_run_service.return_value.get_run_versioned_view.assert_not_awaited()
    container.flow_version_repo.assert_not_called()


@pytest.mark.asyncio
async def test_create_flow_run_allows_service_key_principals():
    container = MagicMock()
    flow_service = AsyncMock()
    flow_run_service = AsyncMock()
    audit_service = AsyncMock()
    container.flow_service.return_value = flow_service
    container.flow_run_service.return_value = flow_run_service
    container.audit_service.return_value = audit_service
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
        active_api_key=_service_key(),
    )
    container.user.return_value.active_api_key.service_principal_id = uuid4()
    _enable_space_access(container, user_permissions=[Permission.FLOWS])

    flow = _flow(uuid4())
    run = _run(
        flow_id=flow.id,
        tenant_id=container.user.return_value.tenant_id,
    ).model_copy(update={"status": FlowRunStatus.QUEUED})
    flow_run_service.create_run.return_value = CreateRunResult(run=run, created=True)
    flow_service.get_flow.return_value = flow

    response = await create_flow_run(
        id=flow.id,
        request=SimpleNamespace(state=SimpleNamespace(), headers={}),
        run_in=FlowRunCreateRequest(input_payload_json={"text": "hello"}),
        background_tasks=BackgroundTasks(),
        container=container,
    )

    assert response.id == run.id
    flow_run_service.create_run.assert_awaited_once()
    audit_service.log_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_flow_run_schedules_background_dispatch():
    container = MagicMock()
    flow_run_service = AsyncMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id).model_copy(
        update={"status": FlowRunStatus.QUEUED}
    )
    flow_run_service.create_run.return_value = CreateRunResult(run=run, created=True)
    events: list[str] = []

    container.flow_run_service.return_value = flow_run_service
    container.flow_service.return_value = AsyncMock()
    container.audit_service.return_value = audit_service
    container.user.return_value = user
    _enable_space_access(container)
    _enable_explicit_transaction(container, events)

    background_tasks = _RecordingBackgroundTasks(events)
    run_in = FlowRunCreateRequest(input_payload_json={"case_id": "123"})

    response = await create_flow_run(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace(), headers={}),
        run_in=run_in,
        background_tasks=background_tasks,
        container=container,
    )

    assert response.id == run.id
    assert events == [
        "transaction_enter",
        "transaction_exit",
        "add_task",
    ]
    assert len(background_tasks.tasks) == 1
    scheduled = background_tasks.tasks[0]
    assert scheduled.func is dispatch_flow_run_recoverably_after_commit
    assert scheduled.kwargs == {
        "run_id": run.id,
        "tenant_id": user.tenant_id,
        "expected_revision": run.revision,
    }
    flow_run_service.create_run.assert_awaited_once_with(
        flow_id=flow_id,
        input_payload_json={"case_id": "123"},
        expected_flow_version=None,
        step_inputs=None,
        idempotency_key=None,
    )
    audit_service.log_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_flow_run_replay_skips_creation_audit_and_dispatch():
    container = MagicMock()
    flow_run_service = AsyncMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id).model_copy(
        update={"status": FlowRunStatus.QUEUED}
    )
    flow_run_service.create_run.return_value = CreateRunResult(run=run, created=False)
    container.flow_run_service.return_value = flow_run_service
    container.flow_service.return_value = AsyncMock()
    container.audit_service.return_value = audit_service
    container.user.return_value = user
    _enable_space_access(container)
    events: list[str] = []
    _enable_explicit_transaction(container, events)

    background_tasks = _RecordingBackgroundTasks(events)

    response = await create_flow_run(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace(), headers={}),
        run_in=FlowRunCreateRequest(input_payload_json={"case_id": "123"}),
        background_tasks=background_tasks,
        idempotency_key="idem-123",
        container=container,
    )

    assert response.id == run.id
    assert events == ["transaction_enter", "transaction_exit"]
    assert background_tasks.tasks == []
    audit_service.log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_review_replay_projects_completed_run_result(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    step_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id).model_copy(
        update={"output_payload_json": {"text": "Reviewed report"}}
    )
    checkpoint = _review_checkpoint(
        flow_id=flow_id,
        run_id=run.id,
        tenant_id=user.tenant_id,
        step_id=step_id,
    )
    checkpoint_public = FlowAssembler().to_review_checkpoint_public(
        checkpoint.model_copy(
            update={
                "requester_user_id": uuid4(),
                "decided_by_user_id": uuid4(),
            }
        )
    )
    final_output = FlowFinalOutputContractPublic(
        step_id=step_id,
        step_order=1,
        output_type=FlowOutputType.TEXT,
        output_mode=FlowOutputMode.PASS_THROUGH,
        delivery=FlowOutputDelivery.PAYLOAD,
    )
    run_service = AsyncMock()
    run_service.enrich_run_with_result_files_and_token_usage.return_value = (
        FlowRunWithResultFilesAndTokenUsage(
            run=run,
            result_files=(),
            token_usage=None,
            final_output=final_output,
        )
    )
    review_service = AsyncMock()
    review_service.resume_review_checkpoint.return_value = SimpleNamespace(
        checkpoint=checkpoint,
        run=run,
        accepted=False,
    )
    container.flow_run_service.return_value = run_service
    container.flow_run_review_checkpoint_service.return_value = review_service
    container.flow_service.return_value = AsyncMock()
    container.user.return_value = user
    _enable_space_access(container)
    monkeypatch.setattr(
        review_router_module,
        "_present_review_checkpoint",
        AsyncMock(return_value=checkpoint_public),
    )

    response = await resume_flow_run_review_checkpoint(
        id=flow_id,
        run_id=run.id,
        checkpoint_id=checkpoint.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        review_in=FlowRunReviewCheckpointResumeRequest(
            expected_checkpoint_revision=checkpoint.revision
        ),
        background_tasks=BackgroundTasks(),
        idempotency_key="completed-review-replay",
        container=container,
    )

    assert response.run.result is not None
    assert response.run.result.kind == "inline_text"
    assert response.run.result.text == "Reviewed report"
    run_service.enrich_run_with_result_files_and_token_usage.assert_awaited_once_with(
        run=run,
    )


@pytest.mark.asyncio
async def test_create_flow_run_forwards_idempotency_key():
    container = MagicMock()
    flow_run_service = AsyncMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id).model_copy(
        update={"status": FlowRunStatus.QUEUED}
    )
    flow_run_service.create_run.return_value = CreateRunResult(run=run, created=True)
    container.flow_run_service.return_value = flow_run_service
    container.flow_service.return_value = AsyncMock()
    container.audit_service.return_value = audit_service
    container.user.return_value = user
    _enable_space_access(container)

    await create_flow_run(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        run_in=FlowRunCreateRequest(input_payload_json={"case_id": "123"}),
        background_tasks=BackgroundTasks(),
        idempotency_key="idem-123",
        container=container,
    )

    flow_run_service.create_run.assert_awaited_once_with(
        flow_id=flow_id,
        input_payload_json={"case_id": "123"},
        expected_flow_version=None,
        step_inputs=None,
        idempotency_key="idem-123",
    )


@pytest.mark.asyncio
async def test_create_flow_run_handles_missing_headers_object():
    container = MagicMock()
    flow_run_service = AsyncMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id).model_copy(
        update={"status": FlowRunStatus.QUEUED}
    )
    flow_run_service.create_run.return_value = CreateRunResult(run=run, created=True)
    container.flow_run_service.return_value = flow_run_service
    container.flow_service.return_value = AsyncMock()
    container.audit_service.return_value = audit_service
    container.user.return_value = user
    _enable_space_access(container)

    await create_flow_run(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        run_in=FlowRunCreateRequest(input_payload_json={"case_id": "123"}),
        background_tasks=BackgroundTasks(),
        container=container,
    )

    assert flow_run_service.create_run.await_args.kwargs["idempotency_key"] is None


@pytest.mark.asyncio
async def test_rerun_flow_run_step_calls_service_and_schedules_recoverable_dispatch(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    step_id = uuid4()
    input_file_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id).model_copy(
        update={"revision": 2, "status": FlowRunStatus.QUEUED}
    )
    rerun_result = _rerun_result(run, step_id, invalidated_step_ids=(step_id, uuid4()))
    events: list[str] = []
    run_service = AsyncMock()
    rerun_service = AsyncMock()
    rerun_service.rerun_step.return_value = rerun_result

    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_run_service.return_value = run_service
    container.flow_run_rerun_service.return_value = rerun_service
    container.flow_service.return_value = flow_service
    container.user.return_value = user
    container.audit_service.return_value = AsyncMock()
    _enable_space_access(container, user_permissions=[Permission.FLOWS_MANAGE])
    _enable_explicit_transaction(container, events)
    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    background_tasks = _RecordingBackgroundTasks(events)
    response = await rerun_flow_run_step(
        id=flow_id,
        run_id=run.id,
        step_id=step_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        rerun_in=FlowRunStepRerunRequest(
            expected_run_revision=1,
            reason="Reviewer accepted corrected transcription",
            input_payload_json={"reviewer_note": "corrected"},
            step_inputs={step_id: {"file_ids": [input_file_id]}},
        ),
        background_tasks=background_tasks,
        container=container,
    )

    assert response.operation_id == rerun_result.operation.id
    assert events == [
        "transaction_enter",
        "transaction_exit",
        "add_task",
    ]
    assert response.run.id == run.id
    assert response.run.revision == 2
    assert response.rerun_step_id == step_id
    assert response.new_attempt_no == 2
    assert response.invalidated_step_ids == [
        step.step_id for step in rerun_result.invalidated_steps
    ]
    assert response.status == FlowRunRerunOperationStatus.QUEUED
    rerun_service.rerun_step.assert_awaited_once_with(
        flow_id=flow_id,
        run_id=run.id,
        rerun_step_id=step_id,
        expected_run_revision=1,
        reason="Reviewer accepted corrected transcription",
        input_payload_json={"reviewer_note": "corrected"},
        step_inputs={step_id: FlowRunStepInputFiles(file_ids=(input_file_id,))},
    )
    audit_kwargs = container.audit_service.return_value.log_async.await_args.kwargs
    assert audit_kwargs["tenant_id"] == user.tenant_id
    assert audit_kwargs["actor_id"] == user.id
    assert audit_kwargs["action"] == ActionType.FLOW_RUN_RERUN_REQUESTED
    assert audit_kwargs["entity_id"] == run.id
    assert audit_kwargs["description"] == (
        f"Requested rerun for flow run {run.id} step {step_id}"
    )
    assert audit_kwargs["metadata"]["extra"] == {
        "flow_id": str(flow_id),
        "rerun_operation_id": str(rerun_result.operation.id),
        "rerun_step_id": str(step_id),
        "rerun_created": True,
    }
    assert len(background_tasks.tasks) == 1
    scheduled = background_tasks.tasks[0]
    assert scheduled.func is dispatch_flow_run_recoverably_after_commit
    assert scheduled.kwargs == {
        "run_id": run.id,
        "tenant_id": user.tenant_id,
        "expected_revision": run.revision,
    }


@pytest.mark.asyncio
async def test_rerun_flow_run_step_replay_does_not_schedule_dispatch(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    step_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id).model_copy(
        update={"output_payload_json": {"text": "Rerun finished"}}
    )
    rerun_result = _rerun_result(
        run,
        step_id,
        created=False,
        status=FlowRunRerunOperationStatus.COMPLETED,
    )
    run_service = AsyncMock()
    run_service.enrich_run_with_result_files_and_token_usage.return_value = (
        FlowRunWithResultFilesAndTokenUsage(
            run=run,
            result_files=(),
            token_usage=None,
            final_output=FlowFinalOutputContractPublic(
                step_id=step_id,
                step_order=1,
                output_type=FlowOutputType.TEXT,
                output_mode=FlowOutputMode.PASS_THROUGH,
                delivery=FlowOutputDelivery.PAYLOAD,
            ),
        )
    )
    rerun_service = AsyncMock()
    rerun_service.rerun_step.return_value = rerun_result
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_run_service.return_value = run_service
    container.flow_run_rerun_service.return_value = rerun_service
    container.flow_service.return_value = flow_service
    container.user.return_value = user
    container.audit_service.return_value = AsyncMock()
    _enable_space_access(container, user_permissions=[Permission.FLOWS_MANAGE])
    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    background_tasks = BackgroundTasks()
    response = await rerun_flow_run_step(
        id=flow_id,
        run_id=run.id,
        step_id=step_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        rerun_in=FlowRunStepRerunRequest(
            expected_run_revision=1,
            reason="Replay existing request",
        ),
        background_tasks=background_tasks,
        container=container,
    )

    assert response.status == FlowRunRerunOperationStatus.COMPLETED
    assert response.run.result is not None
    assert response.run.result.kind == "inline_text"
    assert response.run.result.text == "Rerun finished"
    assert background_tasks.tasks == []
    rerun_service.rerun_step.assert_awaited_once()
    run_service.enrich_run_with_result_files_and_token_usage.assert_awaited_once_with(
        run=run,
    )
    audit_kwargs = container.audit_service.return_value.log_async.await_args.kwargs
    assert audit_kwargs["action"] == ActionType.FLOW_RUN_RERUN_REQUESTED
    assert audit_kwargs["metadata"]["extra"]["rerun_created"] is False


@pytest.mark.asyncio
async def test_rerun_flow_run_step_stale_revision_does_not_schedule_dispatch(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    run_id = uuid4()
    step_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run_service = AsyncMock()
    rerun_service = AsyncMock()
    rerun_service.rerun_step.side_effect = BadRequestException(
        "Flow run revision is stale.",
        code="flow_run_rerun_stale_revision",
    )
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_run_service.return_value = run_service
    container.flow_run_rerun_service.return_value = rerun_service
    container.flow_service.return_value = flow_service
    container.user.return_value = user
    _enable_space_access(container, user_permissions=[Permission.FLOWS_MANAGE])
    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    background_tasks = BackgroundTasks()
    with pytest.raises(BadRequestException) as exc_info:
        await rerun_flow_run_step(
            id=flow_id,
            run_id=run_id,
            step_id=step_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            rerun_in=FlowRunStepRerunRequest(
                expected_run_revision=1,
                reason="Stale request",
            ),
            background_tasks=background_tasks,
            container=container,
        )

    assert exc_info.value.code == "flow_run_rerun_stale_revision"
    assert background_tasks.tasks == []
    rerun_service.rerun_step.assert_awaited_once()


@pytest.mark.asyncio
async def test_flow_run_endpoints_delegate_to_run_service(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4()).model_copy(
        update={"status": FlowRunStatus.QUEUED}
    )
    result_file = _result_file(run=run)
    delivery_now = datetime.now(timezone.utc)
    webhook_delivery = FlowRunWebhookDeliveryRead(
        id=uuid4(),
        step_id=uuid4(),
        step_order=2,
        attempt_no=1,
        delivery_status=FlowOutboxDeliveryStatus.DEAD_LETTERED,
        delivery_attempts=5,
        next_delivery_at=None,
        delivered_at=None,
        dead_lettered_at=delivery_now,
        created_at=delivery_now,
        updated_at=delivery_now,
    )
    run_service = AsyncMock()
    run_service.list_runs_with_result_files_and_token_usage.return_value = (
        FlowRunPageWithResultFilesAndTokenUsage(
            items=(
                FlowRunWithResultFilesAndTokenUsage(
                    run=run,
                    result_files=(result_file,),
                    token_usage=None,
                ),
            ),
            has_more=False,
        )
    )
    run_service.get_run_detail_with_result_files_and_token_usage.return_value = (
        FlowRunDetailView(
            run=run,
            result_files=(result_file,),
            token_usage=None,
            webhook_deliveries=(webhook_delivery,),
        )
    )
    run_service.list_step_results_with_files.return_value = ()
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)
    request = SimpleNamespace(state=SimpleNamespace())

    list_response = await list_flow_runs(
        id=flow_id,
        request=request,
        limit=20,
        offset=2,
        container=container,
    )
    get_response = await get_flow_run(
        id=flow_id,
        run_id=run.id,
        request=request,
        container=container,
    )
    step_response = await list_flow_run_steps(
        id=flow_id,
        run_id=run.id,
        request=request,
        container=container,
    )

    assert list_response["count"] == 1
    assert list_response["has_more"] is False
    assert list_response["items"][0].result_files == [result_file]
    assert get_response.id == run.id
    assert get_response.result_files == [result_file]
    assert len(get_response.webhook_deliveries) == 1
    public_delivery = get_response.webhook_deliveries[0]
    assert public_delivery.delivery_status == "dead_lettered"
    assert public_delivery.delivery_attempts == 5
    assert set(public_delivery.model_dump()) == {
        "id",
        "step_id",
        "step_order",
        "attempt_no",
        "delivery_status",
        "delivery_attempts",
        "next_delivery_at",
        "delivered_at",
        "dead_lettered_at",
        "created_at",
        "updated_at",
    }
    assert step_response == []
    # get_flow is called once per endpoint (3 total) via enforce_flow_scope space check
    assert flow_service.get_flow.await_count == 3
    run_service.list_runs_with_result_files_and_token_usage.assert_awaited_once_with(
        flow_id=flow_id, statuses=None, limit=20, offset=2
    )
    run_service.get_run_detail_with_result_files_and_token_usage.assert_awaited_once_with(
        run_id=run.id, flow_id=flow_id
    )
    run_service.list_runs.assert_not_awaited()
    run_service.get_run.assert_not_awaited()
    run_service.list_step_results_with_files.assert_awaited_once_with(
        run_id=run.id, flow_id=flow_id
    )


@pytest.mark.asyncio
async def test_list_flow_runs_raises_not_found_when_flow_missing_without_scope_filter(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    run_service = AsyncMock()
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.side_effect = NotFoundException("Flow not found.")
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

    with pytest.raises(NotFoundException):
        await list_flow_runs(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            limit=20,
            offset=0,
            container=container,
        )

    run_service.list_runs.assert_not_awaited()
    run_service.list_runs_with_result_files_and_token_usage.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_flow_run_uses_terminalizer_audit_only(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id)
    cancelled_run = run.model_copy(update={"status": FlowRunStatus.CANCELLED})
    events: list[str] = []

    async def _cancel_run(**_kwargs):
        events.append("cancel_run")
        return cancelled_run

    run_service = AsyncMock()
    run_service.cancel_run.side_effect = _cancel_run
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service
    container.user.return_value = user
    container.audit_service.return_value = AsyncMock()

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)
    _enable_explicit_transaction(container, events)

    response = await cancel_flow_run(
        id=flow_id,
        run_id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response.id == cancelled_run.id
    assert events == [
        "transaction_enter",
        "cancel_run",
        "transaction_exit",
    ]
    run_service.get_run.assert_not_awaited()
    run_service.cancel_run.assert_awaited_once_with(run_id=run.id, flow_id=flow_id)
    container.audit_service.return_value.log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_redispatch_flow_run_uses_run_scoped_dispatch_and_audits(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id).model_copy(
        update={"status": FlowRunStatus.QUEUED}
    )
    refreshed = _run(flow_id=flow_id, tenant_id=user.tenant_id).model_copy(
        update={"status": FlowRunStatus.QUEUED}
    )
    events: list[str] = []
    run_service = AsyncMock()
    run_service.get_run.side_effect = [run, refreshed]
    container.flow_run_service.return_value = run_service
    container.user.return_value = user

    async def _dispatch(**_kwargs):
        events.append("dispatch")
        return FlowRunDispatchAccepted(run=refreshed)

    dispatch = AsyncMock(side_effect=_dispatch)

    async def enforce_scope(*_args, **_kwargs):
        events.append("scope")

    monkeypatch.setattr(flow_access_context_module, "enforce_flow_scope", enforce_scope)
    monkeypatch.setattr(
        lifecycle_router_module,
        "redrive_flow_run_recoverably_after_commit",
        dispatch,
    )

    response = await redispatch_flow_run(
        id=flow_id,
        run_id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
        payload=FlowRunRedispatchRequest(expected_dispatch_exhausted_at=run.created_at),
    )

    assert response.run.id == refreshed.id
    assert response.redispatched_count == 1
    assert events == [
        "scope",
        "dispatch",
    ]
    assert run_service.get_run.await_count == 1
    assert run_service.get_run.await_args_list[0].kwargs == {
        "run_id": run.id,
        "flow_id": flow_id,
    }
    dispatch.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=run.tenant_id,
        expected_revision=run.revision,
        actor_id=user.id,
        actor_type=ActorType.USER,
        actor_api_key_id=None,
        audit_metadata=AuditMetadata.standard(actor=user, target=run),
        expected_dispatch_exhausted_at=run.created_at,
    )


@pytest.mark.asyncio
async def test_redispatch_flow_run_returns_zero_when_nothing_redispatched(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id).model_copy(
        update={"output_payload_json": {"text": "Already finished"}}
    )
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.enrich_run_with_result_files_and_token_usage.return_value = (
        FlowRunWithResultFilesAndTokenUsage(
            run=run,
            result_files=(),
            token_usage=None,
            final_output=FlowFinalOutputContractPublic(
                step_id=uuid4(),
                step_order=1,
                output_type=FlowOutputType.TEXT,
                output_mode=FlowOutputMode.PASS_THROUGH,
                delivery=FlowOutputDelivery.PAYLOAD,
            ),
        )
    )
    container.flow_run_service.return_value = run_service
    container.user.return_value = user
    container.audit_service.return_value = AsyncMock()

    dispatch = AsyncMock(return_value=FlowRunDispatchNotClaimed(run=run))

    async def enforce_scope(*_args, **_kwargs):
        return None

    monkeypatch.setattr(flow_access_context_module, "enforce_flow_scope", enforce_scope)
    monkeypatch.setattr(
        lifecycle_router_module,
        "redrive_flow_run_recoverably_after_commit",
        dispatch,
    )

    response = await redispatch_flow_run(
        id=flow_id,
        run_id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
        payload=FlowRunRedispatchRequest(),
    )

    assert response.run.id == run.id
    assert response.run.result is not None
    assert response.run.result.kind == "inline_text"
    assert response.run.result.text == "Already finished"
    assert response.redispatched_count == 0
    assert run_service.get_run.await_count == 1
    dispatch.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=run.tenant_id,
        expected_revision=run.revision,
        actor_id=user.id,
        actor_type=ActorType.USER,
        actor_api_key_id=None,
        audit_metadata=AuditMetadata.standard(actor=user, target=run),
        expected_dispatch_exhausted_at=None,
    )
    run_service.enrich_run_with_result_files_and_token_usage.assert_awaited_once_with(
        run=run
    )


@pytest.mark.asyncio
async def test_redispatch_flow_run_translates_exhaustion_generation_conflict(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id).model_copy(
        update={"status": FlowRunStatus.QUEUED}
    )
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    container.flow_run_service.return_value = run_service
    container.user.return_value = user
    dispatch = AsyncMock(
        side_effect=FlowRunDispatchExhaustionGenerationConflictError(
            current_dispatch_exhausted_at=run.created_at
        )
    )

    async def enforce_scope(*_args, **_kwargs):
        return None

    monkeypatch.setattr(flow_access_context_module, "enforce_flow_scope", enforce_scope)
    monkeypatch.setattr(
        lifecycle_router_module,
        "redrive_flow_run_recoverably_after_commit",
        dispatch,
    )

    with pytest.raises(ConflictException) as exc_info:
        await redispatch_flow_run(
            id=flow_id,
            run_id=run.id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=container,
            payload=FlowRunRedispatchRequest(),
        )

    assert exc_info.value.code == "flow_run_redispatch_conflict"
    assert exc_info.value.context == {"run_id": str(run.id)}
    dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_redispatch_flow_run_translates_dispatch_error(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id)
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    container.flow_run_service.return_value = run_service
    container.user.return_value = user
    container.audit_service.return_value = AsyncMock()

    dispatch = AsyncMock(return_value=FlowRunDispatchFailed(run=run))

    async def enforce_scope(*_args, **_kwargs):
        return None

    monkeypatch.setattr(flow_access_context_module, "enforce_flow_scope", enforce_scope)
    monkeypatch.setattr(
        lifecycle_router_module,
        "redrive_flow_run_recoverably_after_commit",
        dispatch,
    )

    with pytest.raises(InternalServerException) as exc_info:
        await redispatch_flow_run(
            id=flow_id,
            run_id=run.id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=container,
            payload=FlowRunRedispatchRequest(),
        )

    assert exc_info.value.__cause__ is None
    dispatch.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=run.tenant_id,
        expected_revision=run.revision,
        actor_id=user.id,
        actor_type=ActorType.USER,
        actor_api_key_id=None,
        audit_metadata=AuditMetadata.standard(actor=user, target=run),
        expected_dispatch_exhausted_at=None,
    )


@pytest.mark.asyncio
async def test_redispatch_flow_run_checks_scope_before_service_or_backend(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run_id = uuid4()
    events: list[str] = []

    async def enforce_scope(*_args, **_kwargs):
        events.append("scope")
        raise NotFoundException("Flow not found.")

    def flow_run_service():
        events.append("service")
        return AsyncMock()

    monkeypatch.setattr(flow_access_context_module, "enforce_flow_scope", enforce_scope)
    container.flow_run_service.side_effect = flow_run_service
    container.audit_service.return_value = AsyncMock()

    with pytest.raises(NotFoundException):
        await redispatch_flow_run(
            id=flow_id,
            run_id=run_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=container,
            payload=FlowRunRedispatchRequest(),
        )

    assert events == ["scope"]
    container.audit_service.return_value.log_async.assert_not_awaited()
