from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks
from fastapi import HTTPException
from fastapi import UploadFile

from intric.authentication.auth_dependencies import ScopeFilter
from intric.flows.flow import Flow, FlowRun, FlowRunStatus, FlowStep, FlowVersion
from intric.flows.api.flow_models import (
    FlowAssistantCreateRequest,
    FlowCreateRequest,
    FlowRunCreateRequest,
    FlowStepCreateRequest,
)
from intric.flows.api.flow_router import (
    create_flow,
    create_flow_assistant,
    create_flow_run,
    get_flow_input_policy,
    get_flow_run_alias,
    get_flow_graph,
    list_flow_run_steps,
    list_flow_runs_alias,
    upload_flow_file,
    update_flow_assistant,
)
from intric.settings.settings import FlowInputLimitsPublic
from intric.assistants.api.assistant_models import AssistantUpdatePublic
from intric.main.exceptions import BadRequestException


def _flow_step(step_id, step_order: int) -> FlowStep:
    return FlowStep(
        id=step_id,
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=f"Step {step_order}",
        input_source="flow_input" if step_order == 1 else "previous_step",
        input_type="text",
        output_mode="pass_through",
        output_type="json",
        mcp_policy="inherit",
    )


def _flow(flow_id):
    now = datetime.now(timezone.utc)
    return Flow(
        id=flow_id,
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Flow",
        description=None,
        created_by_user_id=uuid4(),
        owner_user_id=uuid4(),
        published_version=1,
        metadata_json=None,
        data_retention_days=None,
        created_at=now,
        updated_at=now,
        steps=[_flow_step(uuid4(), 1)],
    )


def _run(flow_id, tenant_id):
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=flow_id,
        flow_version=1,
        user_id=uuid4(),
        tenant_id=tenant_id,
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json=None,
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_get_flow_graph_uses_run_version_snapshot_when_run_id_supplied():
    container = MagicMock()
    flow_service = AsyncMock()
    flow_run_service = AsyncMock()
    flow_version_repo = AsyncMock()
    container.flow_service.return_value = flow_service
    container.flow_run_service.return_value = flow_run_service
    container.flow_version_repo.return_value = flow_version_repo

    flow_id = uuid4()
    live_flow = _flow(flow_id)
    run = _run(flow_id=flow_id, tenant_id=live_flow.tenant_id)
    flow_service.get_flow.return_value = live_flow
    flow_run_service.get_run.return_value = run
    flow_run_service.get_evidence.return_value = {
        "run": run.model_dump(mode="json"),
        "definition_snapshot": {"steps": []},
        "step_results": [
            {
                "step_id": None,
                "step_order": 1,
                "status": "completed",
                "num_tokens_input": 5,
                "num_tokens_output": 9,
                "error_message": None,
            }
        ],
        "step_attempts": [],
    }
    snapshot_step_id = uuid4()
    flow_version_repo.get.return_value = FlowVersion(
        flow_id=flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": str(snapshot_step_id),
                    "step_order": 1,
                    "user_description": "Snapshot step",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "json",
                    "mcp_policy": "inherit",
                }
            ]
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    graph = await get_flow_graph(id=flow_id, run_id=run.id, container=container)

    llm_nodes = [node for node in graph.nodes if node["type"] == "llm"]
    assert len(llm_nodes) == 1
    assert llm_nodes[0]["id"] == str(snapshot_step_id)
    assert llm_nodes[0]["label"] == "Snapshot step"
    flow_service.get_flow.assert_not_called()


@pytest.mark.asyncio
async def test_get_flow_graph_uses_live_flow_when_run_id_missing():
    container = MagicMock()
    flow_service = AsyncMock()
    container.flow_service.return_value = flow_service
    container.flow_run_service.return_value = AsyncMock()
    container.flow_version_repo.return_value = AsyncMock()

    flow_id = uuid4()
    live_flow = _flow(flow_id)
    flow_service.get_flow.return_value = live_flow

    graph = await get_flow_graph(id=flow_id, run_id=None, container=container)

    llm_nodes = [node for node in graph.nodes if node["type"] == "llm"]
    assert len(llm_nodes) == 1
    assert llm_nodes[0]["label"] == "Step 1"


@pytest.mark.asyncio
async def test_create_flow_run_schedules_background_dispatch():
    container = MagicMock()
    flow_run_service = AsyncMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id)
    flow_run_service.create_run.return_value = run
    container.flow_run_service.return_value = flow_run_service
    container.audit_service.return_value = audit_service
    container.user.return_value = user

    background_tasks = BackgroundTasks()
    run_in = FlowRunCreateRequest(input_payload_json={"case_id": "123"})

    response = await create_flow_run(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        run_in=run_in,
        background_tasks=background_tasks,
        container=container,
    )

    assert response.id == run.id
    assert len(background_tasks.tasks) == 1
    flow_run_service.create_run.assert_awaited_once_with(
        flow_id=flow_id,
        input_payload_json={"case_id": "123"},
        file_ids=None,
    )
    audit_service.log_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_flow_run_rejects_scope_mismatch(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run_service = AsyncMock()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_run_service.return_value = run_service
    container.flow_service.return_value = flow_service

    router_module = __import__("intric.flows.api.flow_router", fromlist=["get_scope_filter"])
    monkeypatch.setattr(
        router_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=uuid4()),
    )

    with pytest.raises(HTTPException) as exc:
        await create_flow_run(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            run_in=FlowRunCreateRequest(input_payload_json={"x": 1}),
            background_tasks=BackgroundTasks(),
            container=container,
        )

    assert exc.value.status_code == 403
    run_service.create_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_flow_run_after_commit_marks_failed_on_dispatch_error(monkeypatch):
    router_module = __import__("intric.flows.api.flow_router", fromlist=["_dispatch_flow_run_after_commit"])

    run_repo = AsyncMock()
    backend = MagicMock()
    backend.dispatch = AsyncMock(side_effect=RuntimeError("broker down"))

    fake_session = MagicMock()

    class _BeginContext:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _SessionContext:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    fake_session.begin = lambda: _BeginContext()

    class _FakeContainer:
        def flow_execution_backend(self):
            return backend

        def flow_run_repo(self):
            return run_repo

    monkeypatch.setattr(router_module.sessionmanager, "session", lambda: _SessionContext())
    monkeypatch.setattr(router_module, "Container", lambda session: _FakeContainer())

    run_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()

    await router_module._dispatch_flow_run_after_commit(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        user_id=uuid4(),
    )

    run_repo.update_status.assert_awaited_once()
    kwargs = run_repo.update_status.await_args.kwargs
    assert kwargs["run_id"] == run_id
    assert kwargs["tenant_id"] == tenant_id
    assert kwargs["status"] == FlowRunStatus.FAILED
    assert kwargs["error_message"].startswith("Flow dispatch failed:")


@pytest.mark.asyncio
async def test_create_flow_rejects_space_scope_mismatch(monkeypatch):
    container = MagicMock()
    container.flow_service.return_value = AsyncMock()
    container.user.return_value = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    container.audit_service.return_value = AsyncMock()

    router_module = __import__("intric.flows.api.flow_router", fromlist=["get_scope_filter"])
    allowed_space_id = uuid4()
    monkeypatch.setattr(
        router_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=allowed_space_id),
    )

    with pytest.raises(HTTPException) as exc:
        await create_flow(
            request=SimpleNamespace(state=SimpleNamespace()),
            flow_in=FlowCreateRequest(
                space_id=uuid4(),
                name="Flow",
                steps=[
                    FlowStepCreateRequest(
                        assistant_id=uuid4(),
                        step_order=1,
                        user_description="Step",
                        input_source="flow_input",
                        input_type="text",
                        output_mode="pass_through",
                        output_type="json",
                        mcp_policy="inherit",
                    )
                ],
            ),
            container=container,
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "insufficient_scope"


@pytest.mark.asyncio
async def test_create_flow_assistant_calls_flow_scoped_service():
    container = MagicMock()
    flow_service = AsyncMock()
    assistant_assembler = MagicMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    flow_id = uuid4()
    assistant = SimpleNamespace(
        id=uuid4(),
        name="Step assistant",
        space_id=uuid4(),
        type=SimpleNamespace(value="assistant"),
        completion_model_kwargs=None,
        data_retention_days=None,
        published=False,
    )
    flow_service.create_flow_assistant.return_value = (assistant, [])
    assistant_assembler.from_assistant_to_model.return_value = {"id": str(assistant.id)}
    container.flow_service.return_value = flow_service
    container.assistant_assembler.return_value = assistant_assembler
    container.audit_service.return_value = audit_service
    container.user.return_value = user

    response = await create_flow_assistant(
        id=flow_id,
        assistant_in=FlowAssistantCreateRequest(name="Step assistant"),
        container=container,
    )

    assert response["id"] == str(assistant.id)
    flow_service.create_flow_assistant.assert_awaited_once_with(
        flow_id=flow_id,
        name="Step assistant",
    )
    audit_service.log_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_flow_assistant_forwards_payload():
    container = MagicMock()
    flow_service = AsyncMock()
    assistant_assembler = MagicMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    flow_id = uuid4()
    assistant_id = uuid4()
    attachment_id = uuid4()
    website_id = uuid4()
    group_id = uuid4()
    integration_knowledge_id = uuid4()
    updated_assistant = SimpleNamespace(
        id=assistant_id,
        name="Updated assistant",
        space_id=uuid4(),
        type=SimpleNamespace(value="assistant"),
        completion_model_kwargs=None,
        data_retention_days=None,
        published=False,
    )
    flow_service.update_flow_assistant.return_value = (updated_assistant, [])
    assistant_assembler.from_assistant_to_model.return_value = {"id": str(assistant_id)}
    container.flow_service.return_value = flow_service
    container.assistant_assembler.return_value = assistant_assembler
    container.audit_service.return_value = audit_service
    container.user.return_value = user

    response = await update_flow_assistant(
        id=flow_id,
        assistant_id=assistant_id,
        assistant_in=AssistantUpdatePublic(
            name="Updated assistant",
            attachments=[{"id": attachment_id}],
            websites=[{"id": website_id}],
            groups=[{"id": group_id}],
            integration_knowledge_list=[{"id": integration_knowledge_id}],
        ),
        container=container,
    )

    assert response["id"] == str(assistant_id)
    flow_service.update_flow_assistant.assert_awaited_once()
    kwargs = flow_service.update_flow_assistant.await_args.kwargs
    assert kwargs["flow_id"] == flow_id
    assert kwargs["assistant_id"] == assistant_id
    assert kwargs["name"] == "Updated assistant"
    assert kwargs["attachment_ids"] == [attachment_id]
    assert kwargs["websites"] == [website_id]
    assert kwargs["groups"] == [group_id]
    assert kwargs["integration_knowledge_ids"] == [integration_knowledge_id]
    audit_service.log_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_flow_input_policy_for_audio_step_returns_audio_mime_and_limit(monkeypatch):
    container = MagicMock()
    flow_service = AsyncMock()
    settings_service = AsyncMock()
    flow_id = uuid4()

    step = _flow_step(uuid4(), 1).model_copy(update={"input_type": "audio"})
    flow_service.get_flow.return_value = _flow(flow_id).model_copy(update={"steps": [step]})
    settings_service.get_flow_input_limits.return_value = FlowInputLimitsPublic(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=25_000_000,
    )
    container.flow_service.return_value = flow_service
    container.settings_service.return_value = settings_service

    router_module = __import__("intric.flows.api.flow_router", fromlist=["get_scope_filter"])
    monkeypatch.setattr(
        router_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    policy = await get_flow_input_policy(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert policy.input_type == "audio"
    assert policy.accepts_file_upload is True
    assert policy.max_file_size_bytes == 25_000_000
    assert policy.max_files_per_run == 10
    assert policy.recommended_run_payload is not None
    assert policy.recommended_run_payload["file_ids"] == ["<file-id-uuid>"]
    assert "audio/mpeg" in policy.accepted_mimetypes


@pytest.mark.asyncio
async def test_upload_flow_file_rejects_when_flow_input_type_not_file_upload(monkeypatch):
    container = MagicMock()
    flow_service = AsyncMock()
    settings_service = AsyncMock()
    file_service = AsyncMock()
    flow_id = uuid4()

    step = _flow_step(uuid4(), 1).model_copy(update={"input_type": "text"})
    flow_service.get_flow.return_value = _flow(flow_id).model_copy(update={"steps": [step]})
    settings_service.get_flow_input_limits.return_value = FlowInputLimitsPublic(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=25_000_000,
    )
    container.flow_service.return_value = flow_service
    container.settings_service.return_value = settings_service
    container.file_service.return_value = file_service

    router_module = __import__("intric.flows.api.flow_router", fromlist=["get_scope_filter"])
    monkeypatch.setattr(
        router_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    upload = UploadFile(
        filename="audio.mp3",
        file=BytesIO(b"audio"),
        headers={"content-type": "audio/mpeg"},
    )

    with pytest.raises(BadRequestException):
        await upload_flow_file(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            upload_file=upload,
            container=container,
        )
    file_service.save_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_flow_file_uses_flow_limit_override(monkeypatch):
    container = MagicMock()
    flow_service = AsyncMock()
    settings_service = AsyncMock()
    file_service = AsyncMock()
    flow_id = uuid4()
    file_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())

    step = _flow_step(uuid4(), 1).model_copy(update={"input_type": "audio"})
    flow_service.get_flow.return_value = _flow(flow_id).model_copy(update={"steps": [step]})
    settings_service.get_flow_input_limits.return_value = FlowInputLimitsPublic(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=31_000_000,
    )
    file_service.save_file.return_value = SimpleNamespace(
        id=file_id,
        name="audio.mp3",
        size=1024,
        mimetype="audio/mpeg",
        file_type=SimpleNamespace(value="audio"),
        created_at=datetime.now(timezone.utc),
    )
    container.flow_service.return_value = flow_service
    container.settings_service.return_value = settings_service
    container.file_service.return_value = file_service
    container.user.return_value = user
    container.audit_service.return_value = AsyncMock()

    router_module = __import__("intric.flows.api.flow_router", fromlist=["get_scope_filter"])
    monkeypatch.setattr(
        router_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    monkeypatch.setattr(
        "intric.flows.flow_file_upload_service._sniff_mimetype",
        lambda _upload_file: "audio/mpeg",
    )

    upload = UploadFile(
        filename="audio.mp3",
        file=BytesIO(b"audio"),
        headers={"content-type": "audio/mpeg"},
    )

    result = await upload_flow_file(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        upload_file=upload,
        container=container,
    )

    assert result.id == file_id
    file_service.save_file.assert_awaited_once()
    assert file_service.save_file.await_args.kwargs["max_size"] == 31_000_000


@pytest.mark.asyncio
async def test_flow_run_alias_endpoints_delegate_to_run_service(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    run_service = AsyncMock()
    run_service.list_runs.return_value = [run]
    run_service.get_run.return_value = run
    run_service.list_step_results.return_value = []
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    router_module = __import__("intric.flows.api.flow_router", fromlist=["get_scope_filter"])
    monkeypatch.setattr(
        router_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    request = SimpleNamespace(state=SimpleNamespace())

    list_response = await list_flow_runs_alias(
        id=flow_id,
        request=request,
        limit=20,
        offset=2,
        container=container,
    )
    get_response = await get_flow_run_alias(
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
    assert get_response.id == run.id
    assert step_response == []
    run_service.list_runs.assert_awaited_once_with(flow_id=flow_id, limit=20, offset=2)
    run_service.get_run.assert_awaited_once_with(run_id=run.id, flow_id=flow_id)
    run_service.list_step_results.assert_awaited_once_with(run_id=run.id, flow_id=flow_id)


@pytest.mark.asyncio
async def test_flow_run_steps_alias_surfaces_diagnostics_dicts_only(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run_id = uuid4()
    run_service = AsyncMock()
    run_service.list_step_results.return_value = [
        SimpleNamespace(
            id=uuid4(),
            step_id=uuid4(),
            step_order=1,
            assistant_id=uuid4(),
            status="completed",
            input_payload_json={
                "diagnostics": [
                    {"code": "typed_io_transcript_near_limit", "severity": "info"},
                    "ignore-me",
                    {"code": "audio_transcribe_only_used", "severity": "info"},
                ]
            },
            output_payload_json={"text": "ok"},
            num_tokens_input=10,
            num_tokens_output=20,
            error_message=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    ]
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    router_module = __import__("intric.flows.api.flow_router", fromlist=["get_scope_filter"])
    monkeypatch.setattr(
        router_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    response = await list_flow_run_steps(
        id=flow_id,
        run_id=run_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert len(response) == 1
    assert len(response[0].diagnostics) == 2
    assert all(isinstance(item, dict) for item in response[0].diagnostics)


@pytest.mark.asyncio
async def test_flow_alias_endpoints_reject_scope_mismatch(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    run_service = AsyncMock()
    run_service.list_runs.return_value = [run]
    run_service.get_run.return_value = run
    run_service.list_step_results.return_value = []
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    router_module = __import__("intric.flows.api.flow_router", fromlist=["get_scope_filter"])
    wrong_space = uuid4()
    monkeypatch.setattr(
        router_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=wrong_space),
    )

    request = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(HTTPException) as list_exc:
        await list_flow_runs_alias(
            id=flow_id,
            request=request,
            limit=10,
            offset=0,
            container=container,
        )
    with pytest.raises(HTTPException) as get_exc:
        await get_flow_run_alias(
            id=flow_id,
            run_id=run.id,
            request=request,
            container=container,
        )

    assert list_exc.value.status_code == 403
    assert get_exc.value.status_code == 403
    run_service.list_runs.assert_not_awaited()
    run_service.get_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_flow_run_steps_alias_handles_non_list_diagnostics(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run_id = uuid4()
    run_service = AsyncMock()
    run_service.list_step_results.return_value = [
        SimpleNamespace(
            id=uuid4(),
            step_id=uuid4(),
            step_order=1,
            assistant_id=uuid4(),
            status="completed",
            input_payload_json={"diagnostics": {"code": "not-a-list"}},
            output_payload_json={"text": "ok"},
            num_tokens_input=10,
            num_tokens_output=20,
            error_message=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
        SimpleNamespace(
            id=uuid4(),
            step_id=uuid4(),
            step_order=2,
            assistant_id=uuid4(),
            status="completed",
            input_payload_json=None,
            output_payload_json={"text": "ok"},
            num_tokens_input=10,
            num_tokens_output=20,
            error_message=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
    ]
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    router_module = __import__("intric.flows.api.flow_router", fromlist=["get_scope_filter"])
    monkeypatch.setattr(
        router_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    response = await list_flow_run_steps(
        id=flow_id,
        run_id=run_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert len(response) == 2
    assert response[0].diagnostics == []
    assert response[1].diagnostics == []
