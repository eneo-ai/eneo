"""Tests for AI Builder service."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4


@asynccontextmanager
async def _noop_savepoint() -> AsyncIterator[None]:
    """Drop-in async context manager so AsyncMock repos can satisfy
    `async with repo.savepoint():` in unit tests without needing a live
    database.
    """
    yield


def _make_repo_mock() -> AsyncMock:
    """Return an `AsyncMock` repo wired with a working `savepoint()`
    context manager so tests exercising proposal submission
    can enter its savepoint without tripping the async-CM protocol.
    """
    repo = AsyncMock()
    repo.savepoint = _noop_savepoint
    repo.load_planning_state = AsyncMock(return_value=None)
    return repo


import pytest
from litellm.exceptions import BadRequestError, RateLimitError

from eneo.authentication.auth_models import ApiKeyPermission, ApiKeyScopeType
from eneo.authentication.principal_types import PrincipalType
from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.completion_models.infrastructure.completion_service import (
    ResolvedCompletionModelRoute,
)
from eneo.files.file_models import File, FileType
from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AI_BUILDER_MAX_ATTACHMENTS,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    PROVIDER_TOOL_CALL_ID_MAX_LENGTH,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    BuilderSession,
    ConversationMessage,
    FlowBuilderProposal,
    FlowBuilderProposalContent,
    PlanStatus,
    SessionStatus,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
    AIBuilderProviderOutcomeUnknownException,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    SSE_EVENT_REQUIREMENTS_SUMMARY,
    RequirementsSummaryPayload,
)
from eneo.flows.ai_builder.ai_builder_events import (
    build_done_event,
    encode_ai_builder_stream_event,
)
from eneo.flows.ai_builder.ai_builder_plan_lifecycle import AIBuilderPlanLifecycle
from eneo.flows.ai_builder.ai_builder_planner import AIBuilderPlanner
from eneo.flows.ai_builder.ai_builder_planner_request_preparation import (
    conversation_message_to_llm_message,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    build_requirements_version,
)
from eneo.flows.ai_builder.ai_builder_service import (
    QUALITY_RETRY_WARNING_CODES,
    SSE_EVENT_DONE,
    SSE_EVENT_ERROR,
    SSE_EVENT_QUESTION,
    SSE_EVENT_TEXT,
    AIBuilderService,
    PreparedMessageContext,
)
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionTurnAcceptance,
    SessionTurnClaim,
    SessionTurnClaimDisposition,
    SessionTurnPreflight,
    SessionTurnPreparationBaseline,
)
from eneo.flows.ai_builder.ai_builder_tool_names import PROPOSE_FLOW_TOOL_NAME
from eneo.flows.ai_builder.ai_builder_turn_controller import (
    ConfirmRequirements,
    resolve_turn_control,
)
from eneo.flows.ai_builder.planning_state import (
    PlanningState,
    ResolvedSlot,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    StepSpec,
)
from eneo.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)
from eneo.main.exceptions import BadRequestException, UnauthorizedException

_TEST_CLIENT_TURN_ID = UUID("11111111-1111-4111-8111-111111111111")
_TEST_REQUEST_FINGERPRINT = "a" * 64


def _test_request_snapshot(message: str) -> FlowPersistedJsonObject:
    return {
        "client_turn_id": str(_TEST_CLIENT_TURN_ID),
        "message": message,
    }


def _route(
    *,
    model: str = "openai/gpt-4",
    kwargs: dict[str, object] | None = None,
    supported: SupportedModelKwargs | None = None,
) -> ResolvedCompletionModelRoute:
    return ResolvedCompletionModelRoute(
        litellm_model=model,
        provider_type="openai",
        litellm_kwargs=kwargs or {},
        supported_model_kwargs=supported
        or SupportedModelKwargs(temperature=ModelKwargCapability(supported=True)),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_quality_retry_codes_exclude_informational_policy_warnings() -> None:
    assert (
        not {
            "vague_step_name",
            "unused_form_field",
        }
        & QUALITY_RETRY_WARNING_CODES
    )


def _make_user(
    *,
    user_id: UUID | None = None,
    tenant_id: UUID | None = None,
) -> MagicMock:
    user = MagicMock()
    user.id = user_id or uuid4()
    user.tenant_id = tenant_id or uuid4()
    user.active_api_key = None
    return user


def _make_space_service() -> AsyncMock:
    space_service = AsyncMock()
    space = MagicMock()
    space.get_default_transcription_model.return_value = None
    space.completion_models = []
    space.collections = []
    space.mcp_servers = []
    space_service.get_space.return_value = space
    return space_service


def _make_session(
    *,
    session_id: UUID | None = None,
    tenant_id: UUID | None = None,
    space_id: UUID | None = None,
    flow_id: UUID | None = None,
    target_kind: TargetKind = TargetKind.CREATE,
    status: SessionStatus = SessionStatus.CHATTING,
    actor_user_id: UUID | None = None,
    conversation: list[ConversationMessage] | None = None,
    latest_plan_id: UUID | None = None,
) -> BuilderSession:
    return BuilderSession(
        id=session_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        space_id=space_id or uuid4(),
        flow_id=flow_id,
        target_kind=target_kind,
        status=status,
        actor_user_id=actor_user_id or uuid4(),
        conversation=conversation or [],
        latest_plan_id=latest_plan_id,
    )


def _make_plan(
    *,
    plan_id: UUID | None = None,
    session_id: UUID | None = None,
    tenant_id: UUID | None = None,
    status: PlanStatus = PlanStatus.PROPOSED,
    spec: FlowDraftSpecCore | None = None,
    resource_bindings: tuple[LocalResourceBinding, ...] = tuple(),
    description_override_manual: bool = False,
) -> BuilderPlan:
    if spec is None:
        spec = FlowDraftSpecCore(
            flow_name="Test",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Step A",
                    assistant_spec=AssistantSpec(instructions="Do something."),
                    input_source=InputSource.FLOW_INPUT,
                )
            ],
        )
    return BuilderPlan(
        id=plan_id or uuid4(),
        session_id=session_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        status=status,
        proposal=FlowBuilderProposal(
            content=FlowBuilderProposalContent(
                spec=spec,
                assumptions=["Test assumption"],
                description_override_manual=description_override_manual,
            ),
            resource_bindings=resource_bindings,
        ),
    )


def _make_resource_binding() -> LocalResourceBinding:
    return LocalResourceBinding(
        slot_ref=ResourceSlotRef(
            kind=ResourceSlotKind.MODEL,
            slot="fast-model",
            label="Fast model",
        ),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=uuid4(),
    )


def _make_service(
    user: MagicMock | None = None,
    repo: AsyncMock | None = None,
    flow_service: AsyncMock | None = None,
    completion_service: Any | None = None,
    space_service: AsyncMock | None = None,
) -> AIBuilderService:
    if repo is None:
        repo = AsyncMock()

    async def accept_turn(**kwargs: object) -> SessionTurnClaim:
        acceptance = cast(SessionTurnAcceptance, kwargs["acceptance"])
        session = repo.get_session.return_value
        session.conversation = [*session.conversation, acceptance.user_message]
        return SessionTurnClaim(
            disposition=SessionTurnClaimDisposition.EXECUTE,
            user_message=acceptance.user_message,
            base_planning_state_version=session.planning_state_version,
        )

    async def preflight_turn(**_: object) -> SessionTurnPreflight:
        session = repo.get_session.return_value
        if session.status not in {
            SessionStatus.CHATTING,
            SessionStatus.AWAITING_APPROVAL,
        }:
            raise AIBuilderBadRequestException(
                "Cannot send messages in this AI Builder session right now.",
                code=AIBuilderErrorCode.INVALID_SESSION_TRANSITION,
            )
        return SessionTurnPreflight(
            session=session,
            baseline=SessionTurnPreparationBaseline(
                session_status=session.status,
                latest_plan_id=session.latest_plan_id,
                planning_state_version=session.planning_state_version,
                latest_turn_id=(
                    session.latest_turn.client_turn_id
                    if session.latest_turn is not None
                    else None
                ),
                latest_turn_state=(
                    session.latest_turn.state
                    if session.latest_turn is not None
                    else None
                ),
                attachment_file_ids=(),
            ),
        )

    repo.accept_session_turn.side_effect = accept_turn
    repo.preflight_session_turn.side_effect = preflight_turn
    repo.list_session_file_ids.return_value = []
    repo.load_planning_state.return_value = None
    resolved_completion_service = completion_service or AsyncMock()
    return AIBuilderService(
        user=user or _make_user(),
        repo=repo,
        flow_service=flow_service or AsyncMock(),
        completion_service=resolved_completion_service,
        space_service=space_service or _make_space_service(),
        template_asset_service=AsyncMock(),
    )


def _make_file(
    *,
    file_id: UUID | None = None,
    tenant_id: UUID | None = None,
    owner_user_id: UUID | None = None,
    name: str = "reference.txt",
    text: str | None = "Reference material",
    mimetype: str = "text/plain",
    file_type: FileType = FileType.TEXT,
    transcription: str | None = None,
    blob: bytes | None = None,
) -> File:
    resolved_owner_user_id = owner_user_id or uuid4()
    resolved_text = text or ""
    resolved_blob = blob or None
    return File(
        id=file_id or uuid4(),
        name=name,
        checksum="checksum",
        size=max(
            1,
            len(resolved_text.encode("utf-8"))
            if text is not None
            else len(resolved_blob or b""),
        ),
        mimetype=mimetype,
        file_type=file_type,
        text=text,
        blob=resolved_blob,
        transcription=transcription,
        owner_type=PrincipalType.USER,
        owner_user_id=resolved_owner_user_id,
        tenant_id=tenant_id or uuid4(),
    )


def _make_requirements_decision() -> ConfirmRequirements:
    decision = resolve_turn_control(
        session_state=_make_committed_planning_state(),
        selected_discovery_question_ids=(),
        confirmed_attachment_evidence_fingerprint=None,
        ui_language="en",
    ).decision
    assert isinstance(decision, ConfirmRequirements)
    return decision


def _make_requirements_summary_payload() -> RequirementsSummaryPayload:
    return _make_requirements_decision().payload


def _make_requirements_confirmation() -> dict[str, Any]:
    version = build_requirements_version(_make_requirements_summary_payload())
    return {
        "requirements_confirmed": True,
        "requirements_version": version,
    }


def _make_committed_planning_state() -> PlanningState:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="documents",
            source="requirements_summary",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_text",
            source="requirements_summary",
            confidence="high",
        ),
        "document_material_scope": ResolvedSlot(
            name="document_material_scope",
            value="flexible_document_case",
            source="policy_default",
            confidence="medium",
        ),
        "runtime_metadata_fields": ResolvedSlot(
            name="runtime_metadata_fields",
            value="no_extra_metadata",
            source="policy_default",
            confidence="medium",
        ),
    }
    architecture_draft = derive_architecture_commit_draft(state)
    assert architecture_draft is not None
    state.architecture_commit = finalize_architecture_commit(
        architecture_draft,
        now=lambda: datetime(2026, 4, 24, tzinfo=timezone.utc),
    )
    return state


def _make_confirmed_requirements_conversation() -> list[ConversationMessage]:
    decision = _make_requirements_decision()
    summary = decision.payload
    version = build_requirements_version(summary)
    summary_data = summary.model_dump(mode="json")
    return [
        ConversationMessage(
            role="assistant",
            content="Requirements presented to user. Awaiting confirmation.",
            metadata={
                "requirements_summary": summary_data,
                "requirements_version": version,
                "attachment_evidence_fingerprint": (
                    decision.attachment_evidence_fingerprint
                ),
            },
        ),
    ]


def _requirement_answer_message(
    *,
    question_id: str,
    value: str,
    content: str,
    ui_language: str = "sv",
) -> ConversationMessage:
    return ConversationMessage(
        role="user",
        content=content,
        metadata={
            "question_answer": {
                "question_id": question_id,
                "selected_option_ids": [value],
                "selected_values": [value],
            },
            "ui_language": ui_language,
        },
    )


def _make_llm_response(
    *,
    content: str | None = "Hello!",
    tool_calls: list[Any] | None = None,
) -> MagicMock:
    """Create a mock litellm response."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_tool_call(
    *,
    tool_call_id: str = "call_123",
    name: str = PROPOSE_FLOW_TOOL_NAME,
    arguments: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock tool call."""
    arguments = _normalize_tool_arguments(name=name, arguments=arguments)
    tc = MagicMock()
    tc.id = tool_call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    return tc


def _normalize_tool_arguments(
    *,
    name: str,
    arguments: dict[str, Any] | None,
) -> dict[str, Any]:
    if name != PROPOSE_FLOW_TOOL_NAME:
        return arguments or {}
    if arguments is None:
        return {
            "flow_name": "Test Flow",
            "plan_rationale": "Extrahera först och strukturera sedan resultatet.",
            "final_output_type": "text",
            "steps": [
                {
                    "name": "Extrahera fakta",
                    "instructions": "Extrahera fakta.",
                    "output_type": "text",
                }
            ],
        }

    normalized = dict(arguments)
    normalized.setdefault(
        "plan_rationale",
        "Bygg flödet från tydliga steg med backend-härledda kontrakt.",
    )
    steps = normalized.get("steps")
    if isinstance(steps, list):
        normalized["steps"] = [_normalize_create_step(step) for step in steps]
    normalized.setdefault("final_output_type", "text")
    return normalized


def _normalize_create_step(step: Any) -> Any:
    if not isinstance(step, dict):
        return step

    assistant_spec = step.get("assistant_spec") or {}
    output_type = step.get("output_type", "text")
    output_mode = step.get("output_mode")

    normalized: dict[str, Any] = {
        "name": step.get("name", "Step"),
        "instructions": step.get("instructions")
        or assistant_spec.get("instructions")
        or "Do things.",
        "output_type": "text" if output_mode == "transcribe_only" else output_type,
    }
    if normalized["output_type"] == "docx":
        normalized["output_type"] = "docx"
    output_config = step.get("output_config") or {}
    if output_config.get("citations", {}).get("enabled"):
        normalized["citations_requested"] = True
    if step.get("output_contract"):
        normalized["output_fields"] = _output_fields_from_schema(
            step["output_contract"]
        )
    return normalized


def _output_fields_from_schema(schema: dict[str, Any]) -> list[dict[str, Any]]:
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    fields: list[dict[str, Any]] = []
    for field_name, definition in properties.items():
        field_type = definition.get("type", "string")
        field: dict[str, Any] = {
            "name": field_name,
            "field_type": field_type
            if field_type in {"string", "number", "boolean", "object", "array"}
            else "string",
            "description": definition.get("description", f"{field_name} field."),
            "required": field_name in required,
        }
        if field["field_type"] == "object":
            field["fields"] = _output_fields_from_schema(definition)
        if field["field_type"] == "array":
            item_schema = definition.get("items") or {"type": "string"}
            field["item_fields"] = [
                {
                    "name": f"{field_name}_item",
                    "field_type": item_schema.get("type", "string"),
                    "description": item_schema.get(
                        "description", f"One {field_name} item."
                    ),
                    "required": True,
                }
            ]
        fields.append(field)
    return fields


def _make_model() -> MagicMock:
    model = MagicMock()
    model.id = uuid4()
    model.name = "test-model"
    return model


def _make_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.litellm_model = "openai/gpt-4"
    adapter.credential_resolver.get_api_key.return_value = "sk-test"
    adapter.credential_resolver.get_credential_field.return_value = None
    return adapter


async def _collect_events(gen) -> list[dict[str, str]]:
    events = []
    async for event in gen:
        events.append(encode_ai_builder_stream_event(event))
    return events


# ---------------------------------------------------------------------------
# Session lifecycle tests
# ---------------------------------------------------------------------------


class TestCreateSession:
    @pytest.mark.anyio
    async def test_create_edit_session_reuses_existing_matching_draft(self):
        user = _make_user()
        repo = AsyncMock()
        flow_id = uuid4()
        space_id = uuid4()
        existing = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            target_kind=TargetKind.EDIT,
            flow_id=flow_id,
            space_id=space_id,
        )
        repo.find_latest_resumable_session.return_value = existing
        flow_service = AsyncMock()
        flow_service.get_flow.return_value = SimpleNamespace(
            id=flow_id,
            space_id=space_id,
        )
        service = _make_service(user=user, repo=repo, flow_service=flow_service)

        result = await service.create_session(
            space_id=existing.space_id,
            target_kind=TargetKind.EDIT,
            flow_id=existing.flow_id,
        )

        assert result == existing
        repo.create_session.assert_not_called()

    @pytest.mark.anyio
    async def test_create_session_does_not_auto_resume_existing_draft(self):
        user = _make_user()
        repo = AsyncMock()
        repo.find_latest_resumable_session.return_value = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
        )
        repo.create_session.return_value = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
        )
        service = _make_service(user=user, repo=repo)

        await service.create_session(
            space_id=uuid4(),
            target_kind=TargetKind.CREATE,
        )

        repo.find_latest_resumable_session.assert_not_called()
        repo.create_session.assert_called_once()

    @pytest.mark.anyio
    async def test_create_session_creates_and_returns(self):
        user = _make_user()
        repo = AsyncMock()
        repo.find_latest_resumable_session.return_value = None
        expected = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
        )
        repo.create_session.return_value = expected

        service = _make_service(user=user, repo=repo)
        space_id = uuid4()
        result = await service.create_session(
            space_id=space_id,
            target_kind=TargetKind.CREATE,
        )

        assert result == expected
        repo.create_session.assert_called_once_with(
            tenant_id=user.tenant_id,
            space_id=space_id,
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )

    @pytest.mark.anyio
    async def test_create_edit_session_without_flow_id_raises(self):
        service = _make_service()
        with pytest.raises(BadRequestException, match="flow_id is required"):
            await service.create_session(
                space_id=uuid4(),
                target_kind=TargetKind.EDIT,
                flow_id=None,
            )

    @pytest.mark.anyio
    async def test_create_edit_session_verifies_flow_exists(self):
        flow_service = AsyncMock()
        repo = AsyncMock()
        repo.find_latest_resumable_session.return_value = None
        service = _make_service(flow_service=flow_service, repo=repo)
        flow_id = uuid4()
        space_id = uuid4()
        flow_service.get_flow.return_value = SimpleNamespace(
            id=flow_id,
            space_id=space_id,
        )

        await service.create_session(
            space_id=space_id,
            target_kind=TargetKind.EDIT,
            flow_id=flow_id,
        )

        flow_service.get_flow.assert_called_once_with(flow_id)

    @pytest.mark.anyio
    async def test_create_edit_session_rejects_flow_space_mismatch(self):
        flow_service = AsyncMock()
        repo = AsyncMock()
        repo.find_latest_resumable_session.return_value = None
        service = _make_service(flow_service=flow_service, repo=repo)
        flow_id = uuid4()
        flow_service.get_flow.return_value = SimpleNamespace(
            id=flow_id,
            space_id=uuid4(),
        )

        with pytest.raises(BadRequestException, match="space"):
            await service.create_session(
                space_id=uuid4(),
                target_kind=TargetKind.EDIT,
                flow_id=flow_id,
            )

    @pytest.mark.anyio
    async def test_create_session_with_nonexistent_flow_propagates_error(self):
        flow_service = AsyncMock()
        flow_service.get_flow.side_effect = Exception("Flow not found")
        repo = AsyncMock()
        repo.find_latest_resumable_session.return_value = None
        service = _make_service(flow_service=flow_service, repo=repo)

        with pytest.raises(Exception, match="Flow not found"):
            await service.create_session(
                space_id=uuid4(),
                target_kind=TargetKind.EDIT,
                flow_id=uuid4(),
            )

    @pytest.mark.anyio
    async def test_force_new_cancels_matching_draft_before_creating(self):
        user = _make_user()
        repo = AsyncMock()
        repo.create_session.return_value = _make_session(
            tenant_id=user.tenant_id, actor_user_id=user.id
        )
        service = _make_service(user=user, repo=repo)
        space_id = uuid4()

        await service.create_session(
            space_id=space_id,
            target_kind=TargetKind.CREATE,
            force_new=True,
        )

        repo.cancel_matching_active_sessions.assert_called_once_with(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            space_id=space_id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )

    @pytest.mark.anyio
    async def test_create_session_serializes_creation_before_resume_or_create(self):
        user = _make_user()
        repo = AsyncMock()
        repo.find_latest_resumable_session.return_value = None
        repo.create_session.return_value = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            target_kind=TargetKind.EDIT,
        )
        flow_id = uuid4()
        space_id = uuid4()
        flow_service = AsyncMock()
        flow_service.get_flow.return_value = SimpleNamespace(
            id=flow_id,
            space_id=space_id,
        )
        service = _make_service(user=user, repo=repo, flow_service=flow_service)

        await service.create_session(
            space_id=space_id,
            target_kind=TargetKind.EDIT,
            flow_id=flow_id,
        )

        repo.acquire_session_creation_lock.assert_awaited_once_with(
            tenant_id=user.tenant_id
        )
        method_order = [call[0] for call in repo.mock_calls]
        lock_index = method_order.index("acquire_session_creation_lock")
        resume_index = method_order.index("find_latest_resumable_session")
        create_index = method_order.index("create_session")
        assert lock_index < resume_index < create_index

    @pytest.mark.anyio
    async def test_force_new_supersedes_actionable_plans_on_cancelled_sessions(self):
        user = _make_user()
        repo = AsyncMock()
        repo.cancel_matching_active_sessions.return_value = [uuid4(), uuid4()]
        repo.create_session.return_value = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            target_kind=TargetKind.EDIT,
        )
        flow_id = uuid4()
        space_id = uuid4()
        flow_service = AsyncMock()
        flow_service.get_flow.return_value = SimpleNamespace(
            id=flow_id,
            space_id=space_id,
        )
        service = _make_service(
            user=user,
            repo=repo,
            flow_service=flow_service,
        )

        await service.create_session(
            space_id=space_id,
            target_kind=TargetKind.EDIT,
            flow_id=flow_id,
            force_new=True,
        )

        assert repo.supersede_existing_plans.await_count == 2
        superseded_session_ids = {
            call.kwargs["session_id"]
            for call in repo.supersede_existing_plans.await_args_list
        }
        assert superseded_session_ids == set(
            repo.cancel_matching_active_sessions.return_value
        )


class TestSessionRecovery:
    @pytest.mark.anyio
    async def test_list_sessions_builds_draft_titles_from_latest_plan(self):
        user = _make_user()
        repo = AsyncMock()
        session = _make_session(
            tenant_id=user.tenant_id, actor_user_id=user.id, latest_plan_id=uuid4()
        )
        repo.list_sessions_with_draft_titles.return_value = [
            (session, "Recovered Draft")
        ]
        service = _make_service(user=user, repo=repo)

        result = await service.list_sessions()

        assert result[0].draft_title == "Recovered Draft"
        assert result[0].space_id == session.space_id
        repo.list_sessions_with_draft_titles.assert_awaited_once_with(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            actor_user_group_ids=user.user_groups_ids,
            scoped_space_id=None,
        )
        repo.get_plan.assert_not_called()

    @pytest.mark.anyio
    async def test_list_sessions_preserves_read_only_api_key_edit_constraint(self):
        user = _make_user()
        user.active_api_key = MagicMock(permission=ApiKeyPermission.READ)
        repo = AsyncMock()
        repo.list_sessions_with_draft_titles.return_value = []
        service = _make_service(user=user, repo=repo)

        assert await service.list_sessions() == []
        repo.list_sessions_with_draft_titles.assert_not_awaited()

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("scope_type", "space_lookup"),
        [
            ("assistant", "get_space_by_assistant"),
            ("app", "get_space_by_app"),
        ],
    )
    async def test_list_sessions_preserves_resource_scope_constraint(
        self,
        scope_type: str,
        space_lookup: str,
    ):
        user = _make_user()
        resource_id = uuid4()
        user.active_api_key = MagicMock(
            permission=ApiKeyPermission.WRITE,
            scope_type=ApiKeyScopeType(scope_type),
            scope_id=resource_id,
        )
        repo = AsyncMock()
        repo.list_sessions_with_draft_titles.return_value = []
        space_service = _make_space_service()
        scoped_space_id = uuid4()
        lookup = getattr(space_service, space_lookup)
        lookup.return_value.id = scoped_space_id
        service = _make_service(user=user, repo=repo, space_service=space_service)

        assert await service.list_sessions() == []

        repo.list_sessions_with_draft_titles.assert_awaited_once_with(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            actor_user_group_ids=user.user_groups_ids,
            scoped_space_id=scoped_space_id,
        )
        lookup.assert_awaited_once_with(resource_id)

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("scope_type", "scope_id"),
        [
            (ApiKeyScopeType.SPACE, uuid4()),
            (ApiKeyScopeType.TENANT, None),
        ],
    )
    async def test_list_sessions_preserves_space_and_tenant_scope_constraints(
        self,
        scope_type: ApiKeyScopeType,
        scope_id: UUID | None,
    ):
        user = _make_user()
        user.active_api_key = MagicMock(
            permission=ApiKeyPermission.WRITE,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        repo = AsyncMock()
        repo.list_sessions_with_draft_titles.return_value = []
        service = _make_service(user=user, repo=repo)

        assert await service.list_sessions() == []
        repo.list_sessions_with_draft_titles.assert_awaited_once_with(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            actor_user_group_ids=user.user_groups_ids,
            scoped_space_id=scope_id,
        )

    @pytest.mark.anyio
    async def test_list_sessions_keeps_sessions_without_latest_plan_title(self):
        user = _make_user()
        repo = AsyncMock()
        session = _make_session(tenant_id=user.tenant_id, actor_user_id=user.id)
        repo.list_sessions_with_draft_titles.return_value = [(session, None)]
        service = _make_service(user=user, repo=repo)

        result = await service.list_sessions()

        assert result[0].draft_title is None
        assert result[0].session_id == session.id
        repo.get_plan.assert_not_called()

    @pytest.mark.anyio
    async def test_cancel_session_updates_status_and_returns_session(self):
        user = _make_user()
        repo = AsyncMock()
        session = _make_session(tenant_id=user.tenant_id, actor_user_id=user.id)
        cancelled = _make_session(
            session_id=session.id,
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            status=SessionStatus.CANCELLED,
        )
        repo.get_session.side_effect = [session, cancelled]
        service = _make_service(user=user, repo=repo)

        result = await service.cancel_session(session.id)

        assert result.status == SessionStatus.CANCELLED
        repo.cancel_session.assert_called_once_with(
            session_id=session.id,
            tenant_id=user.tenant_id,
        )


class TestGetSession:
    @pytest.mark.anyio
    async def test_get_session_returns_session(self):
        user = _make_user()
        repo = AsyncMock()
        expected = _make_session(tenant_id=user.tenant_id)
        repo.get_session.return_value = expected

        service = _make_service(user=user, repo=repo)
        result = await service.get_session(expected.id)

        assert result == expected
        repo.get_session.assert_called_once_with(
            session_id=expected.id,
            tenant_id=user.tenant_id,
        )


class TestGetPlan:
    @pytest.mark.anyio
    async def test_get_plan_returns_plan(self):
        user = _make_user()
        repo = AsyncMock()
        expected = _make_plan(tenant_id=user.tenant_id)
        repo.get_plan.return_value = expected

        service = _make_service(user=user, repo=repo)
        result = await service.get_plan(expected.id)

        assert result == expected
        repo.get_plan.assert_called_once_with(
            plan_id=expected.id,
            tenant_id=user.tenant_id,
        )

    @pytest.mark.anyio
    async def test_list_session_plans_returns_plans(self):
        user = _make_user()
        repo = AsyncMock()
        session = _make_session(tenant_id=user.tenant_id)
        expected = [_make_plan(session_id=session.id, tenant_id=user.tenant_id)]
        repo.list_session_plans.return_value = expected

        service = _make_service(user=user, repo=repo)
        result = await service.list_session_plans(session.id)

        assert result == expected
        repo.list_session_plans.assert_called_once_with(
            session_id=session.id,
            tenant_id=user.tenant_id,
        )


class TestServiceComposition:
    @pytest.mark.anyio
    async def test_send_message_delegates_to_planner(self):
        service = _make_service()
        service.repo.get_session.return_value = _make_session(
            tenant_id=service.user.tenant_id
        )

        async def planner_events():
            yield build_done_event()

        with patch.object(
            AIBuilderPlanner,
            "send_message",
            return_value=planner_events(),
        ) as mock_send_message:
            events = await _collect_events(
                service.send_message(
                    session_id=uuid4(),
                    client_turn_id=_TEST_CLIENT_TURN_ID,
                    request_fingerprint=_TEST_REQUEST_FINGERPRINT,
                    request_snapshot=_test_request_snapshot("Build a flow"),
                    message="Build a flow",
                    completion_model_route=_route(kwargs={"api_key": "sk-test"}),
                )
            )

        assert events == [{"event": SSE_EVENT_DONE, "data": ""}]
        mock_send_message.assert_called_once()
        assert mock_send_message.call_args.kwargs["message"] == "Build a flow"

    @pytest.mark.anyio
    async def test_approve_plan_delegates_to_lifecycle(self):
        service = _make_service()
        plan = _make_plan()

        with patch.object(
            AIBuilderPlanLifecycle,
            "approve_plan",
            new=AsyncMock(return_value=plan),
        ) as mock_approve_plan:
            result = await service.approve_plan(plan_id=plan.id)

        assert result == plan
        mock_approve_plan.assert_awaited_once_with(plan_id=plan.id)

    @pytest.mark.anyio
    async def test_apply_plan_delegates_to_lifecycle(self):
        service = _make_service()
        expected = MagicMock()
        plan_id = uuid4()

        with patch.object(
            AIBuilderPlanLifecycle,
            "apply_plan",
            new=AsyncMock(return_value=expected),
        ) as mock_apply_plan:
            result = await service.apply_plan(
                plan_id=plan_id,
                expected_revision=7,
            )

        assert result == expected
        mock_apply_plan.assert_awaited_once_with(
            plan_id=plan_id,
            expected_revision=7,
        )


class TestPlannerContextPreparation:
    @pytest.mark.anyio
    async def test_prepare_message_context_prefetches_planner_and_flow_context(self):
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()
        completion_service = AsyncMock()

        model = _make_model()
        model.max_input_tokens = 4096
        model.max_output_tokens = 2048
        model.provider_type = "openai"

        space = MagicMock()
        space.completion_models = [model]
        space.collections = []
        space.get_default_completion_model.return_value = model

        session = _make_session(
            tenant_id=user.tenant_id,
            flow_id=uuid4(),
        )
        flow = MagicMock()
        flow.id = session.flow_id
        flow.space_id = session.space_id
        snapshots = {uuid4(): {"name": "Assistant"}}
        flow_service.get_flow.return_value = flow
        flow_service.get_flow_assistant_snapshots.return_value = snapshots
        completion_service.resolve_model_route.return_value = _route(
            model="azure/gpt-4",
            kwargs={
                "api_key": "sk-test",
                "api_base": "https://azure.example.com",
                "temperature": 0.7,
                "additional_drop_params": ["top_p"],
                "tools": [{"type": "function"}],
                "tool_choice": "auto",
                "function_call": "auto",
            },
        )

        service = _make_service(
            user=user,
            repo=repo,
            flow_service=flow_service,
            completion_service=completion_service,
        )

        result = await service.prepare_message_context(
            session=session,
            space=space,
            model_id=model.id,
            tenant_flow_settings=None,
        )

        assert isinstance(result, PreparedMessageContext)
        assert result.completion_model_route.litellm_model == "azure/gpt-4"
        assert result.completion_model_route.litellm_kwargs == {
            "api_key": "sk-test",
            "api_base": "https://azure.example.com",
            "temperature": 0.7,
            "additional_drop_params": ["top_p"],
        }
        assert result.flow is flow
        assert result.assistant_snapshots == snapshots
        assert result.planner_context.available_models == [
            {
                "id": str(model.id),
                "ref": str(model.id),
                "name": "test-model",
                "display_name": "test-model",
                "provider": "openai",
            }
        ]
        completion_service.resolve_model_route.assert_awaited_once_with(model)
        flow_service.get_flow.assert_awaited_once_with(session.flow_id)
        flow_service.get_flow_assistant_snapshots.assert_awaited_once_with(flow)

    @pytest.mark.anyio
    async def test_prepare_message_context_accepts_exact_merged_attachment_limit(
        self,
    ) -> None:
        user = _make_user()
        repo = AsyncMock()
        file_service = AsyncMock()
        model = _make_model()
        model.max_input_tokens = 4096
        model.max_output_tokens = 2048
        model.provider_type = "openai"
        space = MagicMock()
        space.completion_models = [model]
        space.collections = []
        space.get_default_completion_model.return_value = model
        session = _make_session(tenant_id=user.tenant_id)
        persisted_files = [
            _make_file(tenant_id=user.tenant_id, owner_user_id=user.id)
            for _ in range(AI_BUILDER_MAX_ATTACHMENTS - 1)
        ]
        current_file = _make_file(tenant_id=user.tenant_id, owner_user_id=user.id)
        files_by_id = {file.id: file for file in [*persisted_files, current_file]}
        repo.list_session_file_ids.return_value = [file.id for file in persisted_files]
        file_service.get_files_by_ids.side_effect = lambda file_ids: [
            files_by_id[file_id] for file_id in file_ids
        ]
        completion_service = AsyncMock()
        completion_service.resolve_model_route.return_value = _route(
            model="openai/gpt-test"
        )
        service = AIBuilderService(
            user=user,
            repo=repo,
            flow_service=AsyncMock(),
            completion_service=completion_service,
            space_service=AsyncMock(),
            template_asset_service=AsyncMock(),
            file_service=file_service,
        )

        context = await service.prepare_message_context(
            session=session,
            space=space,
            model_id=None,
            tenant_flow_settings=None,
            message_file_ids=[current_file.id],
        )

        assert len(context.attachment_files) == AI_BUILDER_MAX_ATTACHMENTS
        assert {file.id for file in context.attachment_files} == set(files_by_id)

    @pytest.mark.anyio
    async def test_prepare_message_context_rejects_merged_attachment_limit_plus_one(
        self,
    ) -> None:
        user = _make_user()
        repo = AsyncMock()
        file_service = AsyncMock()
        model = _make_model()
        model.max_input_tokens = 4096
        model.max_output_tokens = 2048
        model.provider_type = "openai"
        space = MagicMock()
        space.completion_models = [model]
        space.collections = []
        space.get_default_completion_model.return_value = model
        session = _make_session(tenant_id=user.tenant_id)
        repo.list_session_file_ids.return_value = [
            uuid4() for _ in range(AI_BUILDER_MAX_ATTACHMENTS - 1)
        ]
        current_file_ids = [uuid4(), uuid4()]
        completion_service = AsyncMock()
        service = AIBuilderService(
            user=user,
            repo=repo,
            flow_service=AsyncMock(),
            completion_service=completion_service,
            space_service=AsyncMock(),
            template_asset_service=AsyncMock(),
            file_service=file_service,
        )

        with pytest.raises(
            AIBuilderBadRequestException,
            match=f"at most {AI_BUILDER_MAX_ATTACHMENTS}",
        ) as error:
            await service.prepare_message_context(
                session=session,
                space=space,
                model_id=None,
                tenant_flow_settings=None,
                message_file_ids=current_file_ids,
            )

        assert error.value.code is AIBuilderErrorCode.BAD_REQUEST
        assert "Detach an existing attachment" in str(error.value)
        file_service.get_files_by_ids.assert_not_awaited()
        completion_service.resolve_model_route.assert_not_awaited()

    @pytest.mark.anyio
    async def test_prepare_message_context_enforces_resolved_builder_operating_limits(
        self,
    ) -> None:
        user = _make_user()
        repo = AsyncMock()
        repo.list_session_file_ids.return_value = [uuid4()]
        file_service = AsyncMock()
        model = _make_model()
        model.max_input_tokens = 4096
        model.max_output_tokens = 2048
        model.provider_type = "openai"
        space = MagicMock()
        space.completion_models = [model]
        space.collections = []
        space.get_default_completion_model.return_value = model
        service = AIBuilderService(
            user=user,
            repo=repo,
            flow_service=AsyncMock(),
            completion_service=AsyncMock(),
            space_service=AsyncMock(),
            template_asset_service=AsyncMock(),
            file_service=file_service,
        )

        with pytest.raises(
            AIBuilderBadRequestException,
            match="at most 2 attachments",
        ):
            await service.prepare_message_context(
                session=_make_session(tenant_id=user.tenant_id),
                space=space,
                model_id=None,
                tenant_flow_settings={
                    "ai_builder": {
                        "max_attachments": 2,
                        "max_message_chars": 5,
                    }
                },
                message="valid",
                message_file_ids=[uuid4(), uuid4()],
            )

        with pytest.raises(
            AIBuilderBadRequestException,
            match="at most 5 characters",
        ):
            await service.prepare_message_context(
                session=_make_session(tenant_id=user.tenant_id),
                space=space,
                model_id=None,
                tenant_flow_settings={
                    "ai_builder": {
                        "max_attachments": 2,
                        "max_message_chars": 5,
                    }
                },
                message="too long",
            )

        file_service.get_files_by_ids.assert_not_awaited()

    @pytest.mark.anyio
    async def test_prepare_message_context_rejects_flow_space_mismatch(self):
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()
        completion_service = AsyncMock()

        model = _make_model()
        space = MagicMock()
        space.id = uuid4()
        space.completion_models = [model]
        space.collections = []
        space.get_default_completion_model.return_value = model

        session = _make_session(
            tenant_id=user.tenant_id,
            flow_id=uuid4(),
            space_id=space.id,
        )
        flow_service.get_flow.return_value = SimpleNamespace(
            id=session.flow_id,
            space_id=uuid4(),
        )
        completion_service.resolve_model_route.return_value = _route(
            kwargs={"api_key": "sk-test"}
        )

        service = _make_service(
            user=user,
            repo=repo,
            flow_service=flow_service,
            completion_service=completion_service,
        )

        with pytest.raises(BadRequestException, match="space"):
            await service.prepare_message_context(
                session=session,
                space=space,
                model_id=model.id,
                tenant_flow_settings=None,
            )


# ---------------------------------------------------------------------------
# Send message tests
# ---------------------------------------------------------------------------


class TestSendMessage:
    @pytest.mark.anyio
    async def test_rejects_applied_session(self):
        user = _make_user()
        repo = AsyncMock()
        session = _make_session(
            status=SessionStatus.APPLIED,
            tenant_id=user.tenant_id,
        )
        repo.get_session.return_value = session
        service = _make_service(user=user, repo=repo)

        with pytest.raises(BadRequestException, match="Cannot send messages"):
            await _collect_events(
                service.send_message(
                    session_id=session.id,
                    client_turn_id=_TEST_CLIENT_TURN_ID,
                    request_fingerprint=_TEST_REQUEST_FINGERPRINT,
                    request_snapshot=_test_request_snapshot("Hello"),
                    message="Hello",
                    completion_model_route=_route(kwargs={"api_key": "sk-test"}),
                )
            )

    @pytest.mark.anyio
    async def test_awaiting_approval_transitions_to_chatting(self):
        user = _make_user()
        repo = AsyncMock()
        session = _make_session(
            status=SessionStatus.AWAITING_APPROVAL,
            tenant_id=user.tenant_id,
        )
        repo.get_session.return_value = session

        completion_service = AsyncMock()
        adapter = _make_adapter()
        completion_service._get_adapter.return_value = adapter

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        with patch("eneo.flows.ai_builder.ai_builder_service.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(content="OK")
            )
            await _collect_events(
                service.send_message(
                    session_id=session.id,
                    client_turn_id=_TEST_CLIENT_TURN_ID,
                    request_fingerprint=_TEST_REQUEST_FINGERPRINT,
                    request_snapshot=_test_request_snapshot("Change step 2"),
                    message="Change step 2",
                    completion_model_route=_route(kwargs={"api_key": "sk-test"}),
                )
            )

        repo.update_session_status.assert_awaited_once()
        status_call = repo.update_session_status.call_args
        assert status_call.kwargs["session_id"] == session.id
        assert status_call.kwargs["tenant_id"] == user.tenant_id
        assert status_call.kwargs["status"] == SessionStatus.CHATTING
        assert isinstance(status_call.kwargs["lease"], SessionSendLease)
        assert isinstance(status_call.kwargs["lease"].request_id, UUID)
        assert isinstance(status_call.kwargs["lease"].lock_token, UUID)

        repo.update_session_status.assert_awaited_once_with(
            session_id=session.id,
            tenant_id=user.tenant_id,
            status=SessionStatus.CHATTING,
            lease=status_call.kwargs["lease"],
        )

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
    )
    @pytest.mark.anyio
    async def test_known_provider_rejection_commits_typed_error_without_acknowledgement(
        self,
        provider_error: Exception,
        expected_exception_class: str,
    ) -> None:
        user = _make_user()
        repo = _make_repo_mock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=_make_confirmed_requirements_conversation(),
        )
        repo.get_session.return_value = session

        completion_service = AsyncMock()
        completion_service._get_adapter.return_value = _make_adapter()
        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )
        repo.load_planning_state.return_value = _make_committed_planning_state()

        with patch("eneo.flows.ai_builder.ai_builder_service.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=provider_error)
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    client_turn_id=_TEST_CLIENT_TURN_ID,
                    request_fingerprint=_TEST_REQUEST_FINGERPRINT,
                    request_snapshot=_test_request_snapshot("Hello"),
                    message="Hello",
                    question_answer=_make_requirements_confirmation(),
                    completion_model_route=_route(kwargs={"api_key": "sk-test"}),
                )
            )

        assert [event["event"] for event in events] == [SSE_EVENT_ERROR, SSE_EVENT_DONE]
        public_error = json.loads(events[0]["data"])
        assert public_error["code"] == "planner_upstream_error"
        assert public_error["details"] == {
            "another_call_permitted": False,
            "provider_disposition": "known_rejection",
            "provider_exception_class": expected_exception_class,
            "retry_scope": "new_turn",
        }
        assert "sensitive-provider-material" not in json.dumps(public_error)
        repo.complete_session_turn.assert_awaited_once()
        assert (
            repo.complete_session_turn.await_args.kwargs["error"].model_dump(
                mode="json", exclude_none=True
            )
            == public_error
        )
        acceptance = repo.accept_session_turn.await_args.kwargs["acceptance"]
        assert acceptance.acknowledge_duplicate_provider_spend is False
        assert mock_litellm.acompletion.await_count == 1

    @pytest.mark.anyio
    async def test_context_limit_after_slot_classification_commits_without_ack(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = _make_user()
        repo = _make_repo_mock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=_make_confirmed_requirements_conversation(),
        )
        repo.get_session.return_value = session
        completion_service = AsyncMock()
        completion_service._get_adapter.return_value = _make_adapter()
        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )
        repo.load_planning_state.return_value = _make_committed_planning_state()
        monkeypatch.setattr(
            "eneo.flows.ai_builder.ai_builder_proposal_tool_contracts.count_message_tokens",
            lambda _messages, _model: 1_000_000_000,
        )
        monkeypatch.setattr(
            "eneo.flows.ai_builder.ai_builder_proposal_tool_contracts.count_tool_tokens",
            lambda _tools, _model: 0,
        )

        with patch("eneo.flows.ai_builder.ai_builder_service.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock()
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    client_turn_id=_TEST_CLIENT_TURN_ID,
                    request_fingerprint=_TEST_REQUEST_FINGERPRINT,
                    request_snapshot=_test_request_snapshot("Hello"),
                    message="Hello",
                    question_answer=_make_requirements_confirmation(),
                    completion_model_route=_route(kwargs={"api_key": "sk-test"}),
                )
            )

        assert [event["event"] for event in events] == [SSE_EVENT_ERROR, SSE_EVENT_DONE]
        public_error = json.loads(events[0]["data"])
        assert public_error["code"] == "planner_context_limit_exceeded"
        assert public_error["details"] == {
            "another_call_permitted": False,
            "retry_scope": "new_turn",
        }
        repo.complete_session_turn.assert_awaited_once()
        assert (
            repo.complete_session_turn.await_args.kwargs["error"].model_dump(
                mode="json", exclude_none=True
            )
            == public_error
        )
        acceptance = repo.accept_session_turn.await_args.kwargs["acceptance"]
        assert acceptance.acknowledge_duplicate_provider_spend is False
        mock_litellm.acompletion.assert_awaited_once()
        classification_call = mock_litellm.acompletion.await_args.kwargs
        assert classification_call["stream"] is False
        assert "tools" not in classification_call
        assert classification_call["response_format"]["type"] == "json_schema"
        assert classification_call["response_format"]["json_schema"]["name"].startswith(
            "ai_builder_slot_classification_v"
        )

    @pytest.mark.anyio
    async def test_llm_error_preserves_provider_outcome_unknown(self):
        user = _make_user()
        repo = _make_repo_mock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=_make_confirmed_requirements_conversation(),
        )
        repo.get_session.return_value = session

        completion_service = AsyncMock()
        adapter = _make_adapter()
        completion_service._get_adapter.return_value = adapter

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )
        repo.load_planning_state.return_value = _make_committed_planning_state()

        with patch("eneo.flows.ai_builder.ai_builder_service.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=RuntimeError("API error"))
            with pytest.raises(AIBuilderProviderOutcomeUnknownException):
                await _collect_events(
                    service.send_message(
                        session_id=session.id,
                        client_turn_id=_TEST_CLIENT_TURN_ID,
                        request_fingerprint=_TEST_REQUEST_FINGERPRINT,
                        request_snapshot=_test_request_snapshot("Hello"),
                        message="Hello",
                        question_answer=_make_requirements_confirmation(),
                        completion_model_route=_route(kwargs={"api_key": "sk-test"}),
                    )
                )

        repo.mark_session_turn_processing.assert_awaited_once()


class TestSendMessageToolCall:
    @pytest.mark.anyio
    async def test_backend_discovery_asks_for_unresolved_runtime_fields_after_slot_classification(
        self,
    ):
        user = _make_user()
        repo = _make_repo_mock()
        session = _make_session(status=SessionStatus.CHATTING, tenant_id=user.tenant_id)
        repo.get_session.return_value = session

        service = _make_service(user=user, repo=repo)

        async def classification_response(**kwargs: object):
            messages = kwargs["messages"]
            assert isinstance(messages, list)
            latest_message = messages[-1]
            assert isinstance(latest_message, Mapping)
            prompt = latest_message.get("content")
            assert isinstance(prompt, str)
            source_id = prompt.split('"source_id": "', maxsplit=1)[1].split(
                '"', maxsplit=1
            )[0]
            return _make_llm_response(
                content=json.dumps(
                    {
                        "slots": [
                            {
                                "slot_name": "report_disposition",
                                "value": "synthesized_overview",
                                "confidence": "high",
                                "reason": "The user wants to compare uploaded documents.",
                                "evidence": [
                                    {
                                        "source_id": source_id,
                                        "quote": "jämföra dem",
                                    }
                                ],
                                "evidence_level": "explicit",
                            }
                        ],
                        "assumptions": [],
                        "contradictions": [],
                    }
                )
            )

        with patch("eneo.flows.ai_builder.ai_builder_service.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=classification_response)
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    client_turn_id=_TEST_CLIENT_TURN_ID,
                    request_fingerprint=_TEST_REQUEST_FINGERPRINT,
                    request_snapshot=_test_request_snapshot(
                        "Jag vill ladda upp ett eller flera PDF-dokument, jämföra dem och skapa "
                        "en DOCX-rapport."
                    ),
                    message=(
                        "Jag vill ladda upp ett eller flera PDF-dokument, jämföra dem och skapa "
                        "en DOCX-rapport."
                    ),
                    completion_model_route=_route(kwargs={"api_key": "sk-test"}),
                )
            )

        assert mock_litellm.acompletion.await_count == 1
        question_events = [e for e in events if e["event"] == SSE_EVENT_QUESTION]
        assert len(question_events) == 1
        assert json.loads(question_events[0]["data"])["question_id"] == (
            "runtime_metadata_fields"
        )

    @pytest.mark.anyio
    async def test_conversation_replay_preserves_tool_calls(self):
        """Verify planner encoding preserves tool_calls and tool_call_id in replay payloads."""
        prior_conversation = [
            ConversationMessage(role="user", content="Build a flow"),
            ConversationMessage(
                role="assistant",
                content="Här är mitt förslag:",
                tool_calls=[
                    {
                        "id": "call_prior",
                        "name": PROPOSE_FLOW_TOOL_NAME,
                        "arguments": {"flow_name": "Old"},
                    }
                ],
            ),
            ConversationMessage(
                role="tool",
                content="Plan: Old\nAntal steg: 1",
                tool_call_id="call_prior",
            ),
        ]

        messages = [
            conversation_message_to_llm_message(message)
            for message in prior_conversation
        ]
        assistant_msgs = [
            m for m in messages if m["role"] == "assistant" and m.get("tool_calls")
        ]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0]["tool_calls"][0]["id"] == "call_prior"
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "call_prior"

    @pytest.mark.anyio
    async def test_conversation_replay_provider_normalizes_oversized_tool_call_ids(
        self,
    ):
        legacy_id = "server_scoped_model_revision:00000000-0000-0000-0000-000000000000"
        assert len(legacy_id) == PROVIDER_TOOL_CALL_ID_MAX_LENGTH + 1
        prior_conversation = [
            ConversationMessage(
                role="assistant",
                content="Jag uppdaterade modellen.",
                tool_calls=[
                    {
                        "id": legacy_id,
                        "name": PROPOSE_FLOW_TOOL_NAME,
                        "arguments": {"revision_kind": "scoped_step_model"},
                    }
                ],
            ),
            ConversationMessage(
                role="tool",
                content="Plan: updated",
                tool_call_id=legacy_id,
            ),
        ]

        messages = [
            conversation_message_to_llm_message(message)
            for message in prior_conversation
        ]

        assistant_id = messages[0]["tool_calls"][0]["id"]
        tool_result_id = messages[1]["tool_call_id"]
        assert assistant_id == tool_result_id
        assert assistant_id != legacy_id
        assert len(assistant_id) <= PROVIDER_TOOL_CALL_ID_MAX_LENGTH
        assert all(
            len(tool_call["id"]) <= PROVIDER_TOOL_CALL_ID_MAX_LENGTH
            for message in messages
            for tool_call in message.get("tool_calls", [])
        )
        assert all(
            len(message["tool_call_id"]) <= PROVIDER_TOOL_CALL_ID_MAX_LENGTH
            for message in messages
            if "tool_call_id" in message
        )

    @pytest.mark.anyio
    async def test_unknown_tool_calls_are_ignored(self):
        user = _make_user()
        repo = _make_repo_mock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=_make_confirmed_requirements_conversation(),
        )
        repo.get_session.return_value = session

        completion_service = AsyncMock()
        adapter = _make_adapter()
        completion_service._get_adapter.return_value = adapter

        # Tool call with wrong name
        tc = MagicMock()
        tc.id = "call_other"
        tc.function.name = "unknown_tool"
        tc.function.arguments = "{}"

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )
        repo.load_planning_state.return_value = _make_committed_planning_state()

        with patch("eneo.flows.ai_builder.ai_builder_service.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(content=None, tool_calls=[tc])
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    client_turn_id=_TEST_CLIENT_TURN_ID,
                    request_fingerprint=_TEST_REQUEST_FINGERPRINT,
                    request_snapshot=_test_request_snapshot("Build it"),
                    message="Build it",
                    question_answer=_make_requirements_confirmation(),
                    completion_model_route=_route(kwargs={"api_key": "sk-test"}),
                )
            )

        # Only the done event (no plan, no text)
        assert events[-1]["event"] == SSE_EVENT_DONE
        repo.create_plan.assert_not_called()

    @pytest.mark.anyio
    async def test_primary_planner_call_uses_lower_temperature(self):
        user = _make_user()
        repo = _make_repo_mock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=_make_confirmed_requirements_conversation(),
        )
        repo.get_session.return_value = session

        good_tc = _make_tool_call(
            arguments={
                "flow_name": "Temperature test",
                "steps": [
                    {
                        "plan_step_ref": "step_a",
                        "name": "Extrahera",
                        "assistant_spec": {"instructions": "Extrahera information."},
                        "input_source": "flow_input",
                    }
                ],
            }
        )
        repo.create_plan.return_value = _make_plan(
            session_id=session.id, tenant_id=user.tenant_id
        )
        service = _make_service(user=user, repo=repo)
        repo.load_planning_state.return_value = _make_committed_planning_state()

        with patch("eneo.flows.ai_builder.ai_builder_service.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(content=None, tool_calls=[good_tc])
            )
            await _collect_events(
                service.send_message(
                    session_id=session.id,
                    client_turn_id=_TEST_CLIENT_TURN_ID,
                    request_fingerprint=_TEST_REQUEST_FINGERPRINT,
                    request_snapshot=_test_request_snapshot("Build it"),
                    message="Build it",
                    question_answer=_make_requirements_confirmation(),
                    completion_model_route=_route(kwargs={"api_key": "sk-test"}),
                )
            )

        proposal_calls = [
            call
            for call in mock_litellm.acompletion.await_args_list
            if call.kwargs.get("tools")
        ]
        assert proposal_calls
        assert proposal_calls[0].kwargs["temperature"] == 0.4

    @pytest.mark.anyio
    async def test_self_correction_bail_without_question_mark_emits_error_not_text(
        self,
    ):
        """Planner bail text (no question mark, no action intent) must not leak as a conversational text event."""
        user = _make_user()
        repo = _make_repo_mock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=_make_confirmed_requirements_conversation(),
        )
        repo.get_session.return_value = session

        completion_service = AsyncMock()
        adapter = _make_adapter()
        completion_service._get_adapter.return_value = adapter

        bad_args = {
            "flow_name": "Bad",
            "plan_rationale": "Invalid semantic outline.",
            "final_output_type": "text",
            "steps": [
                {
                    "name": "Bad {{ Step }}",
                    "instructions": "X",
                }
            ],
        }
        bad_tc = _make_tool_call(arguments=bad_args)

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )
        repo.load_planning_state.return_value = _make_committed_planning_state()

        bail_text = (
            "Jag försökte skapa flödet men backend-valideringen stoppade mig: "
            "flera av mina output_fields överskrider max-nästningsnivån. "
            "Säg bara 'OK, platta ut JSON-fälten' så fortsätter jag."
        )

        with patch("eneo.flows.ai_builder.ai_builder_service.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    _make_llm_response(content=None, tool_calls=[bad_tc]),
                    _make_llm_response(content=bail_text),
                    _make_llm_response(content=bail_text),
                ]
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    client_turn_id=_TEST_CLIENT_TURN_ID,
                    request_fingerprint=_TEST_REQUEST_FINGERPRINT,
                    request_snapshot=_test_request_snapshot("Build it"),
                    message="Build it",
                    question_answer=_make_requirements_confirmation(),
                    completion_model_route=_route(kwargs={"api_key": "sk-test"}),
                )
            )

        text_events = [e for e in events if e["event"] == SSE_EVENT_TEXT]
        error_events = [e for e in events if e["event"] == SSE_EVENT_ERROR]
        assert text_events == [], (
            f"Planner bail must not reach the user as text; got: {text_events}"
        )
        assert error_events, (
            f"Planner bail must surface as an error event; got: {events}"
        )
        combined_payload = " ".join(str(e.get("data", "")) for e in error_events)
        assert "Säg bara" not in combined_payload, (
            "Planner bail text must not appear inside the user-visible error; "
            f"got: {combined_payload}"
        )
        assert "platta ut JSON-fälten" not in combined_payload, (
            "Planner bail phrasing must not leak into the error payload; "
            f"got: {combined_payload}"
        )


# ---------------------------------------------------------------------------
# Plan approval tests
# ---------------------------------------------------------------------------


class TestApprovePlan:
    @pytest.mark.anyio
    async def test_approve_proposed_plan(self):
        user = _make_user()
        repo = AsyncMock()
        session = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            status=SessionStatus.AWAITING_APPROVAL,
        )
        plan = _make_plan(
            session_id=session.id,
            status=PlanStatus.PROPOSED,
            tenant_id=user.tenant_id,
        )
        approved_plan = _make_plan(
            plan_id=plan.id,
            session_id=session.id,
            status=PlanStatus.APPROVED,
            tenant_id=user.tenant_id,
        )
        repo.get_plan.side_effect = [plan, approved_plan]
        repo.get_plan_for_update.return_value = plan
        repo.get_session.return_value = session
        repo.get_session_for_update.return_value = session
        session.latest_plan_id = plan.id
        repo.update_plan_status_if.return_value = True

        service = _make_service(user=user, repo=repo)
        result = await service.approve_plan(plan_id=plan.id)

        assert result.status == PlanStatus.APPROVED
        repo.update_plan_status_if.assert_called_once_with(
            plan_id=plan.id,
            tenant_id=user.tenant_id,
            expected_status=PlanStatus.PROPOSED,
            status=PlanStatus.APPROVED,
        )

    @pytest.mark.anyio
    async def test_approve_non_proposed_plan_raises(self):
        user = _make_user()
        repo = AsyncMock()
        session = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            status=SessionStatus.AWAITING_APPROVAL,
        )
        plan = _make_plan(
            session_id=session.id,
            status=PlanStatus.APPLIED,
            tenant_id=user.tenant_id,
        )
        repo.get_plan.return_value = plan
        repo.get_plan_for_update.return_value = plan
        repo.get_session_for_update.return_value = session
        session.latest_plan_id = plan.id

        service = _make_service(user=user, repo=repo)
        with pytest.raises(BadRequestException, match="Cannot approve plan"):
            await service.approve_plan(plan_id=plan.id)

    @pytest.mark.anyio
    async def test_approve_already_approved_plan_raises(self):
        user = _make_user()
        repo = AsyncMock()
        session = _make_session(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            status=SessionStatus.AWAITING_APPROVAL,
        )
        plan = _make_plan(
            session_id=session.id,
            status=PlanStatus.APPROVED,
            tenant_id=user.tenant_id,
        )
        session.latest_plan_id = plan.id
        repo.get_plan.return_value = plan
        repo.get_plan_for_update.return_value = plan
        repo.get_session_for_update.return_value = session

        service = _make_service(user=user, repo=repo)
        with pytest.raises(BadRequestException, match="Cannot approve plan"):
            await service.approve_plan(plan_id=plan.id)

    @pytest.mark.anyio
    async def test_approve_requires_session_creator(self):
        user = _make_user()
        repo = AsyncMock()
        plan = _make_plan(
            status=PlanStatus.PROPOSED,
            tenant_id=user.tenant_id,
        )
        session = _make_session(
            session_id=plan.session_id,
            actor_user_id=uuid4(),
            tenant_id=user.tenant_id,
        )
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        service = _make_service(user=user, repo=repo)
        with pytest.raises(UnauthorizedException, match="session creator"):
            await service.approve_plan(plan_id=plan.id)


# ---------------------------------------------------------------------------
# Revise plan tests
# ---------------------------------------------------------------------------


class TestRevisePlan:
    @pytest.mark.anyio
    async def test_keep_current_description_delegates_to_plan_lifecycle(self):
        user = _make_user()
        repo = AsyncMock()
        revised_plan = _make_plan(
            tenant_id=user.tenant_id,
            description_override_manual=True,
        )

        service = _make_service(user=user, repo=repo)
        lifecycle = AsyncMock()
        lifecycle.revise_plan.return_value = revised_plan

        with patch.object(service, "_build_plan_lifecycle", return_value=lifecycle):
            result = await service.revise_plan(
                plan_id=revised_plan.id,
                revision_type="keep_current_description",
            )

        assert result == revised_plan
        lifecycle.revise_plan.assert_awaited_once_with(
            plan_id=revised_plan.id,
            revision_type="keep_current_description",
        )
        repo.get_plan.assert_not_called()


class TestSendMessageStructuredQuestion:
    @pytest.mark.anyio
    async def test_spent_budget_emits_unresolved_processing_goal_question(self):
        user = _make_user()
        repo = AsyncMock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=[
                ConversationMessage(
                    role="user",
                    content="Jag vill bygga ett flöde som analyserar dokument.",
                    metadata={"ui_language": "sv"},
                ),
                _requirement_answer_message(
                    question_id="processing_scope",
                    value="single_case",
                    content="Ett dokument åt gången",
                ),
                _requirement_answer_message(
                    question_id="primary_runtime_input",
                    value="documents",
                    content="Dokument",
                ),
                _requirement_answer_message(
                    question_id="document_material_scope",
                    value="multiple_documents_case",
                    content="Flera relaterade dokument för samma ärende",
                ),
                _requirement_answer_message(
                    question_id="runtime_metadata_fields",
                    value="basic_runtime_metadata",
                    content="Grundläggande metadata",
                ),
            ],
        )
        repo.get_session.return_value = session
        service = _make_service(user=user, repo=repo)

        with patch(
            "eneo.flows.ai_builder.ai_builder_discovery_runtime.classify_slots",
            new=AsyncMock(return_value=None),
        ):
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    client_turn_id=_TEST_CLIENT_TURN_ID,
                    request_fingerprint=_TEST_REQUEST_FINGERPRINT,
                    request_snapshot=_test_request_snapshot("DOCX utan mall"),
                    message="DOCX utan mall",
                    question_answer={
                        "question_id": "final_output_format",
                        "selected_option_ids": ["docx_generated"],
                        "selected_values": ["docx_generated"],
                        "answer": "docx_generated",
                        "ui_language": "sv",
                    },
                    completion_model_route=_route(kwargs={"api_key": "sk-test"}),
                )
            )

        question_events = [
            event for event in events if event["event"] == SSE_EVENT_QUESTION
        ]
        assert len(question_events) == 1
        assert json.loads(question_events[0]["data"])["question_id"] == (
            "post_processing_goal"
        )

    @pytest.mark.anyio
    async def test_spent_budget_runtime_default_reaches_requirements_confirmation(self):
        user = _make_user()
        repo = AsyncMock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=[
                ConversationMessage(
                    role="user",
                    content="Jag vill bygga ett flöde som analyserar dokument.",
                    metadata={"ui_language": "sv"},
                ),
                _requirement_answer_message(
                    question_id="processing_scope",
                    value="single_case",
                    content="Ett dokument åt gången",
                ),
                _requirement_answer_message(
                    question_id="primary_runtime_input",
                    value="documents",
                    content="Dokument",
                ),
                _requirement_answer_message(
                    question_id="document_material_scope",
                    value="single_document_case",
                    content="Ett huvuddokument per ärende",
                ),
                _requirement_answer_message(
                    question_id="terminal_output",
                    value="structured_text",
                    content="Strukturerat textresultat",
                ),
                _requirement_answer_message(
                    question_id="post_processing_goal",
                    value="summarize_or_overview",
                    content="Sammanfatta och ge en överblick",
                ),
            ],
        )
        repo.get_session.return_value = session
        persisted_state = _make_committed_planning_state()
        persisted_state.resolved_slots.pop("runtime_metadata_fields")
        persisted_state.resolved_slots["post_processing_goal"] = ResolvedSlot(
            name="post_processing_goal",
            value="summarize_or_overview",
            source="structured_answer",
            confidence="high",
        )
        repo.commit_turn.return_value = 2
        service = _make_service(user=user, repo=repo)
        repo.load_planning_state.return_value = persisted_state

        with patch(
            "eneo.flows.ai_builder.ai_builder_discovery_runtime.classify_slots",
            new=AsyncMock(return_value=None),
        ):
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    client_turn_id=_TEST_CLIENT_TURN_ID,
                    request_fingerprint=_TEST_REQUEST_FINGERPRINT,
                    request_snapshot=_test_request_snapshot("Bygg planen"),
                    message="Bygg planen",
                    question_answer=None,
                    completion_model_route=_route(kwargs={"api_key": "sk-test"}),
                )
            )

        summary_events = [
            event
            for event in events
            if event["event"] == SSE_EVENT_REQUIREMENTS_SUMMARY
        ]
        assert len(summary_events) == 1
        summary = json.loads(summary_events[0]["data"])
        expected_assumption = (
            "Antar tills vidare att inga extra formulärfält behövs vid körning; "
            "du kan lägga till dem innan du bekräftar."
        )
        assert expected_assumption in summary["assumptions"]

        persisted_messages = repo.commit_turn.await_args.kwargs["new_messages"]
        persisted_summary = persisted_messages[-1].metadata["requirements_summary"]
        assert expected_assumption in persisted_summary["assumptions"]

    @pytest.mark.anyio
    async def test_duplicate_output_question_alias_allows_report_disposition_followup(
        self,
    ):
        """A duplicate terminal-output question is suppressed.

        Generated multi-source document reports still get the server-owned
        report-disposition follow-up because it changes the final document
        contract, not just polish.
        """
        user = _make_user()
        repo = AsyncMock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=[
                ConversationMessage(
                    role="user",
                    content="Jag vill bygga ett flöde som analyserar dokument och sammanfattar dem",
                ),
                ConversationMessage(
                    role="user",
                    content="Ett dokument åt gången",
                    metadata={
                        "question_answer": {
                            "question_id": "processing_scope",
                            "selected_option_ids": ["single_case"],
                            "selected_values": ["single_case"],
                        },
                        "ui_language": "sv",
                    },
                ),
                ConversationMessage(
                    role="user",
                    content="Dokument",
                    metadata={
                        "question_answer": {
                            "question_id": "primary_runtime_input",
                            "selected_option_ids": ["documents"],
                            "selected_values": ["documents"],
                        },
                        "ui_language": "sv",
                    },
                ),
                ConversationMessage(
                    role="user",
                    content="Flera relaterade dokument för samma ärende",
                    metadata={
                        "question_answer": {
                            "question_id": "document_material_scope",
                            "selected_option_ids": ["multiple_documents_case"],
                            "selected_values": ["multiple_documents_case"],
                        },
                        "ui_language": "sv",
                    },
                ),
                ConversationMessage(
                    role="user",
                    content="Grundläggande metadata",
                    metadata={
                        "question_answer": {
                            "question_id": "runtime_metadata_fields",
                            "selected_option_ids": ["basic_runtime_metadata"],
                            "selected_values": ["basic_runtime_metadata"],
                        },
                        "ui_language": "sv",
                    },
                ),
                ConversationMessage(
                    role="user",
                    content="Sammanfatta och ge en överblick",
                    metadata={
                        "question_answer": {
                            "question_id": "post_processing_goal",
                            "selected_option_ids": ["summarize_or_overview"],
                            "selected_values": ["summarize_or_overview"],
                        },
                        "ui_language": "sv",
                    },
                ),
            ],
        )
        repo.get_session.return_value = session

        completion_service = AsyncMock()
        adapter = _make_adapter()
        completion_service._get_adapter.return_value = adapter

        duplicate_question_args = {
            "question_id": "terminal_output",
            "question": "Vad ska flödet producera som slutresultat?",
            "options": [
                {"id": "structured_text", "label": "Text"},
                {"id": "pdf_document", "label": "PDF"},
                {"id": "docx_document", "label": "DOCX"},
            ],
            "selection_mode": "single",
            "allow_custom": True,
        }
        tc = _make_tool_call(
            name="ask_structured_question",
            arguments=duplicate_question_args,
        )

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        with patch("eneo.flows.ai_builder.ai_builder_service.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(content=None, tool_calls=[tc])
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    client_turn_id=_TEST_CLIENT_TURN_ID,
                    request_fingerprint=_TEST_REQUEST_FINGERPRINT,
                    request_snapshot=_test_request_snapshot("DOCX utan mall"),
                    message="DOCX utan mall",
                    question_answer={
                        "question_id": "final_output_format",
                        "selected_option_ids": ["docx_generated"],
                        "selected_values": ["docx_generated"],
                        "answer": "docx_generated",
                        "ui_language": "sv",
                    },
                    completion_model_route=_route(kwargs={"api_key": "sk-test"}),
                )
            )

        question_events = [e for e in events if e["event"] == SSE_EVENT_QUESTION]
        assert len(question_events) == 1
        assert json.loads(question_events[0]["data"])["question_id"] == (
            "report_disposition"
        )

    @pytest.mark.anyio
    async def test_unsupported_model_question_is_replaced_by_framework_question(self):
        user = _make_user()
        repo = AsyncMock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
        )
        repo.get_session.return_value = session

        completion_service = AsyncMock()
        adapter = _make_adapter()
        completion_service._get_adapter.return_value = adapter

        unsupported_question_args = {
            "question_id": "multi_file_strategy",
            "question": "How should multiple files be processed?",
            "options": [
                {"id": "combine_all", "label": "Combine all"},
                {"id": "one_by_one", "label": "One by one"},
            ],
            "selection_mode": "single",
            "allow_custom": True,
        }
        tc = _make_tool_call(
            name="ask_structured_question",
            arguments=unsupported_question_args,
        )

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        with patch("eneo.flows.ai_builder.ai_builder_service.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(content=None, tool_calls=[tc])
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    client_turn_id=_TEST_CLIENT_TURN_ID,
                    request_fingerprint=_TEST_REQUEST_FINGERPRINT,
                    request_snapshot=_test_request_snapshot(
                        "Jag vill ladda upp flera PDF-filer och jämföra innehållet mellan dokumenten."
                    ),
                    message="Jag vill ladda upp flera PDF-filer och jämföra innehållet mellan dokumenten.",
                    completion_model_route=_route(kwargs={"api_key": "sk-test"}),
                )
            )

        question_events = [e for e in events if e["event"] == SSE_EVENT_QUESTION]
        assert len(question_events) == 1
        data = json.loads(question_events[0]["data"])
        assert data["question_id"] in {
            "processing_scope",
            "document_material_scope",
            "terminal_output",
        }
        assert data["question_id"] != "multi_file_strategy"

    @pytest.mark.anyio
    async def test_repeated_processing_scope_question_after_answer_advances_to_different_backend_question(
        self,
    ):
        user = _make_user()
        repo = AsyncMock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=[
                ConversationMessage(
                    role="user",
                    content="Bygg ett flöde som sammanfattar dokument",
                    metadata={"ui_language": "sv"},
                ),
                ConversationMessage(
                    role="assistant",
                    content="Jag behöver förstå hur flödet ska arbeta innan jag går vidare.",
                    tool_calls=[
                        {
                            "id": "call_scope_q1",
                            "name": "ask_structured_question",
                            "arguments": {
                                "question_id": "processing_scope",
                                "question": "Hur ska flödet arbeta?",
                                "options": [
                                    {
                                        "id": "single_case",
                                        "label": "Ett ärende åt gången",
                                    },
                                    {"id": "batch_cases", "label": "Många ärenden"},
                                ],
                                "selection_mode": "single",
                                "allow_custom": True,
                            },
                        }
                    ],
                ),
                ConversationMessage(
                    role="tool",
                    content="Question presented to user. Awaiting their selection.",
                    tool_call_id="call_scope_q1",
                ),
            ],
        )
        repo.get_session.return_value = session

        completion_service = AsyncMock()
        adapter = _make_adapter()
        completion_service._get_adapter.return_value = adapter

        repeated_question = _make_tool_call(
            name="ask_structured_question",
            arguments={
                "question_id": "processing_scope",
                "question": "Hur ska flödet arbeta?",
                "options": [
                    {"id": "single_case", "label": "Ett ärende åt gången"},
                    {"id": "batch_cases", "label": "Många ärenden"},
                ],
                "selection_mode": "single",
                "allow_custom": True,
            },
        )

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        with patch("eneo.flows.ai_builder.ai_builder_service.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(
                    content=None, tool_calls=[repeated_question]
                )
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    client_turn_id=_TEST_CLIENT_TURN_ID,
                    request_fingerprint=_TEST_REQUEST_FINGERPRINT,
                    request_snapshot=_test_request_snapshot("Ett ärende åt gången"),
                    message="Ett ärende åt gången",
                    question_answer={
                        "question_id": "processing_scope",
                        "selected_option_ids": ["single_case"],
                        "selected_values": ["single_case"],
                        "ui_language": "sv",
                    },
                    completion_model_route=_route(kwargs={"api_key": "sk-test"}),
                )
            )

        error_events = [e for e in events if e["event"] == SSE_EVENT_ERROR]
        assert error_events == []
        question_events = [e for e in events if e["event"] == SSE_EVENT_QUESTION]
        assert len(question_events) == 1
        data = json.loads(question_events[0]["data"])
        assert data["question_id"] != "processing_scope"

    @pytest.mark.anyio
    async def test_invalid_supported_question_without_question_text_uses_generic_fallback(
        self,
    ):
        user = _make_user()
        repo = AsyncMock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
        )
        repo.get_session.return_value = session

        completion_service = AsyncMock()
        adapter = _make_adapter()
        completion_service._get_adapter.return_value = adapter

        bad_args = {
            "question_id": "structured_analysis_need",
            "options": [
                {"id": "docx_only", "label": "Bara färdig DOCX"},
            ],
        }
        tc = _make_tool_call(
            name="ask_structured_question",
            arguments=bad_args,
        )

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        with patch("eneo.flows.ai_builder.ai_builder_service.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(content=None, tool_calls=[tc])
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    client_turn_id=_TEST_CLIENT_TURN_ID,
                    request_fingerprint=_TEST_REQUEST_FINGERPRINT,
                    request_snapshot=_test_request_snapshot(
                        "Bygg ett flöde som sammanfattar ett dokument."
                    ),
                    message="Bygg ett flöde som sammanfattar ett dokument.",
                    completion_model_route=_route(kwargs={"api_key": "sk-test"}),
                )
            )

        error_events = [e for e in events if e["event"] == SSE_EVENT_ERROR]
        assert error_events == []

        text_events = [e for e in events if e["event"] == SSE_EVENT_TEXT]
        assert len(text_events) == 1
        text = json.loads(text_events[0]["data"])["text"]
        assert text

        question_events = [e for e in events if e["event"] == SSE_EVENT_QUESTION]
        assert len(question_events) == 1


class TestReasoningLeakRegression:
    """Reasoning field must never be exposed in public API responses."""

    def test_plan_event_rejects_retired_reasoning_field(self):
        """Plan proposals reject reasoning before public SSE serialization."""
        from eneo.flows.ai_builder.ai_builder_events import (
            build_plan_event,
            encode_ai_builder_stream_event,
        )

        spec = FlowDraftSpecCore(
            flow_name="Test",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Step A",
                    assistant_spec=AssistantSpec(instructions="Do something."),
                    input_source=InputSource.FLOW_INPUT,
                )
            ],
        )
        content = FlowBuilderProposalContent(spec=spec, assumptions=["Test"])
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            FlowBuilderProposal.model_validate(
                {
                    "content": content,
                    "reasoning": "SECRET REASONING THAT SHOULD NOT LEAK",
                }
            )

        proposal = FlowBuilderProposal(content=content)

        event = build_plan_event(plan_id=uuid4(), proposal=proposal.content)
        wire_event = encode_ai_builder_stream_event(event)
        assert "SECRET REASONING" not in wire_event["data"]
        parsed = json.loads(wire_event["data"])
        assert "reasoning" not in parsed["proposal"]

    def test_append_plan_messages_strips_reasoning_from_conversation(self):
        """append_plan_messages must strip reasoning and store only a compact
        summary in the conversation. Full spec lives in BuilderPlans table."""
        from eneo.flows.ai_builder.ai_builder_plan_store import append_plan_messages

        conversation: list[ConversationMessage] = []
        arguments = {
            "reasoning": "SECRET REASONING THAT SHOULD NOT LEAK",
            "flow_name": "Test Flow",
            "steps": [],
        }
        spec = FlowDraftSpecCore(
            flow_name="Test Flow",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Step A",
                    assistant_spec=AssistantSpec(instructions="Do."),
                    input_source=InputSource.FLOW_INPUT,
                )
            ],
        )

        append_plan_messages(
            conversation=conversation,
            assistant_content="Here is a flow.",
            tool_call_id="call_123",
            tool_name=PROPOSE_FLOW_TOOL_NAME,
            arguments=arguments,
            spec=spec,
            assumptions=["Test"],
        )

        assistant_msg = conversation[0]
        stored_args = assistant_msg.tool_calls[0]["arguments"]
        assert "reasoning" not in stored_args
        assert stored_args["flow_name"] == "Test Flow"
        assert stored_args["step_count"] == 1
        assert stored_args["step_names"] == ["Step A"]


@pytest.mark.asyncio
async def test_prepare_message_context_stages_new_files_and_builds_attachment_context() -> (
    None
):
    user = _make_user()
    repo = AsyncMock()
    completion_service = AsyncMock()
    file_service = AsyncMock()
    service = AIBuilderService(
        user=user,
        repo=repo,
        flow_service=AsyncMock(),
        completion_service=completion_service,
        space_service=AsyncMock(),
        template_asset_service=AsyncMock(),
        file_service=file_service,
    )

    session = _make_session(actor_user_id=user.id)
    space = MagicMock()
    model = MagicMock()
    model.id = uuid4()
    model.name = "gpt-5.4"
    model.max_input_tokens = 8192
    model.max_output_tokens = 2048
    model.litellm_model_name = "openai/gpt-5.4"
    space.get_default_completion_model.return_value = model
    space.completion_models = [model]
    space.collections = []

    file_id = uuid4()
    attached_file = _make_file(
        file_id=file_id, tenant_id=user.tenant_id, owner_user_id=user.id
    )
    file_service.get_files_by_ids.return_value = [attached_file]
    completion_service.resolve_model_route.return_value = _route(
        model="openai/gpt-5.4",
        kwargs={"api_key": "test"},
    )
    repo.list_session_file_ids.return_value = []

    context = await service.prepare_message_context(
        session=session,
        space=space,
        model_id=None,
        tenant_flow_settings=None,
        message_file_ids=[file_id],
    )

    assert len(context.attachment_files) == 1
    assert context.attachment_files[0].name == "reference.txt"


@pytest.mark.asyncio
async def test_prepare_message_context_does_not_persist_new_files_before_message_acceptance() -> (
    None
):
    user = _make_user()
    repo = AsyncMock()
    completion_service = AsyncMock()
    file_service = AsyncMock()
    service = AIBuilderService(
        user=user,
        repo=repo,
        flow_service=AsyncMock(),
        completion_service=completion_service,
        space_service=AsyncMock(),
        template_asset_service=AsyncMock(),
        file_service=file_service,
    )

    session = _make_session(actor_user_id=user.id)
    space = MagicMock()
    model = MagicMock()
    model.id = uuid4()
    model.name = "gpt-5.4"
    model.max_input_tokens = 8192
    model.max_output_tokens = 2048
    model.litellm_model_name = "openai/gpt-5.4"
    space.get_default_completion_model.return_value = model
    space.completion_models = [model]
    space.collections = []

    file_id = uuid4()
    attached_file = _make_file(
        file_id=file_id, tenant_id=user.tenant_id, owner_user_id=user.id
    )
    file_service.get_files_by_ids.return_value = [attached_file]
    completion_service.resolve_model_route.return_value = _route(
        model="openai/gpt-5.4",
        kwargs={"api_key": "test"},
    )
    repo.list_session_file_ids.return_value = []

    context = await service.prepare_message_context(
        session=session,
        space=space,
        model_id=None,
        tenant_flow_settings=None,
        message_file_ids=[file_id],
    )

    file_service.get_files_by_ids.assert_awaited_once_with([file_id])
    assert len(context.attachment_files) == 1
    assert context.attachment_files[0].id == file_id


@pytest.mark.asyncio
async def test_prepare_message_context_rejects_missing_or_unavailable_file_ids() -> (
    None
):
    user = _make_user()
    repo = AsyncMock()
    completion_service = AsyncMock()
    file_service = AsyncMock()
    service = AIBuilderService(
        user=user,
        repo=repo,
        flow_service=AsyncMock(),
        completion_service=completion_service,
        space_service=AsyncMock(),
        template_asset_service=AsyncMock(),
        file_service=file_service,
    )

    session = _make_session(actor_user_id=user.id)
    space = MagicMock()
    model = MagicMock()
    model.id = uuid4()
    model.name = "gpt-5.4"
    model.max_input_tokens = 8192
    model.max_output_tokens = 2048
    model.litellm_model_name = "openai/gpt-5.4"
    space.get_default_completion_model.return_value = model
    space.completion_models = [model]
    space.collections = []
    completion_service.resolve_model_route.return_value = _route(model="openai/gpt-5.4")
    file_service.get_files_by_ids.return_value = []

    with pytest.raises(BadRequestException, match="referenced files are unavailable"):
        await service.prepare_message_context(
            session=session,
            space=space,
            model_id=None,
            tenant_flow_settings=None,
            message_file_ids=[uuid4()],
        )


@pytest.mark.asyncio
async def test_get_session_attachment_snapshot_returns_warning_when_some_files_missing() -> (
    None
):
    user = _make_user()
    repo = AsyncMock()
    file_service = AsyncMock()
    available_file = _make_file(
        file_id=uuid4(), tenant_id=user.tenant_id, owner_user_id=user.id
    )
    repo.list_session_file_ids.return_value = [available_file.id, uuid4()]
    file_service.get_files_by_ids.return_value = [available_file]
    service = AIBuilderService(
        user=user,
        repo=repo,
        flow_service=AsyncMock(),
        completion_service=AsyncMock(),
        space_service=AsyncMock(),
        template_asset_service=AsyncMock(),
        file_service=file_service,
    )

    snapshot = await service.get_session_attachment_snapshot(session_id=uuid4())

    assert snapshot.files == [available_file]
    assert snapshot.warnings


@pytest.mark.asyncio
async def test_get_session_attachment_snapshot_warns_when_attached_file_has_no_readable_content() -> (
    None
):
    user = _make_user()
    repo = AsyncMock()
    file_service = AsyncMock()
    unreadable_file = _make_file(
        file_id=uuid4(),
        tenant_id=user.tenant_id,
        owner_user_id=user.id,
        text=None,
        blob=b"%PDF-1.7 unreadable",
        mimetype="application/pdf",
        file_type=FileType.DOCUMENT,
    )
    repo.list_session_file_ids.return_value = [unreadable_file.id]
    file_service.get_files_by_ids.return_value = [unreadable_file]
    service = AIBuilderService(
        user=user,
        repo=repo,
        flow_service=AsyncMock(),
        completion_service=AsyncMock(),
        space_service=AsyncMock(),
        template_asset_service=AsyncMock(),
        file_service=file_service,
    )

    snapshot = await service.get_session_attachment_snapshot(session_id=uuid4())

    assert snapshot.files == [unreadable_file]
    assert any("readable" in warning.lower() for warning in snapshot.warnings)
    assert any(unreadable_file.name in warning for warning in snapshot.warnings)
