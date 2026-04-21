"""Tests for AI Builder router endpoints."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.files.file_models import FilePublic
from intric.flows.ai_builder.ai_builder_models import (
    ApplyPlanRequest,
    ApplyResultResponse,
    BuilderPlan,
    BuilderSession,
    ConversationMessage,
    CreateSessionRequest,
    PlanResponse,
    PlanStatus,
    RevisePlanRequest,
    SendMessageRequest,
    SessionListItemResponse,
    SessionListResponse,
    SessionModelsResponse,
    SessionPlansResponse,
    SessionStatus,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_router import (
    _get_planner_model,
    _get_space_kbs,
    _get_space_models,
    _require_flow_edit_permission,
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
from intric.main.exceptions import (
    BadRequestException,
    ErrorCodes,
    NotFoundException,
    UnauthorizedException,
)
from intric.roles.permissions import Permission

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
            max_input_tokens=4096,
            max_output_tokens=2048,
            budget_policy=SimpleNamespace(),
        ),
        litellm_model="openai/gpt-4",
        litellm_kwargs={"api_key": "sk-test"},
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


def _make_request(*, scoped_space_id=None) -> MagicMock:
    request = MagicMock()
    if scoped_space_id is None:
        request.state = SimpleNamespace()
    else:
        request.state = SimpleNamespace(
            scope_enforcement_enabled=True,
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
    from intric.flows.ai_builder.ai_builder_models import (
        AssistantSpec,
        FlowDraftSpecCore,
        InputSource,
        PlannerPlanEnvelope,
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


class TestRequireFlowEditPermission:
    @pytest.mark.anyio
    async def test_allows_when_can_edit(self):
        container = _make_container(can_edit_flows=True)
        # Should not raise
        await _require_flow_edit_permission(container, uuid4())

    @pytest.mark.anyio
    async def test_raises_when_cannot_edit(self):
        container = _make_container(can_edit_flows=False)
        with pytest.raises(UnauthorizedException, match="permission"):
            await _require_flow_edit_permission(container, uuid4())


class TestGetPlannerModel:
    @pytest.mark.anyio
    async def test_returns_default_model_when_available(self):
        container = _make_container()
        default_model = MagicMock()
        space_service = container.space_service.return_value
        space = space_service.get_space.return_value
        space.get_default_completion_model.return_value = default_model

        result = await _get_planner_model(container, uuid4())
        assert result is default_model

    @pytest.mark.anyio
    async def test_returns_first_model_when_no_default(self):
        container = _make_container()
        model = MagicMock()
        space_service = container.space_service.return_value
        space = space_service.get_space.return_value
        space.get_default_completion_model.return_value = None
        space.completion_models = [model]

        result = await _get_planner_model(container, uuid4())
        assert result is model

    @pytest.mark.anyio
    async def test_raises_when_no_space_model_is_available(self):
        container = _make_container()
        space_service = container.space_service.return_value
        space = space_service.get_space.return_value
        space.get_default_completion_model.return_value = None
        space.completion_models = []

        model_service = container.completion_model_crud_service.return_value

        with pytest.raises(BadRequestException, match="No AI builder planner model"):
            await _get_planner_model(container, uuid4())

        model_service.get_default_completion_model.assert_not_called()


class TestGetSpaceModels:
    @pytest.mark.anyio
    async def test_returns_model_info(self):
        container = _make_container()
        model = MagicMock()
        model.id = uuid4()
        model.name = "GPT-4"
        model.provider_type = "openai"
        space_service = container.space_service.return_value
        space_service.get_space.return_value.completion_models = [model]

        result = await _get_space_models(container, uuid4())
        assert len(result) == 1
        assert result[0]["name"] == "GPT-4"
        assert result[0]["provider"] == "openai"

    @pytest.mark.anyio
    async def test_returns_empty_for_no_models(self):
        container = _make_container()
        result = await _get_space_models(container, uuid4())
        assert result == []


class TestGetSpaceKBs:
    @pytest.mark.anyio
    async def test_returns_kb_info(self):
        container = _make_container()
        collection = MagicMock()
        collection.id = uuid4()
        collection.name = "Docs"
        collection.description = "Documentation"
        space_service = container.space_service.return_value
        space_service.get_space.return_value.collections = [collection]

        result = await _get_space_kbs(container, uuid4())
        assert len(result) == 1
        assert result[0]["name"] == "Docs"
        assert result[0]["description"] == "Documentation"


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
        _configure_space_with_planner_model(container)
        session = _make_session_domain()
        service = container.ai_builder_service.return_value
        service.create_session.return_value = session

        body = CreateSessionRequest(
            target_kind=TargetKind.CREATE,
            space_id=uuid4(),
        )
        await create_session(
            request=MagicMock(),
            body=body,
            container=container,
        )

        audit_service = container.audit_service.return_value
        audit_service.log_async.assert_called_once()
        call_kwargs = audit_service.log_async.call_args.kwargs
        assert call_kwargs["action"] == ActionType.AI_BUILDER_SESSION_CREATED
        assert call_kwargs["entity_type"] == EntityType.AI_BUILDER_SESSION
        assert call_kwargs["entity_id"] == session.id

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
        session = _make_session_domain(actor_user_id=container.user.return_value.id)
        cancelled = _make_session_domain(
            session_id=session.id,
            space_id=session.space_id,
            actor_user_id=container.user.return_value.id,
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
                max_input_tokens=4096,
                max_output_tokens=2048,
                budget_policy=SimpleNamespace(),
            ),
            litellm_model="openai/gpt-4",
            litellm_kwargs={"api_key": "sk-test"},
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
        assert error_payload["code"] == "planner_stream_failed"
        assert error_payload["phase"] == "router"
        assert error_payload["intric_error_code"] == int(
            ErrorCodes.INTERNAL_SERVER_ERROR
        )
        assert error_payload["request_id"] == "req-stream-1"


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
        plan = _make_plan_domain(status=PlanStatus.APPROVED)
        session = _make_session_domain(
            session_id=plan.session_id,
            actor_user_id=container.user.return_value.id,
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
        audit_service.log_async.assert_called_once()
        call_kwargs = audit_service.log_async.call_args.kwargs
        assert call_kwargs["action"] == ActionType.AI_BUILDER_PLAN_APPROVED
        assert call_kwargs["entity_type"] == EntityType.AI_BUILDER_SESSION
        assert call_kwargs["entity_id"] == plan.session_id

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
        audit_service.log_async.assert_called_once()
        call_kwargs = audit_service.log_async.call_args.kwargs
        assert call_kwargs["action"] == ActionType.AI_BUILDER_FLOW_APPLIED
        assert call_kwargs["entity_type"] == EntityType.FLOW
        assert call_kwargs["entity_id"] == flow_id

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
        service.apply_plan.side_effect = BadRequestException(
            "Flow draft revision is stale.",
            code="stale_revision",
        )

        response = await apply_plan(
            request=MagicMock(),
            plan_id=plan.id,
            body=ApplyPlanRequest(expected_revision=3),
            container=container,
        )

        payload = __import__("json").loads(response.body)
        assert response.status_code == 409
        assert payload["message"] == "Flow draft revision is stale."
        assert payload["code"] == "stale_revision"
        assert payload["intric_error_code"] == ErrorCodes.BAD_REQUEST


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
