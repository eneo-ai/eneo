from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import (
    AsyncMock,
    MagicMock,
)
from uuid import uuid4

import httpx
import pytest

import intric.flows.api.flow_http_test_router as flow_http_test_router_module
from intric.actors.actors.space_actor import SpaceRole
from intric.assistants.api.assistant_models import AssistantUpdatePublic
from intric.authentication.auth_dependencies import ScopeFilter
from intric.flows.api import flow_router_common as router_common_module
from intric.flows.api.flow_assistant_router import (
    create_flow_assistant,
    update_flow_assistant,
)
from intric.flows.api.flow_authoring_router import (
    get_flow as definition_get_flow,
)
from intric.flows.api.flow_authoring_router import (
    get_published_flow_runtime,
)
from intric.flows.api.flow_authoring_router import (
    list_flows as definition_list_flows,
)
from intric.flows.api.flow_authoring_router import (
    update_flow as definition_update_flow,
)
from intric.flows.api.flow_http_test_router import (
    test_flow_http as flow_definition_test_flow_http,
)
from intric.flows.api.flow_models import (
    FlowAssistantCreateRequest,
    FlowUpdateRequest,
)
from intric.flows.application.flow_assistant_update import FlowAssistantUpdateCommand
from intric.flows.http_transport.test_action import HttpTestResult
from intric.main.exceptions import UnauthorizedException
from intric.roles.permissions import Permission
from tests.unittests.flows.test_flow_router import (
    _enable_space_access,
    _flow,
    _flow_step,
    _request,
    _service_key,
    _user,
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
    assert isinstance(update, FlowAssistantUpdateCommand)
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
