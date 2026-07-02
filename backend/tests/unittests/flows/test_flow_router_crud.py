from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import (
    AsyncMock,
    MagicMock,
)
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import eneo.flows.api.flow_http_test_router as flow_http_test_router_module
from eneo.actors.actors.space_actor import SpaceRole
from eneo.assistants.api.assistant_models import AssistantUpdatePublic
from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.audit.domain.action_types import ActionType
from eneo.authentication.auth_dependencies import ScopeFilter
from eneo.flows.api import flow_access_context as flow_access_context_module
from eneo.flows.api.flow_assistant_router import (
    create_flow_assistant,
    update_flow_assistant,
)
from eneo.flows.api.flow_authoring_router import (
    create_flow,
    get_published_flow_runtime,
)
from eneo.flows.api.flow_authoring_router import (
    get_flow as definition_get_flow,
)
from eneo.flows.api.flow_authoring_router import (
    list_flows as definition_list_flows,
)
from eneo.flows.api.flow_authoring_router import (
    update_flow as definition_update_flow,
)
from eneo.flows.api.flow_http_test_models import HttpTestRequest
from eneo.flows.api.flow_http_test_router import (
    router as flow_http_test_router,
)
from eneo.flows.api.flow_http_test_router import (
    test_flow_http as flow_definition_test_flow_http,
)
from eneo.flows.api.flow_models import (
    FlowAssistantCreateRequest,
    FlowCreateRequest,
    FlowStepCreateRequest,
    FlowStepUpdateRequest,
    FlowUpdateRequest,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.http_transport import SECRET_SENTINEL
from eneo.flows.http_transport.request_preview import HttpRequestPreview
from eneo.flows.http_transport.test_action import HttpTestResult
from eneo.main.exceptions import UnauthorizedException
from eneo.roles.permissions import Permission
from tests.unit.api_key_test_utils import flatten_routes
from tests.unittests.flows.test_flow_router import (
    _enable_space_access,
    _flow,
    _flow_step,
    _request,
    _service_key,
    _user,
)


def _http_test_client(container, monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(flow_http_test_router)

    for route in flatten_routes(list(app.routes)):
        if not isinstance(route.route, APIRoute):
            continue
        for dependency in route.dependant.dependencies:
            app.dependency_overrides[dependency.call] = lambda: container

    async def _allow_flow_edit_access(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        flow_http_test_router_module,
        "require_flow_edit_access",
        _allow_flow_edit_access,
    )
    return TestClient(app)


def test_test_flow_http_rejects_malformed_config_at_request_boundary(monkeypatch):
    container = MagicMock()
    client = _http_test_client(container, monkeypatch)

    response = client.post(
        f"/{uuid4()}/http-test",
        json={
            "config": {
                "url": "https://example.org/api",
                "auth": {"mode": "not-a-real-auth-mode"},
                "timeout_seconds": 30,
            },
            "direction": "output",
            "method": "POST",
        },
    )

    assert response.status_code == 422


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
            request_preview=HttpRequestPreview(
                method="POST",
                url="https://example.org/api",
                headers={},
                body_preview=None,
            ),
            error_code=None,
        )
    )
    monkeypatch.setattr(flow_http_test_router_module, "execute_http_test", execute)

    response = await flow_definition_test_flow_http(
        id=flow_id,
        request=_request(),
        body=HttpTestRequest(
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
    assert response.request_preview is not None
    assert response.request_preview.model_dump() == {
        "method": "POST",
        "url": "https://example.org/api",
        "headers": {},
        "body_preview": None,
    }
    execute.assert_awaited_once()
    audit_service.log_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_test_flow_http_round_trips_stored_bearer_secret(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    user = _user()
    flow_service = AsyncMock()
    flow = _flow(flow_id).model_copy(
        update={
            "steps": [
                _flow_step(uuid4(), 1).model_copy(
                    update={
                        "output_config": {
                            "url": "https://example.org/api",
                            "auth": {
                                "mode": "bearer_token",
                                "token": "stored-token",
                            },
                            "body": {"mode": "auto"},
                            "custom_headers": [],
                            "timeout_seconds": 30,
                        }
                    }
                )
            ]
        }
    )
    flow.owner_user_id = user.id
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.audit_service.return_value = AsyncMock()
    container.user.return_value = user
    container.encryption_service.return_value = None
    _enable_space_access(container)

    sent: dict[str, object] = {}

    class _FakeRuntimeHelper:
        def __init__(self, **_kwargs):
            pass

        async def assert_url_allowed(self, url: str):
            return {"203.0.113.10"}

        def assert_connected_peer_allowed(self, *, response, preflight_resolved_ips):
            return None

    async def _fake_request(self, *, method, url, headers, content, json, timeout):
        sent["headers"] = dict(headers)
        request = httpx.Request(method=method, url=url, headers=headers)
        return httpx.Response(status_code=200, text="ok", request=request)

    monkeypatch.setattr(
        flow_http_test_router_module,
        "FlowHttpRuntimeHelper",
        _FakeRuntimeHelper,
        raising=False,
    )
    monkeypatch.setattr(httpx.AsyncClient, "request", _fake_request)

    response = await flow_definition_test_flow_http(
        id=flow_id,
        request=_request(),
        body=HttpTestRequest(
            config={
                "url": "https://example.org/api",
                "auth": {
                    "mode": "bearer_token",
                    "token": SECRET_SENTINEL,
                },
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
    assert sent["headers"] == {"Authorization": "Bearer stored-token"}


@pytest.mark.asyncio
async def test_test_flow_http_interpolates_variables_with_real_executor(monkeypatch):
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
    sent: dict[str, object] = {}

    class _FakeRuntimeHelper:
        def __init__(self, **kwargs):
            guard_calls["resolver_class"] = type(kwargs["variable_resolver"]).__name__

        async def assert_url_allowed(self, url: str):
            guard_calls["preflight_url"] = url
            return {"203.0.113.10"}

        def assert_connected_peer_allowed(self, *, response, preflight_resolved_ips):
            guard_calls["peer_status"] = response.status_code
            guard_calls["peer_ips"] = preflight_resolved_ips

    async def _fake_request(self, *, method, url, headers, content, json, timeout):
        sent.update(
            {
                "method": method,
                "url": str(url),
                "headers": dict(headers),
                "json": json,
                "timeout": timeout,
            }
        )
        request = httpx.Request(method=method, url=url, headers=headers)
        return httpx.Response(status_code=200, text="ok", request=request)

    monkeypatch.setattr(
        flow_http_test_router_module,
        "FlowHttpRuntimeHelper",
        _FakeRuntimeHelper,
        raising=False,
    )
    monkeypatch.setattr(httpx.AsyncClient, "request", _fake_request)

    response = await flow_definition_test_flow_http(
        id=flow_id,
        request=_request(),
        body=HttpTestRequest(
            config={
                "url": "{{base_url}}/api/{{name}}",
                "auth": {"mode": "none"},
                "body": {
                    "mode": "json_template",
                    "template": '{"message":"{{text}}"}',
                },
                "custom_headers": [
                    {"name": "X-Case", "value": "{{flow_input.case_id}}"}
                ],
                "timeout_seconds": 30,
            },
            direction="output",
            method="POST",
            test_variables={
                "base_url": "https://example.org",
                "name": "alex",
                "flow_input": {"case_id": "CASE-1"},
                "text": "hello",
            },
        ),
        container=container,
    )

    assert response.success is True
    assert response.request_preview is not None
    assert response.request_preview.model_dump() == {
        "method": "POST",
        "url": "https://example.org/api/alex",
        "headers": {"X-Case": "CASE-1"},
        "body_preview": '{"message": "hello"}',
    }
    assert sent["url"] == "https://example.org/api/alex"
    assert sent["json"] == {"message": "hello"}
    assert guard_calls["resolver_class"] == "FlowVariableResolver"
    assert guard_calls["preflight_url"] == "https://example.org/api/alex"
    assert guard_calls["peer_status"] == 200
    container.audit_service.return_value.log_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_flow_pins_audit_entity_ids(monkeypatch):
    container = MagicMock()
    user = _user()
    flow_id = uuid4()
    space_id = uuid4()
    flow = _flow(flow_id)
    flow.space_id = space_id
    flow.owner_user_id = user.id
    flow_service = AsyncMock()
    flow_service.create_flow.return_value = flow
    audit_service = AsyncMock()
    container.flow_service.return_value = flow_service
    container.audit_service.return_value = audit_service
    container.user.return_value = user
    _enable_space_access(container)
    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    response = await create_flow(
        request=_request(),
        flow_in=FlowCreateRequest(
            space_id=space_id,
            name="Flow",
            steps=[
                FlowStepCreateRequest(
                    assistant_id=uuid4(),
                    step_order=1,
                    input_source="flow_input",
                    input_type="text",
                    output_mode="pass_through",
                    output_type="json",
                    output_classification_override=2,
                    mcp_policy="inherit",
                )
            ],
        ),
        container=container,
    )

    assert response.id == flow_id
    assert [
        call.kwargs["action"] for call in audit_service.log_async.await_args_list
    ] == [
        ActionType.FLOW_CREATED,
        ActionType.FLOW_CLASSIFICATION_OVERRIDE,
    ]
    assert [
        call.kwargs["entity_id"] for call in audit_service.log_async.await_args_list
    ] == [flow_id, flow_id]


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
            request_preview=HttpRequestPreview(
                method="POST",
                url="https://example.org/api",
                headers={},
                body_preview=None,
            ),
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
        body=HttpTestRequest(
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
        result = flow_http_test_router_module.find_stored_http_config(flow, "output")

    assert result is None
    assert "Failed to parse stored HTTP config" in caplog.text


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
    update = kwargs["update"]
    assert isinstance(update, AssistantUpdateCommand)
    assert update.name == "Updated assistant"
    assert update.attachment_ids == [attachment_id]
    assert update.websites == [website_id]
    assert update.groups == [group_id]
    assert update.integration_knowledge_ids == [integration_knowledge_id]
    assert update.mcp_server_ids == [mcp_server_id]
    assert update.mcp_tools == [(mcp_tool_id, True)]
    assert update.completion_model_id == completion_model_id
    audit_service.log_async.assert_awaited_once()


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
async def test_update_flow_pins_audit_entity_ids():
    container = MagicMock()
    user = _user()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow.owner_user_id = user.id
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    flow_service.update_flow.return_value = flow
    audit_service = AsyncMock()
    container.flow_service.return_value = flow_service
    container.audit_service.return_value = audit_service
    container.user.return_value = user
    _enable_space_access(container, can_edit=True)

    update_req = FlowUpdateRequest(
        steps=[
            FlowStepUpdateRequest(
                id=flow.steps[0].id,
                assistant_id=flow.steps[0].assistant_id,
                step_order=flow.steps[0].step_order,
                input_source=flow.steps[0].input_source,
                input_type=flow.steps[0].input_type,
                output_mode=flow.steps[0].output_mode,
                output_type=flow.steps[0].output_type,
                output_classification_override=3,
                mcp_policy=flow.steps[0].mcp_policy,
            )
        ]
    )

    await definition_update_flow(
        id=flow_id,
        request=_request(),
        flow_in=update_req,
        container=container,
    )

    assert [
        call.kwargs["action"] for call in audit_service.log_async.await_args_list
    ] == [
        ActionType.FLOW_UPDATED,
        ActionType.FLOW_CLASSIFICATION_OVERRIDE,
    ]
    assert [
        call.kwargs["entity_id"] for call in audit_service.log_async.await_args_list
    ] == [flow_id, flow_id]


@pytest.mark.asyncio
async def test_update_flow_without_steps_does_not_log_classification_override():
    container = MagicMock()
    user = _user()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow.owner_user_id = user.id
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    flow_service.update_flow.return_value = flow
    audit_service = AsyncMock()
    container.flow_service.return_value = flow_service
    container.audit_service.return_value = audit_service
    container.user.return_value = user
    _enable_space_access(container, can_edit=True)

    await definition_update_flow(
        id=flow_id,
        request=_request(),
        flow_in=FlowUpdateRequest(name="New Name"),
        container=container,
    )

    assert [
        call.kwargs["action"] for call in audit_service.log_async.await_args_list
    ] == [ActionType.FLOW_UPDATED]


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
        flow_access_context_module,
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
        flow_access_context_module,
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
async def test_get_flow_allows_admin_service_key_principal(monkeypatch):
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
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="space", space_id=flow.space_id),
    )
    actor = _enable_space_access(
        container, can_read=True, user_permissions=[Permission.FLOWS]
    )
    actor.get_current_role.return_value = SpaceRole.ADMIN

    result = await definition_get_flow(
        id=flow_id,
        request=_request(),
        container=container,
    )

    assert result.id == flow.id
    assert result.steps[0].id == flow.steps[0].id
    actor.can_read_flow.assert_called_once_with(flow)


@pytest.mark.asyncio
async def test_get_flow_requires_admin_service_key_principal(monkeypatch):
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
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="space", space_id=flow.space_id),
    )
    actor = _enable_space_access(
        container, can_read=True, user_permissions=[Permission.FLOWS]
    )
    actor.get_current_role.return_value = SpaceRole.EDITOR

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_get_flow(
            id=flow_id,
            request=_request(),
            container=container,
        )

    assert exc_info.value.code == FlowApiErrorCode.SERVICE_KEY_ADMIN_REQUIRED.value
    assert str(exc_info.value) == (
        "Service-key principals require admin role to read draft definitions. "
        "Use /api/v1/flows/{id}/published/ for runtime-safe published projections."
    )
    context = exc_info.value.context
    assert context is not None
    assert context["auth_layer"] == "service_key_principal"
    assert context["capability"] == "view_current_definition"
    assert context["required_role"] == "admin"
    hint = context["runtime_endpoint_hint"]
    assert isinstance(hint, dict)
    assert hint == {
        "key": "published_flow_runtime",
        "description": "Use the published runtime projection for service-key Flow clients.",
        "endpoint_template": "/api/v1/flows/{id}/published/",
    }
    actor.can_read_flow.assert_not_called()


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
        flow_access_context_module,
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
        flow_access_context_module,
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
        flow_access_context_module,
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
