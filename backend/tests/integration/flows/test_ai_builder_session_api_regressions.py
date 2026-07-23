from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    BadRequestError,
    RateLimitError,
    Timeout,
)
from pydantic import ValidationError
from sqlalchemy import insert, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette import ServerSentEvent
from starlette.requests import Request
from starlette.types import Message, Scope

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.completion_models.infrastructure.completion_service import (
    ResolvedCompletionModelRoute,
)
from eneo.database.database import (
    get_session,
    get_session_with_transaction,
    sessionmanager,
)
from eneo.database.tables.ai_models_table import TranscriptionModels
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    BuilderPlans,
    BuilderSessionFiles,
    BuilderSessions,
    Flows,
)
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.tables.spaces_table import (
    Spaces,
    SpacesCompletionModels,
    SpacesTranscriptionModels,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.ai_builder import ai_builder_error_contract as error_contract_module
from eneo.flows.ai_builder.ai_builder_api_models import SendMessageRequest
from eneo.flows.ai_builder.ai_builder_conversation_compaction import (
    MAX_SESSION_CONVERSATION_BYTES,
    conversation_serialized_size_bytes,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderTurnState,
    ConversationMessage,
    FlowBuilderEditApproval,
    FlowBuilderProposal,
    FlowBuilderProposalContent,
    PlanStatus,
    SessionStatus,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_edit_preview_models import (
    FlowEditDiff,
    StepChange,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
    AIBuilderPublicError,
    build_ai_builder_error,
)
from eneo.flows.ai_builder.ai_builder_event_models import RequirementsSummaryPayload
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
)
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.ai_builder.ai_builder_router import send_message
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
    SessionTurnAcceptance,
)
from eneo.flows.ai_builder.ai_builder_slot_classifier import (
    ClassifiedEvidence,
    ClassifiedSlot,
    SlotClassificationInput,
    SlotClassificationResult,
)
from eneo.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME
from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from eneo.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
    ArchitectureCommit,
    PlanningState,
    ResolvedSlot,
    StepTriple,
)
from eneo.flows.application.flow_authoring_command import FlowAuthoringCommandService
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.main.container.container import Container
from eneo.main.exceptions import BadRequestException, ErrorCodes, NotFoundException
from eneo.main.models import GeneralError, ModelId
from eneo.prompts.api.prompt_models import PromptCreate
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserUpdate


def _route(
    *,
    model: str = "openai/gpt-4o-mini",
    kwargs: dict[str, object] | None = None,
) -> ResolvedCompletionModelRoute:
    return ResolvedCompletionModelRoute(
        litellm_model=model,
        litellm_kwargs=kwargs or {},
        supported_model_kwargs=SupportedModelKwargs(
            temperature=ModelKwargCapability(supported=True)
        ),
    )


@pytest.fixture
async def bearer_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"ai-builder-regression-{uuid4().hex[:8]}",
                permissions=[
                    Permission.ASSISTANTS,
                    Permission.SHARED_SPACES,
                    Permission.FLOWS_MANAGE,
                    Permission.FLOWS_AI_BUILDER,
                ],
                tenant_id=admin_user.tenant_id,
            )
        )
        user = await container.user_repo().update(
            UserUpdate(
                id=admin_user.id,
                roles=[ModelId(id=role.id)],
            )
        )
        assert user is not None
        auth_service = container.auth_service()
        token = auth_service.create_access_token_for_user(user)
    return token


def _make_llm_response(
    *,
    content: str | None = None,
    tool_calls: list[MagicMock] | None = None,
) -> MagicMock:
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    return response


def _make_tool_call(
    *,
    tool_call_id: str = "call_123",
    name: str,
    arguments: dict[str, object],
) -> MagicMock:
    tool_call = MagicMock()
    tool_call.id = tool_call_id
    tool_call.function.name = name
    tool_call.function.arguments = json.dumps(arguments)
    return tool_call


def _parse_sse_payload(body: str) -> list[dict[str, object]]:
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
        if line == "":
            if current_event is not None:
                raw_data = "\n".join(data_lines)
                parsed: object
                if raw_data:
                    parsed = json.loads(raw_data)
                else:
                    parsed = {}
                events.append({"event": current_event, "data": parsed})
            current_event = None
            data_lines = []

    if current_event is not None:
        raw_data = "\n".join(data_lines)
        parsed = json.loads(raw_data) if raw_data else {}
        events.append({"event": current_event, "data": parsed})

    return events


def _make_session_send_turn(
    *,
    session_id: UUID,
    tenant_id: UUID,
    base_planning_state_version: int = 0,
) -> SessionSendTurn:
    return SessionSendTurn(
        session_id=session_id,
        tenant_id=tenant_id,
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=base_planning_state_version,
    )


async def _claim_session_send_turn(
    *,
    repo: AIBuilderRepository,
    session_id: UUID,
    tenant_id: UUID,
    lock_expires_at: datetime | None = None,
    client_turn_id: UUID | None = None,
    lease: SessionSendLease | None = None,
) -> SessionSendTurn:
    resolved_lease = lease or SessionSendLease(
        request_id=uuid4(),
        lock_token=uuid4(),
    )
    resolved_turn_id = client_turn_id or uuid4()
    message = ConversationMessage(role="user", content="Accepted turn")
    preflight = await repo.preflight_session_turn(
        session_id=session_id,
        tenant_id=tenant_id,
        client_turn_id=resolved_turn_id,
        request_fingerprint="a" * 64,
        acknowledge_duplicate_provider_spend=False,
    )
    requested_expiry = lock_expires_at or (
        datetime.now(timezone.utc) + timedelta(seconds=30)
    )
    lock_lease_seconds = max(
        -1,
        int((requested_expiry - datetime.now(timezone.utc)).total_seconds()),
    )
    claim = await repo.accept_session_turn(
        session_id=session_id,
        tenant_id=tenant_id,
        lease=resolved_lease,
        lock_lease_seconds=lock_lease_seconds,
        acceptance=SessionTurnAcceptance(
            client_turn_id=resolved_turn_id,
            request_fingerprint="a" * 64,
            request={
                "client_turn_id": str(resolved_turn_id),
                "message": message.content,
            },
            user_message=message,
            file_ids=(),
        ),
        preparation_baseline=preflight.baseline,
    )
    return SessionSendTurn(
        session_id=session_id,
        tenant_id=tenant_id,
        lease=resolved_lease,
        base_planning_state_version=claim.base_planning_state_version,
    )


async def _load_session_send_lock(
    repo: AIBuilderRepository,
    *,
    session_id: UUID,
    tenant_id: UUID,
) -> tuple[UUID | None, UUID | None, datetime | None, datetime | None]:
    row = (
        await repo.session.execute(
            select(
                BuilderSessions.active_request_id,
                BuilderSessions.lock_token,
                BuilderSessions.locked_at,
                BuilderSessions.lock_expires_at,
            ).where(
                BuilderSessions.id == session_id,
                BuilderSessions.tenant_id == tenant_id,
            )
        )
    ).one()
    return (
        cast(UUID | None, row[0]),
        cast(UUID | None, row[1]),
        cast(datetime | None, row[2]),
        cast(datetime | None, row[3]),
    )


async def _create_ai_builder_session(
    *,
    client,
    bearer_token: str,
    space_id: str,
    target_kind: str = "create",
    flow_id: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "target_kind": target_kind,
        "space_id": space_id,
    }
    if flow_id is not None:
        payload["flow_id"] = flow_id

    response = await client.post(
        "/api/v1/flows/ai-builder/sessions",
        json=payload,
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


async def _create_space_via_api(*, client, bearer_token: str, name: str) -> str:
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": name},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_space_with_planner_model(
    *,
    client,
    bearer_token: str,
    db_container,
    completion_model_factory,
    space_name: str,
) -> str:
    space_id = await _create_space_via_api(
        client=client,
        bearer_token=bearer_token,
        name=space_name,
    )

    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(
            session,
            "gpt-4o-mini",
            litellm_model_name="openai/gpt-4o-mini",
        )
        session.add(
            SpacesCompletionModels(
                space_id=UUID(space_id),
                completion_model_id=model.id,
            )
        )
        await session.flush()

    return space_id


async def _create_default_transcription_model(
    *,
    db_container,
    space_id: str,
    tenant_id: UUID,
) -> None:
    async with db_container() as container:
        session = container.session()
        provider = ModelProviders(
            tenant_id=tenant_id,
            name="OpenAI Transcription",
            provider_type="openai",
            credentials={"api_key": "test-key"},
            config={},
            is_active=True,
        )
        session.add(provider)
        await session.flush()

        model = TranscriptionModels(
            tenant_id=tenant_id,
            provider_id=provider.id,
            name="whisper-1",
            model_name="whisper-1",
            family="openai",
            hosting="usa",
            stability="stable",
            org="OpenAI",
            base_url="https://api.openai.com/v1",
            is_enabled=True,
            is_default=True,
        )
        session.add(model)
        await session.flush()

        session.add(
            SpacesTranscriptionModels(
                space_id=UUID(space_id),
                transcription_model_id=model.id,
            )
        )
        await session.flush()


async def _send_builder_message(
    *,
    client,
    bearer_token: str,
    session_id: str,
    message: str,
    client_turn_id: UUID | None = None,
    file_ids: list[str] | None = None,
    question_answer: dict[str, object] | None = None,
    acknowledge_duplicate_provider_spend: bool = False,
) -> list[dict[str, object]]:
    payload: dict[str, object] = {
        "client_turn_id": str(client_turn_id or uuid4()),
        "message": message,
        "ui_language": "sv",
    }
    if acknowledge_duplicate_provider_spend:
        payload["acknowledge_duplicate_provider_spend"] = True
    if file_ids is not None:
        payload["file_ids"] = file_ids
    if question_answer is not None:
        payload["question_answer"] = _request_question_answer(question_answer)

    response = await client.post(
        f"/api/v1/flows/ai-builder/sessions/{session_id}/messages",
        json=payload,
        headers={
            "Authorization": f"Bearer {bearer_token}",
            "accept": "text/event-stream",
        },
    )
    assert response.status_code == 200, response.text
    return _parse_sse_payload(response.text)


def _request_question_answer(
    question_answer: dict[str, object],
) -> dict[str, object]:
    payload = dict(question_answer)
    if "kind" in payload:
        return payload
    # Happy-path API helpers use the current discriminator; invalid-payload tests should post directly.
    if payload.get("requirements_confirmed") is True:
        payload["kind"] = "requirements_confirmation"
    else:
        payload["kind"] = "structured_question_answer"
    return payload


async def _upload_reference_file(
    *,
    client,
    bearer_token: str,
    filename: str = "reference.txt",
    content: bytes = b"hello world",
    mimetype: str = "text/plain",
) -> str:
    response = await client.post(
        "/api/v1/files/",
        files={"upload_file": (filename, content, mimetype)},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


async def _create_extra_tenant(*, db_container, name: str) -> UUID:
    async with db_container() as container:
        session = container.session()
        tenant = Tenants(
            name=name,
            quota_limit=1_000_000,
            state="active",
        )
        session.add(tenant)
        await session.flush()
        return tenant.id


async def _create_space_and_flow_for_tenant(
    *,
    db_container,
    tenant_id: UUID,
    owner_user_id: UUID | None,
    name_prefix: str,
) -> tuple[UUID, UUID]:
    async with db_container() as container:
        session = container.session()
        space = Spaces(
            tenant_id=tenant_id,
            user_id=None,
            name=f"{name_prefix}-space",
        )
        session.add(space)
        await session.flush()
        flow = Flows(
            tenant_id=tenant_id,
            space_id=space.id,
            name=f"{name_prefix}-flow",
            created_by_user_id=owner_user_id,
            owner_user_id=owner_user_id,
        )
        session.add(flow)
        await session.flush()
        return space.id, flow.id


def _make_builder_plan_spec(*, existing_step_ref: str | None) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Testplan",
        flow_description="Testplan för apply",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                existing_step_ref=existing_step_ref,
                name="Steg A",
                assistant_spec=AssistantSpec(instructions="Gör jobbet."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            )
        ],
    )


def _compiled_builder_plan(spec: FlowDraftSpecCore) -> CompiledProposal:
    return CompiledProposal(
        content=FlowBuilderProposalContent(spec=spec),
        validation=SpecValidationResult(),
    )


def _make_builder_edit_approval(
    *,
    spec: FlowDraftSpecCore,
    base_flow_revision: int,
) -> FlowBuilderEditApproval:
    step = spec.steps[0]
    return FlowBuilderEditApproval(
        base_flow_revision=base_flow_revision,
        diff=FlowEditDiff(
            step_changes=[
                StepChange(
                    kind="unchanged",
                    step_name=step.name,
                    step_ref=step.existing_step_ref,
                )
            ]
        ),
    )


async def _create_proposed_ai_builder_plan(
    *,
    client,
    bearer_token: str,
    db_container,
    space_id: str,
) -> tuple[UUID, UUID, UUID, SessionSendLease]:
    from eneo.flows.ai_builder.ai_builder_plan_store import (
        store_plan_and_update_conversation,
    )

    session_id = UUID(
        await _create_ai_builder_session(
            client=client,
            bearer_token=bearer_token,
            space_id=space_id,
        )
    )

    async with db_container() as container:
        tenant_id = (
            await container.session().execute(
                select(BuilderSessions.tenant_id).where(
                    BuilderSessions.id == session_id
                )
            )
        ).scalar_one()

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session_id,
            tenant_id=tenant_id,
        )
        stored_plan = await store_plan_and_update_conversation(
            repo=repo,
            turn=turn,
            conversation=[],
            new_messages_start=0,
            assistant_content="plan ready",
            tool_call_id=f"call-revise-{uuid4()}",
            tool_name=PROPOSE_FLOW_TOOL_NAME,
            arguments={},
            compiled=_compiled_builder_plan(
                _make_builder_plan_spec(existing_step_ref=None)
            ),
            flow=None,
        )
        await repo.release_session_send(
            session_id=session_id,
            tenant_id=tenant_id,
            lease=turn.lease,
        )
        return session_id, tenant_id, stored_plan.plan.id, turn.lease


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_session_is_committed_at_final_response_body_boundary(
    app,
    client,
    bearer_token: str,
    completion_model_factory,
    db_container,
) -> None:
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder response boundary durability",
    )
    request_body = json.dumps({"target_kind": "create", "space_id": space_id}).encode()
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/flows/ai-builder/sessions",
        "raw_path": b"/api/v1/flows/ai-builder/sessions",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"test.local"),
            (b"content-type", b"application/json"),
            (b"authorization", f"Bearer {bearer_token}".encode()),
        ],
        "client": ("127.0.0.1", 123),
        "server": ("test.local", 80),
    }
    final_body_received = asyncio.Event()
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    request_received = False
    response_status: int | None = None
    response_body = bytearray()

    def is_create_session_request(request: Request) -> bool:
        return (
            request.method == "POST"
            and request.url.path == "/api/v1/flows/ai-builder/sessions"
        )

    async def gated_transaction_session(
        request: Request,
    ) -> AsyncGenerator[AsyncSession, None]:
        async for session in get_session_with_transaction():
            try:
                yield session
            finally:
                if is_create_session_request(request):
                    cleanup_started.set()
                    await release_cleanup.wait()

    async def gated_session(
        request: Request,
    ) -> AsyncGenerator[AsyncSession, None]:
        async for session in get_session():
            try:
                yield session
            finally:
                if is_create_session_request(request):
                    cleanup_started.set()
                    await release_cleanup.wait()

    previous_transaction_override = app.dependency_overrides.get(
        get_session_with_transaction
    )
    previous_session_override = app.dependency_overrides.get(get_session)
    app.dependency_overrides[get_session_with_transaction] = gated_transaction_session
    app.dependency_overrides[get_session] = gated_session

    async def receive() -> Message:
        nonlocal request_received
        if not request_received:
            request_received = True
            return {
                "type": "http.request",
                "body": request_body,
                "more_body": False,
            }
        await release_cleanup.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        nonlocal response_status
        if message["type"] == "http.response.start":
            response_status = cast(int, message["status"])
            return
        if message["type"] != "http.response.body":
            return
        response_body.extend(cast(bytes, message.get("body", b"")))
        if not message.get("more_body", False):
            final_body_received.set()

    post_task = asyncio.create_task(app(scope, receive, send))

    async def wait_for_response_boundary() -> None:
        await final_body_received.wait()
        await cleanup_started.wait()

    response_boundary_wait = asyncio.create_task(wait_for_response_boundary())
    try:
        completed, _ = await asyncio.wait(
            {post_task, response_boundary_wait},
            return_when=asyncio.FIRST_COMPLETED,
        )
        assert response_boundary_wait in completed
        assert not post_task.done()
        assert response_status == 201

        response_payload = cast(dict[str, object], json.loads(response_body))
        session_id = UUID(cast(str, response_payload["session_id"]))
        headers = {"Authorization": f"Bearer {bearer_token}"}
        session_response, models_response = await asyncio.gather(
            client.get(
                f"/api/v1/flows/ai-builder/sessions/{session_id}",
                headers=headers,
            ),
            client.get(
                f"/api/v1/flows/ai-builder/sessions/{session_id}/models",
                headers=headers,
            ),
        )

        assert (
            session_response.status_code,
            models_response.status_code,
        ) == (200, 200)
        assert session_response.json()["session_id"] == str(session_id)

        async with db_container() as container:
            audit_count = await container.session().scalar(
                select(sa.func.count(AuditLogTable.id)).where(
                    AuditLogTable.tenant_id == container.user().tenant_id,
                    AuditLogTable.action == ActionType.AI_BUILDER_SESSION_CREATED.value,
                    AuditLogTable.entity_type == EntityType.AI_BUILDER_SESSION.value,
                    AuditLogTable.entity_id == session_id,
                )
            )

        assert audit_count == 1
        assert not post_task.done()
    finally:
        release_cleanup.set()
        try:
            await post_task
        finally:
            if not response_boundary_wait.done():
                response_boundary_wait.cancel()
            try:
                await response_boundary_wait
            except asyncio.CancelledError:
                pass
            if previous_transaction_override is None:
                app.dependency_overrides.pop(get_session_with_transaction, None)
            else:
                app.dependency_overrides[get_session_with_transaction] = (
                    previous_transaction_override
                )
            if previous_session_override is None:
                app.dependency_overrides.pop(get_session, None)
            else:
                app.dependency_overrides[get_session] = previous_session_override


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_session_is_immediately_readable_and_commits_one_audit_log(
    client,
    bearer_token: str,
    completion_model_factory,
    db_container,
) -> None:
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder transactional audit",
    )

    session_id = UUID(
        await _create_ai_builder_session(
            client=client,
            bearer_token=bearer_token,
            space_id=space_id,
        )
    )
    headers = {"Authorization": f"Bearer {bearer_token}"}
    session_response = await client.get(
        f"/api/v1/flows/ai-builder/sessions/{session_id}",
        headers=headers,
    )
    models_response = await client.get(
        f"/api/v1/flows/ai-builder/sessions/{session_id}/models",
        headers=headers,
    )

    assert session_response.status_code == 200
    assert session_response.json()["session_id"] == str(session_id)
    assert models_response.status_code == 200

    async with db_container() as container:
        audit_result = await container.session().execute(
            select(AuditLogTable.description).where(
                AuditLogTable.tenant_id == container.user().tenant_id,
                AuditLogTable.action == ActionType.AI_BUILDER_SESSION_CREATED.value,
                AuditLogTable.entity_type == EntityType.AI_BUILDER_SESSION.value,
                AuditLogTable.entity_id == session_id,
            )
        )
        audit_descriptions = audit_result.scalars().all()

    assert audit_descriptions == ["Started AI builder session (create)"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_session_rolls_back_when_canonical_audit_insert_fails(
    client,
    bearer_token: str,
    completion_model_factory,
    db_container,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder audit rollback",
    )

    async def fail_audit_insert(
        _repository: AuditLogRepositoryImpl,
        _audit_log: object,
    ) -> object:
        raise RuntimeError("forced canonical audit insert failure")

    monkeypatch.setattr(AuditLogRepositoryImpl, "create", fail_audit_insert)

    with pytest.raises(RuntimeError, match="forced canonical audit insert failure"):
        await client.post(
            "/api/v1/flows/ai-builder/sessions",
            json={"target_kind": "create", "space_id": space_id},
            headers={"Authorization": f"Bearer {bearer_token}"},
        )

    async with db_container() as container:
        session_count = await container.session().scalar(
            select(sa.func.count(BuilderSessions.id)).where(
                BuilderSessions.tenant_id == container.user().tenant_id,
                BuilderSessions.space_id == UUID(space_id),
            )
        )
        audit_count = await container.session().scalar(
            select(sa.func.count(AuditLogTable.id)).where(
                AuditLogTable.tenant_id == container.user().tenant_id,
                AuditLogTable.action == ActionType.AI_BUILDER_SESSION_CREATED.value,
            )
        )

    assert session_count == 0
    assert audit_count == 0


@pytest.mark.parametrize(
    ("path", "payload", "misspelled_field"),
    [
        (
            "/api/v1/flows/ai-builder/sessions",
            {
                "target_kind": "create",
                "space_id": "00000000-0000-4000-8000-000000000001",
                "force_neew": "invalid-field-value-must-not-be-echoed",
            },
            "force_neew",
        ),
        (
            "/api/v1/flows/ai-builder/sessions/00000000-0000-4000-8000-000000000002/messages",
            {
                "client_turn_id": "00000000-0000-4000-8000-000000000003",
                "message": "Build a flow.",
                "model_iid": "invalid-field-value-must-not-be-echoed",
            },
            "model_iid",
        ),
        (
            "/api/v1/flows/ai-builder/plans/00000000-0000-4000-8000-000000000004/apply",
            {"expected_revison": "invalid-field-value-must-not-be-echoed"},
            "expected_revison",
        ),
        (
            "/api/v1/flows/ai-builder/plans/00000000-0000-4000-8000-000000000005/revise",
            {
                "type": "keep_current_description",
                "revision_typo": "invalid-field-value-must-not-be-echoed",
            },
            "revision_typo",
        ),
    ],
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_launch_requests_reject_misspelled_fields(
    client,
    bearer_token: str,
    path: str,
    payload: dict[str, object],
    misspelled_field: str,
) -> None:
    request_id = f"ai-builder-strict-{misspelled_field}"

    response = await client.post(
        path,
        json=payload,
        headers={
            "Authorization": f"Bearer {bearer_token}",
            "X-Request-ID": request_id,
        },
    )

    assert response.status_code == 422, response.text
    error = GeneralError.model_validate(response.json())
    assert error.message == "Request validation failed."
    assert error.eneo_error_code == ErrorCodes.VALIDATION_ERROR
    assert error.code == "request_validation_error"
    assert error.request_id == request_id
    assert isinstance(error.details, dict)
    errors = error.details.get("errors")
    assert isinstance(errors, list)
    assert {
        "location": ["body", misspelled_field],
        "message": "Extra inputs are not permitted",
        "type": "extra_forbidden",
    } in errors
    assert "invalid-field-value-must-not-be-echoed" not in response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_apply_plan_request_transaction_rolls_back_to_approved_plan_on_failure(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Apply Transaction Rollback",
    )
    session_id, tenant_id, plan_id, _ = await _create_proposed_ai_builder_plan(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        space_id=space_id,
    )

    approve_response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{plan_id}/approve",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert approve_response.status_code == 200, approve_response.text

    async def fail_materialization(self, **_kwargs: object) -> object:
        raise BadRequestException("forced apply failure", code="forced_apply_failure")

    monkeypatch.setattr(
        FlowAuthoringCommandService,
        "apply_prepared",
        fail_materialization,
    )

    apply_response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{plan_id}/apply",
        json={},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )

    assert apply_response.status_code == 400, apply_response.text
    async with db_container() as container:
        persisted_session_status = (
            await container.session().execute(
                select(BuilderSessions.status).where(
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                )
            )
        ).scalar_one()
        persisted_plan_status = (
            await container.session().execute(
                select(BuilderPlans.status).where(
                    BuilderPlans.id == plan_id,
                    BuilderPlans.tenant_id == tenant_id,
                )
            )
        ).scalar_one()

    assert persisted_session_status == SessionStatus.AWAITING_APPROVAL.value
    assert persisted_plan_status == PlanStatus.APPROVED.value


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mark_plan_applied_rolls_back_plan_status_when_session_update_fails(
    db_container,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with db_container() as container:
        user = container.user()
        space = Spaces(
            tenant_id=user.tenant_id,
            user_id=user.id,
            name=f"ai-builder-apply-savepoint-{uuid4().hex}",
        )
        container.session().add(space)
        await container.session().flush()

        repo = AIBuilderRepository(container.session())
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=space.id,
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
        )
        plan = await repo.create_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            proposal=FlowBuilderProposal(
                content=FlowBuilderProposalContent(
                    spec=_make_builder_plan_spec(existing_step_ref=None)
                )
            ),
        )
        await repo.update_plan_status(
            plan_id=plan.id,
            tenant_id=user.tenant_id,
            status=PlanStatus.APPROVED,
        )
        await repo.update_session_status_without_send_lease(
            session_id=session.id,
            tenant_id=user.tenant_id,
            status=SessionStatus.AWAITING_APPROVAL,
        )
        await repo.update_session_latest_plan_without_send_lease(
            session_id=session.id,
            tenant_id=user.tenant_id,
            plan_id=plan.id,
        )

        async def fail_session_status_update(
            *,
            session_id: UUID,
            tenant_id: UUID,
            status: SessionStatus,
        ) -> None:
            raise RuntimeError("forced session status failure")

        monkeypatch.setattr(
            repo,
            "update_session_status_without_send_lease",
            fail_session_status_update,
        )

        with pytest.raises(RuntimeError, match="forced session status failure"):
            await repo.mark_plan_applied(
                plan_id=plan.id,
                session_id=session.id,
                tenant_id=user.tenant_id,
                flow_id=uuid4(),
            )

        persisted_plan_status = (
            await container.session().execute(
                select(BuilderPlans.status).where(
                    BuilderPlans.id == plan.id,
                    BuilderPlans.tenant_id == user.tenant_id,
                )
            )
        ).scalar_one()
        persisted_session_status, persisted_flow_id = (
            await container.session().execute(
                select(BuilderSessions.status, BuilderSessions.flow_id).where(
                    BuilderSessions.id == session.id,
                    BuilderSessions.tenant_id == user.tenant_id,
                )
            )
        ).one()

    assert persisted_plan_status == PlanStatus.APPROVED.value
    assert persisted_session_status == SessionStatus.AWAITING_APPROVAL.value
    assert persisted_flow_id is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mark_plan_applied_rejects_active_send_and_rolls_back(
    db_container,
) -> None:
    async with db_container() as container:
        user = container.user()
        space = Spaces(
            tenant_id=user.tenant_id,
            user_id=user.id,
            name=f"ai-builder-apply-active-send-{uuid4().hex}",
        )
        container.session().add(space)
        await container.session().flush()

        repo = AIBuilderRepository(container.session())
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=space.id,
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
        )
        plan = await repo.create_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            proposal=FlowBuilderProposal(
                content=FlowBuilderProposalContent(
                    spec=_make_builder_plan_spec(existing_step_ref=None)
                )
            ),
        )
        await repo.update_plan_status(
            plan_id=plan.id,
            tenant_id=user.tenant_id,
            status=PlanStatus.APPROVED,
        )
        await repo.update_session_status_without_send_lease(
            session_id=session.id,
            tenant_id=user.tenant_id,
            status=SessionStatus.AWAITING_APPROVAL,
        )
        await repo.update_session_latest_plan_without_send_lease(
            session_id=session.id,
            tenant_id=user.tenant_id,
            plan_id=plan.id,
        )
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
        )

        with pytest.raises(BadRequestException) as exc:
            await repo.mark_plan_applied(
                plan_id=plan.id,
                session_id=session.id,
                tenant_id=user.tenant_id,
                flow_id=None,
            )

        persisted_plan_status = (
            await container.session().execute(
                select(BuilderPlans.status).where(
                    BuilderPlans.id == plan.id,
                    BuilderPlans.tenant_id == user.tenant_id,
                )
            )
        ).scalar_one()
        persisted_session_status, persisted_flow_id = (
            await container.session().execute(
                select(BuilderSessions.status, BuilderSessions.flow_id).where(
                    BuilderSessions.id == session.id,
                    BuilderSessions.tenant_id == user.tenant_id,
                )
            )
        ).one()
        lock_row = await _load_session_send_lock(
            repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
        )

    assert exc.value.code == "session_send_in_progress"
    assert persisted_plan_status == PlanStatus.APPROVED.value
    assert persisted_session_status == SessionStatus.AWAITING_APPROVAL.value
    assert persisted_flow_id is None
    assert lock_row[0] == turn.lease.request_id
    assert lock_row[1] == turn.lease.lock_token


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mark_processing", "expected_state"),
    [
        (False, BuilderTurnState.FAILED_BEFORE_PROVIDER),
        (True, BuilderTurnState.PROVIDER_OUTCOME_UNKNOWN),
    ],
    ids=["open", "processing"],
)
async def test_mark_plan_applied_terminalizes_an_expired_send_turn(
    db_container,
    mark_processing: bool,
    expected_state: BuilderTurnState,
) -> None:
    async with db_container() as container:
        user = container.user()
        space = Spaces(
            tenant_id=user.tenant_id,
            user_id=user.id,
            name=f"ai-builder-apply-expired-send-{uuid4().hex}",
        )
        container.session().add(space)
        await container.session().flush()

        repo = AIBuilderRepository(container.session())
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=space.id,
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
        )
        plan = await repo.create_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            proposal=FlowBuilderProposal(
                content=FlowBuilderProposalContent(
                    spec=_make_builder_plan_spec(existing_step_ref=None)
                )
            ),
        )
        await repo.update_plan_status(
            plan_id=plan.id,
            tenant_id=user.tenant_id,
            status=PlanStatus.APPROVED,
        )
        await repo.update_session_status_without_send_lease(
            session_id=session.id,
            tenant_id=user.tenant_id,
            status=SessionStatus.AWAITING_APPROVAL,
        )
        await repo.update_session_latest_plan_without_send_lease(
            session_id=session.id,
            tenant_id=user.tenant_id,
            plan_id=plan.id,
        )
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
            lock_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        if mark_processing:
            await repo.mark_session_turn_processing(turn=turn)

        await repo.mark_plan_applied(
            plan_id=plan.id,
            session_id=session.id,
            tenant_id=user.tenant_id,
            flow_id=None,
        )
        persisted = await repo.get_session(
            session_id=session.id,
            tenant_id=user.tenant_id,
        )
        lock_row = await _load_session_send_lock(
            repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
        )

    assert persisted.status is SessionStatus.APPLIED
    assert persisted.latest_turn is not None
    assert persisted.latest_turn.state is expected_state
    assert lock_row == (None, None, None, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_list_sessions_with_draft_titles_reads_title_and_nulls_in_recency_order(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
    admin_user,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Session List Titles",
    )
    session_id, tenant_id, _, _ = await _create_proposed_ai_builder_plan(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        space_id=space_id,
    )
    empty_session_id = UUID(
        await _create_ai_builder_session(
            client=client,
            bearer_token=bearer_token,
            space_id=space_id,
        )
    )
    planless_session_id = UUID(
        await _create_ai_builder_session(
            client=client,
            bearer_token=bearer_token,
            space_id=space_id,
        )
    )

    async with db_container() as container:
        now = datetime.now(timezone.utc)
        await container.session().execute(
            update(BuilderSessions)
            .where(BuilderSessions.id == session_id)
            .values(updated_at=now - timedelta(minutes=2))
        )
        await container.session().execute(
            update(BuilderSessions)
            .where(BuilderSessions.id == empty_session_id)
            .values(updated_at=now)
        )
        # A drafting session that never reached a plan: the user's opening
        # message is the only human-meaningful title.
        await container.session().execute(
            update(BuilderSessions)
            .where(BuilderSessions.id == planless_session_id)
            .values(
                updated_at=now - timedelta(minutes=1),
                conversation=[
                    {
                        "message_id": "msg-title-fallback",
                        "role": "user",
                        "content": "Sammanfatta veckans inkomna rapporter",
                    }
                ],
            )
        )

        repo = AIBuilderRepository(container.session())
        sessions = await repo.list_sessions_with_draft_titles(
            tenant_id=tenant_id,
            actor_user_id=admin_user.id,
        )

    assert [(session.id, title) for session, title in sessions] == [
        (empty_session_id, None),
        (planless_session_id, "Sammanfatta veckans inkomna rapporter"),
        (session_id, "Testplan"),
    ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_revise_plan_api_creates_replacement_without_active_send(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Revise Success",
    )
    session_id, tenant_id, old_plan_id, _ = await _create_proposed_ai_builder_plan(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        space_id=space_id,
    )

    response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{old_plan_id}/revise",
        json={"type": "keep_current_description"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )

    assert response.status_code == 200, response.text
    new_plan_id = UUID(response.json()["plan_id"])
    assert new_plan_id != old_plan_id
    response_proposal = response.json()["proposal"]
    assert response_proposal["description_override_manual"] is True
    assert response_proposal.get("edit") is None
    assert "edit_result" not in response_proposal

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        plans = await repo.list_session_plans(
            session_id=session_id,
            tenant_id=tenant_id,
        )
        fetched = await repo.get_session(session_id=session_id, tenant_id=tenant_id)
        audit_event = (
            await container.session().execute(
                select(
                    AuditLogTable.actor_id,
                    AuditLogTable.entity_type,
                    AuditLogTable.entity_id,
                    AuditLogTable.log_metadata,
                ).where(
                    AuditLogTable.tenant_id == tenant_id,
                    AuditLogTable.action == ActionType.AI_BUILDER_PLAN_REVISED.value,
                    AuditLogTable.entity_id == session_id,
                )
            )
        ).one()

    statuses = {plan.id: plan.status for plan in plans}
    assert statuses[old_plan_id] == PlanStatus.SUPERSEDED
    assert statuses[new_plan_id] == PlanStatus.PROPOSED
    assert fetched.latest_plan_id == new_plan_id
    assert fetched.status == SessionStatus.AWAITING_APPROVAL
    assert str(audit_event.actor_id) == audit_event.log_metadata["actor"]["id"]
    assert audit_event.entity_type == EntityType.AI_BUILDER_SESSION.value
    assert audit_event.entity_id == session_id
    assert audit_event.log_metadata["target"]["id"] == str(session_id)
    assert audit_event.log_metadata["extra"] == {
        "old_plan_id": str(old_plan_id),
        "new_plan_id": str(new_plan_id),
        "revision_type": "keep_current_description",
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_revise_plan_api_rejects_active_send_and_rolls_back(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Revise Active Send",
    )
    session_id, tenant_id, old_plan_id, _ = await _create_proposed_ai_builder_plan(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        space_id=space_id,
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        await _claim_session_send_turn(
            repo=repo,
            session_id=session_id,
            tenant_id=tenant_id,
        )

    response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{old_plan_id}/revise",
        json={"type": "keep_current_description"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "session_message_in_progress"
    assert (
        response.json()["message"]
        == "Another AI Builder message is already being processed."
    )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        plans = await repo.list_session_plans(
            session_id=session_id,
            tenant_id=tenant_id,
        )
        fetched = await repo.get_session(session_id=session_id, tenant_id=tenant_id)
        audit_count = await container.session().scalar(
            select(sa.func.count(AuditLogTable.id)).where(
                AuditLogTable.tenant_id == tenant_id,
                AuditLogTable.action == ActionType.AI_BUILDER_PLAN_REVISED.value,
                AuditLogTable.entity_id == session_id,
            )
        )

    assert [plan.id for plan in plans] == [old_plan_id]
    assert plans[0].status == PlanStatus.PROPOSED
    assert fetched.latest_plan_id == old_plan_id
    assert fetched.status == SessionStatus.AWAITING_APPROVAL
    assert audit_count == 0


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mark_processing", "expected_state"),
    [
        (False, BuilderTurnState.FAILED_BEFORE_PROVIDER),
        (True, BuilderTurnState.PROVIDER_OUTCOME_UNKNOWN),
    ],
    ids=["open", "processing"],
)
async def test_revise_plan_api_recovers_expired_send_lock_and_fences_old_lease(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
    mark_processing: bool,
    expected_state: BuilderTurnState,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Revise Expired Send",
    )
    session_id, tenant_id, old_plan_id, _ = await _create_proposed_ai_builder_plan(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        space_id=space_id,
    )
    stale_lease = SessionSendLease(request_id=uuid4(), lock_token=uuid4())
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session_id,
            tenant_id=tenant_id,
            lease=stale_lease,
            lock_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        if mark_processing:
            await repo.mark_session_turn_processing(turn=turn)

    response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{old_plan_id}/revise",
        json={"type": "keep_current_description"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )

    assert response.status_code == 200, response.text
    new_plan_id = UUID(response.json()["plan_id"])
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        fetched = await repo.get_session(session_id=session_id, tenant_id=tenant_id)
        stale_refresh = await repo.refresh_session_send_lease(
            session_id=session_id,
            tenant_id=tenant_id,
            lease=stale_lease,
            lock_lease_seconds=30,
        )
        lock_row = (
            await repo.session.execute(
                select(
                    BuilderSessions.active_request_id,
                    BuilderSessions.lock_token,
                    BuilderSessions.locked_at,
                    BuilderSessions.lock_expires_at,
                ).where(BuilderSessions.id == session_id)
            )
        ).one()

    assert fetched.latest_plan_id == new_plan_id
    assert fetched.status == SessionStatus.AWAITING_APPROVAL
    assert fetched.latest_turn is not None
    assert fetched.latest_turn.state is expected_state
    assert stale_refresh is False
    assert lock_row == (None, None, None, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_message_and_attachments_are_committed_before_first_provider_call(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Attachment Persistence",
    )
    file_id = await _upload_reference_file(
        client=client,
        bearer_token=bearer_token,
        filename="reference.txt",
        content=b"reference material",
    )
    client_turn_id = uuid4()
    session_id: str | None = None
    provider_observation: dict[str, object] = {}

    async def observe_durable_turn_before_provider(**_kwargs: object) -> MagicMock:
        assert session_id is not None
        if not provider_observation:
            async with db_container() as container:
                row = (
                    await container.session().execute(
                        select(
                            BuilderSessions.conversation,
                            BuilderSessions.latest_turn_id,
                            BuilderSessions.latest_turn_request_fingerprint,
                            BuilderSessions.latest_turn_request_jsonb,
                            BuilderSessions.latest_turn_state,
                        ).where(BuilderSessions.id == UUID(session_id))
                    )
                ).one()
                repo = AIBuilderRepository(container.session())
                attachment_ids = await repo.list_session_file_ids(
                    session_id=UUID(session_id),
                    tenant_id=container.user().tenant_id,
                )
            provider_observation.update(
                conversation=row[0],
                client_turn_id=row[1],
                request_fingerprint=row[2],
                request=row[3],
                state=row[4],
                attachment_ids=attachment_ids,
            )
        return _make_llm_response(content="Jag kan använda referensmaterialet.")

    with patch(
        "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=AsyncMock(side_effect=observe_durable_turn_before_provider),
    ):
        with patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
        ):
            session_id = await _create_ai_builder_session(
                client=client,
                bearer_token=bearer_token,
                space_id=space_id,
            )

            before_response = await client.get(
                f"/api/v1/flows/ai-builder/sessions/{session_id}",
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
            assert before_response.status_code == 200, before_response.text
            assert before_response.json()["attachments"] == []

            with patch(
                "eneo.flows.ai_builder.ai_builder_router.logger.error"
            ) as log_error:
                events = await _send_builder_message(
                    client=client,
                    bearer_token=bearer_token,
                    session_id=session_id,
                    message="Använd det bifogade referensmaterialet.",
                    client_turn_id=client_turn_id,
                    file_ids=[file_id],
                )
            if log_error.called:
                raise cast(Exception, log_error.call_args.kwargs["exc_info"])
            assert any(event["event"] == "text" for event in events), events

            persisted_messages = cast(
                list[dict[str, object]], provider_observation["conversation"]
            )
            assert [message["role"] for message in persisted_messages] == ["user"]
            assert provider_observation["client_turn_id"] == client_turn_id
            assert provider_observation["request_fingerprint"] is not None
            assert provider_observation["request"] == {
                "client_turn_id": str(client_turn_id),
                "file_ids": [file_id],
                "message": "Använd det bifogade referensmaterialet.",
                "ui_language": "sv",
            }
            assert provider_observation["state"] == "processing"
            assert provider_observation["attachment_ids"] == [UUID(file_id)]

            after_response = await client.get(
                f"/api/v1/flows/ai-builder/sessions/{session_id}",
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
            assert after_response.status_code == 200, after_response.text
            attachment_ids = [
                attachment["id"] for attachment in after_response.json()["attachments"]
            ]
            assert attachment_ids == [file_id]
            assert after_response.json()["latest_turn"] == {
                "client_turn_id": str(client_turn_id),
                "state": "committed",
                "user_message_id": persisted_messages[0]["message_id"],
                "error": None,
                "requires_duplicate_provider_spend_acknowledgement": False,
                "retry_request": {
                    "client_turn_id": str(client_turn_id),
                    "message": "Använd det bifogade referensmaterialet.",
                    "model_id": None,
                    "file_ids": [file_id],
                    "question_answer": None,
                    "edit_context": None,
                    "ui_language": "sv",
                    "acknowledge_duplicate_provider_spend": False,
                },
            }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_same_turn_key_replays_without_provider_or_duplicates(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Turn Replay",
    )
    session_id = await _create_ai_builder_session(
        client=client,
        bearer_token=bearer_token,
        space_id=space_id,
    )
    client_turn_id = uuid4()
    completion = AsyncMock(
        return_value=_make_llm_response(content="Jag kan hjälpa dig bygga flödet.")
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=completion,
    ):
        with patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
        ):
            first_events = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message="Hjälp mig bygga ett flöde.",
                client_turn_id=client_turn_id,
            )
            assert any(event["event"] == "text" for event in first_events)
            calls_after_commit = completion.await_count

            first_session = await client.get(
                f"/api/v1/flows/ai-builder/sessions/{session_id}",
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
            assert first_session.status_code == 200, first_session.text

            replay_events = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message="Hjälp mig bygga ett flöde.",
                client_turn_id=client_turn_id,
            )
            assert [event["event"] for event in replay_events] == ["done"]
            assert completion.await_count == calls_after_commit

            replayed_session = await client.get(
                f"/api/v1/flows/ai-builder/sessions/{session_id}",
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
            assert replayed_session.status_code == 200, replayed_session.text
            assert (
                replayed_session.json()["conversation"]
                == first_session.json()["conversation"]
            )
            assert (
                replayed_session.json()["latest_turn"]
                == first_session.json()["latest_turn"]
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_committed_error_replays_exactly_without_provider_work(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Committed Error Replay",
    )
    session_id = UUID(
        await _create_ai_builder_session(
            client=client,
            bearer_token=bearer_token,
            space_id=space_id,
        )
    )
    request = SendMessageRequest(
        client_turn_id=uuid4(),
        message="Build a report flow.",
        ui_language="sv",
    )
    committed_error = build_ai_builder_error(
        message="The AI planner request exceeds the available context window.",
        code=AIBuilderErrorCode.PLANNER_CONTEXT_LIMIT_EXCEEDED,
        request_id="committed-context-limit-request",
        details={"another_call_permitted": False, "retry_scope": "new_turn"},
    )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        tenant_id = container.user().tenant_id
        request_fingerprint = request.request_fingerprint()
        preflight = await repo.preflight_session_turn(
            session_id=session_id,
            tenant_id=tenant_id,
            client_turn_id=request.client_turn_id,
            request_fingerprint=request_fingerprint,
            acknowledge_duplicate_provider_spend=False,
        )
        lease = SessionSendLease(request_id=uuid4(), lock_token=uuid4())
        user_message = ConversationMessage(role="user", content=request.message)
        claim = await repo.accept_session_turn(
            session_id=session_id,
            tenant_id=tenant_id,
            lease=lease,
            lock_lease_seconds=30,
            acceptance=SessionTurnAcceptance(
                client_turn_id=request.client_turn_id,
                request_fingerprint=request_fingerprint,
                request=request.retry_snapshot(),
                user_message=user_message,
                file_ids=(),
            ),
            preparation_baseline=preflight.baseline,
        )
        turn = SessionSendTurn(
            session_id=session_id,
            tenant_id=tenant_id,
            lease=lease,
            base_planning_state_version=claim.base_planning_state_version,
        )
        await repo.complete_session_turn(turn=turn, error=committed_error)
        await repo.release_session_send(
            session_id=session_id,
            tenant_id=tenant_id,
            lease=lease,
        )

    before_replay = await client.get(
        f"/api/v1/flows/ai-builder/sessions/{session_id}",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert before_replay.status_code == 200, before_replay.text
    assert before_replay.json()["latest_turn"]["error"] == committed_error.model_dump(
        mode="json",
    )
    assert before_replay.json()["latest_turn"]["state"] == "committed"
    assert (
        before_replay.json()["latest_turn"]["retry_request"][
            "acknowledge_duplicate_provider_spend"
        ]
        is False
    )

    completion = AsyncMock(side_effect=AssertionError("Provider work must not replay."))
    with patch(
        "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=completion,
    ):
        replay_events = await _send_builder_message(
            client=client,
            bearer_token=bearer_token,
            session_id=str(session_id),
            message=request.message,
            client_turn_id=request.client_turn_id,
        )

    assert [event["event"] for event in replay_events] == ["error", "done"]
    assert replay_events[0]["data"] == committed_error.model_dump(
        mode="json",
        exclude_none=True,
    )
    completion.assert_not_awaited()

    after_replay = await client.get(
        f"/api/v1/flows/ai-builder/sessions/{session_id}",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert after_replay.status_code == 200, after_replay.text
    assert after_replay.json() == before_replay.json()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_disconnect_after_committed_event_replays_without_provider(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Committed Stream Disconnect",
    )
    session_id = await _create_ai_builder_session(
        client=client,
        bearer_token=bearer_token,
        space_id=space_id,
    )
    client_turn_id = uuid4()
    completion = AsyncMock(
        return_value=_make_llm_response(content="Jag kan hjälpa dig bygga flödet.")
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=completion,
    ):
        with patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
        ):
            async with db_container() as identity_container:
                route_user = identity_container.user()
                route_tenant = identity_container.tenant()
            async with sessionmanager.session() as database_session:
                direct_container = Container(
                    session=providers.Object(database_session),
                    user=providers.Object(route_user),
                    tenant=providers.Object(route_tenant),
                )
                response = await send_message(
                    request=Request(
                        {
                            "type": "http",
                            "method": "POST",
                            "path": (
                                f"/api/v1/flows/ai-builder/sessions/{session_id}/messages"
                            ),
                            "headers": [],
                            "state": {},
                        }
                    ),
                    session_id=UUID(session_id),
                    body=SendMessageRequest(
                        client_turn_id=client_turn_id,
                        message="Hjälp mig bygga ett flöde.",
                        ui_language="sv",
                    ),
                    container=direct_container,
                )
                stream = cast(
                    AsyncGenerator[ServerSentEvent, None],
                    response.body_iterator,
                )
                saw_durable_event = False
                try:
                    async for event in stream:
                        if event.event == "text":
                            saw_durable_event = True
                            break
                finally:
                    await stream.aclose()

            assert saw_durable_event
            calls_after_disconnect = completion.await_count

            persisted = await client.get(
                f"/api/v1/flows/ai-builder/sessions/{session_id}",
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
            assert persisted.status_code == 200, persisted.text
            assert persisted.json()["latest_turn"]["state"] == "committed"

            replay_events = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message="Hjälp mig bygga ett flöde.",
                client_turn_id=client_turn_id,
            )

    assert [event["event"] for event in replay_events] == ["done"]
    assert completion.await_count == calls_after_disconnect


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_latest_turn_replay_and_conflict_survive_compaction(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    from eneo.flows.ai_builder.ai_builder_conversation_compaction import (
        MAX_SESSION_MESSAGES,
    )

    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Turn Compaction Replay",
    )
    session_id = await _create_ai_builder_session(
        client=client,
        bearer_token=bearer_token,
        space_id=space_id,
    )
    async with db_container() as container:
        filler = [
            ConversationMessage(role="user", content=f"filler {index}").model_dump(
                mode="json"
            )
            for index in range(MAX_SESSION_MESSAGES + 5)
        ]
        await container.session().execute(
            update(BuilderSessions)
            .where(BuilderSessions.id == UUID(session_id))
            .values(conversation=filler)
        )

    client_turn_id = uuid4()
    completion = AsyncMock(
        return_value=_make_llm_response(content="Jag kan hjälpa dig bygga flödet.")
    )
    with patch(
        "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=completion,
    ):
        with patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
        ):
            first_events = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message="Bygg ett nytt flöde efter den långa historiken.",
                client_turn_id=client_turn_id,
            )
            assert any(event["event"] == "text" for event in first_events)
            calls_after_commit = completion.await_count

            replay_events = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message="Bygg ett nytt flöde efter den långa historiken.",
                client_turn_id=client_turn_id,
            )
            conflict_response = await client.post(
                f"/api/v1/flows/ai-builder/sessions/{session_id}/messages",
                json={
                    "client_turn_id": str(client_turn_id),
                    "message": "Ändra den redan använda nyckeln.",
                    "ui_language": "sv",
                },
                headers={"Authorization": f"Bearer {bearer_token}"},
            )

    assert [event["event"] for event in replay_events] == ["done"]
    assert conflict_response.status_code == 409
    assert conflict_response.json()["code"] == "session_turn_idempotency_conflict"
    assert completion.await_count == calls_after_commit

    persisted = await client.get(
        f"/api/v1/flows/ai-builder/sessions/{session_id}",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert persisted.status_code == 200, persisted.text
    assert len(persisted.json()["conversation"]) <= MAX_SESSION_MESSAGES
    assert persisted.json()["latest_turn"]["client_turn_id"] == str(client_turn_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_same_turn_key_rejects_different_request_before_provider(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Turn Conflict",
    )
    session_id = await _create_ai_builder_session(
        client=client,
        bearer_token=bearer_token,
        space_id=space_id,
    )
    client_turn_id = uuid4()
    completion = AsyncMock(
        return_value=_make_llm_response(content="Jag kan hjälpa dig bygga flödet.")
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=completion,
    ):
        with patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
        ):
            first_events = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message="Hjälp mig bygga ett flöde.",
                client_turn_id=client_turn_id,
            )
            assert any(event["event"] == "text" for event in first_events)
            calls_after_commit = completion.await_count

            conflict_response = await client.post(
                f"/api/v1/flows/ai-builder/sessions/{session_id}/messages",
                json={
                    "client_turn_id": str(client_turn_id),
                    "message": "Bygg ett annat flöde.",
                    "ui_language": "sv",
                },
                headers={"Authorization": f"Bearer {bearer_token}"},
            )

    assert completion.await_count == calls_after_commit
    assert conflict_response.status_code == 409
    conflict = cast(dict[str, object], conflict_response.json())
    assert conflict["code"] == "session_turn_idempotency_conflict"
    assert conflict["category"] == "conflict"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("provider_error", "expected_exception_class"),
    [
        (
            BadRequestError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "bad_request",
        ),
        (
            RateLimitError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "rate_limit",
        ),
    ],
    ids=["bad_request", "rate_limit"],
)
@pytest.mark.asyncio
async def test_ai_builder_known_provider_rejection_commits_and_replays_without_recall(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
    provider_error: Exception,
    expected_exception_class: str,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name=f"AI Builder Known Rejection {expected_exception_class}",
    )
    session_id = await _create_ai_builder_session(
        client=client,
        bearer_token=bearer_token,
        space_id=space_id,
    )
    client_turn_id = uuid4()
    message = "Hjälp mig bygga ett flöde."
    completion = AsyncMock(
        side_effect=[
            provider_error,
            _make_llm_response(content="Jag kan hjälpa dig bygga flödet."),
        ]
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=completion,
    ):
        with patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
        ):
            first_events = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message=message,
                client_turn_id=client_turn_id,
            )
            assert [event["event"] for event in first_events] == ["error", "done"]
            first_error = cast(dict[str, object], first_events[0]["data"])
            assert first_error["code"] == "planner_upstream_error"
            assert first_error["details"] == {
                "another_call_permitted": False,
                "provider_disposition": "known_rejection",
                "provider_exception_class": expected_exception_class,
                "retry_scope": "new_turn",
            }
            encoded_error = json.dumps(first_error)
            assert "sensitive-provider-material" not in encoded_error
            assert "private-model" not in encoded_error
            assert "private-provider" not in encoded_error
            calls_after_rejection = completion.await_count
            assert calls_after_rejection == 1

            committed_session = await client.get(
                f"/api/v1/flows/ai-builder/sessions/{session_id}",
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
            assert committed_session.status_code == 200, committed_session.text
            latest_turn = committed_session.json()["latest_turn"]
            assert latest_turn["state"] == "committed"
            assert (
                latest_turn["requires_duplicate_provider_spend_acknowledgement"]
                is False
            )
            persisted_error = cast(dict[str, object], latest_turn["error"])
            assert {
                key: value
                for key, value in persisted_error.items()
                if key != "diagnostic_context"
            } == {
                key: value
                for key, value in first_error.items()
                if key != "diagnostic_context"
            }
            persisted_diagnostic_context = cast(
                dict[str, object], persisted_error["diagnostic_context"]
            )
            assert {
                key: value
                for key, value in persisted_diagnostic_context.items()
                if value is not None
            } == first_error["diagnostic_context"]

            replay_events = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message=message,
                client_turn_id=client_turn_id,
            )
            assert [event["event"] for event in replay_events] == ["error", "done"]
            assert replay_events[0]["data"] == first_error
            assert completion.await_count == calls_after_rejection

            changed_response = await client.post(
                f"/api/v1/flows/ai-builder/sessions/{session_id}/messages",
                json={
                    "client_turn_id": str(client_turn_id),
                    "message": "Bygg ett annat flöde.",
                    "ui_language": "sv",
                },
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
            assert changed_response.status_code == 409
            assert changed_response.json()["code"] == (
                "session_turn_idempotency_conflict"
            )
            assert completion.await_count == calls_after_rejection

            new_turn_events = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message=message,
                client_turn_id=uuid4(),
            )
            assert any(event["event"] == "text" for event in new_turn_events)
            assert completion.await_count == calls_after_rejection + 1


@pytest.mark.integration
@pytest.mark.parametrize(
    ("provider_error", "expected_failure_kind"),
    [
        (
            Timeout(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "timeout",
        ),
        (
            APIConnectionError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "transport_ambiguous",
        ),
        (
            APIError(
                503,
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "transport_ambiguous",
        ),
        (RuntimeError("sensitive-provider-material"), "unknown"),
    ],
)
@pytest.mark.asyncio
async def test_ai_builder_unknown_provider_outcome_requires_explicit_acknowledgement(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
    provider_error: Exception,
    expected_failure_kind: str,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Unknown Provider Outcome",
    )
    session_id = await _create_ai_builder_session(
        client=client,
        bearer_token=bearer_token,
        space_id=space_id,
    )
    client_turn_id = uuid4()
    completion = AsyncMock(
        side_effect=[
            provider_error,
            _make_llm_response(content="Jag kan hjälpa dig bygga flödet."),
        ]
    )

    with patch.object(error_contract_module.logger, "info") as provider_failure_log:
        with patch(
            "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
            new=completion,
        ):
            with patch(
                "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
                new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
            ):
                failed_events = await _send_builder_message(
                    client=client,
                    bearer_token=bearer_token,
                    session_id=session_id,
                    message="Hjälp mig bygga ett flöde.",
                    client_turn_id=client_turn_id,
                )

            calls_after_unknown_outcome = completion.await_count
            assert calls_after_unknown_outcome == 1
            provider_failure_log.assert_called_once()
            failure_payload = provider_failure_log.call_args.kwargs["extra"]
            assert failure_payload["operation"] == "slot_classification"
            assert failure_payload["failure_kind"] == expected_failure_kind
            assert len(failure_payload["failure_fingerprint"]) == 12
            encoded_failure = str(failure_payload)
            assert "sensitive-provider-material" not in encoded_failure
            assert "private-model" not in encoded_failure
            assert "private-provider" not in encoded_failure
            failed_error = cast(dict[str, object], failed_events[0]["data"])
            assert failed_error["code"] == "session_turn_provider_outcome_unknown"

            unknown_session = await client.get(
                f"/api/v1/flows/ai-builder/sessions/{session_id}",
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
            assert unknown_session.status_code == 200, unknown_session.text
            assert unknown_session.json()["latest_turn"]["state"] == (
                "provider_outcome_unknown"
            )
            assert (
                unknown_session.json()["latest_turn"][
                    "requires_duplicate_provider_spend_acknowledgement"
                ]
                is True
            )

            blocked_response = await client.post(
                f"/api/v1/flows/ai-builder/sessions/{session_id}/messages",
                json={
                    "client_turn_id": str(client_turn_id),
                    "message": "Hjälp mig bygga ett flöde.",
                    "ui_language": "sv",
                },
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
            assert blocked_response.status_code == 409
            blocked_error = cast(dict[str, object], blocked_response.json())
            assert blocked_error["code"] == "session_turn_provider_outcome_unknown"
            assert completion.await_count == calls_after_unknown_outcome

            with patch(
                "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
                new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
            ):
                retry_events = await _send_builder_message(
                    client=client,
                    bearer_token=bearer_token,
                    session_id=session_id,
                    message="Hjälp mig bygga ett flöde.",
                    client_turn_id=client_turn_id,
                    acknowledge_duplicate_provider_spend=True,
                )
            assert any(event["event"] == "text" for event in retry_events)
            assert completion.await_count == calls_after_unknown_outcome + 1

            committed_session = await client.get(
                f"/api/v1/flows/ai-builder/sessions/{session_id}",
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
            assert committed_session.status_code == 200, committed_session.text
            assert committed_session.json()["latest_turn"]["state"] == "committed"
            user_messages = [
                message
                for message in committed_session.json()["conversation"]
                if message["role"] == "user"
            ]
            assert len(user_messages) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_pre_provider_failure_resumes_same_durable_turn(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Pre-provider Resume",
    )
    session_id = await _create_ai_builder_session(
        client=client,
        bearer_token=bearer_token,
        space_id=space_id,
    )
    client_turn_id = uuid4()
    completion = AsyncMock(
        return_value=_make_llm_response(content="Jag kan hjälpa dig bygga flödet.")
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=completion,
    ):
        with patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
        ):
            with patch(
                "eneo.flows.ai_builder.ai_builder_planner.prepare_planner_request",
                new=AsyncMock(side_effect=RuntimeError("fail before provider")),
            ):
                failed_events = await _send_builder_message(
                    client=client,
                    bearer_token=bearer_token,
                    session_id=session_id,
                    message="Hjälp mig bygga ett flöde.",
                    client_turn_id=client_turn_id,
                )

            assert completion.await_count == 0
            assert [event["event"] for event in failed_events] == ["error", "done"]
            failed_session = await client.get(
                f"/api/v1/flows/ai-builder/sessions/{session_id}",
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
            assert failed_session.status_code == 200, failed_session.text
            assert failed_session.json()["latest_turn"]["state"] == (
                "failed_before_provider"
            )

            retry_events = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message="Hjälp mig bygga ett flöde.",
                client_turn_id=client_turn_id,
            )
            assert any(event["event"] == "text" for event in retry_events)
            assert completion.await_count > 0

            committed_session = await client.get(
                f"/api/v1/flows/ai-builder/sessions/{session_id}",
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
            assert committed_session.status_code == 200, committed_session.text
            assert committed_session.json()["latest_turn"]["state"] == "committed"
            assert (
                len(
                    [
                        message
                        for message in committed_session.json()["conversation"]
                        if message["role"] == "user"
                    ]
                )
                == 1
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_accept_session_turn_can_reclaim_expired_open_lease(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Lease Reclaim",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )

        await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
            lock_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )

        reclaimed_lease = SessionSendLease(request_id=uuid4(), lock_token=uuid4())
        reclaimed = await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
            lease=reclaimed_lease,
            lock_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        )
        assert reclaimed.lease == reclaimed_lease


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_session_reload_projects_expired_turn_recovery_state(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Expired Turn Recovery",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        open_session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        processing_session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        expired_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await _claim_session_send_turn(
            repo=repo,
            session_id=open_session.id,
            tenant_id=user.tenant_id,
            lock_expires_at=expired_at,
        )
        processing_turn = await _claim_session_send_turn(
            repo=repo,
            session_id=processing_session.id,
            tenant_id=user.tenant_id,
            lock_expires_at=expired_at,
        )
        await repo.mark_session_turn_processing(turn=processing_turn)

    open_response = await client.get(
        f"/api/v1/flows/ai-builder/sessions/{open_session.id}",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    processing_response = await client.get(
        f"/api/v1/flows/ai-builder/sessions/{processing_session.id}",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )

    assert open_response.status_code == 200, open_response.text
    assert processing_response.status_code == 200, processing_response.text
    assert open_response.json()["latest_turn"]["state"] == "failed_before_provider"
    assert (
        open_response.json()["latest_turn"][
            "requires_duplicate_provider_spend_acknowledgement"
        ]
        is False
    )
    assert (
        processing_response.json()["latest_turn"]["state"] == "provider_outcome_unknown"
    )
    assert (
        processing_response.json()["latest_turn"][
            "requires_duplicate_provider_spend_acknowledgement"
        ]
        is True
    )


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored_state", "effective_state"),
    [
        (BuilderTurnState.OPEN, BuilderTurnState.FAILED_BEFORE_PROVIDER),
        (
            BuilderTurnState.PROCESSING,
            BuilderTurnState.PROVIDER_OUTCOME_UNKNOWN,
        ),
        (BuilderTurnState.COMMITTED, BuilderTurnState.COMMITTED),
        (
            BuilderTurnState.FAILED_BEFORE_PROVIDER,
            BuilderTurnState.FAILED_BEFORE_PROVIDER,
        ),
        (
            BuilderTurnState.PROVIDER_OUTCOME_UNKNOWN,
            BuilderTurnState.PROVIDER_OUTCOME_UNKNOWN,
        ),
    ],
)
async def test_ai_builder_repo_sql_and_python_turn_projection_are_exhaustive(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
    stored_state: BuilderTurnState,
    effective_state: BuilderTurnState,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name=f"AI Builder Turn Projection {stored_state.value}",
    )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
            lock_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        await repo.session.execute(
            update(BuilderSessions)
            .where(
                BuilderSessions.id == session.id,
                BuilderSessions.tenant_id == user.tenant_id,
            )
            .values(latest_turn_state=stored_state.value)
        )

        projected = await repo.get_session(
            session_id=session.id,
            tenant_id=user.tenant_id,
        )
        released_state = await repo.release_session_send(
            session_id=session.id,
            tenant_id=user.tenant_id,
            lease=turn.lease,
        )
        persisted_state = await repo.session.scalar(
            select(BuilderSessions.latest_turn_state).where(
                BuilderSessions.id == session.id,
                BuilderSessions.tenant_id == user.tenant_id,
            )
        )

    assert projected.latest_turn is not None
    assert projected.latest_turn.state is effective_state
    assert released_state is effective_state
    assert persisted_state == effective_state.value


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_session_reload_uses_database_clock_for_turn_state(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Database Clock Projection",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
            lock_expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        )

    with patch(
        "eneo.flows.ai_builder.ai_builder_repo.datetime", wraps=datetime
    ) as app_clock:
        app_clock.now.return_value = datetime(2099, 1, 1, tzinfo=timezone.utc)
        response = await client.get(
            f"/api/v1/flows/ai-builder/sessions/{session.id}",
            headers={"Authorization": f"Bearer {bearer_token}"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["latest_turn"]["state"] == "open"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_rejects_partial_send_lock_row(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Partial Send Lock",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )

        with pytest.raises(IntegrityError):
            await repo.session.execute(
                update(BuilderSessions)
                .where(
                    BuilderSessions.id == session.id,
                    BuilderSessions.tenant_id == user.tenant_id,
                )
                .values(active_request_id=uuid4(), lock_token=uuid4())
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_send_lock_claim_refresh_release_preserves_invariant(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Send Lock Refresh",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        lease = SessionSendLease(request_id=uuid4(), lock_token=uuid4())

        await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
            lease=lease,
            lock_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        )
        claimed_lock = await _load_session_send_lock(
            repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
        )
        assert claimed_lock[0] == lease.request_id
        assert claimed_lock[1] == lease.lock_token
        assert claimed_lock[2] is not None
        assert claimed_lock[3] is not None

        refreshed = await repo.refresh_session_send_lease(
            session_id=session.id,
            tenant_id=user.tenant_id,
            lease=lease,
            lock_lease_seconds=60,
        )
        assert refreshed is True
        refreshed_lock = await _load_session_send_lock(
            repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
        )
        assert refreshed_lock[0] == lease.request_id
        assert refreshed_lock[1] == lease.lock_token
        assert refreshed_lock[2] is not None
        assert refreshed_lock[3] is not None

        await repo.release_session_send(
            session_id=session.id,
            tenant_id=user.tenant_id,
            lease=lease,
        )
        assert await _load_session_send_lock(
            repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
        ) == (None, None, None, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_accept_lease_uses_database_time_after_row_lock_wait(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Accept Lease Clock",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        client_turn_id = uuid4()
        preflight = await repo.preflight_session_turn(
            session_id=session.id,
            tenant_id=user.tenant_id,
            client_turn_id=client_turn_id,
            request_fingerprint="a" * 64,
            acknowledge_duplicate_provider_spend=False,
        )
        tenant_id = user.tenant_id

    row_locked = asyncio.Event()
    release_row = asyncio.Event()

    async def hold_session_row() -> None:
        async with db_container() as container:
            await container.session().execute(
                select(BuilderSessions.id)
                .where(
                    BuilderSessions.id == session.id,
                    BuilderSessions.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            row_locked.set()
            await release_row.wait()

    async def accept_turn() -> None:
        async with db_container() as container:
            repo = AIBuilderRepository(container.session())
            message = ConversationMessage(role="user", content="Accepted after wait")
            await repo.accept_session_turn(
                session_id=session.id,
                tenant_id=tenant_id,
                lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
                lock_lease_seconds=1,
                acceptance=SessionTurnAcceptance(
                    client_turn_id=client_turn_id,
                    request_fingerprint="a" * 64,
                    request={
                        "client_turn_id": str(client_turn_id),
                        "message": message.content,
                    },
                    user_message=message,
                    file_ids=(),
                ),
                preparation_baseline=preflight.baseline,
            )

    holder = asyncio.create_task(hold_session_row())
    await row_locked.wait()
    accepter = asyncio.create_task(accept_turn())
    try:
        await asyncio.sleep(1.1)
        assert not accepter.done()
    finally:
        release_row.set()
    await asyncio.wait_for(holder, timeout=5)
    await asyncio.wait_for(accepter, timeout=5)

    async with db_container() as container:
        lock_expires_at, database_now = (
            await container.session().execute(
                select(
                    BuilderSessions.lock_expires_at,
                    sa.func.clock_timestamp(),
                ).where(BuilderSessions.id == session.id)
            )
        ).one()
        assert lock_expires_at is not None
        assert lock_expires_at > database_now + timedelta(milliseconds=500)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_refresh_lease_uses_database_time_after_row_lock_wait(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Refresh Lease Clock",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        lease = SessionSendLease(request_id=uuid4(), lock_token=uuid4())
        await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
            lease=lease,
        )
        tenant_id = user.tenant_id

    row_locked = asyncio.Event()
    release_row = asyncio.Event()

    async def hold_session_row() -> None:
        async with db_container() as container:
            await container.session().execute(
                select(BuilderSessions.id)
                .where(
                    BuilderSessions.id == session.id,
                    BuilderSessions.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            row_locked.set()
            await release_row.wait()

    async def refresh_lease() -> None:
        async with db_container() as container:
            repo = AIBuilderRepository(container.session())
            refreshed = await repo.refresh_session_send_lease(
                session_id=session.id,
                tenant_id=tenant_id,
                lease=lease,
                lock_lease_seconds=1,
            )
            assert refreshed is True

    holder = asyncio.create_task(hold_session_row())
    await row_locked.wait()
    refresher = asyncio.create_task(refresh_lease())
    try:
        await asyncio.sleep(1.1)
        assert not refresher.done()
    finally:
        release_row.set()
    await asyncio.wait_for(holder, timeout=5)
    await asyncio.wait_for(refresher, timeout=5)

    async with db_container() as container:
        lock_expires_at, database_now = (
            await container.session().execute(
                select(
                    BuilderSessions.lock_expires_at,
                    sa.func.clock_timestamp(),
                ).where(BuilderSessions.id == session.id)
            )
        ).one()
        assert lock_expires_at is not None
        assert lock_expires_at > database_now + timedelta(milliseconds=500)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_release_session_send_requires_matching_lock_token(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Lease Release",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        lease = SessionSendLease(request_id=uuid4(), lock_token=uuid4())
        await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
            lease=lease,
            lock_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        )

        await repo.release_session_send(
            session_id=session.id,
            tenant_id=user.tenant_id,
            lease=SessionSendLease(request_id=lease.request_id, lock_token=uuid4()),
        )

        next_lease = SessionSendLease(request_id=uuid4(), lock_token=uuid4())
        with pytest.raises(AIBuilderBadRequestException) as exc_info:
            await _claim_session_send_turn(
                repo=repo,
                session_id=session.id,
                tenant_id=user.tenant_id,
                lease=next_lease,
                lock_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
            )
        assert exc_info.value.code is AIBuilderErrorCode.SESSION_MESSAGE_IN_PROGRESS

        await repo.release_session_send(
            session_id=session.id,
            tenant_id=user.tenant_id,
            lease=lease,
        )

        released_lease = SessionSendLease(request_id=uuid4(), lock_token=uuid4())
        released = await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
            lease=released_lease,
            lock_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        )
        assert released.lease == released_lease


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_terminal_compare_and_set_preserves_first_result(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Terminal Compare And Set",
    )
    first_error = build_ai_builder_error(
        message="First terminal result.",
        code=AIBuilderErrorCode.PLANNER_REJECTED,
        request_id="first-terminal-result",
    )
    stale_error = build_ai_builder_error(
        message="Stale competing result.",
        code=AIBuilderErrorCode.PLANNER_REJECTED,
        request_id="stale-terminal-result",
    )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
        )
        await repo.mark_session_turn_processing(turn=turn)
        await repo.complete_session_turn(turn=turn, error=first_error)
        await repo.complete_session_turn(turn=turn, error=first_error)

        with pytest.raises(AIBuilderBadRequestException) as exc_info:
            await repo.complete_session_turn(turn=turn, error=stale_error)

        reloaded = await repo.get_session(
            session_id=session.id,
            tenant_id=user.tenant_id,
        )

    assert exc_info.value.code is AIBuilderErrorCode.SESSION_SEND_LEASE_LOST
    assert reloaded.latest_turn is not None
    assert reloaded.latest_turn.state is BuilderTurnState.COMMITTED
    assert reloaded.latest_turn.error == first_error


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_concurrent_terminal_writers_have_one_winner(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Concurrent Terminal Writers",
    )
    errors = (
        build_ai_builder_error(
            message="Terminal writer A.",
            code=AIBuilderErrorCode.PLANNER_REJECTED,
            request_id="terminal-writer-a",
        ),
        build_ai_builder_error(
            message="Terminal writer B.",
            code=AIBuilderErrorCode.PLANNER_REJECTED,
            request_id="terminal-writer-b",
        ),
    )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
        )
        await repo.mark_session_turn_processing(turn=turn)
        session_id = session.id
        tenant_id = user.tenant_id

    start = asyncio.Event()

    async def terminalize(
        error: AIBuilderPublicError,
    ) -> tuple[AIBuilderErrorCode | None, AIBuilderPublicError]:
        async with db_container() as container:
            await start.wait()
            try:
                await AIBuilderRepository(container.session()).complete_session_turn(
                    turn=turn,
                    error=error,
                )
            except AIBuilderBadRequestException as exception:
                return exception.code, error
            return None, error

    writers = [asyncio.create_task(terminalize(error)) for error in errors]
    start.set()
    results = await asyncio.gather(*writers)

    successful_errors = [error for code, error in results if code is None]
    rejected_codes = [code for code, _error in results if code is not None]
    assert len(successful_errors) == 1
    assert rejected_codes == [AIBuilderErrorCode.SESSION_SEND_LEASE_LOST]

    async with db_container() as container:
        reloaded = await AIBuilderRepository(container.session()).get_session(
            session_id=session_id,
            tenant_id=tenant_id,
        )

    assert reloaded.latest_turn is not None
    assert reloaded.latest_turn.state is BuilderTurnState.COMMITTED
    assert reloaded.latest_turn.error == successful_errors[0]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_terminal_rollback_reload_and_acknowledged_replay(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Terminal Rollback Replay",
    )
    client_turn_id = uuid4()

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        original_turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
            client_turn_id=client_turn_id,
        )
        await repo.mark_session_turn_processing(turn=original_turn)
        session_id = session.id
        tenant_id = user.tenant_id

    with pytest.raises(RuntimeError, match="simulated process rollback"):
        async with db_container() as container:
            await AIBuilderRepository(container.session()).complete_session_turn(
                turn=original_turn,
            )
            raise RuntimeError("simulated process rollback")

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        await repo.session.execute(
            update(BuilderSessions)
            .where(
                BuilderSessions.id == session_id,
                BuilderSessions.tenant_id == tenant_id,
            )
            .values(
                lock_expires_at=sa.func.clock_timestamp()
                - sa.text("interval '1 second'")
            )
        )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        expired = await repo.get_session(
            session_id=session_id,
            tenant_id=tenant_id,
        )
        assert expired.latest_turn is not None
        assert expired.latest_turn.state is BuilderTurnState.PROVIDER_OUTCOME_UNKNOWN

        preflight = await repo.preflight_session_turn(
            session_id=session_id,
            tenant_id=tenant_id,
            client_turn_id=client_turn_id,
            request_fingerprint="a" * 64,
            acknowledge_duplicate_provider_spend=True,
        )
        replay_lease = SessionSendLease(request_id=uuid4(), lock_token=uuid4())
        claim = await repo.accept_session_turn(
            session_id=session_id,
            tenant_id=tenant_id,
            lease=replay_lease,
            lock_lease_seconds=30,
            acceptance=SessionTurnAcceptance(
                client_turn_id=client_turn_id,
                request_fingerprint="a" * 64,
                request={
                    "client_turn_id": str(client_turn_id),
                    "message": "Accepted turn",
                },
                user_message=ConversationMessage(
                    role="user",
                    content="Accepted turn",
                ),
                file_ids=(),
                acknowledge_duplicate_provider_spend=True,
            ),
            preparation_baseline=preflight.baseline,
        )
        replay_turn = SessionSendTurn(
            session_id=session_id,
            tenant_id=tenant_id,
            lease=replay_lease,
            base_planning_state_version=claim.base_planning_state_version,
        )
        await repo.mark_session_turn_processing(turn=replay_turn)
        await repo.complete_session_turn(turn=replay_turn)
        await repo.release_session_send(
            session_id=session_id,
            tenant_id=tenant_id,
            lease=replay_lease,
        )

    async with db_container() as container:
        reloaded = await AIBuilderRepository(container.session()).get_session(
            session_id=session_id,
            tenant_id=tenant_id,
        )

    assert reloaded.latest_turn is not None
    assert reloaded.latest_turn.client_turn_id == client_turn_id
    assert reloaded.latest_turn.state is BuilderTurnState.COMMITTED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_idempotency_horizon_is_latest_turn_only(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Latest Turn Idempotency Horizon",
    )
    first_turn_id = uuid4()
    second_turn_id = uuid4()

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        first_turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
            client_turn_id=first_turn_id,
        )
        await repo.complete_session_turn(turn=first_turn)
        await repo.release_session_send(
            session_id=session.id,
            tenant_id=user.tenant_id,
            lease=first_turn.lease,
        )

        current_replay = await repo.preflight_session_turn(
            session_id=session.id,
            tenant_id=user.tenant_id,
            client_turn_id=first_turn_id,
            request_fingerprint="a" * 64,
            acknowledge_duplicate_provider_spend=False,
        )
        assert current_replay.replayed is True

        second_turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
            client_turn_id=second_turn_id,
        )
        await repo.complete_session_turn(turn=second_turn)
        await repo.release_session_send(
            session_id=session.id,
            tenant_id=user.tenant_id,
            lease=second_turn.lease,
        )

        historical_key = await repo.preflight_session_turn(
            session_id=session.id,
            tenant_id=user.tenant_id,
            client_turn_id=first_turn_id,
            request_fingerprint="a" * 64,
            acknowledge_duplicate_provider_spend=False,
        )

    assert historical_key.replayed is False
    assert historical_key.baseline.latest_turn_id == second_turn_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_conversation_json_aggregate_has_bounded_rewrite_and_lock(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Conversation Aggregate Measurement",
    )
    representative_messages = [
        ConversationMessage(
            role="assistant",
            content="".join(str(uuid4()) for _index in range(5_000)),
        )
        for _message_index in range(5)
    ]

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
            lock_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        session_id = session.id
        tenant_id = user.tenant_id

        relation_before, toast_before = (
            await repo.session.execute(
                sa.text(
                    """
                    SELECT
                        pg_total_relation_size('builder_sessions'::regclass),
                        pg_total_relation_size(reltoastrelid)
                    FROM pg_class
                    WHERE oid = 'builder_sessions'::regclass
                    """
                )
            )
        ).one()
        first_lsn = await repo.session.scalar(
            sa.text("SELECT pg_current_wal_insert_lsn()")
        )
        stored = await repo.append_session_messages(
            session_id=session_id,
            tenant_id=tenant_id,
            conversation=representative_messages,
            lease=turn.lease,
        )
        first_wal_bytes = await repo.session.scalar(
            sa.text(
                "SELECT pg_wal_lsn_diff(pg_current_wal_insert_lsn(), "
                "CAST(:start_lsn AS pg_lsn))"
            ),
            {"start_lsn": first_lsn},
        )
        second_lsn = await repo.session.scalar(
            sa.text("SELECT pg_current_wal_insert_lsn()")
        )
        stored = await repo.append_session_messages(
            session_id=session_id,
            tenant_id=tenant_id,
            conversation=[ConversationMessage(role="assistant", content="rewrite")],
            lease=turn.lease,
        )
        second_wal_bytes = await repo.session.scalar(
            sa.text(
                "SELECT pg_wal_lsn_diff(pg_current_wal_insert_lsn(), "
                "CAST(:start_lsn AS pg_lsn))"
            ),
            {"start_lsn": second_lsn},
        )
        jsonb_column_bytes, jsonb_text_bytes = (
            await repo.session.execute(
                select(
                    sa.func.pg_column_size(BuilderSessions.conversation),
                    sa.func.octet_length(
                        sa.cast(BuilderSessions.conversation, sa.Text)
                    ),
                ).where(
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                )
            )
        ).one()
        relation_after, toast_after = (
            await repo.session.execute(
                sa.text(
                    """
                    SELECT
                        pg_total_relation_size('builder_sessions'::regclass),
                        pg_total_relation_size(reltoastrelid)
                    FROM pg_class
                    WHERE oid = 'builder_sessions'::regclass
                    """
                )
            )
        ).one()

    serialized_bytes = conversation_serialized_size_bytes(stored)
    assert 700_000 < serialized_bytes <= MAX_SESSION_CONVERSATION_BYTES
    assert int(first_wal_bytes) > 0
    assert 0 < int(second_wal_bytes) <= 8 * MAX_SESSION_CONVERSATION_BYTES
    assert int(jsonb_column_bytes) > 0
    assert int(jsonb_text_bytes) >= serialized_bytes
    assert int(relation_after) >= int(relation_before)
    assert int(toast_after) > int(toast_before)

    async with (
        sessionmanager.session() as holder_session,
        sessionmanager.session() as contender_session,
    ):
        await holder_session.begin()
        await contender_session.begin()
        await holder_session.execute(
            select(BuilderSessions)
            .where(
                BuilderSessions.id == session_id,
                BuilderSessions.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        await contender_session.execute(sa.text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(DBAPIError):
            await AIBuilderRepository(contender_session).append_session_messages(
                session_id=session_id,
                tenant_id=tenant_id,
                conversation=[
                    ConversationMessage(role="assistant", content="contended")
                ],
                lease=turn.lease,
            )
        await contender_session.rollback()
        await holder_session.commit()

        await contender_session.begin()
        retried = await AIBuilderRepository(contender_session).append_session_messages(
            session_id=session_id,
            tenant_id=tenant_id,
            conversation=[ConversationMessage(role="assistant", content="retry")],
            lease=turn.lease,
        )
        await contender_session.commit()

    assert retried[-1].content == "retry"
    print(
        "conversation_aggregate_measurement "
        f"serialized_bytes={serialized_bytes} "
        f"jsonb_column_bytes={int(jsonb_column_bytes)} "
        f"jsonb_text_bytes={int(jsonb_text_bytes)} "
        f"first_wal_bytes={int(first_wal_bytes)} "
        f"rewrite_wal_bytes={int(second_wal_bytes)} "
        f"relation_growth_bytes={int(relation_after) - int(relation_before)} "
        f"toast_growth_bytes={int(toast_after) - int(toast_before)} "
        "lock_timeout_ms=100 retry=passed"
    )


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mark_processing", "expected_state"),
    [
        (False, "failed_before_provider"),
        (True, "provider_outcome_unknown"),
    ],
    ids=["open", "processing"],
)
async def test_ai_builder_detach_attachment_reconciles_expired_turn(
    client,
    bearer_token,
    db_container,
    mark_processing: bool,
    expected_state: str,
):
    space_id = await _create_space_via_api(
        client=client,
        bearer_token=bearer_token,
        name="AI Builder Expired Detach",
    )
    session_id = await _create_ai_builder_session(
        client=client,
        bearer_token=bearer_token,
        space_id=space_id,
    )
    file_id = await _upload_reference_file(
        client=client,
        bearer_token=bearer_token,
        filename=f"expired-{expected_state}.txt",
    )

    async with db_container() as container:
        session = container.session()
        user = container.user()
        await session.execute(
            insert(BuilderSessionFiles).values(
                session_id=UUID(session_id),
                file_id=UUID(file_id),
                tenant_id=user.tenant_id,
            )
        )
        turn = await _claim_session_send_turn(
            repo=AIBuilderRepository(session),
            session_id=UUID(session_id),
            tenant_id=user.tenant_id,
            lock_expires_at=datetime.now(timezone.utc) - timedelta(seconds=5),
        )
        if mark_processing:
            await AIBuilderRepository(session).mark_session_turn_processing(turn=turn)

    response = await client.delete(
        f"/api/v1/flows/ai-builder/sessions/{session_id}/attachments/{file_id}",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )

    assert response.status_code == 204, response.text
    async with db_container() as container:
        session = container.session()
        user = container.user()
        membership = await session.scalar(
            select(BuilderSessionFiles.file_id).where(
                BuilderSessionFiles.session_id == UUID(session_id),
                BuilderSessionFiles.file_id == UUID(file_id),
                BuilderSessionFiles.tenant_id == user.tenant_id,
            )
        )
        row = (
            await session.execute(
                select(
                    BuilderSessions.active_request_id,
                    BuilderSessions.lock_token,
                    BuilderSessions.locked_at,
                    BuilderSessions.lock_expires_at,
                    BuilderSessions.latest_turn_state,
                ).where(
                    BuilderSessions.id == UUID(session_id),
                    BuilderSessions.tenant_id == user.tenant_id,
                )
            )
        ).one()
        audit_event = (
            await session.execute(
                select(
                    AuditLogTable.actor_id,
                    AuditLogTable.entity_type,
                    AuditLogTable.entity_id,
                    AuditLogTable.log_metadata,
                ).where(
                    AuditLogTable.tenant_id == user.tenant_id,
                    AuditLogTable.action
                    == ActionType.AI_BUILDER_ATTACHMENT_DETACHED.value,
                    AuditLogTable.entity_id == UUID(session_id),
                )
            )
        ).one()

    assert membership is None
    assert tuple(row) == (None, None, None, None, expected_state)
    assert str(audit_event.actor_id) == audit_event.log_metadata["actor"]["id"]
    assert audit_event.entity_type == EntityType.AI_BUILDER_SESSION.value
    assert audit_event.entity_id == UUID(session_id)
    assert audit_event.log_metadata["target"]["id"] == session_id
    assert audit_event.log_metadata["extra"] == {"file_id": file_id}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_detach_attachment_rejects_live_turn_and_preserves_membership(
    client,
    bearer_token,
    db_container,
):
    space_id = await _create_space_via_api(
        client=client,
        bearer_token=bearer_token,
        name="AI Builder Live Detach",
    )
    session_id = await _create_ai_builder_session(
        client=client,
        bearer_token=bearer_token,
        space_id=space_id,
    )
    file_id = await _upload_reference_file(
        client=client,
        bearer_token=bearer_token,
        filename="live-turn.txt",
    )

    async with db_container() as container:
        session = container.session()
        user = container.user()
        await session.execute(
            insert(BuilderSessionFiles).values(
                session_id=UUID(session_id),
                file_id=UUID(file_id),
                tenant_id=user.tenant_id,
            )
        )
        turn = await _claim_session_send_turn(
            repo=AIBuilderRepository(session),
            session_id=UUID(session_id),
            tenant_id=user.tenant_id,
            lock_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        )

    response = await client.delete(
        f"/api/v1/flows/ai-builder/sessions/{session_id}/attachments/{file_id}",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "session_send_in_progress"
    async with db_container() as container:
        session = container.session()
        user = container.user()
        repo = AIBuilderRepository(session)
        membership = await session.scalar(
            select(BuilderSessionFiles.file_id).where(
                BuilderSessionFiles.session_id == UUID(session_id),
                BuilderSessionFiles.file_id == UUID(file_id),
                BuilderSessionFiles.tenant_id == user.tenant_id,
            )
        )
        lock = await _load_session_send_lock(
            repo,
            session_id=UUID(session_id),
            tenant_id=user.tenant_id,
        )
        state = await session.scalar(
            select(BuilderSessions.latest_turn_state).where(
                BuilderSessions.id == UUID(session_id),
                BuilderSessions.tenant_id == user.tenant_id,
            )
        )
        audit_count = await session.scalar(
            select(sa.func.count(AuditLogTable.id)).where(
                AuditLogTable.tenant_id == user.tenant_id,
                AuditLogTable.action == ActionType.AI_BUILDER_ATTACHMENT_DETACHED.value,
                AuditLogTable.entity_id == UUID(session_id),
            )
        )

    assert membership == UUID(file_id)
    assert lock[0] == turn.lease.request_id
    assert lock[1] == turn.lease.lock_token
    assert lock[2] is not None
    assert lock[3] is not None
    assert state == "open"
    assert audit_count == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cancel_applied_session_returns_typed_conflict_without_mutation(
    client,
    bearer_token,
    db_container,
):
    space_id = await _create_space_via_api(
        client=client,
        bearer_token=bearer_token,
        name="AI Builder Applied Cancel Rejection",
    )
    session_id = UUID(
        await _create_ai_builder_session(
            client=client,
            bearer_token=bearer_token,
            space_id=space_id,
        )
    )
    file_id = UUID(
        await _upload_reference_file(
            client=client,
            bearer_token=bearer_token,
            filename="applied-session-reference.txt",
        )
    )
    async with db_container() as container:
        session = container.session()
        tenant_id = container.user().tenant_id
        session_state_stmt = select(
            BuilderSessions.status,
            BuilderSessions.active_request_id,
            BuilderSessions.lock_token,
            BuilderSessions.locked_at,
            BuilderSessions.lock_expires_at,
            BuilderSessions.latest_turn_state,
        ).where(
            BuilderSessions.id == session_id,
            BuilderSessions.tenant_id == tenant_id,
        )
        attachment_stmt = select(BuilderSessionFiles.file_id).where(
            BuilderSessionFiles.session_id == session_id,
            BuilderSessionFiles.tenant_id == tenant_id,
        )
        await session.execute(
            insert(BuilderSessionFiles).values(
                session_id=session_id,
                file_id=file_id,
                tenant_id=tenant_id,
            )
        )
        await session.execute(
            update(BuilderSessions)
            .where(
                BuilderSessions.id == session_id,
                BuilderSessions.tenant_id == tenant_id,
            )
            .values(status=SessionStatus.APPLIED.value)
        )
        before_state = tuple((await session.execute(session_state_stmt)).one())
        before_attachments = tuple(
            (await session.execute(attachment_stmt)).scalars().all()
        )

    request_id = f"cancel-applied-{uuid4()}"
    response = await client.post(
        f"/api/v1/flows/ai-builder/sessions/{session_id}/cancel",
        headers={
            "Authorization": f"Bearer {bearer_token}",
            "X-Request-ID": request_id,
        },
    )

    assert response.status_code == 409, response.text
    error = AIBuilderPublicError.model_validate(response.json())
    assert error.code is AIBuilderErrorCode.INVALID_SESSION_TRANSITION
    assert error.category.value == "conflict"
    assert error.request_id == request_id

    async with db_container() as container:
        session = container.session()
        after_state = tuple((await session.execute(session_state_stmt)).one())
        after_attachments = tuple(
            (await session.execute(attachment_stmt)).scalars().all()
        )

    assert after_state == before_state
    assert after_attachments == before_attachments == (file_id,)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_cancel_session_clears_send_lock_fields(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Send Lock Cancel",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
        )

        await repo.cancel_session(session_id=session.id, tenant_id=user.tenant_id)

        assert await _load_session_send_lock(
            repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
        ) == (None, None, None, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_cancel_serializes_attachment_cleanup_with_turn_acceptance(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Cancel Attachment Serialization",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        existing_file_id, accepted_file_id = (
            (
                await container.session().execute(
                    insert(Files)
                    .values(
                        [
                            {
                                "name": "existing.txt",
                                "text": "existing",
                                "blob": None,
                                "checksum": uuid4().hex,
                                "size": 8,
                                "mimetype": "text/plain",
                                "file_type": "text",
                                "transcription": None,
                                "owner_type": "user",
                                "owner_user_id": user.id,
                                "owner_service_id": None,
                                "tenant_id": user.tenant_id,
                                "parent_file_id": None,
                            },
                            {
                                "name": "accepted.txt",
                                "text": "accepted",
                                "blob": None,
                                "checksum": uuid4().hex,
                                "size": 8,
                                "mimetype": "text/plain",
                                "file_type": "text",
                                "transcription": None,
                                "owner_type": "user",
                                "owner_user_id": user.id,
                                "owner_service_id": None,
                                "tenant_id": user.tenant_id,
                                "parent_file_id": None,
                            },
                        ]
                    )
                    .returning(Files.id)
                )
            )
            .scalars()
            .all()
        )
        await container.session().execute(
            insert(BuilderSessionFiles).values(
                session_id=session.id,
                file_id=existing_file_id,
                tenant_id=user.tenant_id,
            )
        )
        client_turn_id = uuid4()
        preflight = await repo.preflight_session_turn(
            session_id=session.id,
            tenant_id=user.tenant_id,
            client_turn_id=client_turn_id,
            request_fingerprint="a" * 64,
            acknowledge_duplicate_provider_spend=False,
        )
        tenant_id = user.tenant_id

    child_locked = asyncio.Event()
    release_child = asyncio.Event()

    async def hold_existing_membership() -> None:
        async with db_container() as container:
            await container.session().execute(
                select(BuilderSessionFiles.file_id)
                .where(
                    BuilderSessionFiles.session_id == session.id,
                    BuilderSessionFiles.file_id == existing_file_id,
                )
                .with_for_update()
            )
            child_locked.set()
            await release_child.wait()

    async def cancel() -> None:
        async with db_container() as container:
            repo = AIBuilderRepository(container.session())
            await repo.cancel_session(session_id=session.id, tenant_id=tenant_id)

    async def accept() -> None:
        async with db_container() as container:
            repo = AIBuilderRepository(container.session())
            message = ConversationMessage(role="user", content="Accept with file")
            await repo.accept_session_turn(
                session_id=session.id,
                tenant_id=tenant_id,
                lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
                lock_lease_seconds=30,
                acceptance=SessionTurnAcceptance(
                    client_turn_id=client_turn_id,
                    request_fingerprint="a" * 64,
                    request={
                        "client_turn_id": str(client_turn_id),
                        "message": message.content,
                        "file_ids": [str(accepted_file_id)],
                    },
                    user_message=message,
                    file_ids=(accepted_file_id,),
                ),
                preparation_baseline=preflight.baseline,
            )

    holder = asyncio.create_task(hold_existing_membership())
    await child_locked.wait()
    canceller = asyncio.create_task(cancel())
    await asyncio.sleep(0.1)
    accepter = asyncio.create_task(accept())
    try:
        await asyncio.sleep(0.2)
        assert not accepter.done()
    finally:
        release_child.set()
    await asyncio.wait_for(holder, timeout=5)
    await asyncio.wait_for(canceller, timeout=5)
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        await asyncio.wait_for(accepter, timeout=5)
    assert exc_info.value.code is AIBuilderErrorCode.INVALID_SESSION_TRANSITION

    async with db_container() as container:
        remaining_file_ids = (
            (
                await container.session().execute(
                    select(BuilderSessionFiles.file_id).where(
                        BuilderSessionFiles.session_id == session.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert remaining_file_ids == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_send_message_status_jump_under_lock_uses_lease(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    """The AWAITING_APPROVAL -> CHATTING send-message transition must be lease-guarded."""
    from eneo.flows.ai_builder.ai_builder_planner import AIBuilderPlanner
    from eneo.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy

    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Send Status Lease",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        await repo.update_session_status_without_send_lease(
            session_id=session.id,
            tenant_id=user.tenant_id,
            status=SessionStatus.AWAITING_APPROVAL,
        )
        original_update = repo.update_session_status

        async def lose_lease_before_status_update(**kwargs):
            now = datetime.now(timezone.utc)
            await repo.session.execute(
                update(BuilderSessions)
                .where(
                    BuilderSessions.id == kwargs["session_id"],
                    BuilderSessions.tenant_id == kwargs["tenant_id"],
                )
                .values(
                    active_request_id=uuid4(),
                    lock_token=uuid4(),
                    locked_at=now,
                    lock_expires_at=now + timedelta(seconds=30),
                )
            )
            await original_update(**kwargs)

        repo.update_session_status = lose_lease_before_status_update  # type: ignore[method-assign]
        planner = AIBuilderPlanner(
            user=user,
            repo=repo,
            litellm_client=AsyncMock(),
            quality_retry_warning_codes=set(),
        )
        client_turn_id = uuid4()

        with pytest.raises(BadRequestException) as exc:
            async for _ in planner.send_message(
                session_id=session.id,
                client_turn_id=client_turn_id,
                request_fingerprint="a" * 64,
                request_snapshot={
                    "client_turn_id": str(client_turn_id),
                    "message": "Bygg vidare.",
                    "ui_language": "sv",
                },
                message="Bygg vidare.",
                completion_model_route=_route(kwargs={"api_key": "sk-test"}),
                available_models=[],
                available_kbs=[],
                flow=None,
                assistant_snapshots=None,
                attachment_files=[],
                max_input_tokens=4096,
                max_output_tokens=512,
                budget_policy=AIBuilderBudgetPolicy(
                    conversation_safety_buffer_tokens=128,
                    minimum_conversation_budget_tokens=256,
                    unknown_model_context_window_tokens=8192,
                ),
            ):
                pass

    assert exc.value.code == "session_send_lease_lost"

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        fetched = await repo.get_session(
            session_id=session.id, tenant_id=user.tenant_id
        )

    assert fetched.status == SessionStatus.AWAITING_APPROVAL
    assert [message.content for message in fetched.conversation] == ["Bygg vidare."]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_create_plan_rejects_cross_tenant_session_reference(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Cross Tenant Plan",
    )
    other_tenant_id = await _create_extra_tenant(
        db_container=db_container,
        name=f"other-tenant-{uuid4()}",
    )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        spec = _make_builder_plan_spec(existing_step_ref=None)

        with pytest.raises(IntegrityError):
            await repo.create_plan(
                session_id=session.id,
                tenant_id=other_tenant_id,
                proposal=FlowBuilderProposal(
                    content=FlowBuilderProposalContent(spec=spec),
                ),
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_create_session_rejects_cross_tenant_flow_reference(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Cross Tenant Flow",
    )
    other_tenant_id = await _create_extra_tenant(
        db_container=db_container,
        name=f"other-tenant-{uuid4()}",
    )
    _other_space_id, other_flow_id = await _create_space_and_flow_for_tenant(
        db_container=db_container,
        tenant_id=other_tenant_id,
        owner_user_id=None,
        name_prefix=f"other-{uuid4()}",
    )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()

        with pytest.raises(IntegrityError):
            await repo.create_session(
                tenant_id=user.tenant_id,
                space_id=UUID(space_id),
                actor_user_id=user.id,
                target_kind=TargetKind.EDIT,
                flow_id=other_flow_id,
            )


def _planning_state_fixture() -> PlanningState:
    return PlanningState(
        fcm_version=FCM_VERSION,
        planner_contract_version=PLANNER_CONTRACT_VERSION,
        builder_schema_version=BUILDER_SCHEMA_VERSION,
        resolved_slots={
            "primary_runtime_input": ResolvedSlot(
                name="primary_runtime_input",
                value="documents",
                source="heuristic",
                evidence=["heuristic:role-aware freeform analysis"],
                confidence="medium",
            )
        },
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_save_planning_state_explicit_administrative_replace(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Planning Save Version",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        state = _planning_state_fixture()

        first = await repo.save_planning_state(
            session_id=session.id,
            tenant_id=user.tenant_id,
            state=state,
            base_version=None,
        )
        second = await repo.save_planning_state(
            session_id=session.id,
            tenant_id=user.tenant_id,
            state=state,
            base_version=None,
        )

    assert first == 1
    assert second == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_save_planning_state_rejects_stale_base_version(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    """Optimistic concurrency: two writers can both observe version N
    and build their own updates. Only one can land; the other's save
    with `base_version=N` must fail because the row is now at N+1. The
    winning writer commits; the losing writer retries with the fresh
    version instead of silently clobbering the newer snapshot.
    """
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Planning Optimistic Concurrency",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        session_id = session.id
        tenant_id = user.tenant_id

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        first = await repo.save_planning_state(
            session_id=session_id,
            tenant_id=tenant_id,
            state=_planning_state_fixture(),
            base_version=0,
        )
    assert first == 1

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        with pytest.raises(BadRequestException) as exc:
            await repo.save_planning_state(
                session_id=session_id,
                tenant_id=tenant_id,
                state=_planning_state_fixture(),
                base_version=0,
            )
    assert exc.value.code == "planning_state_version_mismatch"

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        third = await repo.save_planning_state(
            session_id=session_id,
            tenant_id=tenant_id,
            state=_planning_state_fixture(),
            base_version=1,
        )
    assert third == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_load_planning_state_returns_none_for_unsaved_session(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Planning Load Unsaved",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )

        loaded = await repo.load_planning_state(
            session_id=session.id,
            tenant_id=user.tenant_id,
        )

    assert loaded is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_load_planning_state_round_trips_saved_state(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Planning Round Trip",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        state = _planning_state_fixture()
        await repo.save_planning_state(
            session_id=session.id,
            tenant_id=user.tenant_id,
            state=state,
            base_version=None,
        )

        loaded = await repo.load_planning_state(
            session_id=session.id,
            tenant_id=user.tenant_id,
        )

    assert loaded == state.validated_snapshot()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_planning_state_round_trip_byte_identical(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    """load → no-op re-save → reload must produce a byte-identical
    serialized payload modulo the version bump. This pins the
    full-snapshot discipline: save cannot silently reshape the JSONB.
    """
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Planning Byte Identical",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        session_id = session.id
        tenant_id = user.tenant_id
        await repo.save_planning_state(
            session_id=session_id,
            tenant_id=tenant_id,
            state=_planning_state_fixture(),
            base_version=None,
        )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        first_loaded = await repo.load_planning_state(
            session_id=session_id, tenant_id=tenant_id
        )
        first_version = (
            await repo.session.execute(
                select(BuilderSessions.planning_state_version).where(
                    BuilderSessions.id == session_id
                )
            )
        ).scalar_one()

    assert first_loaded is not None
    first_payload = first_loaded.model_dump(mode="json")

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        await repo.save_planning_state(
            session_id=session_id,
            tenant_id=tenant_id,
            state=first_loaded,
            base_version=None,
        )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        second_loaded = await repo.load_planning_state(
            session_id=session_id, tenant_id=tenant_id
        )
        second_version = (
            await repo.session.execute(
                select(BuilderSessions.planning_state_version).where(
                    BuilderSessions.id == session_id
                )
            )
        ).scalar_one()

    assert second_loaded is not None
    assert second_loaded.model_dump(mode="json") == first_payload
    assert second_version == first_version + 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_load_planning_state_raises_for_missing_session(
    db_container,
):
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())

        with pytest.raises(NotFoundException):
            await repo.load_planning_state(
                session_id=uuid4(),
                tenant_id=uuid4(),
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_save_planning_state_raises_for_wrong_tenant(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Planning Wrong Tenant",
    )
    other_tenant_id = await _create_extra_tenant(
        db_container=db_container,
        name=f"planning-other-tenant-{uuid4()}",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        state = _planning_state_fixture()

        with pytest.raises(NotFoundException):
            await repo.save_planning_state(
                session_id=session.id,
                tenant_id=other_tenant_id,
                state=state,
                base_version=None,
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_commit_turn_persists_conversation_and_planning_state(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Commit Turn Happy",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        assistant_msg = ConversationMessage(role="assistant", content="Hej")
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
        )

        await repo.commit_turn(
            turn=turn,
            new_messages=[assistant_msg],
        )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        fetched = await repo.get_session(
            session_id=session.id, tenant_id=user.tenant_id
        )
        loaded = await repo.load_planning_state(
            session_id=session.id, tenant_id=user.tenant_id
        )

    assert [(message.role, message.content) for message in fetched.conversation] == [
        ("user", "Accepted turn"),
        ("assistant", "Hej"),
    ]
    assert loaded is not None
    assert loaded.resolved_slots == {}
    assert "evidence" not in loaded.model_dump(mode="json")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_commit_turn_rolls_back_when_planning_state_drifts(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Commit Turn Rollback",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        assistant_msg = ConversationMessage(
            role="assistant", content="Should roll back"
        )
        drifted = _planning_state_fixture()
        # Bypass Pydantic's field validator to simulate post-construction
        # container-level drift. validated_snapshot() inside commit_turn
        # must catch this and roll back the conversation append.
        drifted.signals.append("not a signal")  # type: ignore[arg-type]
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
        )

        with patch(
            "eneo.flows.ai_builder.ai_builder_repo.build_planning_state_from_conversation",
            return_value=drifted,
        ):
            with pytest.raises(Exception):
                await repo.commit_turn(
                    turn=turn,
                    new_messages=[assistant_msg],
                )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        fetched = await repo.get_session(
            session_id=session.id, tenant_id=user.tenant_id
        )

    assert [message.content for message in fetched.conversation] == ["Accepted turn"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_commit_turn_rejects_write_when_lease_is_lost(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    """Lease-lost guard: commit_turn must reject the write when the
    caller's request_id/lock_token no longer matches the row's lease.
    Otherwise a reclaimed session could land a stale planner turn on top
    of another worker's active commit.
    """
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Commit Turn Lease",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        active_lease = SessionSendLease(request_id=uuid4(), lock_token=uuid4())
        await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
            lease=active_lease,
            lock_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        )
        stale_turn = _make_session_send_turn(
            session_id=session.id,
            tenant_id=user.tenant_id,
            base_planning_state_version=0,
        )
        assistant_msg = ConversationMessage(role="assistant", content="Stale lease")

        with pytest.raises(BadRequestException):
            await repo.commit_turn(
                turn=stale_turn,
                new_messages=[assistant_msg],
            )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        fetched = await repo.get_session(
            session_id=session.id, tenant_id=user.tenant_id
        )
        loaded = await repo.load_planning_state(
            session_id=session.id, tenant_id=user.tenant_id
        )

    assert [message.content for message in fetched.conversation] == ["Accepted turn"]
    assert loaded is None


def _architecture_commit_fixture() -> ArchitectureCommit:
    return ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=["input_text", "output_mode_pass_through"],
        committed_at=datetime(2026, 4, 23, tzinfo=timezone.utc),
        architecture_hash="c" * 64,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_commit_turn_persists_architecture_commit_atomically(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    """commit_turn must stamp a planner-supplied architecture_commit on
    the persisted PlanningState, inside the same savepoint as the
    conversation append. A later load sees the commit exactly as
    provided.
    """
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Commit Turn Architecture Commit",
    )
    commit = _architecture_commit_fixture()
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        assistant_msg = ConversationMessage(
            role="assistant", content="Commit the architecture"
        )
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
        )

        await repo.commit_turn(
            turn=turn,
            new_messages=[assistant_msg],
            architecture_commit=commit,
        )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        loaded = await repo.load_planning_state(
            session_id=session.id, tenant_id=user.tenant_id
        )

    assert loaded is not None
    assert loaded.architecture_commit is not None
    assert loaded.architecture_commit.architecture_hash == commit.architecture_hash
    assert loaded.architecture_commit.chosen_patterns == commit.chosen_patterns
    assert (
        loaded.architecture_commit.required_capabilities == commit.required_capabilities
    )
    assert [
        (t.input_type, t.output_type, t.output_mode)
        for t in loaded.architecture_commit.tuples_chain
    ] == [("text", "text", "pass_through")]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_commit_turn_rolls_back_architecture_commit_on_drift(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    """If the planning-state validation inside the savepoint fails, the
    architecture_commit must roll back alongside the conversation
    append — never landing as a partial half-write.
    """
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Commit Turn Architecture Commit Rollback",
    )
    commit = _architecture_commit_fixture()
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        assistant_msg = ConversationMessage(
            role="assistant", content="Should roll back"
        )
        drifted = _planning_state_fixture()
        drifted.signals.append("not a signal")  # type: ignore[arg-type]
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
        )

        with patch(
            "eneo.flows.ai_builder.ai_builder_repo.build_planning_state_from_conversation",
            return_value=drifted,
        ):
            with pytest.raises(ValidationError):
                await repo.commit_turn(
                    turn=turn,
                    new_messages=[assistant_msg],
                    architecture_commit=commit,
                )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        fetched = await repo.get_session(
            session_id=session.id, tenant_id=user.tenant_id
        )
        loaded = await repo.load_planning_state(
            session_id=session.id, tenant_id=user.tenant_id
        )

    assert [message.content for message in fetched.conversation] == ["Accepted turn"]
    assert loaded is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_commit_turn_preserves_previously_persisted_architecture_commit(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    """Once a commit is persisted, a later `commit_turn` that does
    NOT pass the `architecture_commit` kwarg must carry it forward.
    `build_planning_state_from_conversation` seeds only the
    deterministic slot surface and returns `architecture_commit=None`;
    without preservation every later turn would erase the commit.
    """
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Commit Turn Preserve Commit",
    )
    commit = _architecture_commit_fixture()
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
        )
        next_version = await repo.commit_turn(
            turn=turn,
            new_messages=[
                ConversationMessage(role="assistant", content="commit turn 1")
            ],
            architecture_commit=commit,
        )
        await repo.commit_turn(
            turn=replace(turn, base_planning_state_version=next_version),
            new_messages=[
                ConversationMessage(role="assistant", content="commit turn 2")
            ],
        )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        loaded = await repo.load_planning_state(
            session_id=session.id, tenant_id=user.tenant_id
        )

    assert loaded is not None
    assert loaded.architecture_commit is not None
    assert loaded.architecture_commit.architecture_hash == commit.architecture_hash


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_commit_turn_replaces_persisted_commit_when_kwarg_explicit(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    """Explicit replacement still works: a second `commit_turn` that
    passes its own `architecture_commit` overrides the previously
    persisted one. Preservation applies only when the kwarg is None.
    """
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Commit Turn Replace Commit",
    )
    first = _architecture_commit_fixture()
    second = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            ),
            StepTriple(
                input_type="text",
                output_type="json",
                output_mode="pass_through",
            ),
        ],
        chosen_patterns=["extract_structured_fields"],
        required_capabilities=["input_text", "output_mode_pass_through"],
        committed_at=datetime(2026, 4, 23, tzinfo=timezone.utc),
        architecture_hash="d" * 64,
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
        )
        next_version = await repo.commit_turn(
            turn=turn,
            new_messages=[
                ConversationMessage(role="assistant", content="first commit")
            ],
            architecture_commit=first,
        )
        await repo.commit_turn(
            turn=replace(turn, base_planning_state_version=next_version),
            new_messages=[
                ConversationMessage(role="assistant", content="second commit")
            ],
            architecture_commit=second,
        )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        loaded = await repo.load_planning_state(
            session_id=session.id, tenant_id=user.tenant_id
        )

    assert loaded is not None
    assert loaded.architecture_commit is not None
    assert loaded.architecture_commit.architecture_hash == second.architecture_hash
    assert len(loaded.architecture_commit.tuples_chain) == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_plan_and_update_conversation_rejects_stale_planning_state_version_and_rolls_back(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    """A stale proposal save must fail CAS and leave the savepoint untouched."""
    from eneo.flows.ai_builder.ai_builder_plan_store import (
        store_plan_and_update_conversation,
    )

    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Plan Proposal Stale CAS",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        session_id = session.id
        tenant_id = user.tenant_id
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session_id,
            tenant_id=tenant_id,
        )

    concurrent_state = _planning_state_fixture()
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        advanced_version = await repo.save_planning_state(
            session_id=session_id,
            tenant_id=tenant_id,
            state=concurrent_state,
            base_version=0,
        )
    assert advanced_version == 1

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        with pytest.raises(BadRequestException) as exc:
            await store_plan_and_update_conversation(
                repo=repo,
                turn=turn,
                conversation=[],
                new_messages_start=0,
                assistant_content="stale plan ready",
                tool_call_id="call-stale-1",
                tool_name=PROPOSE_FLOW_TOOL_NAME,
                arguments={},
                compiled=_compiled_builder_plan(
                    _make_builder_plan_spec(existing_step_ref=None)
                ),
                flow=None,
            )

    assert exc.value.code == "planning_state_version_mismatch"

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        plans = await repo.list_session_plans(
            session_id=session_id, tenant_id=tenant_id
        )
        fetched = await repo.get_session(session_id=session_id, tenant_id=tenant_id)
        loaded_state = await repo.load_planning_state(
            session_id=session_id, tenant_id=tenant_id
        )
        version = (
            await repo.session.execute(
                select(BuilderSessions.planning_state_version).where(
                    BuilderSessions.id == session_id
                )
            )
        ).scalar_one()

    assert plans == []
    assert fetched.latest_plan_id is None
    assert fetched.status == SessionStatus.CHATTING
    assert [message.content for message in fetched.conversation] == ["Accepted turn"]
    assert version == 1
    assert loaded_state is not None
    assert loaded_state.resolved_slots["primary_runtime_input"].value == "documents"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_plan_and_update_conversation_rejects_lost_session_send_lease_and_rolls_back(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    """Proposal storage must not create a plan if the active send lease is lost."""
    from eneo.flows.ai_builder.ai_builder_plan_store import (
        store_plan_and_update_conversation,
    )

    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Plan Proposal Lost Lease",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        session_id = session.id
        tenant_id = user.tenant_id
        await _claim_session_send_turn(
            repo=repo,
            session_id=session_id,
            tenant_id=tenant_id,
        )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        stale_turn = _make_session_send_turn(
            session_id=session_id,
            tenant_id=tenant_id,
            base_planning_state_version=0,
        )
        with pytest.raises(BadRequestException) as exc:
            await store_plan_and_update_conversation(
                repo=repo,
                turn=stale_turn,
                conversation=[],
                new_messages_start=0,
                assistant_content="lost lease plan",
                tool_call_id="call-lost-lease-1",
                tool_name=PROPOSE_FLOW_TOOL_NAME,
                arguments={},
                compiled=_compiled_builder_plan(
                    _make_builder_plan_spec(existing_step_ref=None)
                ),
                flow=None,
            )

    assert exc.value.code == "session_send_lease_lost"

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        plans = await repo.list_session_plans(
            session_id=session_id, tenant_id=tenant_id
        )
        fetched = await repo.get_session(session_id=session_id, tenant_id=tenant_id)
        loaded_state = await repo.load_planning_state(
            session_id=session_id, tenant_id=tenant_id
        )

    assert plans == []
    assert fetched.latest_plan_id is None
    assert [message.content for message in fetched.conversation] == ["Accepted turn"]
    assert loaded_state is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_server_requirements_confirmation_with_lost_lease_rolls_back(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    """Server-owned requirements persistence must reject a stale active-turn lease."""
    from eneo.flows.ai_builder.ai_builder_server_decision_dispatch import (
        ServerDecisionDispatchRequest,
        ServerDecisionTelemetry,
        dispatch_server_decision,
    )
    from eneo.flows.ai_builder.ai_builder_turn_controller import (
        ConfirmRequirements,
    )

    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Confirm Requirements Lost Lease",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        session_id = session.id
        tenant_id = user.tenant_id
        await _claim_session_send_turn(
            repo=repo,
            session_id=session_id,
            tenant_id=tenant_id,
        )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        stale_turn = _make_session_send_turn(
            session_id=session_id,
            tenant_id=tenant_id,
            base_planning_state_version=0,
        )
        with pytest.raises(BadRequestException) as exc:
            await dispatch_server_decision(
                ServerDecisionDispatchRequest(
                    repo=repo,
                    turn=stale_turn,
                    decision=ConfirmRequirements(
                        payload=RequirementsSummaryPayload(
                            summary="Bygg ett textflöde.",
                            key_decisions=[],
                            input_description="Användaren skriver text.",
                            output_description="Flödet svarar med text.",
                        )
                    ),
                    conversation=[],
                    new_messages_start=0,
                    flow=None,
                    requirements_confirmed=False,
                    ui_language="sv",
                    telemetry=ServerDecisionTelemetry(
                        request_id="req-requirements-lost-lease",
                        litellm_model="server",
                        used_auxiliary_llm=False,
                    ),
                    planning_state=PlanningState.empty(),
                )
            )

    assert exc.value.code == "session_send_lease_lost"

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        fetched = await repo.get_session(session_id=session_id, tenant_id=tenant_id)
        loaded_state = await repo.load_planning_state(
            session_id=session_id, tenant_id=tenant_id
        )

    assert [message.content for message in fetched.conversation] == ["Accepted turn"]
    assert loaded_state is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_server_question_with_lost_lease_rolls_back(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    """Server-owned backend questions must reject a stale active-turn lease."""
    from eneo.flows.ai_builder.ai_builder_server_decision_dispatch import (
        ServerDecisionDispatchRequest,
        ServerDecisionTelemetry,
        dispatch_server_decision,
    )
    from eneo.flows.ai_builder.ai_builder_turn_controller import (
        AskCanonicalQuestion,
    )

    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Structured Question Lost Lease",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        session_id = session.id
        tenant_id = user.tenant_id
        await _claim_session_send_turn(
            repo=repo,
            session_id=session_id,
            tenant_id=tenant_id,
        )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        stale_turn = _make_session_send_turn(
            session_id=session_id,
            tenant_id=tenant_id,
            base_planning_state_version=0,
        )
        with pytest.raises(BadRequestException) as exc:
            await dispatch_server_decision(
                ServerDecisionDispatchRequest(
                    repo=repo,
                    turn=stale_turn,
                    decision=AskCanonicalQuestion(
                        slot_name="primary_runtime_input",
                        prompt="Vilken indata ska flödet använda?",
                    ),
                    conversation=[],
                    new_messages_start=0,
                    flow=None,
                    requirements_confirmed=False,
                    ui_language="sv",
                    telemetry=ServerDecisionTelemetry(
                        request_id="req-question-lost-lease",
                        litellm_model="server",
                        used_auxiliary_llm=False,
                    ),
                    planning_state=PlanningState.empty(),
                )
            )

    assert exc.value.code == "session_send_lease_lost"

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        fetched = await repo.get_session(session_id=session_id, tenant_id=tenant_id)
        loaded_state = await repo.load_planning_state(
            session_id=session_id, tenant_id=tenant_id
        )

    assert [message.content for message in fetched.conversation] == ["Accepted turn"]
    assert loaded_state is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_handle_edit_flow_with_lost_lease_rolls_back(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
    space_factory,
    admin_user,
):
    """Edit proposal storage must roll back if the active send lease is stale."""
    from eneo.flows.ai_builder.ai_builder_proposal_processor import (
        AIBuilderProposalProcessor,
    )
    from eneo.flows.ai_builder.ai_builder_resource_catalog import (
        build_ai_builder_resource_catalog,
    )

    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session,
            "AI Builder edit_flow lost lease",
            [model.id],
            user_id=admin_user.id,
        )
        flow_service = container.flow_service()
        flow = await flow_service.create_flow(
            space_id=space.id,
            name="Beslutsunderlag",
            description="Skapar ett kort beslutsunderlag.",
            steps=[],
        )
        repo = AIBuilderRepository(session)
        builder_session = await repo.create_session(
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            actor_user_id=admin_user.id,
            target_kind=TargetKind.EDIT,
            flow_id=flow.id,
        )
        session_id = builder_session.id
        tenant_id = admin_user.tenant_id
        await _claim_session_send_turn(
            repo=repo,
            session_id=session_id,
            tenant_id=tenant_id,
        )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        edit_flow_call = _make_tool_call(
            tool_call_id="call-edit-lost-lease",
            name=PROPOSE_FLOW_TOOL_NAME,
            arguments={
                "plan_rationale": "Lägg till ett textsammanfattningssteg.",
                "steps": [
                    {
                        "kind": "add",
                        "step": {
                            "name": "Sammanfatta text",
                            "instructions": "Sammanfatta användarens text.",
                            "output_type": "text",
                        },
                    }
                ],
            },
        )
        litellm_client = AsyncMock()
        litellm_client.acompletion = AsyncMock(
            return_value=_make_llm_response(tool_calls=[edit_flow_call])
        )
        processor = AIBuilderProposalProcessor(
            user=user,
            repo=repo,
            litellm_client=litellm_client,
            self_correction_temperature=0.2,
            self_correction_bumped_temperature=0.5,
            forced_proposal_temperature=0.3,
            quality_retry_warning_codes=set(),
        )
        stale_turn = _make_session_send_turn(
            session_id=session_id,
            tenant_id=tenant_id,
            base_planning_state_version=0,
        )

        async def mark_provider_work_started() -> None:
            await repo.mark_session_turn_processing(turn=stale_turn)

        resource_catalog = build_ai_builder_resource_catalog(
            available_models=[],
            available_kbs=[],
        )
        with pytest.raises(BadRequestException) as exc:
            _ = [
                event
                async for event in processor.propose_plan(
                    turn=stale_turn,
                    conversation=[],
                    new_messages_start=0,
                    llm_messages=[],
                    completion_model_route=_route(kwargs={"api_key": "sk-test"}),
                    available_model_refs=None,
                    available_kb_refs=None,
                    resource_catalog=resource_catalog,
                    max_output_tokens=512,
                    proposal_temperature=0.3,
                    request_id="req-edit-lost-lease",
                    flow=flow,
                    assistant_snapshots=None,
                    before_provider_call=mark_provider_work_started,
                )
            ]

    assert exc.value.code == "session_send_lease_lost"
    litellm_client.acompletion.assert_not_awaited()

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        plans = await repo.list_session_plans(
            session_id=session_id, tenant_id=tenant_id
        )
        fetched = await repo.get_session(session_id=session_id, tenant_id=tenant_id)
        loaded_state = await repo.load_planning_state(
            session_id=session_id, tenant_id=tenant_id
        )

    assert plans == []
    assert fetched.latest_plan_id is None
    assert [message.content for message in fetched.conversation] == ["Accepted turn"]
    assert loaded_state is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_plan_and_update_conversation_accepts_matching_planning_state_version(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    from eneo.flows.ai_builder.ai_builder_plan_store import (
        store_plan_and_update_conversation,
    )

    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Plan Proposal Matching CAS",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        session_id = session.id
        tenant_id = user.tenant_id

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session_id,
            tenant_id=tenant_id,
        )
        stored_plan = await store_plan_and_update_conversation(
            repo=repo,
            turn=turn,
            conversation=[],
            new_messages_start=0,
            assistant_content="plan ready",
            tool_call_id="call-match-1",
            tool_name=PROPOSE_FLOW_TOOL_NAME,
            arguments={},
            compiled=_compiled_builder_plan(
                _make_builder_plan_spec(existing_step_ref=None)
            ),
            flow=None,
        )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        fetched = await repo.get_session(session_id=session_id, tenant_id=tenant_id)
        loaded_state = await repo.load_planning_state(
            session_id=session_id, tenant_id=tenant_id
        )
        version = (
            await repo.session.execute(
                select(BuilderSessions.planning_state_version).where(
                    BuilderSessions.id == session_id
                )
            )
        ).scalar_one()

    assert fetched.latest_plan_id == stored_plan.plan.id
    assert loaded_state is not None
    assert "phase" not in loaded_state.model_dump(mode="json")
    assert version == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_plan_and_update_conversation_preserves_persisted_architecture_commit(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    """When the planner proposes a plan after a prior commit has
    landed, the save path inside `store_plan_and_update_conversation`
    must carry the persisted architecture_commit forward. Otherwise
    the proposal save erases the commit that gated it.
    """
    from eneo.flows.ai_builder.ai_builder_plan_store import (
        store_plan_and_update_conversation,
    )

    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Plan Store Preserve Commit",
    )
    commit = _architecture_commit_fixture()
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
        )
        await repo.commit_turn(
            turn=turn,
            new_messages=[
                ConversationMessage(role="user", content="user prompt"),
                ConversationMessage(role="assistant", content="architecture committed"),
            ],
            architecture_commit=commit,
        )

        fetched = await repo.get_session(
            session_id=session.id, tenant_id=user.tenant_id
        )
        working_conversation = list(fetched.conversation)

        spec = FlowDraftSpecCore(
            flow_name="Example",
            flow_description="desc",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    existing_step_ref=None,
                    name="Step A",
                    assistant_spec=AssistantSpec(instructions="Summarize."),
                    input_source=InputSource.FLOW_INPUT,
                    input_type=InputType.TEXT,
                    output_mode=OutputMode.PASS_THROUGH,
                    output_type=OutputType.TEXT,
                )
            ],
        )
        stored_plan = await store_plan_and_update_conversation(
            repo=repo,
            turn=replace(
                turn,
                base_planning_state_version=fetched.planning_state_version,
            ),
            conversation=working_conversation,
            new_messages_start=len(working_conversation),
            assistant_content="Here is the plan",
            assistant_metadata=None,
            tool_call_id="call_plan",
            tool_name="propose_plan",
            arguments={},
            compiled=_compiled_builder_plan(spec),
        )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        fetched = await repo.get_session(
            session_id=session.id, tenant_id=user.tenant_id
        )
        loaded = await repo.load_planning_state(
            session_id=session.id, tenant_id=user.tenant_id
        )

    assert fetched.latest_plan_id == stored_plan.plan.id
    assert loaded is not None
    assert loaded.architecture_commit is not None
    assert loaded.architecture_commit.architecture_hash == commit.architecture_hash


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_plan_and_update_conversation_rolls_back_when_append_fails(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    """store_plan_and_update_conversation must roll back every repo
    write as one unit: if the conversation append fails after the plan
    writes succeed, there must be no orphaned plan row and the session
    must remain in its pre-turn state.
    """
    from eneo.flows.ai_builder.ai_builder_plan_store import (
        store_plan_and_update_conversation,
    )

    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Plan Proposal Rollback",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        session_id = session.id
        tenant_id = user.tenant_id

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        spec = _make_builder_plan_spec(existing_step_ref=None)
        original_append = repo.append_session_messages
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session_id,
            tenant_id=tenant_id,
        )

        async def raising_append(*args: object, **kwargs: object) -> None:
            raise RuntimeError("simulated append failure")

        repo.append_session_messages = raising_append  # type: ignore[method-assign]
        try:
            with pytest.raises(RuntimeError):
                await store_plan_and_update_conversation(
                    repo=repo,
                    turn=turn,
                    conversation=[],
                    new_messages_start=0,
                    assistant_content="simulated",
                    tool_call_id="call-1",
                    tool_name=PROPOSE_FLOW_TOOL_NAME,
                    arguments={},
                    compiled=_compiled_builder_plan(spec),
                )
        finally:
            repo.append_session_messages = original_append  # type: ignore[method-assign]

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        plans = await repo.list_session_plans(
            session_id=session_id, tenant_id=tenant_id
        )
        fetched = await repo.get_session(session_id=session_id, tenant_id=tenant_id)
        loaded_state = await repo.load_planning_state(
            session_id=session_id, tenant_id=tenant_id
        )

    assert plans == []
    assert fetched.status == SessionStatus.CHATTING
    assert fetched.latest_plan_id is None
    assert loaded_state is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_plan_and_update_conversation_saves_planning_state(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    """The plan-proposal path must save a fresh PlanningState snapshot
    alongside the plan writes so the next turn reads a coherent state.
    """
    from eneo.flows.ai_builder.ai_builder_plan_store import (
        store_plan_and_update_conversation,
    )

    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Plan Proposal Planning State",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        session_id = session.id
        tenant_id = user.tenant_id

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        spec = _make_builder_plan_spec(existing_step_ref=None)
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session_id,
            tenant_id=tenant_id,
        )
        stored_plan = await store_plan_and_update_conversation(
            repo=repo,
            turn=turn,
            conversation=[],
            new_messages_start=0,
            assistant_content="plan ready",
            tool_call_id="call-ps-1",
            tool_name=PROPOSE_FLOW_TOOL_NAME,
            arguments={},
            compiled=_compiled_builder_plan(spec),
            flow=None,
        )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        plans = await repo.list_session_plans(
            session_id=session_id, tenant_id=tenant_id
        )
        fetched = await repo.get_session(session_id=session_id, tenant_id=tenant_id)
        loaded_state = await repo.load_planning_state(
            session_id=session_id, tenant_id=tenant_id
        )

    assert len(plans) == 1
    assert fetched.latest_plan_id == stored_plan.plan.id
    assert loaded_state is not None
    assert loaded_state.planner_contract_version == PLANNER_CONTRACT_VERSION
    assert "evidence" not in loaded_state.model_dump(mode="json")
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        stmt = select(BuilderSessions.planning_state_version).where(
            BuilderSessions.id == session_id
        )
        version = (await repo.session.execute(stmt)).scalar_one()
    assert version == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_plan_and_update_conversation_updates_latest_plan_pointer(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    """After the plan-proposal path persists a plan, the session's
    `latest_plan_id` is the canonical plan identity; PlanningState does
    not duplicate plan lifecycle.
    """
    from eneo.flows.ai_builder.ai_builder_plan_store import (
        store_plan_and_update_conversation,
    )

    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Plan Proposal Plan Identity Stamp",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        session_id = session.id
        tenant_id = user.tenant_id

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        spec = _make_builder_plan_spec(existing_step_ref=None)
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session_id,
            tenant_id=tenant_id,
        )
        stored_plan = await store_plan_and_update_conversation(
            repo=repo,
            turn=turn,
            conversation=[],
            new_messages_start=0,
            assistant_content="plan ready",
            tool_call_id="call-identity-1",
            tool_name=PROPOSE_FLOW_TOOL_NAME,
            arguments={},
            compiled=_compiled_builder_plan(spec),
            flow=None,
        )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        fetched = await repo.get_session(session_id=session_id, tenant_id=tenant_id)
        loaded_state = await repo.load_planning_state(
            session_id=session_id, tenant_id=tenant_id
        )

    assert fetched.latest_plan_id == stored_plan.plan.id
    assert loaded_state is not None
    assert "phase" not in loaded_state.model_dump(mode="json")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_plan_and_update_conversation_state_matches_compacted_conversation(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    """Long sessions hit the compaction threshold: the persisted
    conversation is shorter than the caller's in-memory list. The saved
    PlanningState must still be derived from the compacted, persisted
    conversation that the next turn reads.
    """
    from eneo.flows.ai_builder.ai_builder_conversation_compaction import (
        MAX_SESSION_MESSAGES,
    )
    from eneo.flows.ai_builder.ai_builder_plan_store import (
        store_plan_and_update_conversation,
    )

    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Plan Proposal Compaction",
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=UUID(space_id),
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        session_id = session.id
        tenant_id = user.tenant_id

    pre_compaction_conversation = [
        ConversationMessage(role="user", content=f"filler {index}")
        for index in range(MAX_SESSION_MESSAGES + 5)
    ]
    pre_compaction_conversation[-1] = ConversationMessage(
        role="user",
        content="Skapa ett flöde som tar emot text och returnerar JSON.",
    )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        spec = _make_builder_plan_spec(existing_step_ref=None)
        turn = await _claim_session_send_turn(
            repo=repo,
            session_id=session_id,
            tenant_id=tenant_id,
        )
        await store_plan_and_update_conversation(
            repo=repo,
            turn=turn,
            conversation=list(pre_compaction_conversation),
            new_messages_start=0,
            assistant_content="plan ready",
            tool_call_id="call-cmp-1",
            tool_name=PROPOSE_FLOW_TOOL_NAME,
            arguments={},
            compiled=_compiled_builder_plan(spec),
            flow=None,
        )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        fetched = await repo.get_session(session_id=session_id, tenant_id=tenant_id)
        loaded_state = await repo.load_planning_state(
            session_id=session_id, tenant_id=tenant_id
        )

    assert len(fetched.conversation) <= MAX_SESSION_MESSAGES
    assert len(fetched.conversation) < len(pre_compaction_conversation) + 2
    assert loaded_state is not None
    assert loaded_state.resolved_slots["primary_runtime_input"].value == "text"
    assert loaded_state.resolved_slots["terminal_output"].value == "structured_json"


async def _get_latest_plan_id(*, client, bearer_token: str, session_id: str) -> str:
    response = await client.get(
        f"/api/v1/flows/ai-builder/sessions/{session_id}/plans",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 200, response.text
    plans = response.json()["plans"]
    assert plans, response.text
    return plans[0]["plan_id"]


async def _progress_builder_session_to_plan(
    *,
    client,
    bearer_token: str,
    session_id: str,
    initial_message: str,
    structured_answers: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    message = initial_message
    question_answer: dict[str, object] | None = None
    answers = structured_answers or {}

    for _ in range(6):
        events = await _send_builder_message(
            client=client,
            bearer_token=bearer_token,
            session_id=session_id,
            message=message,
            question_answer=question_answer,
        )
        if any(event["event"] == "plan" for event in events):
            return events

        requirements_event = next(
            (event for event in events if event["event"] == "requirements_summary"),
            None,
        )
        if requirements_event is not None:
            message = "Ja, det stämmer. Bygg planen."
            question_answer = {
                "requirements_confirmed": True,
                "requirements_version": requirements_event["data"][
                    "requirements_version"
                ],
                "ui_language": "sv",
            }
            continue

        question_event = next(
            (event for event in events if event["event"] == "question"), None
        )
        assert question_event is not None, events

        question_id = question_event["data"]["question_id"]
        selected_option_id = answers.get(question_id)
        assert selected_option_id is not None, events

        selected_option = next(
            (
                option
                for option in question_event["data"]["options"]
                if option["id"] == selected_option_id
            ),
            None,
        )
        assert selected_option is not None, question_event

        message = selected_option["label"]
        question_answer = {
            "question_id": question_id,
            "selected_option_ids": [selected_option_id],
            "selected_values": [selected_option_id],
            "ui_language": "sv",
        }

    raise AssertionError(
        "AI Builder session did not reach a plan within the expected number of turns."
    )


def _make_flow_step(
    *,
    assistant_id,
    step_order: int,
    user_description: str,
    input_source: str = "flow_input",
    input_type: str = "text",
    output_mode: str = "pass_through",
    output_type: str = "text",
    input_bindings: dict | None = None,
    input_config: dict | None = None,
) -> FlowStep:
    return FlowStep(
        id=None,
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=assistant_id,
        step_order=step_order,
        user_description=user_description,
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        input_bindings=input_bindings,
        input_contract=None,
        output_contract=None,
        input_config=input_config,
        output_config=None,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_builder_api_does_not_repeat_report_disposition_after_structured_answer(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder report-disposition monotonicity",
    )

    classification_call_count = 0

    async def classify_report_shape(**kwargs: object) -> SlotClassificationResult:
        nonlocal classification_call_count
        classification_input = kwargs.get("classification_input")
        assert isinstance(classification_input, SlotClassificationInput)
        source = classification_input.sources[-1]
        evidence = (
            ClassifiedEvidence(
                source_id=source.source_id,
                quote=source.text[:80],
            ),
        )
        classification_call_count += 1
        if classification_call_count == 1:
            return SlotClassificationResult(
                slots=(
                    ClassifiedSlot(
                        slot_name="primary_runtime_input",
                        value="documents",
                        confidence="high",
                        reason="The flow reads several uploaded documents.",
                        evidence=evidence,
                    ),
                    ClassifiedSlot(
                        slot_name="document_material_scope",
                        value="multiple_documents_case",
                        confidence="high",
                        reason="Each run handles a document set.",
                        evidence=evidence,
                    ),
                    ClassifiedSlot(
                        slot_name="post_processing_goal",
                        value="structure_key_information",
                        confidence="high",
                        reason="The requested result is a structured report.",
                        evidence=evidence,
                    ),
                )
            )
        return SlotClassificationResult(
            slots=(
                ClassifiedSlot(
                    slot_name="report_disposition",
                    value="synthesized_overview",
                    confidence="medium",
                    reason="Older classifier inference from the whole transcript.",
                    evidence=evidence,
                ),
            )
        )

    mock_classifier = AsyncMock(side_effect=classify_report_shape)
    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_discovery_runtime.classify_slots",
            new=mock_classifier,
        ),
        patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
        ),
    ):
        session_id = await _create_ai_builder_session(
            client=client,
            bearer_token=bearer_token,
            space_id=space_id,
        )
        first_events = await _send_builder_message(
            client=client,
            bearer_token=bearer_token,
            session_id=session_id,
            message="Skapa ett flöde för rapportering.",
        )
        second_events = await _send_builder_message(
            client=client,
            bearer_token=bearer_token,
            session_id=session_id,
            message="PDF",
            question_answer={
                "question_id": "terminal_output",
                "selected_option_ids": ["pdf_document"],
                "selected_values": ["pdf_document"],
                "ui_language": "sv",
            },
        )
        third_events = await _send_builder_message(
            client=client,
            bearer_token=bearer_token,
            session_id=session_id,
            message="Strukturera materialet",
            question_answer={
                "question_id": "post_processing_goal",
                "selected_option_ids": ["structure_key_information"],
                "selected_values": ["structure_key_information"],
                "ui_language": "sv",
            },
        )
        fourth_events = await _send_builder_message(
            client=client,
            bearer_token=bearer_token,
            session_id=session_id,
            message="Avsnitt per källa",
            question_answer={
                "question_id": "report_disposition",
                "selected_option_ids": ["per_source_sections"],
                "selected_values": ["per_source_sections"],
                "ui_language": "sv",
            },
        )

    assert any(
        event["event"] == "question"
        and cast(dict[str, object], event["data"]).get("question_id")
        == "terminal_output"
        for event in first_events
    )
    assert any(
        event["event"] == "question"
        and cast(dict[str, object], event["data"]).get("question_id")
        == "post_processing_goal"
        for event in second_events
    ), [
        (
            event["event"],
            cast(dict[str, object], event["data"]).get("question_id"),
        )
        for event in second_events
    ]
    assert any(
        event["event"] == "question"
        and cast(dict[str, object], event["data"]).get("question_id")
        == "report_disposition"
        for event in third_events
    )
    assert not any(event["event"] == "error" for event in fourth_events), fourth_events
    assert not any(
        event["event"] == "question"
        and cast(dict[str, object], event["data"]).get("question_id")
        == "report_disposition"
        for event in fourth_events
    )
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        loaded_state = await repo.load_planning_state(
            session_id=UUID(session_id),
            tenant_id=user.tenant_id,
        )

    assert loaded_state is not None
    report_disposition = loaded_state.resolved_slots["report_disposition"]
    assert report_disposition.value == "per_source_sections"
    assert report_disposition.source == "structured_answer"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_builder_api_repeated_output_question_after_freeform_label_recovers_without_internal_error(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder API freeform recovery",
    )

    initial_question = _make_tool_call(
        tool_call_id="call_q1",
        name="ask_structured_question",
        arguments={
            "question_id": "final_output_mode",
            "question": "Vad ska flödet producera som slutresultat?",
            "options": [
                {
                    "id": "structured_text",
                    "label": "Strukturerat textresultat",
                },
                {"id": "pdf_document", "label": "PDF-dokument"},
                {"id": "docx_document", "label": "DOCX-dokument"},
                {"id": "structured_json", "label": "Strukturerad JSON"},
            ],
            "selection_mode": "single",
            "allow_custom": True,
        },
    )
    repeated_question = _make_tool_call(
        tool_call_id="call_q2",
        name="ask_structured_question",
        arguments={
            "question_id": "final_output_mode",
            "question": "Vad ska flödet producera som slutresultat?",
            "options": [
                {"id": "structured_text", "label": "Text"},
                {"id": "pdf_document", "label": "PDF"},
            ],
            "selection_mode": "single",
            "allow_custom": True,
        },
    )
    requirements_summary = _make_tool_call(
        tool_call_id="call_requirements",
        name="confirm_requirements",
        arguments={
            "summary": "Ett ljudbaserat transkriberingsflöde som levererar PDF.",
            "key_decisions": [
                {"topic": "Input", "decision": "Ljudfil"},
                {"topic": "Output", "decision": "PDF"},
            ],
            "input_description": "Användaren laddar upp en ljudfil.",
            "output_description": "Flödet producerar en PDF-sammanfattning.",
        },
    )

    mock_completion = AsyncMock(
        side_effect=[
            _make_llm_response(tool_calls=[initial_question]),
            _make_llm_response(tool_calls=[repeated_question]),
            _make_llm_response(tool_calls=[requirements_summary]),
        ]
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=mock_completion,
    ):
        with patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
        ):
            session_id = await _create_ai_builder_session(
                client=client,
                bearer_token=bearer_token,
                space_id=space_id,
            )
            first_events = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message="Skapa en ljudfil transkriberare samt sammanfattare",
            )
            second_events = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message="PDF-dokument",
            )

    assert any(event["event"] == "question" for event in first_events)
    assert not any(event["event"] == "error" for event in second_events)
    assert any(
        event["event"] in {"requirements_summary", "question"}
        for event in second_events
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_builder_api_resolved_architecture_emits_requirements_summary(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder API recovery exhaustion",
    )

    with patch(
        "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
        new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
    ):
        session_id = await _create_ai_builder_session(
            client=client,
            bearer_token=bearer_token,
            space_id=space_id,
        )
        async with db_container() as container:
            repo = AIBuilderRepository(container.session())
            session = await repo.get_session(
                session_id=UUID(session_id),
                tenant_id=container.user().tenant_id,
            )
            turn = await _claim_session_send_turn(
                repo=repo,
                session_id=session.id,
                tenant_id=session.tenant_id,
            )
            await repo.append_session_messages(
                session_id=session.id,
                tenant_id=session.tenant_id,
                conversation=[
                    ConversationMessage(
                        role="user",
                        content="Jag vill bygga ett enkelt PDF-flöde.",
                        metadata={"ui_language": "sv"},
                    ),
                    ConversationMessage(
                        role="user",
                        content="Ett ärende åt gången",
                        metadata={
                            "question_answer": {
                                "question_id": "processing_scope",
                                "selected_option_id": "single_case",
                                "answer": "single_case",
                            },
                            "ui_language": "sv",
                        },
                    ),
                    ConversationMessage(
                        role="user",
                        content="Dokument",
                        metadata={
                            "question_answer": {
                                "question_id": "input_material_mode",
                                "selected_option_id": "documents",
                                "answer": "documents",
                            },
                            "ui_language": "sv",
                        },
                    ),
                    ConversationMessage(
                        role="user",
                        content="Ett huvuddokument per ärende",
                        metadata={
                            "question_answer": {
                                "question_id": "document_material_scope",
                                "selected_option_id": "single_document_case",
                                "answer": "single_document_case",
                            },
                            "ui_language": "sv",
                        },
                    ),
                    ConversationMessage(
                        role="user",
                        content="PDF-dokument",
                        metadata={
                            "question_answer": {
                                "question_id": "final_output_mode",
                                "selected_option_id": "pdf_document",
                                "answer": "pdf_document",
                            },
                            "ui_language": "sv",
                        },
                    ),
                    ConversationMessage(
                        role="user",
                        content="Strukturerad rapport",
                        metadata={
                            "question_answer": {
                                "question_id": "final_pdf_type",
                                "selected_option_id": "structured_report_pdf",
                                "answer": "structured_report_pdf",
                            },
                            "ui_language": "sv",
                        },
                    ),
                    ConversationMessage(
                        role="user",
                        content="Blandad målgrupp",
                        metadata={
                            "question_answer": {
                                "question_id": "output_reader",
                                "selected_option_id": "mixed_reader",
                                "answer": "mixed_reader",
                            },
                            "ui_language": "sv",
                        },
                    ),
                    ConversationMessage(
                        role="user",
                        content="Sammanfatta underlaget",
                        metadata={
                            "question_answer": {
                                "question_id": "post_processing_goal",
                                "selected_option_id": "summarize_or_overview",
                                "answer": "summarize_or_overview",
                            },
                            "ui_language": "sv",
                        },
                    ),
                    ConversationMessage(
                        role="user",
                        content="Inga extra fält",
                        metadata={
                            "question_answer": {
                                "question_id": "runtime_metadata_fields",
                                "selected_option_id": "no_extra_metadata",
                                "answer": "no_extra_metadata",
                            },
                            "ui_language": "sv",
                        },
                    ),
                ],
                lease=turn.lease,
            )
            await repo.complete_session_turn(turn=turn)
            await repo.release_session_send(
                session_id=session.id,
                tenant_id=session.tenant_id,
                lease=turn.lease,
            )
        second_events = await _send_builder_message(
            client=client,
            bearer_token=bearer_token,
            session_id=session_id,
            message="Bygg vidare",
        )

    assert not any(event["event"] == "error" for event in second_events), second_events
    assert any(event["event"] == "requirements_summary" for event in second_events)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_builder_api_create_mode_can_generate_approve_apply_and_publish_a_flow(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder API create/apply/publish",
    )

    outline_flow = _make_tool_call(
        tool_call_id="call_plan",
        name=PROPOSE_FLOW_TOOL_NAME,
        arguments={
            "flow_name": "Dokumentsammanfattning till PDF",
            "flow_description": "Sammanfattar uppladdade dokument i en PDF-rapport.",
            "plan_rationale": "Extrahera en grundad sammanfattning och skapa en PDF-rapport.",
            "steps": [
                {
                    "name": "Extrahera sammanfattning",
                    "instructions": (
                        "Sammanfatta dokumentunderlaget på tydlig svenska med de "
                        "viktigaste punkterna för en mänsklig läsare."
                    ),
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "Kort sammanfattning grundad i källmaterialet.",
                        }
                    ],
                },
            ],
        },
    )

    mock_completion = AsyncMock(
        return_value=_make_llm_response(tool_calls=[outline_flow])
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=mock_completion,
    ):
        with patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
        ):
            session_id = await _create_ai_builder_session(
                client=client,
                bearer_token=bearer_token,
                space_id=space_id,
            )
            plan_events = await _progress_builder_session_to_plan(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                initial_message=(
                    "Skapa ett flöde som sammanfattar uppladdade dokument i en "
                    "PDF-rapport för en mänsklig läsare."
                ),
                structured_answers={
                    "input_material_mode": "documents",
                    "flow_input_architecture": "document_primary_input",
                    "document_kind": "case_documents",
                    "terminal_output": "pdf_document",
                    "post_processing_goal": "summarize_or_overview",
                },
            )

    assert any(event["event"] == "plan" for event in plan_events), plan_events

    plan_id = await _get_latest_plan_id(
        client=client,
        bearer_token=bearer_token,
        session_id=session_id,
    )

    plan_response = await client.get(
        f"/api/v1/flows/ai-builder/plans/{plan_id}",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert plan_response.status_code == 200, plan_response.text
    assert plan_response.json()["status"] == "proposed"

    approve_response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{plan_id}/approve",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert approve_response.status_code == 200, approve_response.text
    assert approve_response.json()["status"] == "approved"

    apply_response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{plan_id}/apply",
        json={},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert apply_response.status_code == 200, apply_response.text
    apply_payload = apply_response.json()
    assert apply_payload["steps_updated"] == 0
    assert apply_payload["steps_removed"] == 0

    flow_id = apply_payload["flow_id"]
    flow_response = await client.get(
        f"/api/v1/flows/{flow_id}/",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert flow_response.status_code == 200, flow_response.text
    flow_payload = flow_response.json()
    assert flow_payload["name"] == "Dokumentsammanfattning till PDF"
    assert apply_payload["steps_created"] == 3
    assert len(flow_payload["steps"]) == 3
    assert flow_payload["steps"][0]["input_type"] == "document"
    assert flow_payload["steps"][0]["output_type"] == "json"
    assert flow_payload["steps"][1]["output_type"] == "text"
    assert flow_payload["steps"][-1]["output_type"] == "pdf"

    publish_response = await client.post(
        f"/api/v1/flows/{flow_id}/publish/",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert publish_response.status_code == 200, publish_response.text
    assert publish_response.json()["published_version"] == 1

    published_flow_response = await client.get(
        f"/api/v1/flows/{flow_id}/",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert published_flow_response.status_code == 200, published_flow_response.text
    assert published_flow_response.json()["published_version"] == 1

    async with db_container() as container:
        published_flow = await container.flow_service().get_flow(UUID(flow_id))
    assert published_flow.published is True
    assert published_flow.published_version == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_builder_api_edit_apply_replays_committed_output_change_once(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder API edit output-only",
    )
    async with db_container() as container:
        flow_service = container.flow_service()
        original_description = (
            "Tar emot uppladdade ärendedokument vid körning och skapar ett kort "
            "svenskt beslutsunderlag i textformat."
        )
        flow = await flow_service.create_flow(
            space_id=UUID(space_id),
            name="Beslutsunderlag",
            description=original_description,
            steps=[],
        )
        assistant, _ = await flow_service.create_flow_assistant(
            flow_id=flow.id,
            name="summary",
        )
        await flow_service.update_flow_assistant(
            flow_id=flow.id,
            assistant_id=assistant.id,
            update=AssistantUpdateCommand(
                prompt=PromptCreate(text="Skriv ett kort beslutsunderlag i textformat.")
            ),
        )
        flow = await flow_service.update_flow(
            flow_id=flow.id,
            steps=[
                _make_flow_step(
                    assistant_id=assistant.id,
                    step_order=1,
                    user_description="Skriv beslutsunderlag",
                    input_source="flow_input",
                    input_type="document",
                    output_type="text",
                ),
            ],
        )
        flow_id = flow.id
        flow_revision = flow.draft_revision

    edit_flow = _make_tool_call(
        tool_call_id="call_edit",
        name=PROPOSE_FLOW_TOOL_NAME,
        arguments={
            "plan_rationale": "Byter bara slutformatet till DOCX och behåller övriga delar.",
            "steps": [
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "output_type": "docx",
                }
            ],
        },
    )
    mock_completion = AsyncMock(return_value=_make_llm_response(tool_calls=[edit_flow]))

    with patch(
        "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=mock_completion,
    ):
        with patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
        ):
            session_id = await _create_ai_builder_session(
                client=client,
                bearer_token=bearer_token,
                space_id=space_id,
                target_kind="edit",
                flow_id=str(flow_id),
            )
            plan_events = await _progress_builder_session_to_plan(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                initial_message="Byt slutformat till DOCX men behåll resten av flödet.",
                structured_answers={
                    "terminal_output": "docx_document",
                    "docx_output_mode": "generated_docx",
                    "report_disposition": "synthesized_overview",
                },
            )
    assert any(event["event"] == "plan" for event in plan_events)
    plan_id = await _get_latest_plan_id(
        client=client,
        bearer_token=bearer_token,
        session_id=session_id,
    )

    approve_response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{plan_id}/approve",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert approve_response.status_code == 200, approve_response.text

    first_apply_response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{plan_id}/apply",
        json={"expected_revision": flow_revision},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert first_apply_response.status_code == 200, first_apply_response.text
    assert first_apply_response.json()["steps_created"] == 0
    assert first_apply_response.json()["steps_updated"] == 1
    assert first_apply_response.json()["steps_removed"] == 0

    async with db_container() as container:
        flow_service = container.flow_service()
        after_first_apply = await flow_service.get_flow(flow_id)
        after_first_snapshots = await flow_service.get_flow_assistant_snapshots(
            after_first_apply
        )

    replay_response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{plan_id}/apply",
        json={"expected_revision": flow_revision},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert replay_response.status_code == 200, replay_response.text
    assert replay_response.json() == first_apply_response.json()

    async with db_container() as container:
        after_replay = await container.flow_service().get_flow(flow_id)

    assert after_first_apply.draft_revision == flow_revision + 1
    assert after_replay.draft_revision == after_first_apply.draft_revision
    assert after_replay.description == after_first_apply.description
    assert len(after_replay.steps) == len(after_first_apply.steps) == 1
    assert after_replay.steps[0].output_type == after_first_apply.steps[0].output_type
    assert after_first_apply.steps[0].output_type == "docx"
    assert after_first_apply.description == (
        "Tar emot uppladdade ärendedokument vid körning och skapar ett kort "
        "svenskt beslutsunderlag i DOCX-format."
    )
    assert (
        after_first_snapshots[after_first_apply.steps[0].assistant_id].instructions
        == "Skriv ett kort beslutsunderlag i textformat."
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_builder_api_edit_mode_invalid_existing_step_ref_returns_typed_bad_request(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder API invalid edit existing ref",
    )
    async with db_container() as container:
        flow_service = container.flow_service()
        flow = await flow_service.create_flow(
            space_id=UUID(space_id),
            name="Befintligt flöde",
            description="Beskrivning",
            steps=[],
        )
        assistant, _ = await flow_service.create_flow_assistant(
            flow_id=flow.id,
            name="summary",
        )
        flow = await flow_service.update_flow(
            flow_id=flow.id,
            steps=[
                _make_flow_step(
                    assistant_id=assistant.id,
                    step_order=1,
                    user_description="Sammanfatta",
                    input_source="flow_input",
                    input_type="document",
                    output_type="text",
                ),
            ],
        )
        flow_id = flow.id
        flow_revision = flow.draft_revision

    session_id = await _create_ai_builder_session(
        client=client,
        bearer_token=bearer_token,
        space_id=space_id,
        target_kind="edit",
        flow_id=str(flow_id),
    )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        builder_session = await repo.get_session(
            session_id=UUID(session_id),
            tenant_id=container.user().tenant_id,
        )
        spec = _make_builder_plan_spec(existing_step_ref="step_a")
        plan = await repo.create_plan(
            session_id=builder_session.id,
            tenant_id=builder_session.tenant_id,
            proposal=FlowBuilderProposal(
                content=FlowBuilderProposalContent(
                    spec=spec,
                    edit=_make_builder_edit_approval(
                        spec=spec,
                        base_flow_revision=flow_revision,
                    ),
                ),
            ),
        )
        await repo.update_plan_status(
            plan_id=plan.id,
            tenant_id=builder_session.tenant_id,
            status=PlanStatus.APPROVED,
        )
        await repo.update_session_status_without_send_lease(
            session_id=builder_session.id,
            tenant_id=builder_session.tenant_id,
            status=SessionStatus.AWAITING_APPROVAL,
        )
        await repo.update_session_latest_plan_without_send_lease(
            session_id=builder_session.id,
            tenant_id=builder_session.tenant_id,
            plan_id=plan.id,
        )

    apply_response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{plan.id}/apply",
        json={"expected_revision": flow_revision},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert apply_response.status_code == 400, apply_response.text
    payload = apply_response.json()
    assert payload["code"] == "invalid_existing_step_ref"
    assert payload["eneo_error_code"] == 9007


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_builder_api_edit_mode_transcription_insert_clears_stale_runtime_input(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder API edit transcription",
    )
    async with db_container() as container:
        flow_service = container.flow_service()
        tenant_id = container.user().tenant_id

        flow = await flow_service.create_flow(
            space_id=UUID(space_id),
            name="IBIC dokumentflöde",
            description="Tar emot dokument och analyserar dem.",
            steps=[],
        )
        assistant, _ = await flow_service.create_flow_assistant(
            flow_id=flow.id,
            name="analysis",
        )
        flow = await flow_service.update_flow(
            flow_id=flow.id,
            steps=[
                _make_flow_step(
                    assistant_id=assistant.id,
                    step_order=1,
                    user_description="IBIC-extraktion",
                    input_source="flow_input",
                    input_type="document",
                    input_config={
                        "runtime_input": {
                            "enabled": True,
                            "required": True,
                            "input_format": "document",
                            "description": "Ladda upp dokument som detta steg ska analysera.",
                        }
                    },
                ),
            ],
        )
        flow_id = flow.id
        flow_revision = flow.draft_revision

    await _create_default_transcription_model(
        db_container=db_container,
        space_id=space_id,
        tenant_id=tenant_id,
    )

    edit_flow = _make_tool_call(
        tool_call_id="call_edit",
        name=PROPOSE_FLOW_TOOL_NAME,
        arguments={
            "plan_rationale": "Lägger till ett transkriberingssteg före analysen och gör analyssteget textbaserat.",
            "steps": [
                {
                    "kind": "add",
                    "step": {
                        "name": "Transkribera ljudfil",
                        "instructions": "Transkribera ljudfilen ordagrant till svensk text.",
                        "output_type": "text",
                    },
                },
                {
                    "kind": "modify",
                    "existing_step_ref": "existing_step_1",
                    "input_source": "previous_step",
                    "input_type": "text",
                    "assistant_spec": {"instructions": "Analysera transkriberingen."},
                },
            ],
        },
    )
    mock_completion = AsyncMock(return_value=_make_llm_response(tool_calls=[edit_flow]))

    with patch(
        "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=mock_completion,
    ):
        with patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
        ):
            session_id = await _create_ai_builder_session(
                client=client,
                bearer_token=bearer_token,
                space_id=space_id,
                target_kind="edit",
                flow_id=str(flow_id),
            )
            plan_events = await _progress_builder_session_to_plan(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                initial_message=(
                    "Lägg till ett första steg som tar emot en uppladdad "
                    "ljudfil, transkriberar den före det befintliga "
                    "dokumentsteget och behåll resten."
                ),
                structured_answers={
                    "document_kind": "case_documents",
                    "input_material_mode": "audio",
                    "flow_input_architecture": "audio_primary_input",
                },
            )
    assert any(event["event"] == "plan" for event in plan_events)
    plan_id = await _get_latest_plan_id(
        client=client,
        bearer_token=bearer_token,
        session_id=session_id,
    )

    approve_response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{plan_id}/approve",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert approve_response.status_code == 200, approve_response.text

    apply_response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{plan_id}/apply",
        json={"expected_revision": flow_revision},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert apply_response.status_code == 200, apply_response.text

    async with db_container() as container:
        flow_service = container.flow_service()
        updated = await flow_service.get_flow(flow_id)

    assert len(updated.steps) == 2
    assert updated.steps[0].input_source == "flow_input"
    assert updated.steps[0].input_type == "audio"
    assert updated.steps[0].output_mode == "transcribe_only"
    assert updated.steps[0].input_config == {
        "runtime_input": {
            "enabled": True,
            "required": True,
            "input_format": "audio",
            "description": "Ladda upp ljudfiler som detta steg ska transkribera eller analysera.",
        }
    }
    assert updated.steps[1].input_source == "previous_step"
    assert updated.steps[1].input_type == "text"
    assert updated.steps[1].input_config is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_builder_api_create_mode_audio_apply_without_transcription_model_returns_typed_error_and_no_orphan_flow(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder API audio missing transcription model",
    )

    outline_flow = _make_tool_call(
        tool_call_id="call_plan",
        name=PROPOSE_FLOW_TOOL_NAME,
        arguments={
            "flow_name": "Ljudtranskribering till PDF",
            "flow_description": "Transkriberar uppladdat ljud och skapar en PDF-sammanfattning.",
            "plan_rationale": "Transkribera först och generera sedan PDF-sammanfattningen.",
            "steps": [
                {
                    "name": "Skapa PDF-sammanfattning",
                    "instructions": (
                        "Sammanfatta transkriberingen på tydlig svenska med de "
                        "viktigaste punkterna för en mänsklig läsare."
                    ),
                    "output_type": "text",
                },
                {
                    "name": "Generera PDF-dokument",
                    "instructions": (
                        "Skapa ett läsbart PDF-dokument utifrån sammanfattningen."
                    ),
                    "output_type": "pdf",
                },
            ],
        },
    )

    mock_completion = AsyncMock(
        return_value=_make_llm_response(tool_calls=[outline_flow])
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=mock_completion,
    ):
        with patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
        ):
            session_id = await _create_ai_builder_session(
                client=client,
                bearer_token=bearer_token,
                space_id=space_id,
            )
            events = await _progress_builder_session_to_plan(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                initial_message=(
                    "Skapa ett flöde som tar en ljudfil, transkriberar den och "
                    "sammanfattar innehållet för en mänsklig läsare."
                ),
                structured_answers={
                    "input_material_mode": "audio",
                    "flow_input_architecture": "audio_primary_input",
                    "terminal_output": "pdf_document",
                    "post_processing_goal": "summarize_or_overview",
                },
            )

    plan_event = next((event for event in events if event["event"] == "plan"), None)
    assert plan_event is not None, events
    plan_id = plan_event["data"]["plan_id"]

    approve_response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{plan_id}/approve",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert approve_response.status_code == 200, approve_response.text

    apply_response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{plan_id}/apply",
        json={},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert apply_response.status_code == 400, apply_response.text
    assert apply_response.json()["code"] == "transcription_model_required"

    list_response = await client.get(
        "/api/v1/flows/",
        params={"space_id": space_id},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert list_response.status_code == 200, list_response.text
    assert list_response.json()["count"] == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_builder_api_create_mode_invalid_existing_step_ref_returns_typed_bad_request(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder API invalid create existing ref",
    )

    session_id = await _create_ai_builder_session(
        client=client,
        bearer_token=bearer_token,
        space_id=space_id,
    )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.get_session(
            session_id=UUID(session_id),
            tenant_id=user.tenant_id,
        )
        spec = _make_builder_plan_spec(existing_step_ref="step_a")
        plan = await repo.create_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            proposal=FlowBuilderProposal(content=FlowBuilderProposalContent(spec=spec)),
        )
        await repo.update_plan_status(
            plan_id=plan.id,
            tenant_id=user.tenant_id,
            status=PlanStatus.APPROVED,
        )
        await repo.update_session_status_without_send_lease(
            session_id=session.id,
            tenant_id=user.tenant_id,
            status=SessionStatus.AWAITING_APPROVAL,
        )
        await repo.update_session_latest_plan_without_send_lease(
            session_id=session.id,
            tenant_id=user.tenant_id,
            plan_id=plan.id,
        )

    apply_response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{plan.id}/apply",
        json={},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert apply_response.status_code == 400, apply_response.text
    payload = apply_response.json()
    assert payload["code"] == "invalid_existing_step_ref"
    assert payload["eneo_error_code"] == 9007


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_builder_api_rejects_persisted_legacy_mcp_plan_before_create_effects(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
) -> None:
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder legacy MCP plan rejection",
    )
    session_id, tenant_id, plan_id, _ = await _create_proposed_ai_builder_plan(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        space_id=space_id,
    )

    async with db_container() as container:
        proposal_json = (
            await container.session().execute(
                select(BuilderPlans.proposal_json).where(
                    BuilderPlans.id == plan_id,
                    BuilderPlans.tenant_id == tenant_id,
                )
            )
        ).scalar_one()
        legacy_proposal = json.loads(json.dumps(proposal_json))
        legacy_proposal["content"]["spec"]["steps"][0]["assistant_spec"][
            "mcp_tool_refs"
        ] = ["mcp_tool.synthetic"]
        await container.session().execute(
            update(BuilderPlans)
            .where(
                BuilderPlans.id == plan_id,
                BuilderPlans.tenant_id == tenant_id,
            )
            .values(proposal_json=legacy_proposal)
        )

    provider_call = AsyncMock(
        side_effect=AssertionError("persisted plan rejection reached the provider")
    )
    authoring_prepare = AsyncMock(
        side_effect=AssertionError("persisted plan rejection reached Flow authoring")
    )
    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
            new=provider_call,
        ),
        patch.object(
            FlowAuthoringCommandService,
            "prepare",
            new=authoring_prepare,
        ),
    ):
        response = await client.post(
            f"/api/v1/flows/ai-builder/plans/{plan_id}/create",
            headers={"Authorization": f"Bearer {bearer_token}"},
        )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == AIBuilderErrorCode.BAD_REQUEST.value
    provider_call.assert_not_awaited()
    authoring_prepare.assert_not_awaited()

    async with db_container() as container:
        flow_count = (
            await container.session().execute(
                select(sa.func.count())
                .select_from(Flows)
                .where(Flows.space_id == UUID(space_id))
            )
        ).scalar_one()
        persisted_plan_status = (
            await container.session().execute(
                select(BuilderPlans.status).where(
                    BuilderPlans.id == plan_id,
                    BuilderPlans.tenant_id == tenant_id,
                )
            )
        ).scalar_one()
        persisted_session_status = (
            await container.session().execute(
                select(BuilderSessions.status).where(
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                )
            )
        ).scalar_one()

    assert (
        flow_count,
        persisted_plan_status,
        persisted_session_status,
    ) == (
        0,
        PlanStatus.PROPOSED.value,
        SessionStatus.AWAITING_APPROVAL.value,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_builder_api_audio_report_prompt_reaches_requirements_summary_without_input_or_output_questions(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder API audio report prompt",
    )

    requirements_summary = _make_tool_call(
        tool_call_id="call_requirements_audio_report",
        name="confirm_requirements",
        arguments={
            "summary": (
                "Flödet ska ta en ljudfil, transkribera den och skriva en strukturerad "
                "rapport i text med ämne, sammanfattning, nyckelord, namn och datum."
            ),
            "key_decisions": [
                {"topic": "Input", "decision": "Ljud som primär indata"},
                {"topic": "Output", "decision": "Strukturerad rapport som text"},
            ],
            "input_description": "Användaren laddar upp en ljudfil vid körning.",
            "output_description": "Flödet producerar ett läsbart strukturerat textresultat i flödet.",
        },
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=AsyncMock(
            return_value=_make_llm_response(tool_calls=[requirements_summary])
        ),
    ):
        with patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
        ):
            session_id = await _create_ai_builder_session(
                client=client,
                bearer_token=bearer_token,
                space_id=space_id,
            )
            events = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message=(
                    "Jag vill börja bygga ett flöde där jag kommer skicka in en ljudfil "
                    "som du ska transkribera sen ska du sammanfatta det och ge mig en "
                    "strukturerad rapport med dom viktigaste keywords och själva ämnet. "
                    "Vilka namn som förekommer och om det förekommer ett datum och själva "
                    "ämnet av samtalet också."
                ),
            )

    event_types = [event["event"] for event in events]
    assert "question" not in event_types
    assert "requirements_summary" in event_types


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_and_create_rolls_back_everything_and_recovers_on_retry(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
) -> None:
    """The combined create endpoint is atomic across approval, flow
    materialization and terminalization: a failure injected after the flow has
    been written (but before the plan is marked applied) must leave zero
    flows, the plan still proposed and the session still awaiting approval —
    and a retry of the same call must then create exactly one flow."""
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Combined Create Rollback",
    )
    session_id, tenant_id, plan_id, _ = await _create_proposed_ai_builder_plan(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        space_id=space_id,
    )

    async def fail_terminalization(self, **_kwargs: object) -> None:
        raise BadRequestException("forced create failure", code="forced_create_failure")

    # Scoped patch context: the function-scoped `monkeypatch` fixture is shared
    # with the auth fixtures, so undoing it wholesale would also remove the JWT
    # patch and break the retry request.
    with pytest.MonkeyPatch.context() as failure_patch:
        failure_patch.setattr(
            AIBuilderRepository,
            "mark_plan_applied",
            fail_terminalization,
        )

        failed_response = await client.post(
            f"/api/v1/flows/ai-builder/plans/{plan_id}/create",
            headers={"Authorization": f"Bearer {bearer_token}"},
        )
    assert failed_response.status_code == 400, failed_response.text
    assert "forced create failure" in failed_response.text, failed_response.text

    async with db_container() as container:
        flow_count = (
            await container.session().execute(
                select(sa.func.count())
                .select_from(Flows)
                .where(Flows.space_id == UUID(space_id))
            )
        ).scalar_one()
        persisted_plan_status = (
            await container.session().execute(
                select(BuilderPlans.status).where(
                    BuilderPlans.id == plan_id,
                    BuilderPlans.tenant_id == tenant_id,
                )
            )
        ).scalar_one()
        persisted_session_status = (
            await container.session().execute(
                select(BuilderSessions.status).where(
                    BuilderSessions.id == session_id,
                    BuilderSessions.tenant_id == tenant_id,
                )
            )
        ).scalar_one()

    assert (flow_count, persisted_plan_status, persisted_session_status) == (
        0,
        PlanStatus.PROPOSED.value,
        SessionStatus.AWAITING_APPROVAL.value,
    )

    retry_response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{plan_id}/create",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert retry_response.status_code == 200, retry_response.text
    created_flow_id = retry_response.json()["flow_id"]

    async with db_container() as container:
        flow_ids = (
            (
                await container.session().execute(
                    select(Flows.id).where(Flows.space_id == UUID(space_id))
                )
            )
            .scalars()
            .all()
        )
    assert [str(flow_id) for flow_id in flow_ids] == [created_flow_id]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_approve_and_create_requests_materialize_one_flow(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
) -> None:
    """Two simultaneous create requests for the same plan must not duplicate
    the flow: the plan row is read FOR UPDATE, so the second transaction waits,
    observes the applied plan, and replays the original outcome."""
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Concurrent Create",
    )
    _, _, plan_id, _ = await _create_proposed_ai_builder_plan(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        space_id=space_id,
    )

    first, second = await asyncio.gather(
        client.post(
            f"/api/v1/flows/ai-builder/plans/{plan_id}/create",
            headers={"Authorization": f"Bearer {bearer_token}"},
        ),
        client.post(
            f"/api/v1/flows/ai-builder/plans/{plan_id}/create",
            headers={"Authorization": f"Bearer {bearer_token}"},
        ),
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["flow_id"] == second.json()["flow_id"]

    async with db_container() as container:
        flow_count = (
            await container.session().execute(
                select(sa.func.count())
                .select_from(Flows)
                .where(Flows.space_id == UUID(space_id))
            )
        ).scalar_one()
    assert flow_count == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_create_and_legacy_approve_cannot_resurrect_applied_plan(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
) -> None:
    """A stale legacy /approve racing the combined create must not rewrite the
    terminal plan status: both commands lock session-then-plan, and approval
    uses a conditional PROPOSED→APPROVED transition, so whichever loses the
    race observes the committed state instead of clobbering it."""
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder Create vs Approve Race",
    )
    _, tenant_id, plan_id, _ = await _create_proposed_ai_builder_plan(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        space_id=space_id,
    )

    create_response, approve_response = await asyncio.gather(
        client.post(
            f"/api/v1/flows/ai-builder/plans/{plan_id}/create",
            headers={"Authorization": f"Bearer {bearer_token}"},
        ),
        client.post(
            f"/api/v1/flows/ai-builder/plans/{plan_id}/approve",
            headers={"Authorization": f"Bearer {bearer_token}"},
        ),
    )

    assert create_response.status_code == 200, create_response.text
    # The approval either landed first (200, then create applied it) or lost
    # the race and was rejected — it must never overwrite APPLIED.
    assert approve_response.status_code in (200, 400, 409), approve_response.text

    async with db_container() as container:
        persisted_plan_status = (
            await container.session().execute(
                select(BuilderPlans.status).where(
                    BuilderPlans.id == plan_id,
                    BuilderPlans.tenant_id == tenant_id,
                )
            )
        ).scalar_one()
        flow_count = (
            await container.session().execute(
                select(sa.func.count())
                .select_from(Flows)
                .where(Flows.space_id == UUID(space_id))
            )
        ).scalar_one()

    assert persisted_plan_status == PlanStatus.APPLIED.value
    assert flow_count == 1


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_endpoint", ["approve", "apply", "create"])
async def test_plan_transitions_reject_while_refinement_turn_is_active(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
    legacy_endpoint: str,
) -> None:
    """The handoff requires approval/application to be unreachable while a
    refinement turn is streaming. Locks only make competitors wait; the shared
    post-lock validation must REJECT against the observed active turn."""
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name=f"AI Builder Active Turn Guard {legacy_endpoint}",
    )
    session_id, tenant_id, plan_id, _ = await _create_proposed_ai_builder_plan(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        space_id=space_id,
    )
    if legacy_endpoint == "apply":
        approve_response = await client.post(
            f"/api/v1/flows/ai-builder/plans/{plan_id}/approve",
            headers={"Authorization": f"Bearer {bearer_token}"},
        )
        assert approve_response.status_code == 200, approve_response.text

    # Claim a refinement turn and keep the lease open (state=open).
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        await _claim_session_send_turn(
            repo=repo,
            session_id=session_id,
            tenant_id=tenant_id,
        )

    body = {} if legacy_endpoint == "apply" else None
    response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{plan_id}/{legacy_endpoint}",
        json=body,
        headers={"Authorization": f"Bearer {bearer_token}"},
    )

    assert response.status_code == 409, response.text
    assert "session_message_in_progress" in response.text

    async with db_container() as container:
        persisted_plan_status = (
            await container.session().execute(
                select(BuilderPlans.status).where(
                    BuilderPlans.id == plan_id,
                    BuilderPlans.tenant_id == tenant_id,
                )
            )
        ).scalar_one()
        flow_count = (
            await container.session().execute(
                select(sa.func.count())
                .select_from(Flows)
                .where(Flows.space_id == UUID(space_id))
            )
        ).scalar_one()

    expected_status = (
        PlanStatus.APPROVED.value
        if legacy_endpoint == "apply"
        else PlanStatus.PROPOSED.value
    )
    assert persisted_plan_status == expected_status
    assert flow_count == 0
