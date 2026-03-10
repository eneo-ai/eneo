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
from intric.audit.domain.action_types import ActionType
from intric.flows.flow import Flow, FlowRun, FlowRunStatus, FlowStep, FlowTemplateAsset, FlowVersion
from intric.flows.api import flow_router_common as router_common_module
from intric.flows.api.flow_models import (
    FlowAssistantCreateRequest,
    FlowCreateRequest,
    FlowInputSource,
    FlowInputType,
    FlowRunCreateRequest,
    FlowStepCreateRequest,
)
from intric.flows.api.flow_assistant_router import (
    create_flow_assistant,
    update_flow_assistant,
)
from intric.flows.api.flow_consumer_router import (
    cancel_flow_run_alias,
    create_flow_run,
    get_flow_run_contract,
    get_flow_input_policy,
    get_flow_run_alias,
    get_flow_graph,
    get_flow_run_evidence_alias,
    list_flow_run_steps,
    list_flow_runs_alias,
    redispatch_flow_run_alias,
    upload_flow_file,
    upload_flow_runtime_file,
)
from intric.flows.api.flow_definition_router import create_flow
from intric.flows.api.flow_definition_router import inspect_flow_template
from intric.flows.api.flow_definition_router import upload_flow_template_file
from intric.flows.api.flow_router_common import dispatch_flow_run_after_commit
from intric.settings.settings import FlowInputLimitsPublic
from intric.assistants.api.assistant_models import AssistantUpdatePublic
from intric.main.exceptions import BadRequestException, NotFoundException, UnauthorizedException
from intric.flows.api.flow_consumer_router import generate_flow_run_artifact_signed_url
from intric.flows.api.flow_definition_router import (
    get_flow as definition_get_flow,
    update_flow as definition_update_flow,
    delete_flow as definition_delete_flow,
    list_flows as definition_list_flows,
    publish_flow as definition_publish_flow,
    unpublish_flow as definition_unpublish_flow,
)


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


def _enable_space_access(container, *, can_read=True, can_create=True, can_edit=True,
                         can_delete=True, can_publish=True):
    """Set up space_service + actor_manager mocks so space checks pass."""
    space_service = AsyncMock()
    container.space_service.return_value = space_service
    actor = MagicMock()
    actor.can_read_flows.return_value = can_read
    actor.can_read_flow.return_value = can_read
    actor.can_create_flows.return_value = can_create
    actor.can_edit_flows.return_value = can_edit
    actor.can_delete_flows.return_value = can_delete
    actor.can_publish_flows.return_value = can_publish
    actor_manager = MagicMock()
    actor_manager.get_space_actor_from_space.return_value = actor
    container.actor_manager.return_value = actor_manager
    return actor


@pytest.mark.asyncio
async def test_get_flow_graph_uses_run_version_snapshot_when_run_id_supplied():
    container = MagicMock()
    flow_service = AsyncMock()
    flow_run_service = AsyncMock()
    flow_version_repo = AsyncMock()
    container.flow_service.return_value = flow_service
    container.flow_run_service.return_value = flow_run_service
    container.flow_version_repo.return_value = flow_version_repo
    _enable_space_access(container)

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

    graph = await get_flow_graph(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        run_id=run.id,
        container=container,
    )

    llm_nodes = [node for node in graph.nodes if node["type"] == "llm"]
    assert len(llm_nodes) == 1
    assert llm_nodes[0]["id"] == str(snapshot_step_id)
    assert llm_nodes[0]["label"] == "Snapshot step"
    # enforce_flow_scope now always loads the flow for space membership checks,
    # but the graph should still be built from the version snapshot, not live flow.
    flow_run_service.get_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_flow_graph_uses_live_flow_when_run_id_missing():
    container = MagicMock()
    flow_service = AsyncMock()
    container.flow_service.return_value = flow_service
    container.flow_run_service.return_value = AsyncMock()
    container.flow_version_repo.return_value = AsyncMock()
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

    llm_nodes = [node for node in graph.nodes if node["type"] == "llm"]
    assert len(llm_nodes) == 1
    assert llm_nodes[0]["label"] == "Step 1"


@pytest.mark.asyncio
async def test_get_flow_graph_rejects_scope_mismatch(monkeypatch):
    container = MagicMock()
    container.flow_service.return_value = AsyncMock()
    container.flow_run_service.return_value = AsyncMock()
    container.flow_version_repo.return_value = AsyncMock()
    flow_id = uuid4()

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=uuid4()),
    )

    with pytest.raises(HTTPException) as exc:
        await get_flow_graph(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            run_id=None,
            container=container,
        )

    assert exc.value.status_code == 403
    container.flow_run_service.return_value.get_run.assert_not_awaited()
    container.flow_version_repo.return_value.get.assert_not_awaited()


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
    container.flow_service.return_value = AsyncMock()
    container.audit_service.return_value = audit_service
    container.user.return_value = user
    _enable_space_access(container)

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
        expected_flow_version=None,
        step_inputs=None,
        file_ids=None,
    )
    audit_service.log_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_inspect_flow_template_enforces_scope_and_calls_service(monkeypatch):
    container = MagicMock()
    template_asset_service = AsyncMock()
    container.flow_template_asset_service.return_value = template_asset_service
    flow_id = uuid4()
    file_id = uuid4()
    template_asset_service.inspect_asset.return_value = {
        "file_id": file_id,
        "file_name": "rapport.docx",
        "placeholders": [{"name": "summary", "location": "body", "preview": "{{summary}}"}],
        "extracted_text_preview": "Titel: {{summary}}",
    }

    enforced: list[str] = []

    async def fake_enforce(
        request,
        _container,
        *,
        flow_id,
        require_flow_lookup_without_scope=False,
    ):
        enforced.append(str(flow_id))
        assert require_flow_lookup_without_scope is False

    monkeypatch.setattr(router_common_module, "enforce_flow_scope_for_request", fake_enforce)

    result = await inspect_flow_template(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        file_id=file_id,
        container=container,
    )

    assert enforced == [str(flow_id)]
    template_asset_service.inspect_asset.assert_awaited_once_with(flow_id=flow_id, asset_id=file_id)
    assert result["file_name"] == "rapport.docx"
    assert result["extracted_text_preview"] == "Titel: {{summary}}"


@pytest.mark.asyncio
async def test_upload_flow_template_file_enforces_scope_and_uses_docx_template_save(monkeypatch):
    container = MagicMock()
    template_asset_service = AsyncMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    asset = FlowTemplateAsset.model_validate(
        {
            "id": uuid4(),
            "flow_id": uuid4(),
            "space_id": uuid4(),
            "tenant_id": user.tenant_id,
            "file_id": uuid4(),
            "name": "template.docx",
            "checksum": "checksum",
            "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "placeholders": ["summary"],
            "status": "ready",
            "last_updated_by_name": "User",
            "can_edit": True,
            "can_download": True,
            "can_select": True,
            "can_inspect": True,
        }
    )
    container.flow_template_asset_service.return_value = template_asset_service
    container.audit_service.return_value = audit_service
    container.user.return_value = user
    template_asset_service.upload_asset.return_value = asset
    flow_id = uuid4()
    upload = UploadFile(
        filename="template.docx",
        file=BytesIO(b"fake"),
        headers={
            "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        },
    )

    enforced: list[str] = []

    async def fake_enforce(
        request,
        _container,
        *,
        flow_id,
        require_flow_lookup_without_scope=False,
    ):
        enforced.append(str(flow_id))
        assert require_flow_lookup_without_scope is True

    monkeypatch.setattr(router_common_module, "enforce_flow_scope_for_request", fake_enforce)

    result = await upload_flow_template_file(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        upload_file=upload,
        container=container,
    )

    assert enforced == [str(flow_id)]
    template_asset_service.upload_asset.assert_awaited_once_with(flow_id=flow_id, upload_file=upload)
    audit_service.log_async.assert_awaited_once()
    assert result.id == asset.id


@pytest.mark.asyncio
async def test_get_flow_run_contract_enforces_scope_and_returns_contract(monkeypatch):
    flow_id = uuid4()
    container = MagicMock()
    upload_service = AsyncMock()
    container.flow_service.return_value = AsyncMock()
    monkeypatch.setattr(router_common_module, "flow_upload_service", lambda _container: upload_service)

    async def fake_enforce(
        request,
        _container,
        *,
        flow_id,
        require_flow_lookup_without_scope=False,
    ):
        assert require_flow_lookup_without_scope is False

    monkeypatch.setattr(router_common_module, "enforce_flow_scope_for_request", fake_enforce)
    upload_service.get_run_contract.return_value = {
        "flow_id": flow_id,
        "published_flow_version": 2,
        "form_fields": [],
        "steps_requiring_input": [],
        "aggregate_max_files": 3,
        "template_readiness": [],
    }

    result = await get_flow_run_contract(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    upload_service.get_run_contract.assert_awaited_once_with(flow_id=flow_id)
    assert result.published_flow_version == 2


@pytest.mark.asyncio
async def test_upload_flow_runtime_file_calls_step_upload_service(monkeypatch):
    flow_id = uuid4()
    step_id = uuid4()
    file_id = uuid4()
    container = MagicMock()
    upload_service = AsyncMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    container.audit_service.return_value = audit_service
    container.user.return_value = user
    monkeypatch.setattr(router_common_module, "flow_upload_service", lambda _container: upload_service)

    async def fake_enforce(
        request,
        _container,
        *,
        flow_id,
        require_flow_lookup_without_scope=False,
    ):
        assert require_flow_lookup_without_scope is False

    monkeypatch.setattr(router_common_module, "enforce_flow_scope_for_request", fake_enforce)
    upload_service.upload_runtime_file_for_step.return_value = SimpleNamespace(
        id=file_id,
        name="audio.mp3",
        size=123,
        mimetype="audio/mpeg",
    )

    result = await upload_flow_runtime_file(
        id=flow_id,
        step_id=step_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        upload_file=UploadFile(filename="audio.mp3", file=BytesIO(b"audio")),
        container=container,
    )

    upload_service.upload_runtime_file_for_step.assert_awaited_once()
    audit_service.log_async.assert_awaited_once()
    assert result.id == file_id


@pytest.mark.asyncio
async def test_create_flow_run_rejects_scope_mismatch(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run_service = AsyncMock()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_run_service.return_value = run_service
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        router_common_module,
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

    monkeypatch.setattr(router_common_module.sessionmanager, "session", lambda: _SessionContext())
    monkeypatch.setattr(router_common_module, "Container", lambda session: _FakeContainer())

    run_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()

    await dispatch_flow_run_after_commit(
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
    assert kwargs["error_message"] == (
        "flow_dispatch_failed: Flow dispatch failed before execution started. "
        "Retry creating a new run."
    )


@pytest.mark.asyncio
async def test_dispatch_flow_run_after_commit_dispatches_without_status_update_on_success(monkeypatch):
    run_repo = AsyncMock()
    backend = MagicMock()
    backend.dispatch = AsyncMock()
    fake_session = MagicMock()

    class _SessionContext:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakeContainer:
        def flow_execution_backend(self):
            return backend

        def flow_run_repo(self):
            return run_repo

    monkeypatch.setattr(router_common_module.sessionmanager, "session", lambda: _SessionContext())
    monkeypatch.setattr(router_common_module, "Container", lambda session: _FakeContainer())

    run_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()
    user_id = uuid4()

    await dispatch_flow_run_after_commit(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )

    backend.dispatch.assert_awaited_once_with(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    run_repo.update_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_flow_rejects_space_scope_mismatch(monkeypatch):
    container = MagicMock()
    container.flow_service.return_value = AsyncMock()
    container.user.return_value = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    container.audit_service.return_value = AsyncMock()

    allowed_space_id = uuid4()
    monkeypatch.setattr(
        router_common_module,
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
    completion_model_id = uuid4()
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
            completion_model={"id": completion_model_id},
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
    assert kwargs["completion_model_id"] == completion_model_id
    audit_service.log_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_flow_input_policy_for_audio_step_returns_audio_mime_and_limit(monkeypatch):
    container = MagicMock()
    flow_service = AsyncMock()
    settings_service = AsyncMock()
    flow_id = uuid4()

    step = _flow_step(uuid4(), 1).model_copy(update={"input_type": "audio"})
    flow_service.get_flow.return_value = _flow(flow_id).model_copy(update={"steps": [step]})
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimitsPublic(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=25_000_000,
        audio_max_files_per_run=10,
    )
    container.flow_service.return_value = flow_service
    container.settings_service.return_value = settings_service

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

    policy = await get_flow_input_policy(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert policy.input_type == FlowInputType.AUDIO
    assert policy.input_source == FlowInputSource.FLOW_INPUT
    assert policy.accepts_file_upload is True
    assert policy.max_file_size_bytes == 25_000_000
    assert policy.max_files_per_run == 10
    assert policy.recommended_run_payload is not None
    assert policy.recommended_run_payload["file_ids"] == ["<file-id-uuid>"]
    assert "audio/mpeg" in policy.accepted_mimetypes


@pytest.mark.asyncio
async def test_get_flow_input_policy_tolerates_unexpected_policy_enums(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()

    class _BadPolicyService:
        async def get_input_policy(self, *, flow_id):
            return SimpleNamespace(
                flow_id=flow_id,
                input_type="unexpected",
                input_source="flow_input",
                accepts_file_upload=False,
                accepted_mimetypes=[],
                max_file_size_bytes=None,
                max_files_per_run=None,
                recommended_run_payload=None,
            )

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)
    monkeypatch.setattr(
        router_common_module,
        "flow_upload_service",
        lambda _container: _BadPolicyService(),
    )
    monkeypatch.setattr(
        router_common_module,
        "enforce_flow_scope_for_request",
        AsyncMock(),
    )

    policy = await get_flow_input_policy(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert policy.input_type == "unexpected"
    assert policy.input_source == FlowInputSource.FLOW_INPUT


@pytest.mark.asyncio
async def test_get_flow_input_policy_tolerates_unexpected_input_source(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()

    class _BadSourcePolicyService:
        async def get_input_policy(self, *, flow_id):
            return SimpleNamespace(
                flow_id=flow_id,
                input_type="audio",
                input_source="unexpected_source",
                accepts_file_upload=True,
                accepted_mimetypes=["audio/mpeg"],
                max_file_size_bytes=25_000_000,
                max_files_per_run=10,
                recommended_run_payload={"file_ids": ["<file-id-uuid>"]},
            )

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)
    monkeypatch.setattr(
        router_common_module,
        "flow_upload_service",
        lambda _container: _BadSourcePolicyService(),
    )
    monkeypatch.setattr(
        router_common_module,
        "enforce_flow_scope_for_request",
        AsyncMock(),
    )

    policy = await get_flow_input_policy(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert policy.input_type == FlowInputType.AUDIO
    assert policy.input_source == "unexpected_source"


@pytest.mark.asyncio
async def test_upload_flow_file_rejects_when_flow_input_type_not_file_upload(monkeypatch):
    container = MagicMock()
    flow_service = AsyncMock()
    settings_service = AsyncMock()
    file_service = AsyncMock()
    flow_id = uuid4()

    step = _flow_step(uuid4(), 1).model_copy(update={"input_type": "text"})
    flow_service.get_flow.return_value = _flow(flow_id).model_copy(update={"steps": [step]})
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimitsPublic(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=25_000_000,
    )
    container.flow_service.return_value = flow_service
    container.settings_service.return_value = settings_service
    container.file_service.return_value = file_service

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

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
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimitsPublic(
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

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)
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

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)
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
    # get_flow is called once per endpoint (3 total) via enforce_flow_scope space check
    assert flow_service.get_flow.await_count == 3
    run_service.list_runs.assert_awaited_once_with(flow_id=flow_id, limit=20, offset=2)
    run_service.get_run.assert_awaited_once_with(run_id=run.id, flow_id=flow_id)
    run_service.list_step_results.assert_awaited_once_with(run_id=run.id, flow_id=flow_id)


@pytest.mark.asyncio
async def test_flow_run_alias_list_raises_not_found_when_flow_missing_without_scope_filter(
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
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

    with pytest.raises(NotFoundException):
        await list_flow_runs_alias(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            limit=20,
            offset=0,
            container=container,
        )

    run_service.list_runs.assert_not_awaited()


@pytest.mark.asyncio
async def test_flow_run_alias_cancel_logs_audit_entry(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id)
    cancelled_run = run.model_copy(update={"status": FlowRunStatus.CANCELLED})
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.cancel_run.return_value = cancelled_run
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service
    container.user.return_value = user
    container.audit_service.return_value = AsyncMock()

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

    response = await cancel_flow_run_alias(
        id=flow_id,
        run_id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response.id == cancelled_run.id
    run_service.get_run.assert_awaited_once_with(run_id=run.id, flow_id=flow_id)
    run_service.cancel_run.assert_awaited_once_with(run_id=run.id)
    kwargs = container.audit_service.return_value.log_async.await_args.kwargs
    assert kwargs["action"] == ActionType.FLOW_RUN_CANCELLED
    assert kwargs["entity_id"] == cancelled_run.id


@pytest.mark.asyncio
async def test_flow_run_alias_redispatch_uses_run_scoped_dispatch_and_audits(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id)
    run_service = AsyncMock()
    run_service.get_run.side_effect = [run, run]
    run_service.redispatch_stale_queued_runs.return_value = 1
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service
    container.user.return_value = user
    container.audit_service.return_value = AsyncMock()
    backend = MagicMock()
    container.flow_execution_backend.return_value = backend

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

    response = await redispatch_flow_run_alias(
        id=flow_id,
        run_id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response["run"].id == run.id
    assert response["redispatched_count"] == 1
    run_service.redispatch_stale_queued_runs.assert_awaited_once_with(
        flow_id=flow_id,
        run_id=run.id,
        limit=1,
        execution_backend=backend,
    )
    kwargs = container.audit_service.return_value.log_async.await_args.kwargs
    assert kwargs["action"] == ActionType.FLOW_RUN_REDISPATCHED
    assert kwargs["entity_id"] == run.id


@pytest.mark.asyncio
async def test_flow_run_alias_redispatch_returns_zero_when_nothing_redispatched(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id)
    run_service = AsyncMock()
    run_service.get_run.side_effect = [run, run]
    run_service.redispatch_stale_queued_runs.return_value = 0
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service
    container.user.return_value = user
    container.audit_service.return_value = AsyncMock()
    container.flow_execution_backend.return_value = MagicMock()

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

    response = await redispatch_flow_run_alias(
        id=flow_id,
        run_id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response["run"].id == run.id
    assert response["redispatched_count"] == 0
    kwargs = container.audit_service.return_value.log_async.await_args.kwargs
    assert kwargs["action"] == ActionType.FLOW_RUN_REDISPATCHED
    assert "dispatch_count=0" in kwargs["description"]


@pytest.mark.asyncio
async def test_flow_run_alias_redispatch_propagates_dispatch_failure(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.redispatch_stale_queued_runs.side_effect = RuntimeError("broker down")
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service
    container.flow_execution_backend.return_value = MagicMock()
    container.audit_service.return_value = AsyncMock()

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

    with pytest.raises(RuntimeError, match="broker down"):
        await redispatch_flow_run_alias(
            id=flow_id,
            run_id=run.id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=container,
        )

    container.audit_service.return_value.log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_flow_run_alias_evidence_delegates_to_run_service(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    evidence = {
        "run": run.model_dump(mode="json"),
        "definition_snapshot": {"steps": []},
        "step_results": [],
        "step_attempts": [],
        "debug_export": {
            "schema_version": "eneo.flow.debug-export.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run": {
                "run_id": str(run.id),
                "flow_id": str(run.flow_id),
                "flow_version": run.flow_version,
                "status": run.status.value,
            },
            "definition": {
                "flow_id": str(run.flow_id),
                "version": 1,
                "checksum": "abc",
                "steps_count": 0,
            },
            "definition_snapshot": {"steps": []},
            "steps": [],
            "security": {
                "redaction_applied": True,
                "classification_field": "output_classification_override",
                "mcp_policy_field": "mcp_policy",
            },
        },
    }
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.get_evidence.return_value = evidence
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

    response = await get_flow_run_evidence_alias(
        id=flow_id,
        run_id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response.run["id"] == str(run.id)
    run_service.get_run.assert_awaited_once_with(run_id=run.id, flow_id=flow_id)
    run_service.get_evidence.assert_awaited_once_with(run_id=run.id)


@pytest.mark.asyncio
async def test_flow_run_alias_control_endpoints_reject_scope_mismatch(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.cancel_run.return_value = run
    run_service.get_evidence.return_value = {
        "run": run.model_dump(mode="json"),
        "definition_snapshot": {"steps": []},
        "step_results": [],
        "step_attempts": [],
        "debug_export": {
            "schema_version": "eneo.flow.debug-export.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run": {
                "run_id": str(run.id),
                "flow_id": str(run.flow_id),
                "flow_version": run.flow_version,
                "status": run.status.value,
            },
            "definition": {
                "flow_id": str(run.flow_id),
                "version": 1,
                "checksum": "abc",
                "steps_count": 0,
            },
            "definition_snapshot": {"steps": []},
            "steps": [],
            "security": {
                "redaction_applied": True,
                "classification_field": "output_classification_override",
                "mcp_policy_field": "mcp_policy",
            },
        },
    }
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service
    container.flow_execution_backend.return_value = MagicMock()
    container.user.return_value = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    container.audit_service.return_value = AsyncMock()

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=uuid4()),
    )

    request = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(HTTPException):
        await cancel_flow_run_alias(
            id=flow_id,
            run_id=run.id,
            request=request,
            container=container,
        )
    with pytest.raises(HTTPException):
        await redispatch_flow_run_alias(
            id=flow_id,
            run_id=run.id,
            request=request,
            container=container,
        )
    with pytest.raises(HTTPException):
        await get_flow_run_evidence_alias(
            id=flow_id,
            run_id=run.id,
            request=request,
            container=container,
        )

    run_service.cancel_run.assert_not_awaited()
    run_service.redispatch_stale_queued_runs.assert_not_awaited()
    run_service.get_evidence.assert_not_awaited()


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

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

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

    wrong_space = uuid4()
    monkeypatch.setattr(
        router_common_module,
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

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

    response = await list_flow_run_steps(
        id=flow_id,
        run_id=run_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert len(response) == 2
    assert response[0].diagnostics == []
    assert response[1].diagnostics == []


# ---------------------------------------------------------------------------
# Artifact signed URL endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_artifact_signed_url_delegates_to_service_and_audits(monkeypatch):
    """Artifact endpoint calls service.get_run_artifact_file, generates signed URL, and audits."""
    container = MagicMock()
    flow_id = uuid4()
    run_id = uuid4()
    file_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), username="tester", email="t@e.com")
    container.user.return_value = user

    file_obj = SimpleNamespace(
        id=file_id, name="report.docx", tenant_id=user.tenant_id,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size=2048,
    )
    run_service = AsyncMock()
    run_service.get_run_artifact_file.return_value = file_obj
    container.flow_run_service.return_value = run_service
    container.flow_service.return_value = AsyncMock()
    audit_service = AsyncMock()
    container.audit_service.return_value = audit_service

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container)

    from intric.files.file_models import SignedURLRequest
    signed_req = SignedURLRequest(expires_in=300)

    response = await generate_flow_run_artifact_signed_url(
        id=flow_id,
        run_id=run_id,
        file_id=file_id,
        request=SimpleNamespace(state=SimpleNamespace(), base_url="https://app.example.com/"),
        signed_url_req=signed_req,
        container=container,
    )

    run_service.get_run_artifact_file.assert_awaited_once_with(
        run_id=run_id, flow_id=flow_id, file_id=file_id,
    )
    assert response.url.startswith("https://app.example.com/api/v1/files/")
    assert str(file_id) in response.url
    assert response.expires_at > 0

    audit_service.log_async.assert_awaited_once()
    call_kwargs = audit_service.log_async.call_args[1]
    assert call_kwargs["action"] == ActionType.FLOW_RUN_ARTIFACT_DOWNLOADED
    assert call_kwargs["entity_id"] == file_id
    assert call_kwargs["metadata"]["extra"]["flow_id"] == str(flow_id)
    assert call_kwargs["metadata"]["extra"]["run_id"] == str(run_id)


# ---------------------------------------------------------------------------
# Definition endpoint space membership tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_flow_rejects_non_member():
    """get_flow returns 403 when user has no space membership."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    _enable_space_access(container, can_read=False)

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_get_flow(id=flow_id, container=container)
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
async def test_get_flow_viewer_cannot_read_unpublished():
    """VIEWER cannot see an unpublished flow (published property is False)."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow.published_version = None  # unpublished
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service

    # can_read_flow(flow) returns False for unpublished flows for viewers
    actor = _enable_space_access(container, can_read=True)
    actor.can_read_flow.return_value = False

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_get_flow(id=flow_id, container=container)
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
async def test_update_flow_rejects_viewer():
    """VIEWER cannot update a flow."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    _enable_space_access(container, can_edit=False)

    from intric.flows.api.flow_models import FlowUpdateRequest
    update_req = FlowUpdateRequest(name="New Name")

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_update_flow(id=flow_id, flow_in=update_req, container=container)
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
async def test_delete_flow_rejects_viewer():
    """VIEWER cannot delete a flow."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.user.return_value = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    _enable_space_access(container, can_delete=False)

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_delete_flow(id=flow_id, container=container)
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
async def test_publish_flow_rejects_editor_in_personal_space():
    """No PUBLISH in personal space — should be rejected."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    _enable_space_access(container, can_publish=False)

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_publish_flow(id=flow_id, container=container)
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
async def test_unpublish_flow_rejects_without_publish_permission():
    """User without publish permission cannot unpublish."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    _enable_space_access(container, can_publish=False)

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_unpublish_flow(id=flow_id, container=container)
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
async def test_list_flows_rejects_non_member(monkeypatch):
    """list_flows returns 403 when user has no space membership."""
    container = MagicMock()
    space_id = uuid4()
    container.flow_service.return_value = AsyncMock()
    _enable_space_access(container, can_read=False)

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_list_flows(
            request=SimpleNamespace(state=SimpleNamespace()),
            space_id=space_id,
            container=container,
        )
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
async def test_create_flow_rejects_non_member(monkeypatch):
    """create_flow returns 403 when user cannot create flows in the space."""
    container = MagicMock()
    space_id = uuid4()
    container.flow_service.return_value = AsyncMock()
    _enable_space_access(container, can_create=False)

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    flow_in = FlowCreateRequest(
        space_id=space_id,
        name="Test Flow",
        steps=[FlowStepCreateRequest(
            assistant_id=uuid4(), step_order=1, input_source="flow_input",
            input_type="text", output_mode="pass_through", output_type="json",
            mcp_policy="inherit",
        )],
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await create_flow(
            request=SimpleNamespace(state=SimpleNamespace()),
            flow_in=flow_in,
            container=container,
        )
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
async def test_enforce_flow_scope_rejects_non_member_on_consumer_endpoint(monkeypatch):
    """Consumer endpoint (create_flow_run) returns 403 when user has no space access."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    _enable_space_access(container, can_read=False)

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    run_in = FlowRunCreateRequest(input_payload_json={"test": "value"})

    with pytest.raises(UnauthorizedException) as exc_info:
        await create_flow_run(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            run_in=run_in,
            background_tasks=BackgroundTasks(),
            container=container,
        )
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
async def test_tenant_scoped_api_key_skips_space_membership_check(monkeypatch):
    """Tenant-scoped API keys (scope_type='tenant', space_id=None) must NOT be
    forced through space membership checks — router-level guards already authorize them."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    run = _run(flow_id=flow_id, tenant_id=flow.tenant_id)

    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service

    run_service = AsyncMock()
    run_service.list_runs.return_value = [run]
    container.flow_run_service.return_value = run_service

    # Do NOT set up space_service — if enforce_flow_scope tries to call it,
    # it will fail on MagicMock (not AsyncMock), proving the bug.
    # Tenant-scoped key: scope_type is set, space_id is None.
    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="tenant", space_id=None),
    )

    result = await list_flow_runs_alias(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        limit=50,
        offset=0,
        container=container,
    )

    assert result["count"] == 1
    # space_service should NOT have been called
    container.space_service.assert_not_called()


@pytest.mark.asyncio
async def test_space_scoped_api_key_rejects_wrong_space(monkeypatch):
    """Space-scoped API key for a different space must get 403 scope mismatch."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    wrong_space_id = uuid4()

    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="space", space_id=wrong_space_id),
    )

    with pytest.raises(HTTPException) as exc_info:
        await list_flow_runs_alias(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            limit=50,
            offset=0,
            container=container,
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "insufficient_scope"


@pytest.mark.asyncio
async def test_space_scoped_api_key_matching_space_succeeds(monkeypatch):
    """Space-scoped API key matching the flow's space should pass scope check."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    run = _run(flow_id=flow_id, tenant_id=flow.tenant_id)

    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service

    run_service = AsyncMock()
    run_service.list_runs.return_value = [run]
    container.flow_run_service.return_value = run_service

    # Space-scoped key matching the flow's space
    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="space", space_id=flow.space_id),
    )

    result = await list_flow_runs_alias(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        limit=50,
        offset=0,
        container=container,
    )

    assert result["count"] == 1
    # space_service should NOT be called for API key requests
    container.space_service.assert_not_called()
