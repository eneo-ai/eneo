"""Tests for AI Builder router endpoints."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.files.file_models import FilePublic
from intric.flows.ai_builder.ai_builder_api_models import (
    ApplyPlanRequest,
    ApplyResultResponse,
    CreateSessionRequest,
    PlanResponse,
    RevisePlanRequest,
    SendMessageRequest,
    SessionListItemResponse,
    SessionListResponse,
    SessionModelsResponse,
    SessionPlansResponse,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    BuilderSession,
    ConversationMessage,
    PlanStatus,
    SessionStatus,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
    AIBuilderNotFoundException,
    AIBuilderUnauthorizedException,
)
from intric.flows.ai_builder.ai_builder_router import (
    AIBuilderPublicErrorRoute,
    _authorize_ai_builder_request,
    apply_plan,
    approve_plan,
    cancel_session,
    create_session,
    detach_session_attachment,
    get_plan,
    get_session,
    get_session_models,
    list_session_plans,
    list_sessions,
    revise_plan,
    send_message,
)
from intric.flows.ai_builder.ai_builder_router import (
    router as ai_builder_router,
)
from intric.flows.flow_access_policy import FlowApiAction
from intric.main.exceptions import (
    BadRequestException,
    ErrorCodes,
    NotFoundException,
    UnauthorizedException,
)
from intric.roles.permissions import Permission


def test_ai_builder_openapi_errors_reference_public_error_contract() -> None:
    app = FastAPI()
    app.include_router(ai_builder_router)

    openapi = app.openapi()
    assert "AIBuilderPublicError" in openapi["components"]["schemas"]
    apply_responses = openapi["paths"]["/ai-builder/plans/{plan_id}/apply"]["post"][
        "responses"
    ]
    assert apply_responses["409"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AIBuilderPublicError"
    }


def test_ai_builder_route_class_translates_http_errors_to_public_contract() -> None:
    app = FastAPI()
    test_router = APIRouter(route_class=AIBuilderPublicErrorRoute)

    @test_router.get("/busy")
    async def busy() -> None:
        raise AIBuilderBadRequestException(
            "Another AI Builder message is already being processed.",
            code=AIBuilderErrorCode.SESSION_MESSAGE_IN_PROGRESS,
        )

    @test_router.get("/planner-budget")
    async def planner_budget() -> None:
        raise AIBuilderBadRequestException(
            "No planner output budget is configured.",
            code=AIBuilderErrorCode.PLANNER_BUDGET_MISSING,
            context={"budget_owner": "space"},
        )

    @test_router.get("/invalid-settings")
    async def invalid_settings() -> None:
        raise AIBuilderBadRequestException(
            "minimum_conversation_budget_tokens must be an integer.",
            code=AIBuilderErrorCode.INVALID_AI_BUILDER_SETTINGS,
        )

    @test_router.get("/forbidden")
    async def forbidden() -> None:
        raise AIBuilderUnauthorizedException(
            "You do not have permission to use the AI builder in this space.",
            code=AIBuilderErrorCode.INSUFFICIENT_SPACE_PERMISSION,
            context={"auth_layer": "space_membership"},
        )

    @test_router.get("/missing")
    async def missing() -> None:
        raise AIBuilderNotFoundException(
            "AI Builder resource not found.",
            code=AIBuilderErrorCode.NOT_FOUND,
        )

    app.include_router(test_router)
    client = TestClient(app)

    response = client.get("/busy", headers={"x-request-id": "req-route"})

    assert response.status_code == 409
    assert response.json() == {
        "schema_version": 2,
        "code": "session_message_in_progress",
        "category": "conflict",
        "message": "Another AI Builder message is already being processed.",
        "phase": "router",
        "intric_error_code": int(ErrorCodes.BAD_REQUEST),
        "request_id": "req-route",
        "diagnostic_context": {
            "request_id": "req-route",
            "error_code": "session_message_in_progress",
            "error_category": "conflict",
            "error_phase": "router",
        },
    }

    response = client.get("/planner-budget", headers={"x-request-id": "req-planner"})
    assert response.status_code == 400
    assert response.json() == {
        "schema_version": 2,
        "code": "planner_budget_missing",
        "category": "bad_request",
        "message": "No planner output budget is configured.",
        "phase": "planner",
        "intric_error_code": int(ErrorCodes.BAD_REQUEST),
        "request_id": "req-planner",
        "diagnostic_context": {
            "request_id": "req-planner",
            "error_code": "planner_budget_missing",
            "error_category": "bad_request",
            "error_phase": "planner",
        },
        "details": {"budget_owner": "space"},
    }

    response = client.get("/invalid-settings", headers={"x-request-id": "req-settings"})
    assert response.status_code == 400
    assert response.json() == {
        "schema_version": 2,
        "code": "invalid_ai_builder_settings",
        "category": "bad_request",
        "message": "minimum_conversation_budget_tokens must be an integer.",
        "phase": "router",
        "intric_error_code": int(ErrorCodes.BAD_REQUEST),
        "request_id": "req-settings",
        "diagnostic_context": {
            "request_id": "req-settings",
            "error_code": "invalid_ai_builder_settings",
            "error_category": "bad_request",
            "error_phase": "router",
        },
    }

    response = client.get("/forbidden", headers={"x-request-id": "req-forbidden"})
    assert response.status_code == 403
    assert response.json() == {
        "schema_version": 2,
        "code": "insufficient_space_permission",
        "category": "unauthorized",
        "message": "You do not have permission to use the AI builder in this space.",
        "phase": "router",
        "intric_error_code": int(ErrorCodes.UNAUTHORIZED),
        "request_id": "req-forbidden",
        "diagnostic_context": {
            "request_id": "req-forbidden",
            "error_code": "insufficient_space_permission",
            "error_category": "unauthorized",
            "error_phase": "router",
        },
        "details": {"auth_layer": "space_membership"},
    }

    response = client.get("/missing", headers={"x-request-id": "req-missing"})
    assert response.status_code == 404
    assert response.json() == {
        "schema_version": 2,
        "code": "not_found",
        "category": "not_found",
        "message": "AI Builder resource not found.",
        "phase": "router",
        "intric_error_code": int(ErrorCodes.NOT_FOUND),
        "request_id": "req-missing",
        "diagnostic_context": {
            "request_id": "req-missing",
            "error_code": "not_found",
            "error_category": "not_found",
            "error_phase": "router",
        },
    }


def test_ai_builder_route_class_logs_raw_public_exception_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = FastAPI()
    test_router = APIRouter(route_class=AIBuilderPublicErrorRoute)

    @test_router.get("/raw")
    async def raw_exception() -> None:
        raise BadRequestException("Raw AI Builder exception.", code="not_registered")

    app.include_router(test_router)
    client = TestClient(app)

    with caplog.at_level(
        logging.ERROR,
        logger="intric.flows.ai_builder.ai_builder_router",
    ):
        response = client.get("/raw", headers={"x-request-id": "req-raw"})

    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"
    records = [
        record
        for record in caplog.records
        if record.message == "AI Builder raw public exception reached adapter."
    ]
    assert len(records) == 1
    assert records[0].request_id == "req-raw"
    assert records[0].surface == "route_bad_request"
    assert records[0].raw_error_code == "not_registered"
    assert records[0].fallback_error_code == "bad_request"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_container(
    *,
    user_id=None,
    tenant_id=None,
    can_edit_flows: bool = True,
) -> MagicMock:
    """Build a mock Container with common wiring."""
    container = MagicMock()

    user = MagicMock()
    user.id = user_id or uuid4()
    user.tenant_id = tenant_id or uuid4()
    user.permissions = [Permission.FLOWS]
    container.user.return_value = user

    # Space service + actor
    space = MagicMock()
    space.completion_models = []
    space.collections = []
    space.get_default_completion_model.return_value = None
    space_service = AsyncMock()
    space_service.get_space.return_value = space
    container.space_service.return_value = space_service

    actor = MagicMock()
    actor.can_edit_flows.return_value = can_edit_flows
    actor_manager = MagicMock()
    actor_manager.get_space_actor_from_space.return_value = actor
    container.actor_manager.return_value = actor_manager

    # Services
    service = AsyncMock()
    service.list_session_attachments.return_value = []
    service.get_session_attachment_snapshot.return_value = SimpleNamespace(
        files=[],
        warnings=[],
    )
    service.prepare_message_context.return_value = SimpleNamespace(
        planner_context=SimpleNamespace(
            available_models=[],
            available_kbs=[],
            available_mcps=[],
            max_input_tokens=4096,
            max_output_tokens=2048,
            budget_policy=SimpleNamespace(),
        ),
        litellm_model="openai/gpt-4",
        litellm_kwargs={"api_key": "sk-test"},
        structured_output_decision=object(),
        flow=None,
        assistant_snapshots=None,
        attachment_files=[],
    )
    container.ai_builder_service.return_value = service
    container.audit_service.return_value = AsyncMock()

    # Completion service (adapter resolution for LLM credentials)
    adapter = MagicMock()
    adapter.litellm_model = "openai/gpt-4"
    adapter.credential_resolver.get_api_key.return_value = "sk-test"
    adapter.credential_resolver.get_credential_field.return_value = None
    completion_service = AsyncMock()
    completion_service._get_adapter.return_value = adapter
    container.completion_service.return_value = completion_service

    # Flow service
    container.flow_service.return_value = AsyncMock()

    # Tenant repo
    tenant_mock = MagicMock()
    tenant_mock.flow_settings = None
    tenant_repo = AsyncMock()
    tenant_repo.get.return_value = tenant_mock
    container.tenant_repo.return_value = tenant_repo

    # Model service fallback
    model_service = AsyncMock()
    model_service.get_default_completion_model.return_value = MagicMock()
    container.completion_model_crud_service.return_value = model_service

    return container


def _make_apply_plan_client(container: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(ai_builder_router)

    async def override_container():
        return container

    for route in app.routes:
        if (
            isinstance(route, APIRoute)
            and route.path == "/ai-builder/plans/{plan_id}/apply"
        ):
            for dependency in route.dependant.dependencies:
                if dependency.name == "container":
                    app.dependency_overrides[dependency.call] = override_container
                    return TestClient(app)
            raise AssertionError("AI Builder apply-plan container dependency was missing.")

    raise AssertionError("AI Builder apply-plan route was not registered.")


def _make_request(*, scoped_space_id=None) -> MagicMock:
    request = MagicMock()
    if scoped_space_id is None:
        request.state = SimpleNamespace()
    else:
        request.state = SimpleNamespace(
            api_key_scope_type="space",
            api_key_scope_id=scoped_space_id,
        )
    return request


async def _read_sse_events(response) -> list[dict[str, object]]:
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        if hasattr(chunk, "encode") and not isinstance(chunk, (bytes, str)):
            encoded = chunk.encode()
            chunks.append(
                encoded.decode() if isinstance(encoded, bytes) else str(encoded)
            )
        elif isinstance(chunk, bytes):
            chunks.append(chunk.decode())
        else:
            chunks.append(str(chunk))

    body = "".join(chunks)
    events: list[dict[str, object]] = []
    current_event: str | None = None
    data_lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.rstrip("\r")
        if line.startswith("event:"):
            current_event = line[6:].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
            continue
        if line == "" and current_event is not None:
            raw_data = "\n".join(data_lines)
            events.append(
                {
                    "event": current_event,
                    "data": json.loads(raw_data) if raw_data else {},
                }
            )
            current_event = None
            data_lines = []

    if current_event is not None:
        raw_data = "\n".join(data_lines)
        events.append(
            {"event": current_event, "data": json.loads(raw_data) if raw_data else {}}
        )

    return events


def _make_session_domain(
    *,
    session_id=None,
    space_id=None,
    flow_id=None,
    target_kind=TargetKind.CREATE,
    status=SessionStatus.CHATTING,
    actor_user_id=None,
) -> BuilderSession:
    return BuilderSession(
        id=session_id or uuid4(),
        tenant_id=uuid4(),
        space_id=space_id or uuid4(),
        flow_id=flow_id,
        target_kind=target_kind,
        status=status,
        actor_user_id=actor_user_id or uuid4(),
    )


def _configure_space_with_planner_model(container: MagicMock, *, model=None):
    planner_model = model or MagicMock()
    space = container.space_service.return_value.get_space.return_value
    space.get_default_completion_model.return_value = planner_model
    space.completion_models = [planner_model]
    return planner_model


def _make_plan_domain(
    *,
    plan_id=None,
    session_id=None,
    status=PlanStatus.APPROVED,
) -> BuilderPlan:
    from intric.flows.ai_builder.ai_builder_domain_models import (
        PlannerPlanEnvelope,
    )
    from intric.flows.flow_authoring_spec import (
        AssistantSpec,
        FlowDraftSpecCore,
        InputSource,
        StepSpec,
    )

    spec = FlowDraftSpecCore(
        flow_name="Test",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Step A",
                assistant_spec=AssistantSpec(instructions="Do it."),
                input_source=InputSource.FLOW_INPUT,
            )
        ],
    )
    return BuilderPlan(
        id=plan_id or uuid4(),
        session_id=session_id or uuid4(),
        tenant_id=uuid4(),
        status=status,
        spec=spec,
        spec_hash=spec.spec_hash(),
        envelope=PlannerPlanEnvelope(spec=spec),
    )


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestAuthorizeAIBuilderRequest:
    @pytest.mark.anyio
    async def test_allows_when_can_edit(self):
        container = _make_container(can_edit_flows=True)
        authorization = await _authorize_ai_builder_request(
            _make_request(),
            container,
            action=FlowApiAction.BUILDER_SESSION_CREATE,
            space_id=uuid4(),
        )

        assert authorization.space is not None

    @pytest.mark.anyio
    async def test_raises_when_cannot_edit(self):
        container = _make_container(can_edit_flows=False)
        with pytest.raises(UnauthorizedException, match="permission"):
            await _authorize_ai_builder_request(
                _make_request(),
                container,
                action=FlowApiAction.BUILDER_SESSION_CREATE,
                space_id=uuid4(),
            )


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


class TestCreateSessionEndpoint:
    @pytest.mark.anyio
    async def test_creates_session_and_returns_response(self):
        container = _make_container()
        space_id = uuid4()
        _configure_space_with_planner_model(container)
        session = _make_session_domain(space_id=space_id)
        service = container.ai_builder_service.return_value
        service.create_session.return_value = session

        body = CreateSessionRequest(
            target_kind=TargetKind.CREATE,
            space_id=space_id,
        )
        result = await create_session(
            request=MagicMock(),
            body=body,
            container=container,
        )

        assert result.session_id == session.id
        assert result.status == SessionStatus.CHATTING
        assert result.target_kind == TargetKind.CREATE
        service.create_session.assert_called_once_with(
            space_id=space_id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
            force_new=False,
        )

    @pytest.mark.anyio
    async def test_passes_force_new_to_service(self):
        container = _make_container()
        space_id = uuid4()
        _configure_space_with_planner_model(container)
        session = _make_session_domain(space_id=space_id)
        service = container.ai_builder_service.return_value
        service.create_session.return_value = session

        await create_session(
            request=MagicMock(),
            body=CreateSessionRequest(
                target_kind=TargetKind.CREATE,
                space_id=space_id,
                force_new=True,
            ),
            container=container,
        )

        assert service.create_session.call_args.kwargs["force_new"] is True

    @pytest.mark.anyio
    async def test_logs_audit_event(self):
        container = _make_container()
        user = container.user.return_value
        space_id = uuid4()
        flow_id = uuid4()
        _configure_space_with_planner_model(container)
        session = _make_session_domain(
            space_id=space_id,
            flow_id=flow_id,
            target_kind=TargetKind.EDIT,
            actor_user_id=user.id,
        )
        service = container.ai_builder_service.return_value
        service.create_session.return_value = session

        body = CreateSessionRequest(
            target_kind=TargetKind.EDIT,
            space_id=space_id,
            flow_id=flow_id,
        )
        await create_session(
            request=MagicMock(),
            body=body,
            container=container,
        )

        audit_service = container.audit_service.return_value
        audit_service.log_async.assert_awaited_once()
        call_kwargs = audit_service.log_async.await_args.kwargs
        assert call_kwargs["tenant_id"] == user.tenant_id
        assert call_kwargs["actor_id"] == user.id
        assert call_kwargs["action"] == ActionType.AI_BUILDER_SESSION_CREATED
        assert call_kwargs["entity_type"] == EntityType.AI_BUILDER_SESSION
        assert call_kwargs["entity_id"] == session.id
        metadata = call_kwargs["metadata"]
        assert metadata["actor"]["id"] == str(user.id)
        assert metadata["target"]["id"] == str(session.id)
        assert metadata["target"]["space_id"] == str(space_id)
        assert metadata["extra"] == {
            "target_kind": TargetKind.EDIT.value,
            "flow_id": str(flow_id),
        }

    @pytest.mark.anyio
    async def test_checks_flow_edit_permission(self):
        container = _make_container(can_edit_flows=False)
        body = CreateSessionRequest(
            target_kind=TargetKind.CREATE,
            space_id=uuid4(),
        )
        with pytest.raises(UnauthorizedException):
            await create_session(
                request=MagicMock(),
                body=body,
                container=container,
            )

    @pytest.mark.anyio
    async def test_requires_manage_permission_for_ai_builder(self):
        container = _make_container()
        container.user.return_value.permissions = [Permission.FLOWS_AI_BUILDER]

        with pytest.raises(UnauthorizedException) as exc_info:
            await create_session(
                request=MagicMock(),
                body=CreateSessionRequest(
                    target_kind=TargetKind.CREATE,
                    space_id=uuid4(),
                ),
                container=container,
            )

        assert exc_info.value.code == "insufficient_tenant_permission"

    @pytest.mark.anyio
    async def test_requires_ai_builder_permission_for_ai_builder(self):
        container = _make_container()
        container.user.return_value.permissions = [Permission.FLOWS_MANAGE]

        with pytest.raises(UnauthorizedException) as exc_info:
            await create_session(
                request=MagicMock(),
                body=CreateSessionRequest(
                    target_kind=TargetKind.CREATE,
                    space_id=uuid4(),
                ),
                container=container,
            )

        assert exc_info.value.code == "insufficient_tenant_permission"

    @pytest.mark.anyio
    async def test_rejects_user_with_no_roles(self):
        container = _make_container()
        container.user.return_value.permissions = []

        with pytest.raises(UnauthorizedException) as exc_info:
            await create_session(
                request=MagicMock(),
                body=CreateSessionRequest(
                    target_kind=TargetKind.CREATE,
                    space_id=uuid4(),
                ),
                container=container,
            )

        assert exc_info.value.code == "insufficient_tenant_permission"

    @pytest.mark.anyio
    async def test_rejects_scoped_key_for_other_space(self):
        container = _make_container()
        allowed_space_id = uuid4()
        requested_space_id = uuid4()
        body = CreateSessionRequest(
            target_kind=TargetKind.CREATE,
            space_id=requested_space_id,
        )

        with pytest.raises(UnauthorizedException) as exc_info:
            await create_session(
                request=_make_request(scoped_space_id=allowed_space_id),
                body=body,
                container=container,
            )

        assert exc_info.value.code == "insufficient_scope"
        assert exc_info.value.context == {"auth_layer": "api_key_scope"}
        container.ai_builder_service.return_value.create_session.assert_not_called()

    @pytest.mark.anyio
    async def test_fails_closed_when_no_space_planner_model_exists(self):
        container = _make_container()
        body = CreateSessionRequest(
            target_kind=TargetKind.CREATE,
            space_id=uuid4(),
        )
        space = container.space_service.return_value.get_space.return_value
        space.get_default_completion_model.return_value = None
        space.completion_models = []

        with pytest.raises(BadRequestException, match="No AI builder planner model"):
            await create_session(
                request=MagicMock(),
                body=body,
                container=container,
            )

        container.ai_builder_service.return_value.create_session.assert_not_called()


class TestGetSessionEndpoint:
    @pytest.mark.anyio
    async def test_returns_session_response(self):
        container = _make_container()
        session = _make_session_domain(actor_user_id=container.user.return_value.id)
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session
        service.list_session_attachments.return_value = []

        result = await get_session(
            request=MagicMock(),
            session_id=session.id,
            container=container,
        )

        assert result.session_id == session.id
        assert result.status == session.status
        assert result.target_kind == session.target_kind

    @pytest.mark.anyio
    async def test_returns_session_attachments(self):
        container = _make_container()
        session = _make_session_domain(actor_user_id=container.user.return_value.id)
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session
        service.get_session_attachment_snapshot.return_value = SimpleNamespace(
            files=[
                FilePublic(
                    id=uuid4(), name="brief.pdf", mimetype="application/pdf", size=1234
                )
            ],
            warnings=[],
        )

        result = await get_session(
            request=MagicMock(),
            session_id=session.id,
            container=container,
        )

        assert result.attachments is not None
        assert result.attachments[0].name == "brief.pdf"

    @pytest.mark.anyio
    async def test_returns_session_attachment_warnings(self):
        container = _make_container()
        session = _make_session_domain(actor_user_id=container.user.return_value.id)
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session
        service.get_session_attachment_snapshot.return_value = SimpleNamespace(
            files=[],
            warnings=["One or more files are unavailable."],
        )

        result = await get_session(
            request=MagicMock(),
            session_id=session.id,
            container=container,
        )

        assert result.attachment_warnings == ["One or more files are unavailable."]

    @pytest.mark.anyio
    async def test_returns_session_telemetry_summary(self):
        container = _make_container()
        session = _make_session_domain(actor_user_id=container.user.return_value.id)
        session.conversation = [
            ConversationMessage(
                role="assistant",
                content="Done.",
                metadata={
                    "planner_telemetry": {
                        "request_id": "req-1",
                        "model": "openai/gpt-4",
                        "finish_reason": "stop",
                        "prompt_tokens": 10,
                        "completion_tokens": 4,
                        "total_tokens": 14,
                        "tool_call_count": 0,
                        "used_auxiliary_llm": False,
                    },
                    "session_telemetry": {
                        "planner_request_count": 1,
                        "clarification_question_count": 0,
                        "prompt_tokens_total": 10,
                        "completion_tokens_total": 4,
                        "total_tokens_total": 14,
                        "tool_call_count_total": 0,
                        "auxiliary_llm_call_count": 0,
                        "last_request_id": "req-1",
                        "last_model": "openai/gpt-4",
                        "last_finish_reason": "stop",
                    },
                },
            )
        ]
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session
        service.get_session_attachment_snapshot.return_value = SimpleNamespace(
            files=[],
            warnings=[],
        )

        result = await get_session(
            request=MagicMock(),
            session_id=session.id,
            container=container,
        )

        assert result.telemetry is not None
        assert result.telemetry.planner_request_count == 1
        assert result.telemetry.total_tokens_total == 14
        assert result.telemetry.last_model == "openai/gpt-4"

    @pytest.mark.anyio
    async def test_detach_session_attachment_calls_service(self):
        container = _make_container()
        session = _make_session_domain(actor_user_id=container.user.return_value.id)
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session
        file_id = uuid4()

        response = await detach_session_attachment(
            request=MagicMock(),
            session_id=session.id,
            file_id=file_id,
            container=container,
        )

        assert response.status_code == 204
        service.detach_session_attachment.assert_awaited_once_with(
            session_id=session.id,
            file_id=file_id,
        )

    @pytest.mark.anyio
    async def test_checks_flow_edit_permission(self):
        container = _make_container(can_edit_flows=False)
        session = _make_session_domain()
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        with pytest.raises(UnauthorizedException):
            await get_session(
                request=MagicMock(),
                session_id=session.id,
                container=container,
            )

    @pytest.mark.anyio
    async def test_rejects_without_ai_builder_permission(self):
        container = _make_container()
        container.user.return_value.permissions = [Permission.FLOWS_MANAGE]
        session = _make_session_domain()
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        with pytest.raises(UnauthorizedException) as exc_info:
            await get_session(
                request=MagicMock(),
                session_id=session.id,
                container=container,
            )

        assert exc_info.value.code == "insufficient_tenant_permission"

    @pytest.mark.anyio
    async def test_rejects_scoped_key_for_other_session_space(self):
        container = _make_container()
        session = _make_session_domain(space_id=uuid4())
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        with pytest.raises(UnauthorizedException) as exc_info:
            await get_session(
                request=_make_request(scoped_space_id=uuid4()),
                session_id=session.id,
                container=container,
            )

        assert exc_info.value.code == "insufficient_scope"
        assert exc_info.value.context == {"auth_layer": "api_key_scope"}

    @pytest.mark.anyio
    async def test_rejects_non_creator_even_with_space_edit_permission(self):
        container = _make_container()
        session = _make_session_domain(actor_user_id=uuid4())
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        with pytest.raises(UnauthorizedException) as exc_info:
            await get_session(
                request=MagicMock(),
                session_id=session.id,
                container=container,
            )

        assert exc_info.value.code == "session_creator_required"


class TestListSessionsEndpoint:
    @pytest.mark.anyio
    async def test_returns_visible_sessions(self):
        container = _make_container()
        service = container.ai_builder_service.return_value
        session = SessionListItemResponse(
            session_id=uuid4(),
            space_id=uuid4(),
            status=SessionStatus.CHATTING,
            target_kind=TargetKind.CREATE,
            flow_id=None,
            latest_plan_id=None,
            draft_title="Draft",
        )
        service.list_sessions.return_value = [session]

        result = await list_sessions(request=MagicMock(), container=container)

        assert isinstance(result, SessionListResponse)
        assert result.sessions == [session]
        container.space_service.return_value.get_space.assert_awaited_once_with(
            session.space_id
        )

    @pytest.mark.anyio
    async def test_filters_sessions_for_scoped_api_key(self):
        container = _make_container()
        scoped_space_id = uuid4()
        allowed_session = SessionListItemResponse(
            session_id=uuid4(),
            space_id=scoped_space_id,
            status=SessionStatus.CHATTING,
            target_kind=TargetKind.CREATE,
            flow_id=None,
            latest_plan_id=None,
            draft_title="Allowed draft",
        )
        hidden_session = SessionListItemResponse(
            session_id=uuid4(),
            space_id=uuid4(),
            status=SessionStatus.CHATTING,
            target_kind=TargetKind.CREATE,
            flow_id=None,
            latest_plan_id=None,
            draft_title="Hidden draft",
        )
        service = container.ai_builder_service.return_value
        service.list_sessions.return_value = [allowed_session, hidden_session]

        result = await list_sessions(
            request=_make_request(scoped_space_id=scoped_space_id),
            container=container,
        )

        assert result.sessions == [allowed_session]
        container.space_service.return_value.get_space.assert_awaited_once_with(
            allowed_session.space_id
        )

    @pytest.mark.anyio
    async def test_hides_sessions_when_space_lookup_is_not_found(self):
        container = _make_container()
        session = SessionListItemResponse(
            session_id=uuid4(),
            space_id=uuid4(),
            status=SessionStatus.CHATTING,
            target_kind=TargetKind.CREATE,
            flow_id=None,
            latest_plan_id=None,
            draft_title="Draft",
        )
        service = container.ai_builder_service.return_value
        service.list_sessions.return_value = [session]
        container.space_service.return_value.get_space.side_effect = NotFoundException(
            "missing"
        )

        result = await list_sessions(request=MagicMock(), container=container)

        assert result.sessions == []

    @pytest.mark.anyio
    async def test_list_sessions_propagates_unexpected_space_lookup_errors(self):
        container = _make_container()
        session = SessionListItemResponse(
            session_id=uuid4(),
            space_id=uuid4(),
            status=SessionStatus.CHATTING,
            target_kind=TargetKind.CREATE,
            flow_id=None,
            latest_plan_id=None,
            draft_title="Draft",
        )
        service = container.ai_builder_service.return_value
        service.list_sessions.return_value = [session]
        container.space_service.return_value.get_space.side_effect = RuntimeError(
            "db down"
        )

        with pytest.raises(RuntimeError, match="db down"):
            await list_sessions(request=MagicMock(), container=container)

    @pytest.mark.anyio
    async def test_rejects_list_sessions_without_required_permissions(self):
        container = _make_container()
        container.user.return_value.permissions = []

        with pytest.raises(UnauthorizedException) as exc_info:
            await list_sessions(request=MagicMock(), container=container)

        assert exc_info.value.code == "insufficient_tenant_permission"


class TestCancelSessionEndpoint:
    @pytest.mark.anyio
    async def test_cancels_session_and_logs_audit(self):
        container = _make_container()
        user = container.user.return_value
        flow_id = uuid4()
        session = _make_session_domain(
            actor_user_id=user.id,
            flow_id=flow_id,
            target_kind=TargetKind.EDIT,
        )
        cancelled = _make_session_domain(
            session_id=session.id,
            space_id=session.space_id,
            flow_id=flow_id,
            target_kind=TargetKind.EDIT,
            actor_user_id=user.id,
            status=SessionStatus.CANCELLED,
        )
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session
        service.cancel_session.return_value = cancelled

        result = await cancel_session(
            request=MagicMock(),
            session_id=session.id,
            container=container,
        )

        assert result.status == SessionStatus.CANCELLED
        service.cancel_session.assert_called_once_with(session.id)
        audit_service = container.audit_service.return_value
        audit_service.log_async.assert_awaited_once()
        call_kwargs = audit_service.log_async.await_args.kwargs
        assert call_kwargs["tenant_id"] == user.tenant_id
        assert call_kwargs["actor_id"] == user.id
        assert call_kwargs["action"] == ActionType.AI_BUILDER_SESSION_CANCELLED
        assert call_kwargs["entity_type"] == EntityType.AI_BUILDER_SESSION
        assert call_kwargs["entity_id"] == session.id
        metadata = call_kwargs["metadata"]
        assert metadata["actor"]["id"] == str(user.id)
        assert metadata["target"]["id"] == str(session.id)
        assert metadata["target"]["space_id"] == str(session.space_id)
        assert metadata["extra"] == {"target_kind": TargetKind.EDIT.value}

    @pytest.mark.anyio
    async def test_rejects_non_creator_even_with_space_edit_permission(self):
        container = _make_container()
        session = _make_session_domain(actor_user_id=uuid4())
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        with pytest.raises(UnauthorizedException) as exc_info:
            await cancel_session(
                request=MagicMock(),
                session_id=session.id,
                container=container,
            )

        assert exc_info.value.code == "session_creator_required"
        service.cancel_session.assert_not_called()


class TestGetSessionModelsEndpoint:
    @pytest.mark.anyio
    async def test_returns_typed_models_response(self):
        container = _make_container()
        session = _make_session_domain(actor_user_id=container.user.return_value.id)
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        model = MagicMock()
        model.id = uuid4()
        model.name = "GPT-4"
        model.provider_type = "openai"
        space = container.space_service.return_value.get_space.return_value
        space.completion_models = [model]
        space.get_default_completion_model.return_value = model

        result = await get_session_models(
            request=MagicMock(),
            session_id=session.id,
            container=container,
        )

        assert isinstance(result, SessionModelsResponse)
        assert result.default_model_id == model.id
        assert result.models[0].id == model.id
        assert result.models[0].name == "GPT-4"
        space_service = container.space_service.return_value
        space_service.get_space.assert_awaited_once_with(session.space_id)

    @pytest.mark.anyio
    async def test_checks_flow_edit_permission(self):
        container = _make_container(can_edit_flows=False)
        session = _make_session_domain()
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        with pytest.raises(UnauthorizedException):
            await get_session_models(
                request=MagicMock(),
                session_id=session.id,
                container=container,
            )

    @pytest.mark.anyio
    async def test_rejects_non_creator_even_with_space_edit_permission(self):
        container = _make_container()
        session = _make_session_domain(actor_user_id=uuid4())
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        with pytest.raises(UnauthorizedException) as exc_info:
            await get_session_models(
                request=MagicMock(),
                session_id=session.id,
                container=container,
            )

        assert exc_info.value.code == "session_creator_required"


class TestPlanRecoveryEndpoints:
    @pytest.mark.anyio
    async def test_get_plan_returns_typed_response(self):
        container = _make_container()
        plan = _make_plan_domain()
        session = _make_session_domain(
            session_id=plan.session_id,
            actor_user_id=container.user.return_value.id,
        )
        service = container.ai_builder_service.return_value
        service.get_plan.return_value = plan
        service.get_session.return_value = session

        result = await get_plan(
            request=MagicMock(),
            plan_id=plan.id,
            container=container,
        )

        assert isinstance(result, PlanResponse)
        assert result.plan_id == plan.id
        assert result.session_id == plan.session_id
        assert result.status == plan.status

    @pytest.mark.anyio
    async def test_get_plan_hides_reasoning(self):
        container = _make_container()
        plan = _make_plan_domain()
        plan.envelope.reasoning = "Hidden"
        session = _make_session_domain(
            session_id=plan.session_id,
            actor_user_id=container.user.return_value.id,
        )
        service = container.ai_builder_service.return_value
        service.get_plan.return_value = plan
        service.get_session.return_value = session

        result = await get_plan(
            request=MagicMock(),
            plan_id=plan.id,
            container=container,
        )

        assert result.envelope.reasoning is None

    @pytest.mark.anyio
    async def test_get_plan_rejects_scoped_key_for_other_space(self):
        container = _make_container()
        plan = _make_plan_domain()
        session = _make_session_domain(
            session_id=plan.session_id,
            space_id=uuid4(),
            actor_user_id=container.user.return_value.id,
        )
        service = container.ai_builder_service.return_value
        service.get_plan.return_value = plan
        service.get_session.return_value = session

        with pytest.raises(UnauthorizedException) as exc_info:
            await get_plan(
                request=_make_request(scoped_space_id=uuid4()),
                plan_id=plan.id,
                container=container,
            )

        assert exc_info.value.code == "insufficient_scope"
        assert exc_info.value.context == {"auth_layer": "api_key_scope"}

    @pytest.mark.anyio
    async def test_get_plan_rejects_non_creator_even_with_space_edit_permission(self):
        container = _make_container()
        plan = _make_plan_domain()
        session = _make_session_domain(
            session_id=plan.session_id,
            actor_user_id=uuid4(),
        )
        service = container.ai_builder_service.return_value
        service.get_plan.return_value = plan
        service.get_session.return_value = session

        with pytest.raises(UnauthorizedException) as exc_info:
            await get_plan(
                request=MagicMock(),
                plan_id=plan.id,
                container=container,
            )

        assert exc_info.value.code == "session_creator_required"

    @pytest.mark.anyio
    async def test_list_session_plans_returns_typed_response(self):
        container = _make_container()
        session = _make_session_domain(actor_user_id=container.user.return_value.id)
        plan = _make_plan_domain(session_id=session.id)
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session
        service.list_session_plans.return_value = [plan]

        result = await list_session_plans(
            request=MagicMock(),
            session_id=session.id,
            container=container,
        )

        assert isinstance(result, SessionPlansResponse)
        assert len(result.plans) == 1
        assert result.plans[0].plan_id == plan.id

    @pytest.mark.anyio
    async def test_list_session_plans_checks_permission(self):
        container = _make_container(can_edit_flows=False)
        session = _make_session_domain()
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        with pytest.raises(UnauthorizedException):
            await list_session_plans(
                request=MagicMock(),
                session_id=session.id,
                container=container,
            )

    @pytest.mark.anyio
    async def test_list_session_plans_rejects_non_creator_even_with_space_edit_permission(
        self,
    ):
        container = _make_container()
        session = _make_session_domain(actor_user_id=uuid4())
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        with pytest.raises(UnauthorizedException) as exc_info:
            await list_session_plans(
                request=MagicMock(),
                session_id=session.id,
                container=container,
            )

        assert exc_info.value.code == "session_creator_required"
        service.list_session_plans.assert_not_called()


class TestSendMessageEndpoint:
    @pytest.mark.anyio
    async def test_returns_event_source_response(self):
        from sse_starlette import EventSourceResponse

        container = _make_container()
        _configure_space_with_planner_model(container)
        session = _make_session_domain(actor_user_id=container.user.return_value.id)
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        async def mock_events(*args, **kwargs):
            yield {"event": "text", "data": '{"text": "Hello"}'}
            yield {"event": "done", "data": ""}

        service.send_message.return_value = mock_events()

        body = SendMessageRequest(message="Build a flow")
        result = await send_message(
            request=MagicMock(),
            session_id=session.id,
            body=body,
            container=container,
        )

        assert isinstance(result, EventSourceResponse)

    @pytest.mark.anyio
    async def test_forwards_file_ids_to_prepare_context_and_send_message(self):
        container = _make_container()
        _configure_space_with_planner_model(container)
        session = _make_session_domain(actor_user_id=container.user.return_value.id)
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        async def mock_events(*args, **kwargs):
            yield {"event": "done", "data": ""}

        service.send_message.return_value = mock_events()
        file_id = uuid4()

        response = await send_message(
            request=MagicMock(),
            session_id=session.id,
            body=SendMessageRequest(message="Build a flow", file_ids=[file_id]),
            container=container,
        )
        await _read_sse_events(response)

        assert service.prepare_message_context.await_args.kwargs[
            "message_file_ids"
        ] == [file_id]
        assert service.send_message.call_args.kwargs["file_ids"] == [file_id]

    @pytest.mark.anyio
    async def test_streams_usage_event_after_committed_message_event(self):
        container = _make_container()
        _configure_space_with_planner_model(container)
        session = _make_session_domain(actor_user_id=container.user.return_value.id)
        session.conversation = [
            ConversationMessage(
                role="assistant",
                content="Plan ready",
                metadata={
                    "session_telemetry": {
                        "planner_request_count": 1,
                        "clarification_question_count": 0,
                        "prompt_tokens_total": 10,
                        "completion_tokens_total": 7,
                        "total_tokens_total": 17,
                        "tool_call_count_total": 1,
                        "auxiliary_llm_call_count": 0,
                        "architecture_commit_count": 0,
                        "repair_attempts_total": 0,
                        "parse_repair_attempts_total": 0,
                        "wall_clock_ms_total": 0,
                        "llm_calls_made_total": 1,
                        "token_usage_estimated": False,
                        "last_request_id": "req-usage",
                        "last_model": "openai/gpt-5.4-nano",
                        "last_finish_reason": "tool_calls",
                        "last_outcome_kind": "dispatched",
                        "last_token_usage_source": "provider",
                        "last_token_usage_estimated": False,
                    }
                },
            )
        ]
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        async def mock_events(*args, **kwargs):
            yield {"event": "plan", "data": '{"plan_id":"plan-1"}'}
            yield {"event": "done", "data": ""}

        service.send_message.return_value = mock_events()

        result = await send_message(
            request=MagicMock(),
            session_id=session.id,
            body=SendMessageRequest(message="Build a flow"),
            container=container,
        )

        events = await _read_sse_events(result)
        assert [event["event"] for event in events] == ["plan", "usage", "done"]
        usage = events[1]["data"]
        assert usage["total_tokens_total"] == 17
        assert usage["last_model"] == "openai/gpt-5.4-nano"
        assert usage["last_token_usage_source"] == "provider"

    @pytest.mark.anyio
    async def test_streams_late_usage_before_done_when_summary_is_ready_after_stream(
        self,
    ):
        container = _make_container()
        _configure_space_with_planner_model(container)
        session = _make_session_domain(actor_user_id=container.user.return_value.id)
        telemetry_session = _make_session_domain(
            session_id=session.id,
            space_id=session.space_id,
            target_kind=session.target_kind,
            actor_user_id=session.actor_user_id,
        )
        telemetry_session.conversation = [
            ConversationMessage(
                role="assistant",
                content="Plan ready",
                metadata={
                    "session_telemetry": {
                        "planner_request_count": 1,
                        "clarification_question_count": 0,
                        "prompt_tokens_total": 20,
                        "completion_tokens_total": 5,
                        "total_tokens_total": 25,
                        "tool_call_count_total": 1,
                        "auxiliary_llm_call_count": 0,
                        "architecture_commit_count": 0,
                        "repair_attempts_total": 0,
                        "parse_repair_attempts_total": 0,
                        "wall_clock_ms_total": 0,
                        "llm_calls_made_total": 1,
                        "token_usage_estimated": False,
                        "last_request_id": "req-retry-usage",
                        "last_model": "openai/gpt-5.4-nano",
                        "last_finish_reason": "tool_calls",
                        "last_outcome_kind": "dispatched",
                        "last_token_usage_source": "provider",
                        "last_token_usage_estimated": False,
                    }
                },
            )
        ]
        service = container.ai_builder_service.return_value
        service.get_session.side_effect = [session, telemetry_session]

        async def mock_events(*args, **kwargs):
            yield {"event": "plan", "data": '{"plan_id":"plan-1"}'}
            yield {"event": "done", "data": ""}

        service.send_message.return_value = mock_events()

        result = await send_message(
            request=MagicMock(),
            session_id=session.id,
            body=SendMessageRequest(message="Build a flow"),
            container=container,
        )

        events = await _read_sse_events(result)
        assert [event["event"] for event in events] == ["plan", "usage", "done"]
        usage = events[1]["data"]
        assert usage["total_tokens_total"] == 25
        assert usage["last_request_id"] == "req-retry-usage"

    @pytest.mark.anyio
    async def test_forwards_existing_usage_event_without_duplicate(self):
        container = _make_container()
        _configure_space_with_planner_model(container)
        session = _make_session_domain(actor_user_id=container.user.return_value.id)
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        async def mock_events(*args, **kwargs):
            yield {"event": "plan", "data": '{"plan_id":"plan-1"}'}
            yield {
                "event": "usage",
                "data": json.dumps({"total_tokens_total": 11}),
            }
            yield {"event": "done", "data": ""}

        service.send_message.return_value = mock_events()

        result = await send_message(
            request=MagicMock(),
            session_id=session.id,
            body=SendMessageRequest(message="Build a flow"),
            container=container,
        )

        events = await _read_sse_events(result)
        assert [event["event"] for event in events] == ["plan", "usage", "done"]
        assert events[1]["data"] == {"total_tokens_total": 11}

    @pytest.mark.anyio
    async def test_checks_flow_edit_permission(self):
        container = _make_container(can_edit_flows=False)
        session = _make_session_domain()
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        body = SendMessageRequest(message="Hello")
        with pytest.raises(UnauthorizedException):
            await send_message(
                request=MagicMock(),
                session_id=session.id,
                body=body,
                container=container,
            )

    @pytest.mark.anyio
    async def test_rejects_non_creator_even_with_space_edit_permission(self):
        container = _make_container()
        _configure_space_with_planner_model(container)
        session = _make_session_domain(actor_user_id=uuid4())
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        with pytest.raises(UnauthorizedException) as exc_info:
            await send_message(
                request=MagicMock(),
                session_id=session.id,
                body=SendMessageRequest(message="Hello"),
                container=container,
            )

        assert exc_info.value.code == "session_creator_required"
        service.prepare_message_context.assert_not_called()

    @pytest.mark.anyio
    async def test_resolves_model_and_context(self):
        """Verify the endpoint resolves planner context through the service seam."""
        container = _make_container()
        session = _make_session_domain(
            flow_id=uuid4(),
            actor_user_id=container.user.return_value.id,
        )
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        # Set up space with models and KBs
        model = MagicMock()
        model.id = uuid4()
        model.name = "GPT-4"
        model.provider_type = "openai"
        space_service = container.space_service.return_value
        space = space_service.get_space.return_value
        space.completion_models = [model]
        space.get_default_completion_model.return_value = model

        collection = MagicMock()
        collection.id = uuid4()
        collection.name = "Docs"
        collection.description = "Documentation"
        space.collections = [collection]

        flow = MagicMock()
        flow.id = session.flow_id
        service.prepare_message_context.return_value = SimpleNamespace(
            planner_context=SimpleNamespace(
                available_models=[
                    {"id": str(model.id), "name": "GPT-4", "provider": "openai"}
                ],
                available_kbs=[
                    {
                        "id": str(collection.id),
                        "name": "Docs",
                        "description": "Documentation",
                    }
                ],
                available_mcps=[],
                max_input_tokens=4096,
                max_output_tokens=2048,
                budget_policy=SimpleNamespace(),
            ),
            litellm_model="openai/gpt-4",
            litellm_kwargs={"api_key": "sk-test"},
            structured_output_decision=object(),
            flow=flow,
            assistant_snapshots={},
            attachment_files=[],
        )

        async def mock_events(*args, **kwargs):
            yield {"event": "done", "data": ""}

        service.send_message.return_value = mock_events()

        body = SendMessageRequest(message="Build it")
        await send_message(
            request=MagicMock(),
            session_id=session.id,
            body=body,
            container=container,
        )

        # The EventSourceResponse is returned — service.send_message is called
        # lazily. The router should still reuse one authorized space load, but
        # the remaining prefetch work should come from the service seam.
        assert space_service.get_space.await_count == 1
        service.prepare_message_context.assert_awaited_once()

    @pytest.mark.anyio
    async def test_forwards_full_provider_kwargs_from_service_context(self):
        from sse_starlette import EventSourceResponse

        container = _make_container()
        session = _make_session_domain(actor_user_id=container.user.return_value.id)
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        model = MagicMock()
        model.id = uuid4()
        model.name = "GPT-4"
        model.provider_type = "azure"
        model.max_output_tokens = 4096

        space_service = container.space_service.return_value
        space = space_service.get_space.return_value
        space.completion_models = [model]
        space.get_default_completion_model.return_value = model

        service.prepare_message_context.return_value = SimpleNamespace(
            planner_context=SimpleNamespace(
                available_models=[
                    {"id": str(model.id), "name": "GPT-4", "provider": "azure"}
                ],
                available_kbs=[],
                available_mcps=[],
                max_input_tokens=4096,
                max_output_tokens=4096,
                budget_policy=SimpleNamespace(),
            ),
            litellm_model="azure/gpt-4",
            litellm_kwargs={
                "api_key": "sk-test",
                "api_base": "https://azure.example.com",
                "api_version": "2024-02-15-preview",
                "api_type": "azure",
                "organization": "org-123",
                "deployment_name": "gpt4-prod",
            },
            structured_output_decision=object(),
            flow=None,
            assistant_snapshots=None,
            attachment_files=[],
        )

        captured: dict = {}

        async def mock_events(*args, **kwargs):
            captured.update(kwargs)
            yield {"event": "done", "data": ""}

        service.send_message.side_effect = mock_events

        body = SendMessageRequest(message="Build it")
        result = await send_message(
            request=MagicMock(),
            session_id=session.id,
            body=body,
            container=container,
        )

        assert isinstance(result, EventSourceResponse)
        async for _chunk in result.body_iterator:
            pass

        assert captured["litellm_kwargs"] == {
            "api_key": "sk-test",
            "api_base": "https://azure.example.com",
            "api_version": "2024-02-15-preview",
            "api_type": "azure",
            "organization": "org-123",
            "deployment_name": "gpt4-prod",
        }

    @pytest.mark.anyio
    async def test_keeps_ui_language_separate_from_question_answer(self):
        from sse_starlette import EventSourceResponse

        container = _make_container()
        _configure_space_with_planner_model(container)
        session = _make_session_domain(actor_user_id=container.user.return_value.id)
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        captured: dict[str, object] = {}

        async def mock_events(*args, **kwargs):
            captured.update(kwargs)
            yield {"event": "done", "data": ""}

        service.send_message.side_effect = mock_events

        result = await send_message(
            request=MagicMock(),
            session_id=session.id,
            body=SendMessageRequest(
                message="Bygg ett flöde",
                ui_language="sv",
            ),
            container=container,
        )

        assert isinstance(result, EventSourceResponse)
        async for _chunk in result.body_iterator:
            pass

        assert captured["question_answer"] is None
        assert captured["ui_language"] == "sv"

    @pytest.mark.anyio
    async def test_streams_typed_error_and_done_when_message_stream_raises(self):
        container = _make_container()
        _configure_space_with_planner_model(container)
        session = _make_session_domain(actor_user_id=container.user.return_value.id)
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        async def broken_events(*args, **kwargs):
            yield {"event": "status", "data": '{"status":"thinking"}'}
            raise RuntimeError("planner stream exploded")

        service.send_message.return_value = broken_events()

        request = _make_request()
        request.headers = {"x-request-id": "req-stream-1"}

        result = await send_message(
            request=request,
            session_id=session.id,
            body=SendMessageRequest(message="Bygg ett flöde"),
            container=container,
        )

        events = await _read_sse_events(result)
        assert [event["event"] for event in events] == ["status", "error", "done"]
        error_payload = events[1]["data"]
        assert error_payload["schema_version"] == 2
        assert error_payload["code"] == "planner_stream_failed"
        assert error_payload["category"] == "internal"
        assert error_payload["phase"] == "planner"
        assert error_payload["intric_error_code"] == int(
            ErrorCodes.INTERNAL_SERVER_ERROR
        )
        assert error_payload["request_id"] == "req-stream-1"
        assert error_payload["diagnostic_context"] == {
            "session_id": str(session.id),
            "request_id": "req-stream-1",
            "space_id": str(session.space_id),
            "error_code": "planner_stream_failed",
            "error_category": "internal",
            "error_phase": "planner",
        }

    @pytest.mark.anyio
    async def test_streams_bad_request_code_when_session_message_in_progress(self):
        container = _make_container()
        _configure_space_with_planner_model(container)
        session = _make_session_domain(actor_user_id=container.user.return_value.id)
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        async def rejected_events(*args, **kwargs):
            raise AIBuilderBadRequestException(
                "Another AI Builder message is already being processed for this session.",
                code=AIBuilderErrorCode.SESSION_MESSAGE_IN_PROGRESS,
            )
            yield  # pragma: no cover

        service.send_message.return_value = rejected_events()

        request = _make_request()
        request.headers = {"x-request-id": "req-stream-busy"}

        result = await send_message(
            request=request,
            session_id=session.id,
            body=SendMessageRequest(message="Bygg ett flöde"),
            container=container,
        )

        events = await _read_sse_events(result)
        assert [event["event"] for event in events] == ["error", "done"]
        error_payload = events[0]["data"]
        assert error_payload["schema_version"] == 2
        assert error_payload["code"] == "session_message_in_progress"
        assert error_payload["category"] == "conflict"
        assert error_payload["phase"] == "router"
        assert error_payload["intric_error_code"] == int(ErrorCodes.BAD_REQUEST)
        assert "already being processed" in error_payload["message"]
        assert error_payload["request_id"] == "req-stream-busy"
        assert error_payload["diagnostic_context"] == {
            "session_id": str(session.id),
            "request_id": "req-stream-busy",
            "space_id": str(session.space_id),
            "error_code": "session_message_in_progress",
            "error_category": "conflict",
            "error_phase": "router",
        }

    @pytest.mark.anyio
    async def test_streams_registry_phase_for_planner_budget_errors(self):
        container = _make_container()
        _configure_space_with_planner_model(container)
        session = _make_session_domain(actor_user_id=container.user.return_value.id)
        service = container.ai_builder_service.return_value
        service.get_session.return_value = session

        async def rejected_events(*args, **kwargs):
            raise AIBuilderBadRequestException(
                "No planner output budget is configured.",
                code=AIBuilderErrorCode.PLANNER_BUDGET_MISSING,
                context={"budget_owner": "space"},
            )
            yield  # pragma: no cover

        service.send_message.return_value = rejected_events()

        request = _make_request()
        request.headers = {"x-request-id": "req-stream-budget"}

        result = await send_message(
            request=request,
            session_id=session.id,
            body=SendMessageRequest(message="Bygg ett flöde"),
            container=container,
        )

        events = await _read_sse_events(result)
        assert [event["event"] for event in events] == ["error", "done"]
        error_payload = events[0]["data"]
        assert error_payload["schema_version"] == 2
        assert error_payload["code"] == "planner_budget_missing"
        assert error_payload["category"] == "bad_request"
        assert error_payload["phase"] == "planner"
        assert error_payload["intric_error_code"] == int(ErrorCodes.BAD_REQUEST)
        assert error_payload["details"] == {"budget_owner": "space"}
        assert error_payload["request_id"] == "req-stream-budget"
        assert error_payload["diagnostic_context"] == {
            "session_id": str(session.id),
            "request_id": "req-stream-budget",
            "space_id": str(session.space_id),
            "error_code": "planner_budget_missing",
            "error_category": "bad_request",
            "error_phase": "planner",
        }


class TestApprovePlanEndpoint:
    @pytest.mark.anyio
    async def test_approves_plan_and_returns_response(self):
        container = _make_container()
        plan = _make_plan_domain(status=PlanStatus.APPROVED)
        session = _make_session_domain(
            session_id=plan.session_id,
            actor_user_id=container.user.return_value.id,
        )
        service = container.ai_builder_service.return_value
        service.get_plan.return_value = plan
        service.get_session.return_value = session
        service.approve_plan.return_value = plan

        result = await approve_plan(
            request=MagicMock(),
            plan_id=plan.id,
            container=container,
        )

        assert result.plan_id == plan.id
        assert result.status == PlanStatus.APPROVED
        service.approve_plan.assert_called_once_with(plan_id=plan.id)

    @pytest.mark.anyio
    async def test_logs_audit_event(self):
        container = _make_container()
        user = container.user.return_value
        plan = _make_plan_domain(status=PlanStatus.APPROVED)
        session = _make_session_domain(
            session_id=plan.session_id,
            actor_user_id=user.id,
        )
        service = container.ai_builder_service.return_value
        service.get_plan.return_value = plan
        service.get_session.return_value = session
        service.approve_plan.return_value = plan

        await approve_plan(
            request=MagicMock(),
            plan_id=plan.id,
            container=container,
        )

        audit_service = container.audit_service.return_value
        audit_service.log_async.assert_awaited_once()
        call_kwargs = audit_service.log_async.await_args.kwargs
        assert call_kwargs["tenant_id"] == user.tenant_id
        assert call_kwargs["actor_id"] == user.id
        assert call_kwargs["action"] == ActionType.AI_BUILDER_PLAN_APPROVED
        assert call_kwargs["entity_type"] == EntityType.AI_BUILDER_SESSION
        assert call_kwargs["entity_id"] == plan.session_id
        metadata = call_kwargs["metadata"]
        assert metadata["actor"]["id"] == str(user.id)
        assert metadata["target"]["id"] == str(plan.id)
        assert metadata["extra"] == {"plan_id": str(plan.id)}

    @pytest.mark.anyio
    async def test_checks_flow_edit_permission(self):
        container = _make_container(can_edit_flows=False)
        plan = _make_plan_domain(status=PlanStatus.APPROVED)
        session = _make_session_domain(session_id=plan.session_id)
        service = container.ai_builder_service.return_value
        service.get_plan.return_value = plan
        service.get_session.return_value = session

        with pytest.raises(UnauthorizedException):
            await approve_plan(
                request=MagicMock(),
                plan_id=plan.id,
                container=container,
            )


class TestApplyPlanEndpoint:
    @pytest.mark.anyio
    async def test_applies_plan_and_returns_result(self):
        container = _make_container()
        flow_id = uuid4()
        plan = _make_plan_domain(status=PlanStatus.APPROVED)
        session = _make_session_domain()
        result = ApplyResultResponse(
            flow_id=flow_id,
            flow_name="New Flow",
            steps_created=2,
            steps_updated=0,
            steps_removed=0,
        )

        service = container.ai_builder_service.return_value
        service.repo = AsyncMock()
        service.repo.get_plan.return_value = plan
        service.get_session.return_value = session
        service.apply_plan.return_value = result

        body = ApplyPlanRequest(expected_revision=None)
        apply_result = await apply_plan(
            request=MagicMock(),
            plan_id=plan.id,
            body=body,
            container=container,
        )

        assert apply_result.flow_id == flow_id
        assert apply_result.steps_created == 2
        service.apply_plan.assert_called_once_with(
            plan_id=plan.id,
            expected_revision=None,
        )

    @pytest.mark.anyio
    async def test_logs_audit_event(self):
        container = _make_container()
        user = container.user.return_value
        flow_id = uuid4()
        plan = _make_plan_domain(status=PlanStatus.APPROVED)
        session = _make_session_domain()
        result = ApplyResultResponse(
            flow_id=flow_id,
            flow_name="Flow",
            steps_created=1,
            steps_updated=2,
            steps_removed=0,
        )

        service = container.ai_builder_service.return_value
        service.repo = AsyncMock()
        service.repo.get_plan.return_value = plan
        service.get_session.return_value = session
        service.apply_plan.return_value = result

        body = ApplyPlanRequest()
        await apply_plan(
            request=MagicMock(),
            plan_id=plan.id,
            body=body,
            container=container,
        )

        audit_service = container.audit_service.return_value
        audit_service.log_async.assert_awaited_once()
        call_kwargs = audit_service.log_async.await_args.kwargs
        assert call_kwargs["tenant_id"] == user.tenant_id
        assert call_kwargs["actor_id"] == user.id
        assert call_kwargs["action"] == ActionType.AI_BUILDER_FLOW_APPLIED
        assert call_kwargs["entity_type"] == EntityType.FLOW
        assert call_kwargs["entity_id"] == flow_id
        metadata = call_kwargs["metadata"]
        assert metadata["actor"]["id"] == str(user.id)
        assert metadata["target"]["id"] == str(flow_id)
        assert metadata["target"]["name"] == "Flow"
        assert metadata["extra"] == {
            "plan_id": str(plan.id),
            "steps_created": 1,
            "steps_updated": 2,
            "steps_removed": 0,
        }

    @pytest.mark.anyio
    async def test_checks_flow_edit_permission(self):
        container = _make_container(can_edit_flows=False)
        plan = _make_plan_domain()
        session = _make_session_domain()

        service = container.ai_builder_service.return_value
        service.repo = AsyncMock()
        service.repo.get_plan.return_value = plan
        service.get_session.return_value = session

        body = ApplyPlanRequest()
        with pytest.raises(UnauthorizedException):
            await apply_plan(
                request=MagicMock(),
                plan_id=plan.id,
                body=body,
                container=container,
            )

    @pytest.mark.anyio
    async def test_passes_expected_revision(self):
        container = _make_container()
        plan = _make_plan_domain()
        session = _make_session_domain()
        result = ApplyResultResponse(
            flow_id=uuid4(),
            flow_name="Flow",
            steps_created=0,
            steps_updated=1,
            steps_removed=0,
        )

        service = container.ai_builder_service.return_value
        service.repo = AsyncMock()
        service.repo.get_plan.return_value = plan
        service.get_session.return_value = session
        service.apply_plan.return_value = result

        body = ApplyPlanRequest(expected_revision=5)
        await apply_plan(
            request=MagicMock(),
            plan_id=plan.id,
            body=body,
            container=container,
        )

        service.apply_plan.assert_called_once_with(
            plan_id=plan.id,
            expected_revision=5,
        )

    @pytest.mark.anyio
    async def test_returns_standard_conflict_envelope_for_stale_revision(self):
        container = _make_container()
        plan = _make_plan_domain()
        session = _make_session_domain()
        service = container.ai_builder_service.return_value
        service.get_plan.return_value = plan
        service.get_session.return_value = session
        service.apply_plan.side_effect = AIBuilderBadRequestException(
            "Flow draft revision is stale.",
            code=AIBuilderErrorCode.STALE_REVISION,
        )
        client = _make_apply_plan_client(container)

        response = client.post(
            f"/ai-builder/plans/{plan.id}/apply",
            json={"expected_revision": 3},
        )

        payload = response.json()
        assert response.status_code == 409
        assert payload["schema_version"] == 2
        assert payload["message"] == "Flow draft revision is stale."
        assert payload["code"] == "stale_revision"
        assert payload["category"] == "conflict"
        assert payload["phase"] == "router"
        assert payload["intric_error_code"] == ErrorCodes.BAD_REQUEST

    @pytest.mark.anyio
    async def test_published_flow_apply_error_preserves_diagnostic_flow_and_details(
        self,
    ):
        container = _make_container()
        plan = _make_plan_domain()
        session = _make_session_domain()
        service = container.ai_builder_service.return_value
        service.get_plan.return_value = plan
        service.get_session.return_value = session
        service.apply_plan.side_effect = AIBuilderBadRequestException(
            "Flow is currently published. Unpublish the flow before applying changes.",
            code=AIBuilderErrorCode.FLOW_IS_PUBLISHED,
            context={"flow_id": "flow-1", "published_version": 3},
        )
        client = _make_apply_plan_client(container)

        response = client.post(
            f"/ai-builder/plans/{plan.id}/apply",
            json={"expected_revision": 3},
            headers={"x-request-id": "req-published"},
        )

        payload = response.json()
        assert response.status_code == 400
        assert payload["schema_version"] == 2
        assert payload["code"] == "flow_is_published"
        assert payload["diagnostic_context"]["flow_id"] == "flow-1"
        assert payload["diagnostic_context"]["request_id"] == "req-published"
        assert payload["details"] == {"published_version": 3}


class TestRevisePlanEndpoint:
    @pytest.mark.anyio
    async def test_revises_plan_and_returns_response(self):
        container = _make_container()
        plan = _make_plan_domain(status=PlanStatus.PROPOSED)
        revised = _make_plan_domain(
            session_id=plan.session_id,
            status=PlanStatus.PROPOSED,
        )
        session = _make_session_domain(
            session_id=plan.session_id,
            actor_user_id=container.user.return_value.id,
        )
        service = container.ai_builder_service.return_value
        service.get_plan.return_value = plan
        service.get_session.return_value = session
        service.revise_plan.return_value = revised

        result = await revise_plan(
            request=MagicMock(),
            plan_id=plan.id,
            body=RevisePlanRequest(type="keep_current_description"),
            container=container,
        )

        assert result.plan_id == revised.id
        service.revise_plan.assert_called_once_with(
            plan_id=plan.id,
            revision_type="keep_current_description",
        )

    @pytest.mark.anyio
    async def test_checks_flow_edit_permission(self):
        container = _make_container(can_edit_flows=False)
        plan = _make_plan_domain(status=PlanStatus.PROPOSED)
        session = _make_session_domain(session_id=plan.session_id)
        service = container.ai_builder_service.return_value
        service.get_plan.return_value = plan
        service.get_session.return_value = session

        with pytest.raises(UnauthorizedException):
            await revise_plan(
                request=MagicMock(),
                plan_id=plan.id,
                body=RevisePlanRequest(type="keep_current_description"),
                container=container,
            )
