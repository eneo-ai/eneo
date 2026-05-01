from __future__ import annotations

import json
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile

import intric.flows.api.flow_http_test_router as flow_http_test_router_module
import intric.flows.api.flow_trace_audit as flow_trace_audit_module
import intric.flows.application.flow_dispatch as flow_dispatch_module
from intric.actors.actors.space_actor import SpaceRole
from intric.assistants.api.assistant_models import AssistantUpdatePublic
from intric.audit.domain.action_types import ActionType
from intric.authentication.auth_dependencies import ScopeFilter
from intric.authentication.signed_urls import verify_signed_token
from intric.flows.api import flow_router_common as router_common_module
from intric.flows.api.flow_assistant_router import (
    create_flow_assistant,
    update_flow_assistant,
)
from intric.flows.api.flow_authoring_router import (
    create_flow,
    get_published_flow_runtime,
)
from intric.flows.api.flow_authoring_router import (
    delete_flow as definition_delete_flow,
)
from intric.flows.api.flow_authoring_router import (
    get_flow as definition_get_flow,
)
from intric.flows.api.flow_authoring_router import (
    list_flows as definition_list_flows,
)
from intric.flows.api.flow_authoring_router import (
    publish_flow as definition_publish_flow,
)
from intric.flows.api.flow_authoring_router import (
    unpublish_flow as definition_unpublish_flow,
)
from intric.flows.api.flow_authoring_router import (
    update_flow as definition_update_flow,
)
from intric.flows.api.flow_http_test_router import (
    test_flow_http as flow_definition_test_flow_http,
)
from intric.flows.api.flow_models import (
    FlowAssistantCreateRequest,
    FlowCreateRequest,
    FlowInputSource,
    FlowInputType,
    FlowRunCreateRequest,
    FlowStepCreateRequest,
    FlowUpdateRequest,
)
from intric.flows.api.flow_router_common import dispatch_flow_run_after_commit
from intric.flows.api.flow_run_evidence_router import (
    export_flow_run_evidence_alias,
    get_flow_run_evidence_alias,
)
from intric.flows.api.flow_run_execution_router import (
    cancel_flow_run_alias,
    create_flow_run,
    get_flow_run_alias,
    list_flow_runs_alias,
    redispatch_flow_run_alias,
)
from intric.flows.api.flow_run_steps_router import (
    generate_flow_run_artifact_signed_url,
    get_flow_graph,
    list_flow_run_steps,
)
from intric.flows.api.flow_template_router import (
    inspect_flow_template,
    upload_flow_template_file,
)
from intric.flows.api.flow_upload_router import (
    get_flow_input_policy,
    get_flow_run_contract,
    upload_flow_file,
    upload_flow_runtime_file,
)
from intric.flows.flow import (
    Flow,
    FlowRun,
    FlowRunStatus,
    FlowStep,
    FlowTemplateAsset,
    FlowVersion,
)
from intric.flows.http_transport.test_action import HttpTestResult
from intric.flows.published_definition import FLOW_DEFINITION_SCHEMA_VERSION
from intric.main.exceptions import (
    BadRequestException,
    ErrorCodes,
    NotFoundException,
    UnauthorizedException,
)
from intric.roles.permissions import Permission
from intric.settings.settings import FlowInputLimitsPublic


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
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json=None,
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )


def _evidence_export_payload(run: FlowRun) -> dict:
    generated_at = datetime.now(timezone.utc).isoformat()
    content_hash = "abc123"
    return {
        "schema_version": "flow-evidence-export.v3",
        "generated_at": generated_at,
        "content_hash": content_hash,
        "manifest": {
            "schema_version": "flow-evidence-export.v3",
            "provenance_schema_version_min": "flow-attempt-provenance.v1",
            "provenance_schema_version_current": "flow-attempt-provenance.v1",
            "provenance_persisted_version_status": "not_tracked",
            "run_id": str(run.id),
            "tenant_id": str(run.tenant_id),
            "flow_id": str(run.flow_id),
            "trace_id": str(run.trace_id),
            "flow_version": run.flow_version,
            "content_hash": content_hash,
            "content_hash_input": "redacted",
            "exported_at": generated_at,
            "exported_by_user_id": str(run.user_id),
            "export_reason": "support_debug",
            "detail_mode": "redacted",
            "redaction_applied": True,
            "masked_fields_count": 0,
            "redaction_policy_version": "flow-evidence-redaction.v3",
            "retention_state_summary": {
                "tracking_state": "not_tracked",
                "tombstone_count": 0,
                "retention_purged_count": 0,
                "redacted_for_deletion_count": 0,
                "note": "Tombstone tracking is not yet exposed.",
            },
            "artifact_availability_summary": {
                "tracking_state": "payload_derived",
                "payload_artifact_count": 0,
                "note": "Canonical file availability is not yet exposed.",
            },
        },
        "summary": {
            "status": run.status.value,
            "trace_id": str(run.trace_id),
            "steps_count": 0,
        },
        "redaction": {
            "applied": True,
            "policy_version": "flow-evidence-redaction.v3",
            "masked_fields_count": 0,
            "masked_paths": [],
            "masked_fields": [],
        },
        "bundle": {
            "run": run.model_dump(mode="json"),
            "definition_snapshot": {"steps": []},
            "step_results": [],
            "step_attempts": [],
            "debug_export": {
                "schema_version": "eneo.flow.debug-export.v2",
                "generated_at": generated_at,
                "run": {
                    "run_id": str(run.id),
                    "flow_id": str(run.flow_id),
                    "flow_version": run.flow_version,
                    "trace_id": str(run.trace_id),
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
        },
    }


def _enable_space_access(
    container,
    *,
    can_read=True,
    can_create=True,
    can_edit=True,
    can_delete=True,
    can_publish=True,
    user_permissions=None,
):
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
    user = getattr(container.user, "return_value", None)
    if user is not None:
        user.permissions = list(
            [Permission.FLOWS] if user_permissions is None else user_permissions
        )
    return actor


def _request():
    return SimpleNamespace(state=SimpleNamespace())


def _user() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), permissions=[Permission.FLOWS]
    )


def _service_key() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), ownership="service")


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
    flow_run_service.list_step_results.return_value = [
        SimpleNamespace(
            model_dump=lambda mode="json": {
                "step_id": None,
                "step_order": 1,
                "status": "completed",
                "num_tokens_input": 5,
                "num_tokens_output": 9,
                "error_message": None,
            }
        )
    ]
    snapshot_step_id = uuid4()
    flow_version_repo.get.return_value = FlowVersion(
        flow_id=flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
            "flow_id": str(flow_id),
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
            ],
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

    llm_nodes = [node for node in graph.nodes if node.type == "llm"]
    assert len(llm_nodes) == 1
    assert llm_nodes[0].id == str(snapshot_step_id)
    assert llm_nodes[0].label == "Snapshot step"
    # enforce_flow_scope now always loads the flow for space membership checks,
    # but the graph should still be built from the version snapshot, not live flow.
    flow_run_service.get_run.assert_awaited_once_with(
        run_id=run.id,
        flow_id=flow_id,
        access_kind="content",
    )
    flow_run_service.list_step_results.assert_awaited_once_with(
        run_id=run.id,
        flow_id=flow_id,
    )


@pytest.mark.asyncio
async def test_test_flow_http_returns_typed_invalid_config_payload(monkeypatch):
    container = MagicMock()
    user = _user()
    container.user.return_value = user
    container.audit_service.return_value = AsyncMock()
    container.flow_service.return_value = AsyncMock()
    flow = _flow(uuid4())
    flow.owner_user_id = user.id
    container.flow_service.return_value.get_flow.return_value = flow
    _enable_space_access(container)

    response = await flow_definition_test_flow_http(
        id=uuid4(),
        request=_request(),
        body=flow_http_test_router_module.HttpTestRequest(
            config={"auth": "bad"},
            direction="output",
            method="POST",
        ),
        container=container,
    )

    assert response.success is False
    assert response.error_code == "INVALID_CONFIG"
    container.audit_service.return_value.log_async.assert_not_called()


@pytest.mark.asyncio
async def test_test_flow_http_returns_typed_success_payload(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    user = _user()
    flow_service = AsyncMock()
    flow = _flow(flow_id)
    flow.owner_user_id = user.id
    flow_service.get_flow.return_value = flow
    audit_service = AsyncMock()
    container.flow_service.return_value = flow_service
    container.audit_service.return_value = audit_service
    container.user.return_value = user
    container.encryption_service.return_value = None
    _enable_space_access(container)

    execute = AsyncMock(
        return_value=HttpTestResult(
            success=True,
            status_code=200,
            duration_ms=12.5,
            response_preview="ok",
            request_preview={"method": "POST", "url": "https://example.org/api"},
            error_code=None,
            error_message=None,
        )
    )
    monkeypatch.setattr(flow_http_test_router_module, "execute_http_test", execute)

    response = await flow_definition_test_flow_http(
        id=flow_id,
        request=_request(),
        body=flow_http_test_router_module.HttpTestRequest(
            config={
                "url": "https://example.org/api",
                "auth": {"mode": "none"},
                "body": {"mode": "auto"},
                "custom_headers": [],
                "timeout_seconds": 30,
            },
            direction="output",
            method="POST",
            test_variables={"name": "Alex"},
        ),
        container=container,
    )

    assert response.success is True
    assert response.status_code == 200
    assert response.request_preview == {
        "method": "POST",
        "url": "https://example.org/api",
    }
    execute.assert_awaited_once()
    audit_service.log_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_test_flow_http_applies_ssrf_runtime_guards(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    user = _user()
    flow_service = AsyncMock()
    flow = _flow(flow_id)
    flow.owner_user_id = user.id
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.audit_service.return_value = AsyncMock()
    container.user.return_value = user
    container.encryption_service.return_value = None
    _enable_space_access(container)

    guard_calls: dict[str, object] = {}

    class _FakeRuntimeHelper:
        def __init__(self, **kwargs):
            guard_calls["init"] = kwargs

        async def assert_url_allowed(self, url: str):
            guard_calls["preflight_url"] = url
            return {"203.0.113.10"}

        def assert_connected_peer_allowed(self, *, response, preflight_resolved_ips):
            guard_calls["peer_status"] = response.status_code
            guard_calls["peer_ips"] = preflight_resolved_ips

    async def _fake_request(self, *, method, url, headers, content, json, timeout):
        request = httpx.Request(method=method, url=url, headers=headers)

        class _NetworkStream:
            @staticmethod
            def get_extra_info(name):
                if name == "server_addr":
                    return ("203.0.113.10", 443)
                return None

        return httpx.Response(
            status_code=200,
            content=b"ok",
            request=request,
            extensions={"network_stream": _NetworkStream()},
        )

    async def _fake_execute_http_test(**kwargs):
        await kwargs["send_http_request"](
            method="POST",
            url="https://example.org/api",
            headers={},
            timeout_seconds=5.0,
            body_bytes=None,
            json_body=None,
        )
        return HttpTestResult(
            success=True,
            status_code=200,
            duration_ms=1.0,
            response_preview="ok",
            request_preview={"method": "POST", "url": "https://example.org/api"},
        )

    monkeypatch.setattr(
        flow_http_test_router_module,
        "FlowHttpRuntimeHelper",
        _FakeRuntimeHelper,
        raising=False,
    )
    monkeypatch.setattr(httpx.AsyncClient, "request", _fake_request)
    monkeypatch.setattr(
        flow_http_test_router_module, "execute_http_test", _fake_execute_http_test
    )

    response = await flow_definition_test_flow_http(
        id=flow_id,
        request=_request(),
        body=flow_http_test_router_module.HttpTestRequest(
            config={
                "url": "https://example.org/api",
                "auth": {"mode": "none"},
                "body": {"mode": "auto"},
                "custom_headers": [],
                "timeout_seconds": 30,
            },
            direction="output",
            method="POST",
        ),
        container=container,
    )

    assert response.success is True
    assert guard_calls["preflight_url"] == "https://example.org/api"
    assert guard_calls["peer_status"] == 200
    assert guard_calls["peer_ips"] == {"203.0.113.10"}


def test_find_stored_http_config_logs_parse_failures(caplog, monkeypatch):
    flow = _flow(uuid4()).model_copy(
        update={
            "steps": [
                _flow_step(uuid4(), 1).model_copy(
                    update={
                        "output_config": {
                            "auth": "bad",
                        }
                    }
                )
            ]
        }
    )

    logger = flow_http_test_router_module.logger
    monkeypatch.setattr(logger, "disabled", False)
    monkeypatch.setattr(logger, "propagate", True)

    with caplog.at_level("WARNING", logger=logger.name):
        result = flow_http_test_router_module._find_stored_http_config(flow, "output")

    assert result is None
    assert "Failed to parse stored HTTP config" in caplog.text


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

    llm_nodes = [node for node in graph.nodes if node.type == "llm"]
    assert len(llm_nodes) == 1
    assert llm_nodes[0].label == "Step 1"


@pytest.mark.asyncio
async def test_get_flow_graph_rejects_scope_mismatch(monkeypatch):
    container = MagicMock()
    container.flow_service.return_value = AsyncMock()
    container.flow_run_service.return_value = AsyncMock()
    container.flow_version_repo.return_value = AsyncMock()
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )
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


@pytest.mark.asyncio
async def test_list_flows_rejects_user_without_flow_roles():
    container = MagicMock()
    flow_service = AsyncMock()
    container.flow_service.return_value = flow_service
    _enable_space_access(container, user_permissions=[])

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_list_flows(
            request=SimpleNamespace(state=SimpleNamespace()),
            container=container,
        )

    assert exc_info.value.code == "insufficient_tenant_permission"
    flow_service.list_flows.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_flow_run_rejects_user_without_run_permission():
    container = MagicMock()
    flow_service = AsyncMock()
    flow_run_service = AsyncMock()
    container.flow_service.return_value = flow_service
    container.flow_run_service.return_value = flow_run_service
    _enable_space_access(container, user_permissions=[Permission.FLOWS_VIEW])

    flow = _flow(uuid4())
    flow_service.get_flow.return_value = flow

    with pytest.raises(UnauthorizedException) as exc_info:
        await create_flow_run(
            id=flow.id,
            request=SimpleNamespace(state=SimpleNamespace()),
            run_in=FlowRunCreateRequest(input={}),
            background_tasks=BackgroundTasks(),
            container=container,
        )

    assert exc_info.value.code == "insufficient_tenant_permission"
    flow_run_service.create_run.assert_not_awaited()


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
        active_api_key=SimpleNamespace(id=uuid4(), ownership="service"),
    )
    _enable_space_access(container, user_permissions=[Permission.FLOWS])

    flow = _flow(uuid4())
    run = _run(flow_id=flow.id, tenant_id=container.user.return_value.tenant_id)
    flow_run_service.create_run.return_value = run
    flow_run_service.build_dispatch_request = MagicMock(
        return_value={
            "run_id": run.id,
            "flow_id": flow.id,
            "tenant_id": run.tenant_id,
            "principal_type": "service_key",
            "principal_user_id": None,
            "principal_api_key_id": container.user.return_value.active_api_key.id,
        }
    )
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
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id)
    flow_run_service.create_run.return_value = run
    flow_run_service.build_dispatch_request = MagicMock(
        return_value={
            "run_id": run.id,
            "flow_id": flow_id,
            "tenant_id": user.tenant_id,
            "user_id": user.id,
        }
    )
    container.flow_run_service.return_value = flow_run_service
    container.flow_service.return_value = AsyncMock()
    container.audit_service.return_value = audit_service
    container.user.return_value = user
    _enable_space_access(container)

    background_tasks = BackgroundTasks()
    run_in = FlowRunCreateRequest(input_payload_json={"case_id": "123"})

    response = await create_flow_run(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace(), headers={}),
        run_in=run_in,
        background_tasks=background_tasks,
        container=container,
    )

    assert response.id == run.id
    assert len(background_tasks.tasks) == 1
    scheduled = background_tasks.tasks[0]
    assert scheduled.func is dispatch_flow_run_after_commit
    assert scheduled.kwargs == {
        "run_id": run.id,
        "flow_id": flow_id,
        "tenant_id": user.tenant_id,
        "user_id": user.id,
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
async def test_create_flow_run_forwards_idempotency_key():
    container = MagicMock()
    flow_run_service = AsyncMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id)
    flow_run_service.create_run.return_value = run
    flow_run_service.build_dispatch_request = MagicMock(
        return_value={
            "run_id": run.id,
            "flow_id": flow_id,
            "tenant_id": user.tenant_id,
            "user_id": user.id,
        }
    )
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
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id)
    flow_run_service.create_run.return_value = run
    flow_run_service.build_dispatch_request = MagicMock(
        return_value={
            "run_id": run.id,
            "flow_id": flow_id,
            "tenant_id": user.tenant_id,
            "user_id": user.id,
        }
    )
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
async def test_inspect_flow_template_enforces_scope_and_calls_service(monkeypatch):
    container = MagicMock()
    template_asset_service = AsyncMock()
    container.flow_template_asset_service.return_value = template_asset_service
    flow_id = uuid4()
    file_id = uuid4()
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )
    container.flow_service.return_value = AsyncMock()
    container.flow_service.return_value.get_flow.return_value = _flow(flow_id)
    _enable_space_access(container)
    template_asset_service.inspect_asset.return_value = {
        "file_id": file_id,
        "file_name": "rapport.docx",
        "placeholders": [
            {"name": "summary", "location": "body", "preview": "{{summary}}"}
        ],
        "extracted_text_preview": "Titel: {{summary}}",
    }

    requested_flow_ids: list[str] = []

    async def fake_access_context(
        request,
        _container,
        *,
        flow_id,
        required_access=router_common_module.FlowApiAction.VIEW,
        load_actor_context=True,
    ):
        requested_flow_ids.append(str(flow_id))
        assert required_access == router_common_module.FlowApiAction.EDIT
        assert load_actor_context is True
        flow = _flow(flow_id)
        flow.owner_user_id = container.user.return_value.id
        return SimpleNamespace(
            flow=flow,
            actor=MagicMock(can_edit_flows=MagicMock(return_value=True)),
        )

    monkeypatch.setattr(
        router_common_module,
        "get_flow_access_context_for_request",
        fake_access_context,
    )

    result = await inspect_flow_template(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        file_id=file_id,
        container=container,
    )

    assert requested_flow_ids == [str(flow_id)]
    template_asset_service.inspect_asset.assert_awaited_once_with(
        flow_id=flow_id, asset_id=file_id
    )
    assert result["file_name"] == "rapport.docx"
    assert result["extracted_text_preview"] == "Titel: {{summary}}"


@pytest.mark.asyncio
async def test_upload_flow_template_file_enforces_scope_and_uses_docx_template_save(
    monkeypatch,
):
    container = MagicMock()
    template_asset_service = AsyncMock()
    audit_service = AsyncMock()
    user = SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), permissions=[Permission.FLOWS]
    )
    flow_id = uuid4()
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
    container.flow_service.return_value = AsyncMock()
    container.flow_service.return_value.get_flow.return_value = _flow(flow_id)
    _enable_space_access(container)
    template_asset_service.upload_asset.return_value = asset
    upload = UploadFile(
        filename="template.docx",
        file=BytesIO(b"fake"),
        headers={
            "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        },
    )

    requested_flow_ids: list[str] = []

    async def fake_access_context(
        request,
        _container,
        *,
        flow_id,
        required_access=router_common_module.FlowApiAction.VIEW,
        load_actor_context=True,
    ):
        requested_flow_ids.append(str(flow_id))
        assert required_access == router_common_module.FlowApiAction.EDIT
        assert load_actor_context is True
        flow = _flow(flow_id)
        flow.owner_user_id = container.user.return_value.id
        return SimpleNamespace(
            flow=flow,
            actor=MagicMock(can_edit_flows=MagicMock(return_value=True)),
        )

    monkeypatch.setattr(
        router_common_module,
        "get_flow_access_context_for_request",
        fake_access_context,
    )

    result = await upload_flow_template_file(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        upload_file=upload,
        container=container,
    )

    assert requested_flow_ids == [str(flow_id)]
    template_asset_service.upload_asset.assert_awaited_once_with(
        flow_id=flow_id, upload_file=upload
    )
    audit_service.log_async.assert_awaited_once()
    assert result.id == asset.id


@pytest.mark.asyncio
async def test_get_flow_run_contract_enforces_scope_and_returns_contract(monkeypatch):
    flow_id = uuid4()
    container = MagicMock()
    upload_service = AsyncMock()
    container.flow_service.return_value = AsyncMock()
    monkeypatch.setattr(
        router_common_module, "flow_upload_service", lambda _container: upload_service
    )

    async def fake_enforce(
        request,
        _container,
        *,
        flow_id,
        required_access=router_common_module.FlowApiAction.VIEW,
        require_flow_lookup_without_scope=False,
        allow_service_key_principals=False,
        require_published_for_service_key=False,
    ):
        assert required_access == router_common_module.FlowApiAction.VIEW
        assert require_flow_lookup_without_scope is False
        assert allow_service_key_principals is True
        assert require_published_for_service_key is True

    monkeypatch.setattr(
        router_common_module, "enforce_flow_scope_for_request", fake_enforce
    )
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
    monkeypatch.setattr(
        router_common_module, "flow_upload_service", lambda _container: upload_service
    )

    async def fake_enforce(
        request,
        _container,
        *,
        flow_id,
        required_access=router_common_module.FlowApiAction.VIEW,
        require_flow_lookup_without_scope=False,
        allow_service_key_principals=False,
        require_published_for_service_key=False,
    ):
        assert required_access == router_common_module.FlowApiAction.RUN
        assert require_flow_lookup_without_scope is False
        assert allow_service_key_principals is True
        assert require_published_for_service_key is True

    monkeypatch.setattr(
        router_common_module, "enforce_flow_scope_for_request", fake_enforce
    )
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
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )

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
async def test_dispatch_flow_run_after_commit_marks_failed_on_dispatch_error(
    monkeypatch,
):
    run_repo = AsyncMock()
    terminalizer = AsyncMock()
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

        def flow_run_terminalizer(self):
            return terminalizer

    monkeypatch.setattr(
        flow_dispatch_module.sessionmanager, "session", lambda: _SessionContext()
    )
    monkeypatch.setattr(
        flow_dispatch_module, "Container", lambda session: _FakeContainer()
    )

    run_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()

    await dispatch_flow_run_after_commit(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        user_id=uuid4(),
    )

    terminalizer.terminalize_run.assert_awaited_once()
    kwargs = terminalizer.terminalize_run.await_args.kwargs
    assert kwargs["run_id"] == run_id
    assert kwargs["tenant_id"] == tenant_id
    assert kwargs["target_status"] == FlowRunStatus.FAILED
    assert kwargs["error_message"] == (
        "flow_dispatch_failed: Flow dispatch failed before execution started. "
        "Retry creating a new run."
    )


@pytest.mark.asyncio
async def test_dispatch_flow_run_after_commit_dispatches_without_status_update_on_success(
    monkeypatch,
):
    run_repo = AsyncMock()
    terminalizer = AsyncMock()
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

        def flow_run_terminalizer(self):
            return terminalizer

    monkeypatch.setattr(
        flow_dispatch_module.sessionmanager, "session", lambda: _SessionContext()
    )
    monkeypatch.setattr(
        flow_dispatch_module, "Container", lambda session: _FakeContainer()
    )

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
    terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_flow_rejects_space_scope_mismatch(monkeypatch):
    container = MagicMock()
    container.flow_service.return_value = AsyncMock()
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )
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
    flow_service.get_flow.return_value = _flow(flow_id)
    _enable_space_access(container)

    response = await create_flow_assistant(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
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
    mcp_server_id = uuid4()
    mcp_tool_id = uuid4()
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
    flow_service.get_flow.return_value = _flow(flow_id)
    _enable_space_access(container)

    response = await update_flow_assistant(
        id=flow_id,
        assistant_id=assistant_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        assistant_in=AssistantUpdatePublic(
            name="Updated assistant",
            attachments=[{"id": attachment_id}],
            websites=[{"id": website_id}],
            groups=[{"id": group_id}],
            integration_knowledge_list=[{"id": integration_knowledge_id}],
            mcp_servers=[{"id": mcp_server_id}],
            mcp_tools=[{"tool_id": mcp_tool_id, "is_enabled": True}],
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
    assert kwargs["mcp_server_ids"] == [mcp_server_id]
    assert kwargs["mcp_tools"] == [(mcp_tool_id, True)]
    assert kwargs["completion_model_id"] == completion_model_id
    audit_service.log_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_flow_input_policy_for_audio_step_returns_audio_mime_and_limit(
    monkeypatch,
):
    container = MagicMock()
    flow_service = AsyncMock()
    settings_service = AsyncMock()
    flow_id = uuid4()

    step = _flow_step(uuid4(), 1).model_copy(update={"input_type": "audio"})
    flow_service.get_flow.return_value = _flow(flow_id).model_copy(
        update={"steps": [step]}
    )
    settings_service.get_flow_input_limits_resolved.return_value = (
        FlowInputLimitsPublic(
            file_max_size_bytes=10_000_000,
            audio_max_size_bytes=25_000_000,
            max_files_per_run=10,
            audio_max_files_per_run=10,
        )
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
    assert policy.recommended_run_payload["step_inputs"] == {
        str(step.id): {"file_ids": ["<file-id-uuid>"]}
    }
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
                recommended_run_payload={
                    "step_inputs": {"<step-id-uuid>": {"file_ids": ["<file-id-uuid>"]}}
                },
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
async def test_upload_flow_file_rejects_when_flow_input_type_not_file_upload(
    monkeypatch,
):
    container = MagicMock()
    flow_service = AsyncMock()
    settings_service = AsyncMock()
    file_service = AsyncMock()
    flow_id = uuid4()

    step = _flow_step(uuid4(), 1).model_copy(update={"input_type": "text"})
    flow_service.get_flow.return_value = _flow(flow_id).model_copy(
        update={"steps": [step]}
    )
    settings_service.get_flow_input_limits_resolved.return_value = (
        FlowInputLimitsPublic(
            file_max_size_bytes=10_000_000,
            audio_max_size_bytes=25_000_000,
            max_files_per_run=10,
            audio_max_files_per_run=10,
        )
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
    flow_service.get_flow.return_value = _flow(flow_id).model_copy(
        update={"steps": [step]}
    )
    settings_service.get_flow_input_limits_resolved.return_value = (
        FlowInputLimitsPublic(
            file_max_size_bytes=10_000_000,
            audio_max_size_bytes=31_000_000,
            max_files_per_run=10,
            audio_max_files_per_run=10,
        )
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
    assert list_response["has_more"] is False
    assert get_response.id == run.id
    assert step_response == []
    # get_flow is called once per endpoint (3 total) via enforce_flow_scope space check
    assert flow_service.get_flow.await_count == 3
    run_service.list_runs.assert_awaited_once_with(flow_id=flow_id, limit=21, offset=2)
    run_service.get_run.assert_awaited_once_with(run_id=run.id, flow_id=flow_id)
    run_service.list_step_results.assert_awaited_once_with(
        run_id=run.id, flow_id=flow_id
    )


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
async def test_flow_run_alias_viewer_cannot_read_unpublished_flow(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run_service = AsyncMock()
    container.flow_run_service.return_value = run_service

    flow = _flow(flow_id)
    flow.published_version = None
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    actor = _enable_space_access(container)
    actor.can_read_flow.return_value = False

    with pytest.raises(UnauthorizedException) as exc_info:
        await list_flow_runs_alias(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            limit=20,
            offset=0,
            container=container,
        )

    assert exc_info.value.code == "insufficient_space_permission"
    run_service.list_runs.assert_not_awaited()


@pytest.mark.asyncio
async def test_flow_run_alias_cancel_uses_terminalizer_audit_only(monkeypatch):
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
    container.audit_service.return_value.log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_flow_run_alias_redispatch_uses_run_scoped_dispatch_and_audits(
    monkeypatch,
):
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
async def test_flow_run_alias_redispatch_returns_zero_when_nothing_redispatched(
    monkeypatch,
):
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
            "schema_version": "eneo.flow.debug-export.v2",
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
    container.audit_service.return_value = AsyncMock()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(
        container,
        user_permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_TRACE],
    )

    response = await get_flow_run_evidence_alias(
        id=flow_id,
        run_id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response.run.id == run.id
    run_service.get_run.assert_awaited_once_with(
        run_id=run.id,
        flow_id=flow_id,
        access_kind="evidence_view",
    )
    run_service.get_evidence.assert_awaited_once_with(run_id=run.id, run=run)
    container.audit_service.return_value.log_async.assert_awaited_once()
    assert (
        container.audit_service.return_value.log_async.await_args.kwargs["action"]
        == ActionType.FLOW_EVIDENCE_VIEWED
    )


@pytest.mark.asyncio
async def test_flow_run_alias_evidence_requires_trace_permission(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(container, user_permissions=[Permission.FLOWS_VIEW])

    run_service.get_evidence.side_effect = UnauthorizedException(
        "You do not have permission to view flow trace.",
        code="insufficient_tenant_permission",
    )

    with pytest.raises(UnauthorizedException, match="view flow trace"):
        await get_flow_run_evidence_alias(
            id=flow_id,
            run_id=run.id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=container,
        )

    run_service.get_evidence.assert_awaited_once()


@pytest.mark.asyncio
async def test_flow_run_alias_evidence_allows_space_admin_without_trace_permission(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    evidence = {
        "run": run.model_dump(mode="json"),
        "definition_snapshot": {"steps": []},
        "step_results": [],
        "step_attempts": [],
        "debug_export": {
            "schema_version": "eneo.flow.debug-export.v2",
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
    container.audit_service.return_value = AsyncMock()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    actor = _enable_space_access(container, user_permissions=[Permission.FLOWS_VIEW])
    actor.get_current_role.return_value = SpaceRole.ADMIN

    response = await get_flow_run_evidence_alias(
        id=flow_id,
        run_id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response.run.id == run.id
    run_service.get_evidence.assert_awaited_once()


@pytest.mark.asyncio
async def test_flow_run_evidence_export_alias_returns_json_attachment(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    export_payload = _evidence_export_payload(run)
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.export_evidence_json.return_value = export_payload
    container.flow_run_service.return_value = run_service
    container.audit_service.return_value = AsyncMock()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(
        container,
        user_permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_TRACE],
    )

    response = await export_flow_run_evidence_alias(
        id=flow_id,
        run_id=run.id,
        format="json",
        detail="redacted",
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response.media_type == "application/json"
    assert "attachment;" in response.headers["content-disposition"]
    assert str(run.id) in response.body.decode("utf-8")
    run_service.export_evidence_json.assert_awaited_once_with(
        run_id=run.id,
        detail="redacted",
        run=run,
        export_reason="support_debug",
    )
    container.audit_service.return_value.log_async.assert_awaited_once()
    assert (
        container.audit_service.return_value.log_async.await_args.kwargs["action"]
        == ActionType.FLOW_EVIDENCE_EXPORTED_JSON
    )
    assert container.audit_service.return_value.log_async.await_args.kwargs["metadata"][
        "extra"
    ] == {
        "evidence_detail": "redacted",
        "export_reason": "support_debug",
    }


@pytest.mark.asyncio
async def test_flow_run_evidence_alias_fails_closed_when_audit_write_fails(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    evidence = {
        "run": run.model_dump(mode="json"),
        "definition_snapshot": {"steps": []},
        "step_results": [],
        "step_attempts": [],
        "debug_export": {
            "schema_version": "eneo.flow.debug-export.v2",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run": {
                "run_id": str(run.id),
                "flow_id": str(run.flow_id),
                "flow_version": run.flow_version,
                "trace_id": str(run.trace_id),
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
    audit_service = AsyncMock()
    audit_service.log_async.side_effect = RuntimeError("audit unavailable")
    container.audit_service.return_value = audit_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service
    logger = MagicMock()

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    monkeypatch.setattr(flow_trace_audit_module, "logger", logger)
    _enable_space_access(
        container,
        user_permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_TRACE],
    )

    response = await get_flow_run_evidence_alias(
        id=flow_id,
        run_id=run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response.status_code == 503
    assert json.loads(response.body.decode("utf-8")) == {
        "message": "Evidence audit logging is unavailable.",
        "intric_error_code": int(ErrorCodes.INTERNAL_SERVER_ERROR),
        "code": "flow_evidence_audit_logging_failed",
        "context": {"audit_required": True},
    }
    logger.exception.assert_called_once()


@pytest.mark.asyncio
async def test_flow_run_evidence_export_alias_fails_closed_when_audit_write_fails(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    export_payload = _evidence_export_payload(run)
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.export_evidence_json.return_value = export_payload
    container.flow_run_service.return_value = run_service
    audit_service = AsyncMock()
    audit_service.log_async.side_effect = RuntimeError("audit unavailable")
    container.audit_service.return_value = audit_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service
    logger = MagicMock()

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    monkeypatch.setattr(flow_trace_audit_module, "logger", logger)
    _enable_space_access(
        container,
        user_permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_TRACE],
    )

    response = await export_flow_run_evidence_alias(
        id=flow_id,
        run_id=run.id,
        format="json",
        detail="redacted",
        reason="support_debug",
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response.status_code == 503
    assert json.loads(response.body.decode("utf-8")) == {
        "message": "Evidence audit logging is unavailable.",
        "intric_error_code": int(ErrorCodes.INTERNAL_SERVER_ERROR),
        "code": "flow_evidence_audit_logging_failed",
        "context": {"audit_required": True},
    }
    logger.exception.assert_called_once()


@pytest.mark.asyncio
async def test_flow_run_evidence_export_alias_passes_raw_detail_and_reason(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    export_payload = _evidence_export_payload(run)
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.export_evidence_json.return_value = export_payload
    container.flow_run_service.return_value = run_service
    container.audit_service.return_value = AsyncMock()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(
        container,
        user_permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_TRACE],
    )

    await export_flow_run_evidence_alias(
        id=flow_id,
        run_id=run.id,
        format="json",
        detail="raw",
        reason="government_audit_request",
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    run_service.get_run.assert_awaited_once_with(
        run_id=run.id,
        flow_id=flow_id,
        access_kind="evidence_export_raw",
    )
    run_service.export_evidence_json.assert_awaited_once_with(
        run_id=run.id,
        detail="raw",
        run=run,
        export_reason="government_audit_request",
    )
    assert container.audit_service.return_value.log_async.await_args.kwargs["metadata"][
        "extra"
    ] == {
        "evidence_detail": "raw",
        "export_reason": "government_audit_request",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason", ["support_debug", "   "], ids=["default_sentinel", "whitespace_only"]
)
async def test_flow_run_evidence_export_alias_rejects_raw_invalid_reason(
    monkeypatch,
    reason,
):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    container.flow_run_service.return_value = run_service
    container.audit_service.return_value = AsyncMock()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    _enable_space_access(
        container,
        user_permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_TRACE],
    )

    response = await export_flow_run_evidence_alias(
        id=flow_id,
        run_id=run.id,
        format="json",
        detail="raw",
        reason=reason,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response.status_code == 400
    assert json.loads(response.body.decode("utf-8")) == {
        "message": "Raw evidence export requires an explicit non-default reason.",
        "intric_error_code": int(ErrorCodes.BAD_REQUEST),
        "code": "flow_evidence_export_reason_required",
        "context": {
            "detail": "raw",
            "default_reason": "support_debug",
        },
    }
    run_service.get_run.assert_not_awaited()
    run_service.export_evidence_json.assert_not_awaited()
    container.audit_service.return_value.log_async.assert_not_awaited()


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
            "schema_version": "eneo.flow.debug-export.v2",
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
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )
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
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )

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
    user = SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), username="tester", email="t@e.com"
    )
    container.user.return_value = user
    file_tenant_id = uuid4()

    file_obj = SimpleNamespace(
        id=file_id,
        name="report.docx",
        tenant_id=file_tenant_id,
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
        request=SimpleNamespace(
            state=SimpleNamespace(), base_url="https://app.example.com/"
        ),
        signed_url_req=signed_req,
        container=container,
    )

    run_service.get_run_artifact_file.assert_awaited_once_with(
        run_id=run_id,
        flow_id=flow_id,
        file_id=file_id,
    )
    assert response.url.startswith("https://app.example.com/api/v1/files/")
    assert str(file_id) in response.url
    assert response.expires_at > 0
    token = response.url.split("token=", 1)[1]
    payload = verify_signed_token(token)
    assert payload is not None
    assert payload["tenant_id"] == str(file_tenant_id)

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
        await definition_get_flow(id=flow_id, request=_request(), container=container)
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
        await definition_get_flow(id=flow_id, request=_request(), container=container)
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
        await definition_update_flow(
            id=flow_id,
            request=_request(),
            flow_in=update_req,
            container=container,
        )
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
async def test_update_flow_rejects_same_space_admin_for_other_members_draft():
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow.owner_user_id = uuid4()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    actor = _enable_space_access(container, can_edit=True)
    actor.get_current_role.return_value = SpaceRole.ADMIN
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )

    update_req = FlowUpdateRequest(name="New Name")

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_update_flow(
            id=flow_id,
            request=_request(),
            flow_in=update_req,
            container=container,
        )

    assert exc_info.value.code == "flow_owner_required"


@pytest.mark.asyncio
async def test_update_flow_allows_space_owner_to_override_draft_owner():
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow.owner_user_id = uuid4()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    flow_service.update_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.audit_service.return_value = AsyncMock()
    actor = _enable_space_access(container, can_edit=True)
    actor.get_current_role.return_value = SpaceRole.OWNER
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )

    update_req = FlowUpdateRequest(name="New Name")

    await definition_update_flow(
        id=flow_id,
        request=_request(),
        flow_in=update_req,
        container=container,
    )

    flow_service.update_flow.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_flow_falls_back_to_created_by_when_owner_missing():
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    owner_user_id = uuid4()
    flow.owner_user_id = None
    flow.created_by_user_id = owner_user_id
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    flow_service.update_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.audit_service.return_value = AsyncMock()
    _enable_space_access(container, can_edit=True)
    container.user.return_value = SimpleNamespace(
        id=owner_user_id,
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )

    update_req = FlowUpdateRequest(name="New Name")

    await definition_update_flow(
        id=flow_id,
        request=_request(),
        flow_in=update_req,
        container=container,
    )

    flow_service.update_flow.assert_awaited_once()


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
        await definition_delete_flow(
            id=flow_id, request=_request(), container=container
        )
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
async def test_delete_flow_rejects_same_space_admin_for_other_members_draft():
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow.owner_user_id = uuid4()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    actor = _enable_space_access(container, can_delete=True)
    actor.get_current_role.return_value = SpaceRole.ADMIN
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_delete_flow(
            id=flow_id, request=_request(), container=container
        )

    assert exc_info.value.code == "flow_owner_required"


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
        await definition_publish_flow(
            id=flow_id, request=_request(), container=container
        )
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
async def test_publish_flow_rejects_same_space_admin_for_other_members_draft():
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow.owner_user_id = uuid4()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    actor = _enable_space_access(container, can_publish=True)
    actor.get_current_role.return_value = SpaceRole.ADMIN
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_publish_flow(
            id=flow_id, request=_request(), container=container
        )

    assert exc_info.value.code == "flow_owner_required"


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
        await definition_unpublish_flow(
            id=flow_id, request=_request(), container=container
        )
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_fn", "build_kwargs"),
    [
        (definition_get_flow, lambda flow_id: {}),
        (
            definition_update_flow,
            lambda _flow_id: {"flow_in": FlowUpdateRequest(name="Scoped update")},
        ),
        (definition_delete_flow, lambda flow_id: {}),
        (definition_publish_flow, lambda flow_id: {}),
        (definition_unpublish_flow, lambda flow_id: {}),
    ],
)
async def test_definition_endpoints_reject_scope_mismatch(
    monkeypatch,
    route_fn,
    build_kwargs,
):
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )
    _enable_space_access(container)

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="space", space_id=uuid4()),
    )

    with pytest.raises(HTTPException) as exc_info:
        await route_fn(
            id=flow_id,
            request=_request(),
            container=container,
            **build_kwargs(flow_id),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "insufficient_scope"


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
async def test_list_flows_rejects_without_tenant_view_permission(monkeypatch):
    container = MagicMock()
    space_id = uuid4()
    container.flow_service.return_value = AsyncMock()
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[],
    )
    _enable_space_access(container, user_permissions=[])

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

    assert exc_info.value.code == "insufficient_tenant_permission"


@pytest.mark.asyncio
async def test_list_flows_allows_service_key_principals_for_published_discovery(
    monkeypatch,
):
    container = MagicMock()
    space_id = uuid4()
    flow_service = AsyncMock()
    visible_flow = _flow(uuid4())
    flow_service.list_flows.return_value = [visible_flow]
    container.flow_service.return_value = flow_service
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
        active_api_key=_service_key(),
    )
    _enable_space_access(container, can_edit=True, user_permissions=[Permission.FLOWS])

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    result = await definition_list_flows(
        request=SimpleNamespace(state=SimpleNamespace()),
        space_id=space_id,
        limit=50,
        offset=0,
        container=container,
    )

    assert result["count"] == 1
    assert result["has_more"] is False
    assert result["items"][0].id == visible_flow.id
    flow_service.list_flows.assert_awaited_once_with(
        space_id=space_id,
        sparse=True,
        published_only=True,
        limit=51,
        offset=0,
    )


@pytest.mark.asyncio
async def test_list_flows_requests_published_only_for_non_editors(monkeypatch):
    container = MagicMock()
    space_id = uuid4()
    flow_service = AsyncMock()
    visible_flow = _flow(uuid4())
    flow_service.list_flows.return_value = [visible_flow]
    container.flow_service.return_value = flow_service
    _enable_space_access(container, can_edit=False)

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    result = await definition_list_flows(
        request=SimpleNamespace(state=SimpleNamespace()),
        space_id=space_id,
        limit=50,
        offset=0,
        container=container,
    )

    assert result["count"] == 1
    assert result["has_more"] is False
    assert len(result["items"]) == 1
    assert result["items"][0].id == visible_flow.id
    flow_service.list_flows.assert_awaited_once_with(
        space_id=space_id,
        sparse=True,
        published_only=True,
        limit=51,
        offset=0,
    )


@pytest.mark.asyncio
async def test_get_flow_keeps_service_key_principals_human_only(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
        active_api_key=_service_key(),
    )

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="space", space_id=flow.space_id),
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_get_flow(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=container,
        )

    assert exc_info.value.code == "flow_service_key_principal_not_supported"


@pytest.mark.asyncio
async def test_get_published_flow_runtime_allows_service_key_principals(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
        active_api_key=_service_key(),
    )
    _enable_space_access(container, can_read=True, user_permissions=[Permission.FLOWS])

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="space", space_id=flow.space_id),
    )

    result = await get_published_flow_runtime(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert result.id == flow.id
    assert result.published_version == flow.published_version
    assert result.runtime_paths.create_run.endswith(f"/flows/{flow.id}/runs/")


@pytest.mark.asyncio
async def test_get_published_flow_runtime_hides_unpublished_flow(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow.published_version = None
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    _enable_space_access(container, can_read=True, user_permissions=[Permission.FLOWS])

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="space", space_id=flow.space_id),
    )

    with pytest.raises(NotFoundException):
        await get_published_flow_runtime(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=container,
        )


@pytest.mark.asyncio
async def test_get_published_flow_runtime_hides_unpublished_flow_for_service_key(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow.published_version = None
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
        active_api_key=_service_key(),
    )
    _enable_space_access(container, can_read=True, user_permissions=[Permission.FLOWS])

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="space", space_id=flow.space_id),
    )

    with pytest.raises(NotFoundException):
        await get_published_flow_runtime(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=container,
        )


@pytest.mark.asyncio
async def test_get_published_flow_runtime_returns_runtime_projection_for_human_reader(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    _enable_space_access(container, can_read=True, user_permissions=[Permission.FLOWS])

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="space", space_id=flow.space_id),
    )

    result = await get_published_flow_runtime(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert result.id == flow.id
    assert result.name == flow.name
    assert result.runtime_paths.run_contract.endswith(
        f"/api/v1/flows/{flow.id}/run-contract/"
    )


@pytest.mark.asyncio
async def test_list_flows_requests_all_flows_for_editors(monkeypatch):
    container = MagicMock()
    space_id = uuid4()
    flow_service = AsyncMock()
    flow_service.list_flows.return_value = [_flow(uuid4())]
    container.flow_service.return_value = flow_service
    _enable_space_access(container, can_edit=True)

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    await definition_list_flows(
        request=SimpleNamespace(state=SimpleNamespace()),
        space_id=space_id,
        limit=50,
        offset=0,
        container=container,
    )

    flow_service.list_flows.assert_awaited_once_with(
        space_id=space_id,
        sparse=True,
        published_only=False,
        limit=51,
        offset=0,
    )


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
        steps=[
            FlowStepCreateRequest(
                assistant_id=uuid4(),
                step_order=1,
                input_source="flow_input",
                input_type="text",
                output_mode="pass_through",
                output_type="json",
                mcp_policy="inherit",
            )
        ],
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await create_flow(
            request=SimpleNamespace(state=SimpleNamespace()),
            flow_in=flow_in,
            container=container,
        )
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
async def test_create_flow_rejects_without_tenant_manage_permission(monkeypatch):
    container = MagicMock()
    space_id = uuid4()
    container.flow_service.return_value = AsyncMock()
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS_VIEW],
    )
    _enable_space_access(container, user_permissions=[Permission.FLOWS_VIEW])

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    flow_in = FlowCreateRequest(
        space_id=space_id,
        name="Test Flow",
        steps=[
            FlowStepCreateRequest(
                assistant_id=uuid4(),
                step_order=1,
                input_source="flow_input",
                input_type="text",
                output_mode="pass_through",
                output_type="json",
                mcp_policy="inherit",
            )
        ],
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await create_flow(
            request=SimpleNamespace(state=SimpleNamespace()),
            flow_in=flow_in,
            container=container,
        )

    assert exc_info.value.code == "insufficient_tenant_permission"


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
async def test_create_flow_run_rejects_without_tenant_run_permission(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.flow_run_service.return_value = AsyncMock()
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS_VIEW],
    )
    _enable_space_access(container, user_permissions=[Permission.FLOWS_VIEW])

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

    assert exc_info.value.code == "insufficient_tenant_permission"


@pytest.mark.asyncio
async def test_tenant_scoped_user_api_key_loads_space_membership_check(monkeypatch):
    """Tenant-scoped user-owned API keys should still respect space visibility rules."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    run = _run(flow_id=flow_id, tenant_id=flow.tenant_id)

    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
        active_api_key=SimpleNamespace(ownership="user"),
    )
    _enable_space_access(container)

    run_service = AsyncMock()
    run_service.list_runs.return_value = [run]
    container.flow_run_service.return_value = run_service

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
    assert result["has_more"] is False
    container.space_service.return_value.get_space.assert_awaited_once_with(
        flow.space_id
    )


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
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )

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
    """User-owned space-scoped API keys should still load actor context for flow visibility."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    run = _run(flow_id=flow_id, tenant_id=flow.tenant_id)

    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
        active_api_key=SimpleNamespace(ownership="user"),
    )
    _enable_space_access(container)

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
    assert result["has_more"] is False
    container.space_service.return_value.get_space.assert_awaited_once_with(
        flow.space_id
    )


@pytest.mark.asyncio
async def test_assistant_scoped_api_key_cannot_access_flow_runtime(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    container.flow_service.return_value = AsyncMock()
    container.flow_run_service.return_value = AsyncMock()
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
        active_api_key=SimpleNamespace(ownership="user"),
    )

    monkeypatch.setattr(
        router_common_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="assistant", assistant_id=uuid4()),
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
    container.flow_service.return_value.get_flow.assert_not_awaited()
    container.flow_run_service.return_value.list_runs.assert_not_awaited()
