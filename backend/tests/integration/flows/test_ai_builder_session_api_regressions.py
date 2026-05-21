from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from intric.database.tables.ai_models_table import TranscriptionModels
from intric.database.tables.flow_tables import BuilderSessions, Flows
from intric.database.tables.model_providers_table import ModelProviders
from intric.database.tables.spaces_table import (
    Spaces,
    SpacesCompletionModels,
    SpacesTranscriptionModels,
)
from intric.database.tables.tenant_table import Tenants
from intric.flows.ai_builder.ai_builder_create_outline import OUTLINE_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_domain_models import SessionStatus
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    ConversationMessage,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    PlannerPlanEnvelope,
    PlanStatus,
    StepSpec,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
    ArchitectureCommit,
    EvidenceRef,
    PlanningState,
    ResolvedSlot,
    StepTriple,
)
from intric.flows.application.flow_assistant_update import FlowAssistantUpdateCommand
from intric.flows.flow import FlowStep
from intric.main.exceptions import BadRequestException, NotFoundException
from intric.prompts.api.prompt_models import PromptCreate


@pytest.fixture
async def bearer_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        token = auth_service.create_access_token_for_user(admin_user)
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
    file_ids: list[str] | None = None,
    question_answer: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    payload: dict[str, object] = {
        "message": message,
        "ui_language": "sv",
    }
    if file_ids is not None:
        payload["file_ids"] = file_ids
    if question_answer is not None:
        payload["question_answer"] = question_answer

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
                mcp_policy=MCPPolicy.INHERIT,
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            )
        ],
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_message_attachments_persist_only_after_accepted_send(
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

    with patch(
        "intric.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=AsyncMock(
            return_value=_make_llm_response(
                content="Jag kan använda referensmaterialet."
            )
        ),
    ):
        with patch(
            "intric.flows.ai_builder.ai_builder_router._resolve_litellm_params",
            new=AsyncMock(return_value=("openai/gpt-4o-mini", {"api_key": "sk-test"})),
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

            events = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message="Använd det bifogade referensmaterialet.",
                file_ids=[file_id],
            )
            assert any(event["event"] == "text" for event in events)

            after_response = await client.get(
                f"/api/v1/flows/ai-builder/sessions/{session_id}",
                headers={"Authorization": f"Bearer {bearer_token}"},
            )
            assert after_response.status_code == 200, after_response.text
            attachment_ids = [
                attachment["id"] for attachment in after_response.json()["attachments"]
            ]
            assert attachment_ids == [file_id]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_claim_session_send_can_reclaim_expired_lease(
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

        first_claim = await repo.claim_session_send(
            session_id=session.id,
            tenant_id=user.tenant_id,
            request_id=uuid4(),
            lock_token=uuid4(),
            lock_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        assert first_claim is True

        reclaimed = await repo.claim_session_send(
            session_id=session.id,
            tenant_id=user.tenant_id,
            request_id=uuid4(),
            lock_token=uuid4(),
            lock_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        )
        assert reclaimed is True


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
        request_id = uuid4()
        lock_token = uuid4()
        claimed = await repo.claim_session_send(
            session_id=session.id,
            tenant_id=user.tenant_id,
            request_id=request_id,
            lock_token=lock_token,
            lock_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        )
        assert claimed is True

        await repo.release_session_send(
            session_id=session.id,
            tenant_id=user.tenant_id,
            request_id=request_id,
            lock_token=uuid4(),
        )

        still_locked = await repo.claim_session_send(
            session_id=session.id,
            tenant_id=user.tenant_id,
            request_id=uuid4(),
            lock_token=uuid4(),
            lock_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        )
        assert still_locked is False

        await repo.release_session_send(
            session_id=session.id,
            tenant_id=user.tenant_id,
            request_id=request_id,
            lock_token=lock_token,
        )

        released = await repo.claim_session_send(
            session_id=session.id,
            tenant_id=user.tenant_id,
            request_id=uuid4(),
            lock_token=uuid4(),
            lock_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        )
        assert released is True


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
                spec=spec,
                envelope=_make_plan_envelope(spec),
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_repo_attach_session_files_rejects_cross_tenant_session_reference(
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
        space_name="AI Builder Cross Tenant Attach",
    )
    file_id = await _upload_reference_file(
        client=client,
        bearer_token=bearer_token,
        filename="cross-tenant.txt",
        content=b"reference material",
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

        with pytest.raises(IntegrityError):
            await repo.attach_session_files(
                session_id=session.id,
                tenant_id=other_tenant_id,
                file_ids=[UUID(file_id)],
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
        phase="discovering",
        evidence=EvidenceRef(conversation_message_ids=["msg-1"]),
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
async def test_ai_builder_repo_save_planning_state_bumps_version(
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
        )
        second = await repo.save_planning_state(
            session_id=session.id,
            tenant_id=user.tenant_id,
            state=state,
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

        await repo.commit_turn(
            session_id=session.id,
            tenant_id=user.tenant_id,
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

    assert len(fetched.conversation) == 1
    assert fetched.conversation[0].role == "assistant"
    assert fetched.conversation[0].content == "Hej"
    assert loaded is not None
    assert loaded.evidence.conversation_message_ids == [
        fetched.conversation[0].message_id
    ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_persist_tool_turn_refreshes_planning_state_with_requirements_summary(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    """`persist_tool_turn` must route append + planning-state refresh through
    `commit_turn` so that state-affecting tool metadata
    (`requirements_summary`) lands in one savepoint and the persisted
    `PlanningState` stays coherent with the persisted conversation.
    """
    from intric.flows.ai_builder.ai_builder_repair_transport import (
        build_persisted_tool_call_stub,
        persist_tool_turn,
    )

    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder persist_tool_turn state refresh",
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
        conversation: list[ConversationMessage] = [
            ConversationMessage(
                role="user", content="Jag vill bygga en sammanställning."
            )
        ]
        tool_call = build_persisted_tool_call_stub(
            tool_call_id="call_requirements_1",
            tool_name="confirm_requirements",
        )

        await persist_tool_turn(
            repo=repo,
            tenant_id=user.tenant_id,
            session_id=session.id,
            conversation=conversation,
            new_messages_start=0,
            base_planning_state_version=session.planning_state_version,
            tool_call=tool_call,
            arguments={"summary": "Kort sammanfattning"},
            tool_content="Requirements presented to user. Awaiting confirmation.",
            metadata={
                "requirements_summary": {
                    "summary": "Kort sammanfattning",
                    "assumptions": ["sammanställning från flera dokument"],
                    "requirements_version": "req-v1",
                },
                "requirements_version": "req-v1",
            },
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
        version_row = await container.session().execute(
            select(BuilderSessions.planning_state_version).where(
                BuilderSessions.id == session.id
            )
        )

    persisted_roles = [message.role for message in fetched.conversation]
    assert persisted_roles == ["user", "assistant", "tool"]
    tool_message = fetched.conversation[2]
    assert tool_message.metadata is not None
    assert "requirements_summary" in tool_message.metadata
    assert loaded is not None
    assert loaded.evidence.conversation_message_ids == [
        message.message_id for message in fetched.conversation
    ]
    assert version_row.scalar_one() == 1


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

        with patch(
            "intric.flows.ai_builder.ai_builder_repo.build_planning_state_from_conversation",
            return_value=drifted,
        ):
            with pytest.raises(Exception):
                await repo.commit_turn(
                    session_id=session.id,
                    tenant_id=user.tenant_id,
                    new_messages=[assistant_msg],
                )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        fetched = await repo.get_session(
            session_id=session.id, tenant_id=user.tenant_id
        )

    assert fetched.conversation == []


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
        await repo.claim_session_send(
            session_id=session.id,
            tenant_id=user.tenant_id,
            request_id=uuid4(),
            lock_token=uuid4(),
            lock_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        )
        stale_request_id = uuid4()
        stale_lock_token = uuid4()
        assistant_msg = ConversationMessage(role="assistant", content="Stale lease")

        with pytest.raises(BadRequestException):
            await repo.commit_turn(
                session_id=session.id,
                tenant_id=user.tenant_id,
                new_messages=[assistant_msg],
                request_id=stale_request_id,
                lock_token=stale_lock_token,
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

    assert fetched.conversation == []
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

        await repo.commit_turn(
            session_id=session.id,
            tenant_id=user.tenant_id,
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

        with patch(
            "intric.flows.ai_builder.ai_builder_repo.build_planning_state_from_conversation",
            return_value=drifted,
        ):
            with pytest.raises(ValidationError):
                await repo.commit_turn(
                    session_id=session.id,
                    tenant_id=user.tenant_id,
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

    assert fetched.conversation == []
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
        await repo.commit_turn(
            session_id=session.id,
            tenant_id=user.tenant_id,
            new_messages=[
                ConversationMessage(role="assistant", content="commit turn 1")
            ],
            architecture_commit=commit,
        )
        await repo.commit_turn(
            session_id=session.id,
            tenant_id=user.tenant_id,
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
        chosen_patterns=["multi_step_quality_chain"],
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
        await repo.commit_turn(
            session_id=session.id,
            tenant_id=user.tenant_id,
            new_messages=[
                ConversationMessage(role="assistant", content="first commit")
            ],
            architecture_commit=first,
        )
        await repo.commit_turn(
            session_id=session.id,
            tenant_id=user.tenant_id,
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
    from intric.flows.ai_builder.ai_builder_plan_store import (
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

    concurrent_state = _planning_state_fixture()
    concurrent_state.phase = "awaiting_input"
    concurrent_state.evidence = EvidenceRef(conversation_message_ids=["concurrent"])
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
                tenant_id=tenant_id,
                session_id=session_id,
                conversation=[],
                new_messages_start=0,
                base_planning_state_version=0,
                assistant_content="stale plan ready",
                tool_call_id="call-stale-1",
                tool_name=OUTLINE_FLOW_TOOL_NAME,
                arguments={},
                spec=_make_builder_plan_spec(existing_step_ref=None),
                assumptions=[],
                plan_rationale=None,
                reasoning=None,
                validation=MagicMock(warnings=[]),
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
    assert fetched.conversation == []
    assert version == 1
    assert loaded_state is not None
    assert loaded_state.phase == "awaiting_input"
    assert loaded_state.evidence.conversation_message_ids == ["concurrent"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_plan_and_update_conversation_accepts_matching_planning_state_version(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    from intric.flows.ai_builder.ai_builder_plan_store import (
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
        plan, _envelope = await store_plan_and_update_conversation(
            repo=repo,
            tenant_id=tenant_id,
            session_id=session_id,
            conversation=[],
            new_messages_start=0,
            base_planning_state_version=0,
            assistant_content="plan ready",
            tool_call_id="call-match-1",
            tool_name=OUTLINE_FLOW_TOOL_NAME,
            arguments={},
            spec=_make_builder_plan_spec(existing_step_ref=None),
            assumptions=[],
            plan_rationale=None,
            reasoning=None,
            validation=MagicMock(warnings=[]),
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

    assert fetched.latest_plan_id == plan.id
    assert loaded_state is not None
    assert loaded_state.draft_plan_id == plan.id
    assert loaded_state.phase == "plan_proposed"
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
    from intric.flows.ai_builder.ai_builder_plan_store import (
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
        await repo.commit_turn(
            session_id=session.id,
            tenant_id=user.tenant_id,
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
                    mcp_policy=MCPPolicy.INHERIT,
                    input_source=InputSource.FLOW_INPUT,
                    input_type=InputType.TEXT,
                    output_mode=OutputMode.PASS_THROUGH,
                    output_type=OutputType.TEXT,
                )
            ],
        )
        await store_plan_and_update_conversation(
            repo=repo,
            tenant_id=user.tenant_id,
            session_id=session.id,
            conversation=working_conversation,
            new_messages_start=len(working_conversation),
            base_planning_state_version=fetched.planning_state_version,
            assistant_content="Here is the plan",
            assistant_metadata=None,
            tool_call_id="call_plan",
            tool_name="propose_plan",
            arguments={},
            spec=spec,
            assumptions=[],
            plan_rationale=None,
            reasoning=None,
            validation=SimpleNamespace(warnings=[]),
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
    assert loaded.draft_plan_id is not None
    assert loaded.phase == "plan_proposed"


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
    from intric.flows.ai_builder.ai_builder_plan_store import (
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

        async def raising_append(*args: object, **kwargs: object) -> None:
            raise RuntimeError("simulated append failure")

        repo.append_session_messages = raising_append  # type: ignore[method-assign]
        try:
            with pytest.raises(RuntimeError):
                await store_plan_and_update_conversation(
                    repo=repo,
                    tenant_id=tenant_id,
                    session_id=session_id,
                    conversation=[],
                    new_messages_start=0,
                    base_planning_state_version=0,
                    assistant_content="simulated",
                    tool_call_id="call-1",
                    tool_name=OUTLINE_FLOW_TOOL_NAME,
                    arguments={},
                    spec=spec,
                    assumptions=[],
                    plan_rationale=None,
                    reasoning=None,
                    validation=MagicMock(warnings=[]),
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
    from intric.flows.ai_builder.ai_builder_plan_store import (
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
        plan, _envelope = await store_plan_and_update_conversation(
            repo=repo,
            tenant_id=tenant_id,
            session_id=session_id,
            conversation=[],
            new_messages_start=0,
            base_planning_state_version=0,
            assistant_content="plan ready",
            tool_call_id="call-ps-1",
            tool_name=OUTLINE_FLOW_TOOL_NAME,
            arguments={},
            spec=spec,
            assumptions=[],
            plan_rationale=None,
            reasoning=None,
            validation=MagicMock(warnings=[]),
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
    assert fetched.latest_plan_id == plan.id
    assert loaded_state is not None
    assert loaded_state.planner_contract_version == PLANNER_CONTRACT_VERSION
    # evidence.conversation_message_ids is built from the compacted list
    # that was persisted, so it must match the stored conversation.
    assert loaded_state.evidence.conversation_message_ids == [
        message.message_id for message in fetched.conversation
    ]
    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        stmt = select(BuilderSessions.planning_state_version).where(
            BuilderSessions.id == session_id
        )
        version = (await repo.session.execute(stmt)).scalar_one()
    assert version == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_plan_and_update_conversation_stamps_plan_identity_on_state(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
):
    """After the plan-proposal path persists a plan, the saved PlanningState
    must stamp `draft_plan_id` to the new plan's id and transition `phase`
    to `plan_proposed` so the next turn's reader sees the state is coherent
    with the just-written plan row.
    """
    from intric.flows.ai_builder.ai_builder_plan_store import (
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
        plan, _envelope = await store_plan_and_update_conversation(
            repo=repo,
            tenant_id=tenant_id,
            session_id=session_id,
            conversation=[],
            new_messages_start=0,
            base_planning_state_version=0,
            assistant_content="plan ready",
            tool_call_id="call-identity-1",
            tool_name=OUTLINE_FLOW_TOOL_NAME,
            arguments={},
            spec=spec,
            assumptions=[],
            plan_rationale=None,
            reasoning=None,
            validation=MagicMock(warnings=[]),
            flow=None,
        )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        loaded_state = await repo.load_planning_state(
            session_id=session_id, tenant_id=tenant_id
        )

    assert loaded_state is not None
    assert loaded_state.draft_plan_id == plan.id
    assert loaded_state.phase == "plan_proposed"


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
    PlanningState must reflect the compacted, persisted list — not the
    full pre-compaction one — so the next turn reads coherent state.
    """
    from intric.flows.ai_builder.ai_builder_conversation_compaction import (
        MAX_SESSION_MESSAGES,
    )
    from intric.flows.ai_builder.ai_builder_plan_store import (
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

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        spec = _make_builder_plan_spec(existing_step_ref=None)
        await store_plan_and_update_conversation(
            repo=repo,
            tenant_id=tenant_id,
            session_id=session_id,
            conversation=list(pre_compaction_conversation),
            new_messages_start=0,
            base_planning_state_version=0,
            assistant_content="plan ready",
            tool_call_id="call-cmp-1",
            tool_name=OUTLINE_FLOW_TOOL_NAME,
            arguments={},
            spec=spec,
            assumptions=[],
            plan_rationale=None,
            reasoning=None,
            validation=MagicMock(warnings=[]),
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
    assert loaded_state.evidence.conversation_message_ids == [
        message.message_id for message in fetched.conversation
    ]


def _make_plan_envelope(spec: FlowDraftSpecCore) -> PlannerPlanEnvelope:
    return PlannerPlanEnvelope(
        spec=spec,
        assumptions=[],
        plan_rationale=None,
        reasoning=None,
        lint_warnings=[],
    )


async def _get_latest_plan_id(*, client, bearer_token: str, session_id: str) -> str:
    response = await client.get(
        f"/api/v1/flows/ai-builder/sessions/{session_id}/plans",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 200, response.text
    plans = response.json()["plans"]
    assert plans, response.text
    return plans[0]["plan_id"]


async def _progress_edit_session_to_plan(
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

    for _ in range(4):
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
        "Edit session did not reach a plan within the expected number of turns."
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
        mcp_policy="inherit",
        input_bindings=input_bindings,
        input_contract=None,
        output_contract=None,
        input_config=input_config,
        output_config=None,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_builder_api_repeated_output_question_after_structured_answer_recovers_without_internal_error(
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
        space_name="AI Builder API recovery",
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

    with patch(
        "intric.flows.ai_builder.ai_builder_service.litellm.acompletion"
    ) as mock_completion:
        mock_completion = AsyncMock(
            side_effect=[
                _make_llm_response(tool_calls=[initial_question]),
                _make_llm_response(tool_calls=[repeated_question]),
                _make_llm_response(tool_calls=[requirements_summary]),
            ]
        )

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm.acompletion",
            new=mock_completion,
        ):
            with patch(
                "intric.flows.ai_builder.ai_builder_router._resolve_litellm_params",
                new=AsyncMock(
                    return_value=("openai/gpt-4o-mini", {"api_key": "sk-test"})
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
                    message="Skapa en ljudfil transkriberare samt sammanfattare",
                )
                second_events = await _send_builder_message(
                    client=client,
                    bearer_token=bearer_token,
                    session_id=session_id,
                    message="PDF-dokument",
                    question_answer={
                        "question_id": "final_output_mode",
                        "selected_option_ids": ["pdf_document"],
                        "selected_values": ["pdf_document"],
                        "ui_language": "sv",
                    },
                )

    assert any(event["event"] == "question" for event in first_events)
    assert not any(event["event"] == "error" for event in second_events)
    assert any(
        event["event"] in {"requirements_summary", "question"}
        for event in second_events
    )


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
        "intric.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=mock_completion,
    ):
        with patch(
            "intric.flows.ai_builder.ai_builder_router._resolve_litellm_params",
            new=AsyncMock(return_value=("openai/gpt-4o-mini", {"api_key": "sk-test"})),
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
async def test_ai_builder_api_resolved_architecture_skips_legacy_question_recovery_loop(
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

    mock_completion = AsyncMock(side_effect=AssertionError("LLM should not be called"))

    with patch(
        "intric.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=mock_completion,
    ):
        with patch(
            "intric.flows.ai_builder.ai_builder_router._resolve_litellm_params",
            new=AsyncMock(return_value=("openai/gpt-4o-mini", {"api_key": "sk-test"})),
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
                await repo.update_session_conversation(
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
                    ],
                )
            second_events = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message="Bygg vidare",
            )

    assert not any(event["event"] == "error" for event in second_events)
    assert any(event["event"] == "requirements_summary" for event in second_events)
    mock_completion.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_builder_api_create_mode_can_generate_approve_and_apply_a_flow(
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
        space_name="AI Builder API create/apply",
    )
    async with db_container() as container:
        tenant_id = container.user().tenant_id
    await _create_default_transcription_model(
        db_container=db_container,
        space_id=space_id,
        tenant_id=tenant_id,
    )

    outline_flow = _make_tool_call(
        tool_call_id="call_plan",
        name=OUTLINE_FLOW_TOOL_NAME,
        arguments={
            "flow_name": "Ljudtranskribering till PDF",
            "flow_description": "Transkriberar uppladdat ljud och skapar en PDF-sammanfattning.",
            "plan_rationale": "Transkribera först och generera sedan PDF-sammanfattningen.",
            "runtime_input": {
                "input_type": "text",
                "required": True,
            },
            "final_output_type": "json",
            "steps": [
                {
                    "name": "Transkribera ljud",
                    "task": "Transkribera den uppladdade ljudfilen ordagrant till svensk text.",
                    "output_type": "text",
                },
                {
                    "name": "Skapa PDF-sammanfattning",
                    "task": (
                        "Sammanfatta transkriberingen på tydlig svenska med de "
                        "viktigaste punkterna för en mänsklig läsare."
                    ),
                    "output_type": "text",
                },
                {
                    "name": "Generera PDF-dokument",
                    "task": (
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
        "intric.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=mock_completion,
    ):
        with patch(
            "intric.flows.ai_builder.ai_builder_router._resolve_litellm_params",
            new=AsyncMock(return_value=("openai/gpt-4o-mini", {"api_key": "sk-test"})),
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
                message=(
                    "Skapa ett flöde som tar en ljudfil, transkriberar den och "
                    "sammanfattar innehållet för en mänsklig läsare."
                ),
            )
            second_events = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message="PDF-dokument",
                question_answer={
                    "question_id": "final_output_mode",
                    "selected_option_ids": ["pdf_document"],
                    "selected_values": ["pdf_document"],
                    "ui_language": "sv",
                },
            )
            requirements_event = next(
                event
                for event in second_events
                if event["event"] == "requirements_summary"
            )
            third_events = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message="Ja, det stämmer. Bygg planen.",
                question_answer={
                    "requirements_confirmed": True,
                    "requirements_version": requirements_event["data"][
                        "requirements_version"
                    ],
                    "ui_language": "sv",
                },
            )

    assert any(event["event"] == "question" for event in first_events)
    assert any(event["event"] == "requirements_summary" for event in second_events)
    assert any(event["event"] == "plan" for event in third_events), third_events

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
    assert apply_payload["steps_created"] == 3
    assert apply_payload["steps_updated"] == 0
    assert apply_payload["steps_removed"] == 0

    flow_id = apply_payload["flow_id"]
    flow_response = await client.get(
        f"/api/v1/flows/{flow_id}/",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert flow_response.status_code == 200, flow_response.text
    flow_payload = flow_response.json()
    assert flow_payload["name"] == "Ljudtranskribering till PDF"
    assert len(flow_payload["steps"]) == 3
    assert flow_payload["steps"][0]["input_type"] == "audio"
    assert flow_payload["steps"][0]["output_mode"] == "transcribe_only"
    assert flow_payload["steps"][1]["output_type"] == "text"
    assert flow_payload["steps"][2]["output_type"] == "pdf"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_builder_api_edit_mode_output_only_change_updates_description_and_preserves_assistant(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
    space_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session,
            "AI Builder API edit output-only",
            [model.id],
            user_id=admin_user.id,
        )
        flow_service = container.flow_service()
        original_description = (
            "Tar emot uppladdade ärendedokument vid körning och skapar ett kort "
            "svenskt beslutsunderlag i textformat."
        )
        flow = await flow_service.create_flow(
            space_id=space.id,
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
            update=FlowAssistantUpdateCommand(
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
        space_id = str(space.id)
        flow_id = flow.id
        flow_revision = flow.draft_revision

    requirements_summary = _make_tool_call(
        tool_call_id="call_requirements",
        name="confirm_requirements",
        arguments={
            "summary": "Behåll dokumentflödet men byt slutresultatet till DOCX.",
            "key_decisions": [
                {"topic": "Input", "decision": "Samma dokumentindata som idag"},
                {"topic": "Output", "decision": "DOCX-dokument"},
            ],
            "input_description": "Användaren laddar upp samma ärendedokument som tidigare.",
            "output_description": "Flödet producerar ett DOCX-beslutsunderlag.",
        },
    )
    edit_flow = _make_tool_call(
        tool_call_id="call_edit",
        name="edit_flow",
        arguments={
            "plan_rationale": "Byter bara slutformatet till DOCX och behåller övriga delar.",
            "operations": [
                {
                    "op": "modify",
                    "target_ref": "existing_step_1",
                    "patch": {
                        "output_type": "docx",
                    },
                }
            ],
        },
    )
    mock_completion = AsyncMock(
        side_effect=[
            _make_llm_response(tool_calls=[requirements_summary]),
            _make_llm_response(tool_calls=[edit_flow]),
        ]
    )

    with patch(
        "intric.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=mock_completion,
    ):
        with patch(
            "intric.flows.ai_builder.ai_builder_router._resolve_litellm_params",
            new=AsyncMock(return_value=("openai/gpt-4o-mini", {"api_key": "sk-test"})),
        ):
            session_id = await _create_ai_builder_session(
                client=client,
                bearer_token=bearer_token,
                space_id=space_id,
                target_kind="edit",
                flow_id=str(flow_id),
            )
            plan_events = await _progress_edit_session_to_plan(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                initial_message="Byt slutformat till DOCX men behåll resten av flödet.",
                structured_answers={"docx_output_mode": "generated_docx"},
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
        updated_snapshots = await flow_service.get_flow_assistant_snapshots(updated)

    assert updated.steps[0].output_type == "docx"
    assert updated.description == (
        "Tar emot uppladdade ärendedokument vid körning och skapar ett kort "
        "svenskt beslutsunderlag i DOCX-format."
    )
    assert updated_snapshots[updated.steps[0].assistant_id]["instructions"] == (
        "Skriv ett kort beslutsunderlag i textformat."
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_builder_api_edit_mode_invalid_existing_step_ref_returns_typed_bad_request(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
    space_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session,
            "AI Builder API invalid edit existing ref",
            [model.id],
            user_id=admin_user.id,
        )
        flow_service = container.flow_service()
        flow = await flow_service.create_flow(
            space_id=space.id,
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
        repo = AIBuilderRepository(session)
        builder_session = await repo.create_session(
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            actor_user_id=admin_user.id,
            target_kind=TargetKind.EDIT,
            flow_id=flow.id,
        )
        spec = _make_builder_plan_spec(existing_step_ref="step_a")
        plan = await repo.create_plan(
            session_id=builder_session.id,
            tenant_id=admin_user.tenant_id,
            spec=spec,
            envelope=_make_plan_envelope(spec),
        )
        await repo.update_plan_status(
            plan_id=plan.id,
            tenant_id=admin_user.tenant_id,
            status=PlanStatus.APPROVED,
        )
        flow_revision = flow.draft_revision

    apply_response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{plan.id}/apply",
        json={"expected_revision": flow_revision},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert apply_response.status_code == 400, apply_response.text
    payload = apply_response.json()
    assert payload["code"] == "invalid_existing_step_ref"
    assert payload["intric_error_code"] == 9007


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_builder_api_edit_mode_transcription_insert_clears_stale_runtime_input(
    client,
    bearer_token,
    completion_model_factory,
    db_container,
    space_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session,
            "AI Builder API edit transcription",
            [model.id],
            user_id=admin_user.id,
        )
        flow_service = container.flow_service()

        flow = await flow_service.create_flow(
            space_id=space.id,
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
        space_id = str(space.id)
        flow_id = flow.id
        flow_revision = flow.draft_revision

    await _create_default_transcription_model(
        db_container=db_container,
        space_id=space_id,
        tenant_id=admin_user.tenant_id,
    )

    requirements_summary = _make_tool_call(
        tool_call_id="call_requirements",
        name="confirm_requirements",
        arguments={
            "summary": "Lägg till transkribering först och låt sedan befintligt steg analysera transkriberingen.",
            "key_decisions": [
                {"topic": "Input", "decision": "Ljudfil som transkriberas först"},
                {
                    "topic": "Existing logic",
                    "decision": "Behåll analyssteget men gör det textbaserat",
                },
            ],
            "input_description": "Användaren laddar upp en ljudfil vid körning.",
            "output_description": "Flödet analyserar först transkriberat innehåll vidare.",
        },
    )
    edit_flow = _make_tool_call(
        tool_call_id="call_edit",
        name="edit_flow",
        arguments={
            "plan_rationale": "Lägger till ett transkriberingssteg före analysen och gör analyssteget textbaserat.",
            "operations": [
                {
                    "op": "add",
                    "placement": {
                        "position": "before",
                        "anchor_ref": "existing_step_1",
                    },
                    "add_payload": {
                        "name": "Transkribera ljudfil",
                        "instructions": "Transkribera ljudfilen ordagrant till svensk text.",
                        "input_source": "flow_input",
                        "input_type": "audio",
                        "output_type": "text",
                        "runtime_upload": True,
                        "runtime_required": True,
                    },
                },
                {
                    "op": "modify",
                    "target_ref": "existing_step_1",
                    "patch": {
                        "input_source": "previous_step",
                        "input_type": "text",
                        "assistant_spec": {
                            "instructions": "Analysera transkriberingen."
                        },
                    },
                },
            ],
        },
    )
    mock_completion = AsyncMock(
        side_effect=[
            _make_llm_response(tool_calls=[requirements_summary]),
            _make_llm_response(tool_calls=[edit_flow]),
        ]
    )

    with patch(
        "intric.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=mock_completion,
    ):
        with patch(
            "intric.flows.ai_builder.ai_builder_router._resolve_litellm_params",
            new=AsyncMock(return_value=("openai/gpt-4o-mini", {"api_key": "sk-test"})),
        ):
            session_id = await _create_ai_builder_session(
                client=client,
                bearer_token=bearer_token,
                space_id=space_id,
                target_kind="edit",
                flow_id=str(flow_id),
            )
            plan_events = await _progress_edit_session_to_plan(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                initial_message=(
                    "Lägg till transkribering före det befintliga dokumentsteget men behåll resten."
                ),
                structured_answers={
                    "document_kind": "case_documents",
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
        name=OUTLINE_FLOW_TOOL_NAME,
        arguments={
            "flow_name": "Ljudtranskribering till PDF",
            "flow_description": "Transkriberar uppladdat ljud och skapar en PDF-sammanfattning.",
            "plan_rationale": "Transkribera först och generera sedan PDF-sammanfattningen.",
            "runtime_input": {
                "input_type": "text",
                "required": True,
            },
            "final_output_type": "json",
            "steps": [
                {
                    "name": "Transkribera ljud",
                    "task": "Transkribera den uppladdade ljudfilen ordagrant till svensk text.",
                    "output_type": "text",
                },
                {
                    "name": "Skapa PDF-sammanfattning",
                    "task": (
                        "Sammanfatta transkriberingen på tydlig svenska med de "
                        "viktigaste punkterna för en mänsklig läsare."
                    ),
                    "output_type": "text",
                },
                {
                    "name": "Generera PDF-dokument",
                    "task": (
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
        "intric.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=mock_completion,
    ):
        with patch(
            "intric.flows.ai_builder.ai_builder_router._resolve_litellm_params",
            new=AsyncMock(return_value=("openai/gpt-4o-mini", {"api_key": "sk-test"})),
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
                message=(
                    "Skapa ett flöde som tar en ljudfil, transkriberar den och "
                    "sammanfattar innehållet för en mänsklig läsare."
                ),
            )
            second_events = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message="PDF-dokument",
                question_answer={
                    "question_id": "final_output_mode",
                    "selected_option_ids": ["pdf_document"],
                    "selected_values": ["pdf_document"],
                    "ui_language": "sv",
                },
            )
            requirements_event = next(
                event
                for event in second_events
                if event["event"] == "requirements_summary"
            )
            events = await _send_builder_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                message="Ja, det stämmer. Bygg planen.",
                question_answer={
                    "requirements_confirmed": True,
                    "requirements_version": requirements_event["data"][
                        "requirements_version"
                    ],
                    "ui_language": "sv",
                },
            )

    assert any(event["event"] == "question" for event in first_events)
    assert any(event["event"] == "requirements_summary" for event in second_events)

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
async def test_ai_builder_api_create_mode_strips_invalid_existing_step_ref_and_applies(
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
        spec = _make_builder_plan_spec(existing_step_ref="step_a")
        plan = await repo.create_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            spec=spec,
            envelope=_make_plan_envelope(spec),
        )
        await repo.update_plan_status(
            plan_id=plan.id,
            tenant_id=user.tenant_id,
            status=PlanStatus.APPROVED,
        )
        await repo.update_session_status(
            session_id=session.id,
            tenant_id=user.tenant_id,
            status=SessionStatus.AWAITING_APPROVAL,
        )

    apply_response = await client.post(
        f"/api/v1/flows/ai-builder/plans/{plan.id}/apply",
        json={},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert apply_response.status_code == 200, apply_response.text
    payload = apply_response.json()
    assert payload["steps_created"] == 1
    assert payload["steps_updated"] == 0
    assert payload["steps_removed"] == 0

    flow_response = await client.get(
        f"/api/v1/flows/{payload['flow_id']}/",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert flow_response.status_code == 200, flow_response.text
    flow_payload = flow_response.json()
    assert len(flow_payload["steps"]) == 1
    assert flow_payload["steps"][0]["step_order"] == 1


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
        "intric.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=AsyncMock(
            return_value=_make_llm_response(tool_calls=[requirements_summary])
        ),
    ):
        with patch(
            "intric.flows.ai_builder.ai_builder_router._resolve_litellm_params",
            new=AsyncMock(return_value=("openai/gpt-4o-mini", {"api_key": "sk-test"})),
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
