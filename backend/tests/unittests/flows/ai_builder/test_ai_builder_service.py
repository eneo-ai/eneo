"""Tests for AI Builder service."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch
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
    context manager so tests exercising the plan-proposal orchestrator
    can enter its savepoint without tripping the async-CM protocol.
    """
    repo = AsyncMock()
    repo.savepoint = _noop_savepoint
    return repo


import pytest

from intric.files.file_models import File, FileType
from intric.flows.ai_builder.ai_builder_create_tool_schema import CREATE_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_events import SSE_EVENT_REQUIREMENTS_SUMMARY
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    BuilderPlan,
    BuilderSession,
    ConversationMessage,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    PlannerPlanEnvelope,
    PlanStatus,
    RequirementsSummaryPayload,
    SessionStatus,
    StepSpec,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_plan_lifecycle import AIBuilderPlanLifecycle
from intric.flows.ai_builder.ai_builder_planner import AIBuilderPlanner
from intric.flows.ai_builder.ai_builder_requirements_state import (
    build_requirements_version,
)
from intric.flows.ai_builder.ai_builder_service import (
    SSE_EVENT_DONE,
    SSE_EVENT_ERROR,
    SSE_EVENT_PLAN,
    SSE_EVENT_QUESTION,
    SSE_EVENT_TEXT,
    AIBuilderService,
    PreparedMessageContext,
)
from intric.main.exceptions import BadRequestException, UnauthorizedException

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    *,
    user_id: UUID | None = None,
    tenant_id: UUID | None = None,
) -> MagicMock:
    user = MagicMock()
    user.id = user_id or uuid4()
    user.tenant_id = tenant_id or uuid4()
    return user


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
    edit_result_json: dict[str, object] | None = None,
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
    envelope = PlannerPlanEnvelope(spec=spec, assumptions=["Test assumption"])
    return BuilderPlan(
        id=plan_id or uuid4(),
        session_id=session_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        status=status,
        spec=spec,
        spec_hash=spec.spec_hash(),
        envelope=envelope,
        edit_result_json=edit_result_json,
    )


def _make_service(
    user: MagicMock | None = None,
    repo: AsyncMock | None = None,
    flow_service: AsyncMock | None = None,
    completion_service: AsyncMock | None = None,
) -> AIBuilderService:
    if repo is None:
        repo = AsyncMock()
    repo.list_session_file_ids.return_value = []
    return AIBuilderService(
        user=user or _make_user(),
        repo=repo,
        flow_service=flow_service or AsyncMock(),
        completion_service=completion_service or AsyncMock(),
    )


def _make_file(
    *,
    file_id: UUID | None = None,
    tenant_id: UUID | None = None,
    user_id: UUID | None = None,
    name: str = "reference.txt",
    text: str | None = "Reference material",
    mimetype: str = "text/plain",
    file_type: FileType = FileType.TEXT,
    transcription: str | None = None,
    blob: bytes | None = None,
) -> File:
    resolved_user_id = user_id or uuid4()
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
        owner_type=None,
        owner_user_id=resolved_user_id,
        owner_api_key_id=None,
        user_id=resolved_user_id,
        tenant_id=tenant_id or uuid4(),
    )


def _make_requirements_summary_payload() -> RequirementsSummaryPayload:
    return RequirementsSummaryPayload(
        summary="A confirmed document-analysis flow.",
        key_decisions=[
            {"topic": "Input", "decision": "User uploads documents at runtime."},
            {"topic": "Output", "decision": "Flow produces a structured analysis."},
        ],
        input_description="User uploads files and fills in form values at runtime.",
        output_description="The flow returns a reviewed structured result.",
        manual_setup_notes=[],
    )


def _make_requirements_confirmation() -> dict[str, Any]:
    version = build_requirements_version(_make_requirements_summary_payload())
    return {
        "requirements_confirmed": True,
        "requirements_version": version,
    }


def _make_confirmed_requirements_conversation() -> list[ConversationMessage]:
    summary = _make_requirements_summary_payload()
    version = build_requirements_version(summary)
    summary_data = summary.model_dump(mode="json")
    return [
        ConversationMessage(
            role="tool",
            content="Requirements presented to user. Awaiting confirmation.",
            tool_call_id="call_requirements",
            metadata={
                "requirements_summary": summary_data,
                "requirements_version": version,
            },
        ),
    ]


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
    name: str = CREATE_FLOW_TOOL_NAME,
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
    if name != CREATE_FLOW_TOOL_NAME:
        return arguments or {}
    if arguments is None:
        return {
            "flow_name": "Test Flow",
            "plan_rationale": "Extrahera först och strukturera sedan resultatet.",
            "steps": [
                {
                    "name": "Extrahera fakta",
                    "instructions": "Extrahera fakta.",
                    "input_source": "flow_input",
                    "input_type": "text",
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
    return normalized


def _normalize_create_step(step: Any) -> Any:
    if not isinstance(step, dict):
        return step
    if "instructions" in step and "assistant_spec" not in step:
        return step

    assistant_spec = step.get("assistant_spec") or {}
    input_source = step.get("input_source", "flow_input")
    input_type = step.get("input_type", "text")
    output_type = step.get("output_type", "text")
    output_mode = step.get("output_mode")

    normalized: dict[str, Any] = {
        "name": step.get("name", "Step"),
        "instructions": assistant_spec.get("instructions", "Do things."),
        "input_source": input_source,
        "input_type": "audio" if output_mode == "transcribe_only" else input_type,
        "output_type": "text" if output_mode == "transcribe_only" else output_type,
    }
    if assistant_spec.get("model_ref"):
        normalized["model_ref"] = assistant_spec["model_ref"]
    if assistant_spec.get("knowledge_refs"):
        normalized["knowledge_refs"] = assistant_spec["knowledge_refs"]
    if input_source == "flow_input" and normalized["input_type"] in {
        "audio",
        "document",
        "file",
    }:
        normalized["runtime_upload"] = True
        normalized["runtime_required"] = True
    if normalized["output_type"] == "docx":
        normalized["document_delivery_mode"] = "generated"
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
    """Collect all events from an async generator."""
    events = []
    async for event in gen:
        events.append(event)
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
        repo.list_sessions_for_user.return_value = [session]
        repo.get_plan.return_value = _make_plan(
            plan_id=session.latest_plan_id,
            session_id=session.id,
            tenant_id=user.tenant_id,
            spec=FlowDraftSpecCore(
                flow_name="Recovered Draft",
                steps=[
                    StepSpec(
                        plan_step_ref="step_a",
                        name="Step A",
                        assistant_spec=AssistantSpec(instructions="Do something."),
                        input_source=InputSource.FLOW_INPUT,
                    )
                ],
            ),
        )
        service = _make_service(user=user, repo=repo)

        result = await service.list_sessions()

        assert result[0].draft_title == "Recovered Draft"
        assert result[0].space_id == session.space_id

    @pytest.mark.anyio
    async def test_list_sessions_logs_plan_lookup_failures_and_keeps_summary(
        self, caplog
    ):
        user = _make_user()
        repo = AsyncMock()
        session = _make_session(
            tenant_id=user.tenant_id, actor_user_id=user.id, latest_plan_id=uuid4()
        )
        repo.list_sessions_for_user.return_value = [session]
        repo.get_plan.side_effect = RuntimeError("boom")
        service = _make_service(user=user, repo=repo)

        with patch(
            "intric.flows.ai_builder.ai_builder_service.logger.warning"
        ) as mock_warning:
            caplog.set_level(logging.WARNING)
            result = await service.list_sessions()

        assert result[0].draft_title is None
        assert result[0].session_id == session.id
        mock_warning.assert_called_once()
        assert (
            mock_warning.call_args.args[0]
            == "Failed to resolve AI builder draft title for session list item."
        )

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

        async def planner_events():
            yield {"event": SSE_EVENT_DONE, "data": ""}

        with patch.object(
            AIBuilderPlanner,
            "send_message",
            return_value=planner_events(),
        ) as mock_send_message:
            events = await _collect_events(
                service.send_message(
                    session_id=uuid4(),
                    message="Build a flow",
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
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
        completion_service.resolve_litellm_params.return_value = (
            "azure/gpt-4",
            {
                "api_key": "sk-test",
                "api_base": "https://azure.example.com",
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
        assert result.litellm_model == "azure/gpt-4"
        assert result.litellm_kwargs == {
            "api_key": "sk-test",
            "api_base": "https://azure.example.com",
        }
        assert result.flow is flow
        assert result.assistant_snapshots == snapshots
        assert result.planner_context.available_models == [
            {
                "id": str(model.id),
                "name": "test-model",
                "display_name": "test-model",
                "provider": "openai",
            }
        ]
        completion_service.resolve_litellm_params.assert_awaited_once_with(model)
        flow_service.get_flow.assert_awaited_once_with(session.flow_id)
        flow_service.get_flow_assistant_snapshots.assert_awaited_once_with(flow)

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
        completion_service.resolve_litellm_params.return_value = (
            "openai/gpt-4",
            {"api_key": "sk-test"},
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

    @pytest.mark.anyio
    async def test_resolve_planner_params_falls_back_to_adapter_credentials(self):
        completion_service = MagicMock()
        adapter = _make_adapter()
        adapter.credential_resolver.get_credential_field.side_effect = (
            lambda *, field: {
                "endpoint": "https://azure.example.com",
                "api_version": "2024-02-15-preview",
                "api_type": "azure",
                "organization": "org-123",
                "deployment_name": "gpt4-prod",
            }.get(field)
        )
        completion_service._get_adapter = AsyncMock(return_value=adapter)

        service = _make_service(completion_service=completion_service)

        model = _make_model()
        litellm_model, litellm_kwargs = await service.resolve_planner_params(model)

        assert litellm_model == "openai/gpt-4"
        assert litellm_kwargs == {
            "api_key": "sk-test",
            "api_base": "https://azure.example.com",
            "api_version": "2024-02-15-preview",
            "api_type": "azure",
            "organization": "org-123",
            "deployment_name": "gpt4-prod",
        }
        completion_service._get_adapter.assert_awaited_once_with(model)

    @pytest.mark.anyio
    async def test_resolve_planner_params_returns_sync_resolver_tuple(self):
        completion_service = MagicMock()
        completion_service.resolve_litellm_params = MagicMock(
            return_value=("anthropic/claude-3-7-sonnet", {"api_key": "sk-sync"})
        )
        completion_service._get_adapter = AsyncMock()

        service = _make_service(completion_service=completion_service)

        model = _make_model()
        litellm_model, litellm_kwargs = await service.resolve_planner_params(model)

        assert litellm_model == "anthropic/claude-3-7-sonnet"
        assert litellm_kwargs == {"api_key": "sk-sync"}
        completion_service.resolve_litellm_params.assert_called_once_with(model)
        completion_service._get_adapter.assert_not_awaited()


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
                    message="Hello",
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

    @pytest.mark.anyio
    async def test_rejects_applying_session(self):
        user = _make_user()
        repo = AsyncMock()
        session = _make_session(
            status=SessionStatus.APPLYING,
            tenant_id=user.tenant_id,
        )
        repo.get_session.return_value = session
        service = _make_service(user=user, repo=repo)

        with pytest.raises(BadRequestException, match="Cannot send messages"):
            await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Hello",
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
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

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(content="OK")
            )
            await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Change step 2",
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        repo.update_session_status.assert_called_once_with(
            session_id=session.id,
            tenant_id=user.tenant_id,
            status=SessionStatus.CHATTING,
        )

    @pytest.mark.anyio
    async def test_text_response_yields_text_and_done(self):
        user = _make_user()
        repo = AsyncMock()
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

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(content="Vilken typ av indata?")
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Skapa ett flöde",
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        assert len(events) == 2
        assert events[0]["event"] == SSE_EVENT_TEXT
        data = json.loads(events[0]["data"])
        assert data["text"] == "Vilken typ av indata?"
        assert events[1]["event"] == SSE_EVENT_DONE

    @pytest.mark.anyio
    async def test_text_response_updates_conversation(self):
        user = _make_user()
        repo = AsyncMock()
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

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(content="I understand.")
            )
            await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Build a flow",
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        call = repo.commit_turn.call_args
        conversation = call.kwargs["new_messages"]
        assert len(conversation) == 2
        assert conversation[0].role == "user"
        assert conversation[0].content == "Build a flow"
        assert conversation[1].role == "assistant"
        assert conversation[1].content == "I understand."
        repo.update_session_conversation.assert_not_called()

    @pytest.mark.anyio
    async def test_text_response_persists_planner_telemetry_on_assistant_message(self):
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

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        response = _make_llm_response(content="I understand.")
        response.usage = SimpleNamespace(
            prompt_tokens=12,
            completion_tokens=5,
            total_tokens=17,
        )
        response.choices[0].finish_reason = "stop"

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=response)
            await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Build a flow",
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        conversation = repo.commit_turn.call_args.kwargs["new_messages"]
        assistant_message = conversation[1]
        assert assistant_message.metadata is not None
        planner_telemetry = assistant_message.metadata["planner_telemetry"]
        session_telemetry = assistant_message.metadata["session_telemetry"]
        assert planner_telemetry["prompt_tokens"] == 12
        assert planner_telemetry["completion_tokens"] == 5
        assert planner_telemetry["total_tokens"] == 17
        assert planner_telemetry["finish_reason"] == "stop"
        assert planner_telemetry["model"] == "openai/gpt-4"
        assert session_telemetry["planner_request_count"] == 1
        assert session_telemetry["prompt_tokens_total"] == 12
        assert session_telemetry["completion_tokens_total"] == 5
        assert session_telemetry["total_tokens_total"] == 17

    @pytest.mark.anyio
    async def test_llm_error_yields_error_event(self):
        user = _make_user()
        repo = AsyncMock()
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

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=RuntimeError("API error"))
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Hello",
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        assert len(events) == 2
        assert events[0]["event"] == SSE_EVENT_ERROR
        error_payload = json.loads(events[0]["data"])
        assert error_payload["error"] == "The AI planner failed. Please try again."
        assert error_payload["message"] == "The AI planner failed. Please try again."
        assert error_payload["code"] == "planner_upstream_error"
        assert error_payload["phase"] == "planner"
        assert error_payload["request_id"]
        assert events[1]["event"] == SSE_EVENT_DONE


class TestSendMessageToolCall:
    @pytest.mark.anyio
    async def test_valid_tool_call_yields_plan_event(self):
        user = _make_user()
        repo = _make_repo_mock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=_make_confirmed_requirements_conversation(),
        )
        repo.get_session.return_value = session
        plan = _make_plan(session_id=session.id, tenant_id=user.tenant_id)
        repo.create_plan.return_value = plan

        completion_service = AsyncMock()
        adapter = _make_adapter()
        completion_service._get_adapter.return_value = adapter

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        tool_call = _make_tool_call()
        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(
                    content="Här är mitt förslag:",
                    tool_calls=[tool_call],
                )
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Create a summarization flow",
                    question_answer=_make_requirements_confirmation(),
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        # Should have: text (from tool call content) + plan + done
        event_types = [e["event"] for e in events]
        assert SSE_EVENT_PLAN in event_types
        assert SSE_EVENT_DONE in event_types

        # Plan event data should include plan_id and envelope
        plan_event = next(e for e in events if e["event"] == SSE_EVENT_PLAN)
        plan_data = json.loads(plan_event["data"])
        assert "plan_id" in plan_data
        assert "envelope" in plan_data

    @pytest.mark.anyio
    async def test_plan_event_includes_rationale(self):
        user = _make_user()
        repo = _make_repo_mock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=_make_confirmed_requirements_conversation(),
        )
        repo.get_session.return_value = session
        plan = _make_plan(session_id=session.id, tenant_id=user.tenant_id)
        repo.create_plan.return_value = plan

        service = _make_service(user=user, repo=repo)

        tool_call = _make_tool_call(
            arguments={
                "flow_name": "Test Flow",
                "plan_rationale": "JSON first keeps downstream DOCX bindings explicit and safer.",
                "steps": [
                    {
                        "plan_step_ref": "step_a",
                        "name": "Extrahera fakta",
                        "assistant_spec": {"instructions": "Extrahera fakta."},
                        "input_source": "flow_input",
                    }
                ],
            }
        )
        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(
                    content="Här är mitt förslag:", tool_calls=[tool_call]
                )
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Create a flow",
                    question_answer=_make_requirements_confirmation(),
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        plan_event = next(e for e in events if e["event"] == SSE_EVENT_PLAN)
        plan_data = json.loads(plan_event["data"])
        assert plan_data["envelope"]["plan_rationale"] == (
            "JSON first keeps downstream DOCX bindings explicit and safer."
        )

    @pytest.mark.anyio
    async def test_plan_event_excludes_reasoning(self):
        user = _make_user()
        repo = _make_repo_mock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=_make_confirmed_requirements_conversation(),
        )
        repo.get_session.return_value = session
        plan = _make_plan(session_id=session.id, tenant_id=user.tenant_id)
        repo.create_plan.return_value = plan

        service = _make_service(user=user, repo=repo)

        tool_call = _make_tool_call(
            arguments={
                "reasoning": "Hidden chain of thought that should not reach the client.",
                "flow_name": "Test Flow",
                "steps": [
                    {
                        "plan_step_ref": "step_a",
                        "name": "Extrahera fakta",
                        "assistant_spec": {"instructions": "Extrahera fakta."},
                        "input_source": "flow_input",
                    }
                ],
            }
        )
        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(
                    content="Här är mitt förslag:", tool_calls=[tool_call]
                )
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Create a flow",
                    question_answer=_make_requirements_confirmation(),
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        plan_event = next(e for e in events if e["event"] == SSE_EVENT_PLAN)
        plan_data = json.loads(plan_event["data"])
        assert "reasoning" not in plan_data["envelope"]

    @pytest.mark.anyio
    async def test_plan_event_defaults_runtime_upload_for_document_flow_input(self):
        user = _make_user()
        repo = _make_repo_mock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=_make_confirmed_requirements_conversation(),
        )
        repo.get_session.return_value = session
        repo.create_plan.side_effect = lambda **kwargs: BuilderPlan(
            id=uuid4(),
            session_id=session.id,
            tenant_id=user.tenant_id,
            status=PlanStatus.PROPOSED,
            spec=kwargs["spec"],
            spec_hash=kwargs["spec"].spec_hash(),
            envelope=kwargs["envelope"],
        )

        service = _make_service(user=user, repo=repo)

        tool_call = _make_tool_call(
            arguments={
                "flow_name": "Dokumentflöde",
                "steps": [
                    {
                        "plan_step_ref": "step_a",
                        "name": "Extrahera dokumentpaket",
                        "assistant_spec": {
                            "instructions": "Extrahera struktur från dokumenten."
                        },
                        "input_source": "flow_input",
                        "input_type": "document",
                    }
                ],
            }
        )
        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(
                    content="Här är mitt förslag:", tool_calls=[tool_call]
                )
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Bygg ett dokumentflöde",
                    question_answer=_make_requirements_confirmation(),
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        plan_event = next(e for e in events if e["event"] == SSE_EVENT_PLAN)
        plan_data = json.loads(plan_event["data"])
        runtime_input = plan_data["envelope"]["spec"]["steps"][0]["input_config"][
            "runtime_input"
        ]
        assert runtime_input["enabled"] is True
        assert runtime_input["input_format"] == "document"
        assert (
            runtime_input["description"]
            == "Ladda upp dokument som detta steg ska analysera."
        )

    @pytest.mark.anyio
    async def test_backend_discovery_short_circuits_ambiguous_pdf_docx_flow_before_llm_call(
        self,
    ):
        user = _make_user()
        repo = _make_repo_mock()
        session = _make_session(status=SessionStatus.CHATTING, tenant_id=user.tenant_id)
        repo.get_session.return_value = session

        service = _make_service(user=user, repo=repo)

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock()
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message=(
                        "Jag vill ladda upp ett eller flera PDF-dokument, jämföra dem och skapa "
                        "en DOCX-rapport."
                    ),
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        assert mock_litellm.acompletion.await_count == 0
        question_events = [e for e in events if e["event"] == SSE_EVENT_QUESTION]
        assert len(question_events) == 1
        question = json.loads(question_events[0]["data"])
        assert question["question_id"] in {
            "processing_scope",
            "document_kind",
            "comparison_scope",
        }

    @pytest.mark.anyio
    async def test_tool_call_supersedes_existing_plans(self):
        user = _make_user()
        repo = _make_repo_mock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=_make_confirmed_requirements_conversation(),
        )
        repo.get_session.return_value = session
        plan = _make_plan(session_id=session.id, tenant_id=user.tenant_id)
        repo.create_plan.return_value = plan

        completion_service = AsyncMock()
        adapter = _make_adapter()
        completion_service._get_adapter.return_value = adapter

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        tool_call = _make_tool_call()
        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(
                    content=None,
                    tool_calls=[tool_call],
                )
            )
            await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Build it",
                    question_answer=_make_requirements_confirmation(),
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        repo.supersede_existing_plans.assert_called_once_with(
            session_id=session.id,
            tenant_id=user.tenant_id,
        )

    @pytest.mark.anyio
    async def test_tool_call_updates_latest_plan(self):
        user = _make_user()
        repo = _make_repo_mock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=_make_confirmed_requirements_conversation(),
        )
        repo.get_session.return_value = session
        plan = _make_plan(session_id=session.id, tenant_id=user.tenant_id)
        repo.create_plan.return_value = plan

        completion_service = AsyncMock()
        adapter = _make_adapter()
        completion_service._get_adapter.return_value = adapter

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        tool_call = _make_tool_call()
        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(
                    content=None,
                    tool_calls=[tool_call],
                )
            )
            await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Build it",
                    question_answer=_make_requirements_confirmation(),
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        repo.update_session_latest_plan.assert_called_once_with(
            session_id=session.id,
            tenant_id=user.tenant_id,
            plan_id=plan.id,
            request_id=ANY,
            lock_token=ANY,
        )

    @pytest.mark.anyio
    async def test_tool_call_appends_tool_result_to_conversation(self):
        """Verify that a tool result message is appended after the plan is stored."""
        user = _make_user()
        repo = _make_repo_mock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=_make_confirmed_requirements_conversation(),
        )
        repo.get_session.return_value = session
        plan = _make_plan(session_id=session.id, tenant_id=user.tenant_id)
        repo.create_plan.return_value = plan

        service = _make_service(user=user, repo=repo)

        tool_call = _make_tool_call()
        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(
                    content="Här är mitt förslag:",
                    tool_calls=[tool_call],
                )
            )
            await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Build a flow",
                    question_answer=_make_requirements_confirmation(),
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        call = repo.append_session_messages.call_args
        conversation = call.kwargs["conversation"]
        # Should have: user + assistant (with tool_calls) + tool (result)
        assert len(conversation) == 3
        assert conversation[0].role == "user"
        assert conversation[1].role == "assistant"
        assert conversation[1].tool_calls is not None
        assert conversation[1].metadata is not None
        planner_telemetry = conversation[1].metadata["planner_telemetry"]
        session_telemetry = conversation[1].metadata["session_telemetry"]
        assert planner_telemetry["tool_call_count"] == 1
        assert session_telemetry["planner_request_count"] == 1
        assert session_telemetry["tool_call_count_total"] == 1
        assert conversation[2].role == "tool"
        assert conversation[2].tool_call_id == tool_call.id
        repo.update_session_conversation.assert_not_called()
        assert "Test Flow" in conversation[2].content  # Plan summary includes flow name

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
                        "name": CREATE_FLOW_TOOL_NAME,
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
            AIBuilderPlanner.conversation_msg_to_llm_dict(message)
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
    async def test_invalid_json_arguments_yields_error(self):
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

        # Tool call with invalid JSON
        tc = MagicMock()
        tc.id = "call_bad"
        tc.function.name = CREATE_FLOW_TOOL_NAME
        tc.function.arguments = "not valid json {"

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(content=None, tool_calls=[tc])
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Build it",
                    question_answer=_make_requirements_confirmation(),
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        error_events = [e for e in events if e["event"] == SSE_EVENT_ERROR]
        assert len(error_events) >= 1
        assert (
            "Invalid tool call arguments"
            in json.loads(error_events[0]["data"])["error"]
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

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(content=None, tool_calls=[tc])
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Build it",
                    question_answer=_make_requirements_confirmation(),
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        # Only the done event (no plan, no text)
        assert events[-1]["event"] == SSE_EVENT_DONE
        repo.create_plan.assert_not_called()

    @pytest.mark.anyio
    async def test_validation_failure_triggers_self_correction(self):
        """When the spec has validation errors, the service asks the LLM to fix it."""
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

        # First call: invalid spec (step 1 uses previous_step)
        bad_args = {
            "flow_name": "Bad Flow",
            "steps": [
                {
                    "plan_step_ref": "step_a",
                    "name": "Bad Step",
                    "assistant_spec": {"instructions": "Do things."},
                    "input_source": "previous_step",  # Invalid for step 1
                }
            ],
        }
        bad_tc = _make_tool_call(arguments=bad_args)

        # Second call (self-correction): valid spec
        good_args = {
            "flow_name": "Fixed Flow",
            "steps": [
                {
                    "plan_step_ref": "step_a",
                    "name": "Fixed Step",
                    "assistant_spec": {"instructions": "Do things."},
                    "input_source": "flow_input",
                }
            ],
        }
        good_tc = _make_tool_call(tool_call_id="call_fix", arguments=good_args)

        plan = _make_plan(session_id=session.id, tenant_id=user.tenant_id)
        repo.create_plan.return_value = plan

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    _make_llm_response(content=None, tool_calls=[bad_tc]),
                    _make_llm_response(content=None, tool_calls=[good_tc]),
                ]
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Build it",
                    question_answer=_make_requirements_confirmation(),
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        # Should get plan event (from self-correction) + done
        event_types = [e["event"] for e in events]
        assert SSE_EVENT_PLAN in event_types
        assert mock_litellm.acompletion.call_count == 2

    @pytest.mark.anyio
    async def test_quality_warning_triggers_self_correction(self):
        user = _make_user()
        repo = _make_repo_mock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=_make_confirmed_requirements_conversation(),
        )
        repo.get_session.return_value = session

        bad_args = {
            "flow_name": "Needs structure",
            "steps": [
                {
                    "plan_step_ref": "step_a",
                    "name": "Extrahera fakta",
                    "assistant_spec": {"instructions": "Extrahera JSON-fält."},
                    "input_source": "flow_input",
                    "output_type": "json",
                },
                {
                    "plan_step_ref": "step_b",
                    "name": "Skriv rapport",
                    "assistant_spec": {
                        "instructions": "Skriv en rapport baserat på strukturerade fält."
                    },
                    "input_source": "previous_step",
                    "output_type": "text",
                },
            ],
        }
        good_args = {
            "flow_name": "Needs structure",
            "steps": [
                {
                    "plan_step_ref": "step_a",
                    "name": "Extrahera fakta",
                    "assistant_spec": {
                        "instructions": "Extrahera fälten titel, sammanfattning och risk i JSON-format."
                    },
                    "input_source": "flow_input",
                    "output_type": "json",
                    "output_contract": {
                        "type": "object",
                        "properties": {
                            "titel": {"type": "string", "description": "Kort rubrik"},
                            "sammanfattning": {
                                "type": "string",
                                "description": "Sammanfattning",
                            },
                            "risk": {"type": "string", "description": "Bedömd risk"},
                        },
                    },
                },
                {
                    "plan_step_ref": "step_b",
                    "name": "Skriv rapport",
                    "assistant_spec": {
                        "instructions": "Skriv en rapport baserat på strukturerade fält."
                    },
                    "input_source": "previous_step",
                    "output_type": "text",
                },
            ],
        }

        bad_tc = _make_tool_call(arguments=bad_args)
        good_tc = _make_tool_call(tool_call_id="call_quality_fix", arguments=good_args)
        plan = _make_plan(session_id=session.id, tenant_id=user.tenant_id)
        repo.create_plan.return_value = plan

        service = _make_service(user=user, repo=repo)

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    _make_llm_response(content=None, tool_calls=[bad_tc]),
                    _make_llm_response(content=None, tool_calls=[good_tc]),
                ]
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Bygg ett JSON-flöde",
                    question_answer=_make_requirements_confirmation(),
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        assert any(event["event"] == SSE_EVENT_PLAN for event in events)
        assert mock_litellm.acompletion.call_count == 2

    @pytest.mark.anyio
    async def test_self_correction_retries_when_corrected_plan_still_has_quality_warning(
        self,
    ):
        user = _make_user()
        repo = _make_repo_mock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=_make_confirmed_requirements_conversation(),
        )
        repo.get_session.return_value = session

        initial_bad_args = {
            "flow_name": "Needs structure",
            "steps": [
                {
                    "plan_step_ref": "step_a",
                    "name": "Transkribera",
                    "assistant_spec": {"instructions": "Transkribera ljudet."},
                    "input_source": "flow_input",
                    "input_type": "audio",
                    "output_mode": "transcribe_only",
                },
                {
                    "plan_step_ref": "step_b",
                    "name": "Extrahera marknadsinsikter",
                    "assistant_spec": {
                        "instructions": "Returnera JSON med marknadsinsikter."
                    },
                    "input_source": "previous_step",
                    "output_type": "json",
                },
                {
                    "plan_step_ref": "step_c",
                    "name": "Skriv slutrapport",
                    "assistant_spec": {
                        "instructions": "Skriv slutrapport utifrån den strukturerade analysen."
                    },
                    "input_source": "previous_step",
                    "output_type": "text",
                },
            ],
        }
        corrected_but_still_bad_args = {
            "flow_name": "Needs structure",
            "steps": [
                {
                    "plan_step_ref": "step_a",
                    "name": "Transkribera",
                    "assistant_spec": {"instructions": "Transkribera ljudet."},
                    "input_source": "flow_input",
                    "input_type": "audio",
                    "output_mode": "transcribe_only",
                },
                {
                    "plan_step_ref": "step_b",
                    "name": "Extrahera marknadsinsikter",
                    "assistant_spec": {
                        "instructions": "Returnera JSON med fälten riskler, firsatlar och ozel_hisse_ozeti."
                    },
                    "input_source": "previous_step",
                    "output_type": "json",
                },
                {
                    "plan_step_ref": "step_c",
                    "name": "Skriv slutrapport",
                    "assistant_spec": {
                        "instructions": "Skriv slutrapport utifrån den strukturerade analysen."
                    },
                    "input_source": "previous_step",
                    "output_type": "text",
                },
            ],
        }
        good_args = {
            "flow_name": "Needs structure",
            "steps": [
                {
                    "plan_step_ref": "step_a",
                    "name": "Transkribera",
                    "assistant_spec": {"instructions": "Transkribera ljudet."},
                    "input_source": "flow_input",
                    "input_type": "audio",
                    "output_mode": "transcribe_only",
                },
                {
                    "plan_step_ref": "step_b",
                    "name": "Extrahera marknadsinsikter",
                    "assistant_spec": {
                        "instructions": (
                            "Returnera JSON med fälten riskler, firsatlar och "
                            "ozel_hisse_ozeti. Om något saknas ska du lämna tom lista "
                            "eller tom sträng enligt kontraktet."
                        )
                    },
                    "input_source": "previous_step",
                    "output_type": "json",
                    "output_contract": {
                        "type": "object",
                        "properties": {
                            "riskler": {
                                "type": "array",
                                "description": "Nämnda risker i innehållet.",
                                "items": {"type": "string"},
                            },
                            "firsatlar": {
                                "type": "array",
                                "description": "Möjligheter eller positiva signaler.",
                                "items": {"type": "string"},
                            },
                            "ozel_hisse_ozeti": {
                                "type": "string",
                                "description": "Kort sammanfattning av aktier som nämns.",
                            },
                        },
                    },
                },
                {
                    "plan_step_ref": "step_c",
                    "name": "Skriv slutrapport",
                    "assistant_spec": {
                        "instructions": "Skriv slutrapport utifrån den strukturerade analysen."
                    },
                    "input_source": "previous_step",
                    "output_type": "text",
                },
            ],
        }

        repo.create_plan.return_value = _make_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
        )
        service = _make_service(user=user, repo=repo)

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    _make_llm_response(
                        content=None,
                        tool_calls=[_make_tool_call(arguments=initial_bad_args)],
                    ),
                    _make_llm_response(
                        content=None,
                        tool_calls=[
                            _make_tool_call(
                                tool_call_id="call_retry_1",
                                arguments=corrected_but_still_bad_args,
                            )
                        ],
                    ),
                    _make_llm_response(
                        content=None,
                        tool_calls=[
                            _make_tool_call(
                                tool_call_id="call_retry_2",
                                arguments=good_args,
                            )
                        ],
                    ),
                ]
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Bygg ett ljudflöde med strukturerad JSON-analys",
                    question_answer=_make_requirements_confirmation(),
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        correction_messages = mock_litellm.acompletion.await_args_list[2].kwargs[
            "messages"
        ]
        correction_feedback = correction_messages[-1]["content"]
        assert "Quality issues" in correction_feedback
        assert "output_contract" in correction_feedback
        assert any(event["event"] == SSE_EVENT_PLAN for event in events)
        assert mock_litellm.acompletion.call_count == 3

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

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(content=None, tool_calls=[good_tc])
            )
            await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Build it",
                    question_answer=_make_requirements_confirmation(),
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        # Confirmed requirements → proposal phase → planner temperature (0.4)
        assert mock_litellm.acompletion.await_args_list[0].kwargs["temperature"] == 0.4

    @pytest.mark.anyio
    async def test_parse_failure_triggers_self_correction(self):
        """When create_flow misses required fields, the service asks the LLM to fix it."""
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
            "flow_name": "Dokumentanalys Pro",
            "flow_description": "Narrative summary only, no concrete steps yet.",
        }
        bad_tc = _make_tool_call(arguments=bad_args)

        good_args = {
            "flow_name": "Dokumentanalys Pro",
            "steps": [
                {
                    "plan_step_ref": "step_a",
                    "name": "Analysera dokument",
                    "assistant_spec": {
                        "instructions": "Extrahera strukturerade fakta."
                    },
                    "input_source": "flow_input",
                }
            ],
        }
        good_tc = _make_tool_call(tool_call_id="call_fix", arguments=good_args)

        plan = _make_plan(session_id=session.id, tenant_id=user.tenant_id)
        repo.create_plan.return_value = plan

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    _make_llm_response(content=None, tool_calls=[bad_tc]),
                    _make_llm_response(content=None, tool_calls=[good_tc]),
                ]
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Build it",
                    question_answer=_make_requirements_confirmation(),
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        assert any(e["event"] == SSE_EVENT_PLAN for e in events)
        assert not any(
            "Invalid flow specification" in e.get("data", "")
            for e in events
            if e["event"] == SSE_EVENT_ERROR
        )
        assert mock_litellm.acompletion.call_count == 2

    @pytest.mark.anyio
    async def test_self_correction_failure_yields_error(self):
        """When self-correction also fails validation, yield error event."""
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

        # Initial planner call plus both correction attempts produce invalid specs
        bad_args = {
            "flow_name": "Bad",
            "steps": [
                {
                    "plan_step_ref": "step_a",
                    "name": "Bad",
                    "assistant_spec": {"instructions": "X"},
                    "input_source": "previous_step",
                }
            ],
        }
        bad_tc1 = _make_tool_call(tool_call_id="call_1", arguments=bad_args)
        bad_tc2 = _make_tool_call(tool_call_id="call_2", arguments=bad_args)
        bad_tc3 = _make_tool_call(tool_call_id="call_3", arguments=bad_args)
        bad_tc4 = _make_tool_call(tool_call_id="call_4", arguments=bad_args)
        bad_tc5 = _make_tool_call(tool_call_id="call_5", arguments=bad_args)

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    _make_llm_response(content=None, tool_calls=[bad_tc1]),
                    _make_llm_response(content=None, tool_calls=[bad_tc2]),
                    _make_llm_response(content=None, tool_calls=[bad_tc3]),
                    _make_llm_response(content=None, tool_calls=[bad_tc4]),
                    _make_llm_response(content=None, tool_calls=[bad_tc5]),
                ]
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Build it",
                    question_answer=_make_requirements_confirmation(),
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        error_events = [e for e in events if e["event"] == SSE_EVENT_ERROR]
        assert len(error_events) >= 1
        assert "still invalid" in json.loads(error_events[0]["data"])["error"]
        # 1 planner call + 1 initial correction + 3 retries = 5 LLM calls total.
        # Pin the exact count so MAX_SELF_CORRECTION_RETRIES changes cannot slip.
        assert mock_litellm.acompletion.call_count == 5

    @pytest.mark.anyio
    async def test_self_correction_retries_once_more_before_erroring(self):
        user = _make_user()
        repo = _make_repo_mock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=_make_confirmed_requirements_conversation(),
        )
        repo.get_session.return_value = session

        initial_bad_args = {
            "flow_name": "Retry Flow",
            "flow_description": "Narrative summary only, no steps yet.",
        }
        second_bad_args = {
            "flow_name": "Retry Flow",
            "plan_rationale": "Försöker igen med ett ofullständigt steg.",
            "steps": [
                {
                    "name": "Extrahera",
                    "input_source": "flow_input",
                    "instructions": "   ",
                },
            ],
        }
        corrected_args = {
            "flow_name": "Retry Flow",
            "plan_rationale": "Extrahera först och skriv sedan resultatet.",
            "steps": [
                {
                    "name": "Extrahera",
                    "instructions": "Extrahera.",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_type": "text",
                },
                {
                    "name": "Skriv",
                    "instructions": "Skriv.",
                    "input_source": "previous_step",
                    "input_type": "text",
                    "output_type": "text",
                },
            ],
        }

        repo.create_plan.return_value = _make_plan(
            session_id=session.id, tenant_id=user.tenant_id
        )
        service = _make_service(user=user, repo=repo)

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    _make_llm_response(
                        content=None,
                        tool_calls=[_make_tool_call(arguments=initial_bad_args)],
                    ),
                    _make_llm_response(
                        content=None,
                        tool_calls=[
                            _make_tool_call(
                                tool_call_id="call_retry_1", arguments=second_bad_args
                            )
                        ],
                    ),
                    _make_llm_response(
                        content=None,
                        tool_calls=[
                            _make_tool_call(
                                tool_call_id="call_retry_2", arguments=corrected_args
                            )
                        ],
                    ),
                ]
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Bygg flödet",
                    question_answer=_make_requirements_confirmation(),
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        assert mock_litellm.acompletion.call_count == 3
        assert any(event["event"] == SSE_EVENT_PLAN for event in events)
        assert not any(event["event"] == SSE_EVENT_ERROR for event in events)

    @pytest.mark.anyio
    async def test_self_correction_text_fallback(self):
        """When correction still ends in text after a forced retry, yield text."""
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

        # First call: invalid spec
        bad_args = {
            "flow_name": "Bad",
            "steps": [
                {
                    "plan_step_ref": "step_a",
                    "name": "Bad Step",
                    "assistant_spec": {"instructions": "X"},
                    "input_source": "previous_step",
                }
            ],
        }
        bad_tc = _make_tool_call(arguments=bad_args)

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    _make_llm_response(content=None, tool_calls=[bad_tc]),
                    _make_llm_response(content="I need more information."),
                    _make_llm_response(content="I still need more information."),
                ]
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Build it",
                    question_answer=_make_requirements_confirmation(),
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        text_events = [e for e in events if e["event"] == SSE_EVENT_TEXT]
        assert len(text_events) >= 1
        assert "more information" in json.loads(text_events[0]["data"])["text"]

    @pytest.mark.anyio
    async def test_self_correction_text_retry_can_still_produce_plan(self):
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
            "steps": [
                {
                    "plan_step_ref": "step_a",
                    "name": "Bad Step",
                    "assistant_spec": {"instructions": "X"},
                    "input_source": "previous_step",
                }
            ],
        }
        bad_tc = _make_tool_call(arguments=bad_args)
        good_tc = _make_tool_call(
            tool_call_id="call_fix",
            arguments={
                "flow_name": "Recovered Flow",
                "steps": [
                    {
                        "plan_step_ref": "step_a",
                        "name": "Fixed Step",
                        "assistant_spec": {"instructions": "Do things."},
                        "input_source": "flow_input",
                    }
                ],
            },
        )

        plan = _make_plan(session_id=session.id, tenant_id=user.tenant_id)
        repo.create_plan.return_value = plan

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    _make_llm_response(content=None, tool_calls=[bad_tc]),
                    _make_llm_response(content="Låt mig bygga det kompletta flödet:"),
                    _make_llm_response(content="Här är planen.", tool_calls=[good_tc]),
                ]
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Build it",
                    question_answer=_make_requirements_confirmation(),
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        assert any(e["event"] == SSE_EVENT_PLAN for e in events)


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
        repo.get_session.return_value = session

        service = _make_service(user=user, repo=repo)
        result = await service.approve_plan(plan_id=plan.id)

        assert result.status == PlanStatus.APPROVED
        repo.update_plan_status.assert_called_once_with(
            plan_id=plan.id,
            tenant_id=user.tenant_id,
            status=PlanStatus.APPROVED,
        )

    @pytest.mark.anyio
    async def test_approve_non_proposed_plan_raises(self):
        user = _make_user()
        repo = AsyncMock()
        plan = _make_plan(
            status=PlanStatus.APPLIED,
            tenant_id=user.tenant_id,
        )
        repo.get_plan.return_value = plan

        service = _make_service(user=user, repo=repo)
        with pytest.raises(BadRequestException, match="Cannot approve plan"):
            await service.approve_plan(plan_id=plan.id)

    @pytest.mark.anyio
    async def test_approve_already_approved_plan_raises(self):
        user = _make_user()
        repo = AsyncMock()
        plan = _make_plan(
            status=PlanStatus.APPROVED,
            tenant_id=user.tenant_id,
        )
        repo.get_plan.return_value = plan

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
    @patch(
        "intric.flows.ai_builder.ai_builder_plan_store.persist_plan",
        new_callable=AsyncMock,
    )
    async def test_keep_current_description_sets_manual_override(
        self, mock_persist_plan
    ):
        user = _make_user()
        repo = AsyncMock()

        plan = _make_plan(
            status=PlanStatus.PROPOSED,
            tenant_id=user.tenant_id,
            edit_result_json={"other_key": "value"},
        )
        session = _make_session(
            session_id=plan.session_id,
            actor_user_id=user.id,
            tenant_id=user.tenant_id,
        )
        revised_plan = _make_plan(
            session_id=plan.session_id,
            tenant_id=user.tenant_id,
            edit_result_json={
                "other_key": "value",
                "description_override_manual": True,
            },
        )

        repo.get_plan.return_value = plan
        repo.get_session.return_value = session
        mock_persist_plan.return_value = revised_plan

        service = _make_service(user=user, repo=repo)
        result = await service.revise_plan(
            plan_id=plan.id,
            revision_type="keep_current_description",
        )

        assert result == revised_plan
        assert mock_persist_plan.await_count == 1
        assert (
            mock_persist_plan.await_args.kwargs["edit_result_json"][
                "description_override_manual"
            ]
            is True
        )

    @pytest.mark.anyio
    async def test_unsupported_revision_type_raises(self):
        user = _make_user()
        repo = AsyncMock()

        plan = _make_plan(
            status=PlanStatus.PROPOSED,
            tenant_id=user.tenant_id,
        )
        session = _make_session(
            session_id=plan.session_id,
            actor_user_id=user.id,
            tenant_id=user.tenant_id,
        )
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        service = _make_service(user=user, repo=repo)
        with pytest.raises(BadRequestException) as exc_info:
            await service.revise_plan(
                plan_id=plan.id,
                revision_type="regenerate_description",
            )

        assert exc_info.value.code == "unsupported_revision_type"


# ---------------------------------------------------------------------------
# Apply plan tests
# ---------------------------------------------------------------------------


class TestApplyPlan:
    @pytest.mark.anyio
    async def test_apply_non_approved_plan_raises(self):
        user = _make_user()
        repo = AsyncMock()
        plan = _make_plan(
            status=PlanStatus.PROPOSED,
            tenant_id=user.tenant_id,
        )
        repo.get_plan.return_value = plan

        service = _make_service(user=user, repo=repo)
        with pytest.raises(BadRequestException, match="must be approved"):
            await service.apply_plan(plan_id=plan.id)

    @pytest.mark.anyio
    async def test_apply_checks_actor_matches(self):
        user = _make_user()
        repo = AsyncMock()

        # Plan + session where actor is different user
        plan = _make_plan(
            status=PlanStatus.APPROVED,
            tenant_id=user.tenant_id,
        )
        session = _make_session(
            session_id=plan.session_id,
            actor_user_id=uuid4(),  # Different user
            tenant_id=user.tenant_id,
        )
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        service = _make_service(user=user, repo=repo)
        with pytest.raises(UnauthorizedException, match="session creator"):
            await service.apply_plan(plan_id=plan.id)

    @pytest.mark.anyio
    async def test_apply_edit_session_checks_draft_revision(self):
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()

        flow_id = uuid4()
        plan = _make_plan(
            status=PlanStatus.APPROVED,
            tenant_id=user.tenant_id,
        )
        session = _make_session(
            session_id=plan.session_id,
            actor_user_id=user.id,
            tenant_id=user.tenant_id,
            target_kind=TargetKind.EDIT,
            flow_id=flow_id,
        )

        # Flow has draft_revision=5, but caller expects 3
        flow = MagicMock()
        flow.draft_revision = 5
        flow.space_id = session.space_id
        flow_service.get_flow.return_value = flow

        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        service = _make_service(user=user, repo=repo, flow_service=flow_service)
        with pytest.raises(BadRequestException, match="ändrades"):
            await service.apply_plan(plan_id=plan.id, expected_revision=3)

    @pytest.mark.anyio
    async def test_apply_edit_session_rejects_flow_space_mismatch(self):
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()

        flow_id = uuid4()
        plan = _make_plan(
            status=PlanStatus.APPROVED,
            tenant_id=user.tenant_id,
        )
        session = _make_session(
            session_id=plan.session_id,
            actor_user_id=user.id,
            tenant_id=user.tenant_id,
            space_id=uuid4(),
            target_kind=TargetKind.EDIT,
            flow_id=flow_id,
        )

        flow = MagicMock()
        flow.draft_revision = 1
        flow.space_id = uuid4()
        flow_service.get_flow.return_value = flow

        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        service = _make_service(user=user, repo=repo, flow_service=flow_service)
        with pytest.raises(BadRequestException, match="space"):
            await service.apply_plan(plan_id=plan.id, expected_revision=1)

    @pytest.mark.anyio
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.execute_changeset")
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.compile_changeset")
    async def test_apply_edit_passes_expected_revision_to_executor(
        self, mock_compile, mock_execute
    ):
        from intric.flows.ai_builder.ai_builder_models import ApplyResultResponse

        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()

        flow_id = uuid4()
        plan = _make_plan(
            status=PlanStatus.APPROVED,
            tenant_id=user.tenant_id,
        )
        session = _make_session(
            session_id=plan.session_id,
            actor_user_id=user.id,
            tenant_id=user.tenant_id,
            space_id=uuid4(),
            target_kind=TargetKind.EDIT,
            flow_id=flow_id,
        )

        flow = MagicMock()
        flow.draft_revision = 7
        flow.space_id = session.space_id
        flow.published_version = None
        flow_service.get_flow.return_value = flow

        mock_compile.return_value = MagicMock()
        mock_execute.return_value = ApplyResultResponse(
            flow_id=flow_id,
            flow_name="Flow",
            steps_created=0,
            steps_updated=1,
            steps_removed=0,
        )

        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        service = _make_service(user=user, repo=repo, flow_service=flow_service)
        await service.apply_plan(plan_id=plan.id, expected_revision=7)

        mock_execute.assert_awaited_once()
        assert mock_execute.await_args.kwargs["expected_revision"] == 7

    @pytest.mark.anyio
    async def test_apply_edit_session_no_flow_id_raises(self):
        user = _make_user()
        repo = AsyncMock()

        plan = _make_plan(
            status=PlanStatus.APPROVED,
            tenant_id=user.tenant_id,
        )
        session = _make_session(
            session_id=plan.session_id,
            actor_user_id=user.id,
            tenant_id=user.tenant_id,
            target_kind=TargetKind.EDIT,
            flow_id=None,  # Missing
        )

        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        service = _make_service(user=user, repo=repo)
        with pytest.raises(BadRequestException, match="no flow_id"):
            await service.apply_plan(plan_id=plan.id)

    @pytest.mark.anyio
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.execute_changeset")
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.compile_changeset")
    async def test_apply_create_session_success(self, mock_compile, mock_execute):
        from intric.flows.ai_builder.ai_builder_models import ApplyResultResponse

        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()

        flow_id = uuid4()
        plan = _make_plan(
            status=PlanStatus.APPROVED,
            tenant_id=user.tenant_id,
        )
        session = _make_session(
            session_id=plan.session_id,
            actor_user_id=user.id,
            tenant_id=user.tenant_id,
            target_kind=TargetKind.CREATE,
        )

        result = ApplyResultResponse(
            flow_id=flow_id,
            flow_name="New Flow",
            steps_created=2,
            steps_updated=0,
            steps_removed=0,
        )

        mock_compile.return_value = MagicMock()
        mock_execute.return_value = result

        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        service = _make_service(user=user, repo=repo, flow_service=flow_service)
        apply_result = await service.apply_plan(plan_id=plan.id)

        assert apply_result.flow_id == flow_id
        assert apply_result.steps_created == 2

        # Check status transitions
        status_calls = repo.update_session_status.call_args_list
        assert status_calls[0].kwargs["status"] == SessionStatus.APPLYING
        assert status_calls[1].kwargs["status"] == SessionStatus.APPLIED

        repo.update_plan_status.assert_called_once_with(
            plan_id=plan.id,
            tenant_id=user.tenant_id,
            status=PlanStatus.APPLIED,
        )

        # Create session updates flow_id
        repo.update_session_flow_id.assert_called_once_with(
            session_id=session.id,
            tenant_id=user.tenant_id,
            flow_id=flow_id,
        )

    @pytest.mark.anyio
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.execute_changeset")
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.compile_changeset")
    async def test_apply_create_audio_plan_requires_transcription_model_before_executor(
        self, mock_compile, mock_execute
    ):
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()
        space_service = AsyncMock()

        audio_spec = FlowDraftSpecCore(
            flow_name="Audio flow",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Transcribe",
                    assistant_spec=AssistantSpec(instructions="Transcribe."),
                    input_source=InputSource.FLOW_INPUT,
                    input_type=InputType.AUDIO,
                )
            ],
        )
        plan = _make_plan(
            status=PlanStatus.APPROVED,
            tenant_id=user.tenant_id,
            spec=audio_spec,
        )
        session = _make_session(
            session_id=plan.session_id,
            actor_user_id=user.id,
            tenant_id=user.tenant_id,
            target_kind=TargetKind.CREATE,
        )
        space = MagicMock()
        space.get_default_transcription_model.return_value = None
        space_service.get_space.return_value = space

        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        lifecycle = AIBuilderPlanLifecycle(
            user=user,
            repo=repo,
            flow_service=flow_service,
            space_service=space_service,
        )

        with pytest.raises(
            BadRequestException, match="transcription model must be selected"
        ):
            await lifecycle.apply_plan(plan_id=plan.id)

        repo.update_session_status.assert_not_awaited()
        mock_compile.assert_not_called()
        mock_execute.assert_not_awaited()

    @pytest.mark.anyio
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.execute_changeset")
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.compile_changeset")
    async def test_apply_edit_session_does_not_update_flow_id(
        self, mock_compile, mock_execute
    ):
        from intric.flows.ai_builder.ai_builder_models import ApplyResultResponse

        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()

        flow_id = uuid4()
        plan = _make_plan(
            status=PlanStatus.APPROVED,
            tenant_id=user.tenant_id,
        )
        session = _make_session(
            session_id=plan.session_id,
            actor_user_id=user.id,
            tenant_id=user.tenant_id,
            target_kind=TargetKind.EDIT,
            flow_id=flow_id,
        )

        flow = MagicMock()
        flow.draft_revision = 1
        flow.space_id = session.space_id
        flow.published_version = None
        flow_service.get_flow.return_value = flow

        result = ApplyResultResponse(
            flow_id=flow_id,
            flow_name="Updated Flow",
            steps_created=0,
            steps_updated=1,
            steps_removed=0,
        )

        mock_compile.return_value = MagicMock()
        mock_execute.return_value = result

        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        service = _make_service(user=user, repo=repo, flow_service=flow_service)
        await service.apply_plan(plan_id=plan.id, expected_revision=1)

        repo.update_session_flow_id.assert_not_called()

    @pytest.mark.anyio
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.execute_changeset")
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.compile_changeset")
    async def test_apply_failure_rolls_back_session_status(
        self, mock_compile, mock_execute
    ):
        user = _make_user()
        repo = AsyncMock()

        plan = _make_plan(
            status=PlanStatus.APPROVED,
            tenant_id=user.tenant_id,
        )
        session = _make_session(
            session_id=plan.session_id,
            actor_user_id=user.id,
            tenant_id=user.tenant_id,
            target_kind=TargetKind.CREATE,
        )

        mock_compile.return_value = MagicMock()
        mock_execute.side_effect = RuntimeError("DB explosion")

        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        service = _make_service(user=user, repo=repo)
        with pytest.raises(RuntimeError, match="DB explosion"):
            await service.apply_plan(plan_id=plan.id)

        # Should have set APPLYING, then rolled back to AWAITING_APPROVAL
        status_calls = repo.update_session_status.call_args_list
        assert status_calls[0].kwargs["status"] == SessionStatus.APPLYING
        assert status_calls[1].kwargs["status"] == SessionStatus.AWAITING_APPROVAL

    @pytest.mark.anyio
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.execute_changeset")
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.compile_changeset")
    async def test_apply_edit_matching_revision_succeeds(
        self, mock_compile, mock_execute
    ):
        from intric.flows.ai_builder.ai_builder_models import ApplyResultResponse

        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()

        flow_id = uuid4()
        plan = _make_plan(
            status=PlanStatus.APPROVED,
            tenant_id=user.tenant_id,
        )
        session = _make_session(
            session_id=plan.session_id,
            actor_user_id=user.id,
            tenant_id=user.tenant_id,
            target_kind=TargetKind.EDIT,
            flow_id=flow_id,
        )

        flow = MagicMock()
        flow.draft_revision = 7
        flow.space_id = session.space_id
        flow.published_version = None
        flow_service.get_flow.return_value = flow

        result = ApplyResultResponse(
            flow_id=flow_id,
            flow_name="Flow",
            steps_created=0,
            steps_updated=1,
            steps_removed=0,
        )
        mock_compile.return_value = MagicMock()
        mock_execute.return_value = result

        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        service = _make_service(user=user, repo=repo, flow_service=flow_service)
        apply_result = await service.apply_plan(plan_id=plan.id, expected_revision=7)

        assert apply_result.steps_updated == 1

    @pytest.mark.anyio
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.execute_changeset")
    @patch("intric.flows.ai_builder.ai_builder_plan_lifecycle.compile_changeset")
    async def test_apply_plan_passes_manual_description_override_to_compile(
        self, mock_compile, mock_execute
    ):
        from intric.flows.ai_builder.ai_builder_models import ApplyResultResponse

        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()

        flow_id = uuid4()
        plan = _make_plan(
            status=PlanStatus.APPROVED,
            tenant_id=user.tenant_id,
            edit_result_json={"description_override_manual": True},
        )
        session = _make_session(
            session_id=plan.session_id,
            actor_user_id=user.id,
            tenant_id=user.tenant_id,
            target_kind=TargetKind.EDIT,
            flow_id=flow_id,
        )

        flow = MagicMock()
        flow.draft_revision = 4
        flow.space_id = session.space_id
        flow.published_version = None
        flow.id = flow_id
        flow.steps = []
        flow_service.get_flow.return_value = flow
        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        mock_compile.return_value = MagicMock()
        mock_execute.return_value = ApplyResultResponse(
            flow_id=flow_id,
            flow_name="Flow",
            steps_created=0,
            steps_updated=1,
            steps_removed=0,
        )

        service = _make_service(user=user, repo=repo, flow_service=flow_service)
        await service.apply_plan(plan_id=plan.id, expected_revision=4)

        assert mock_compile.call_args.kwargs["description_override_manual"] is True

    @pytest.mark.anyio
    async def test_apply_published_flow_raises_flow_is_published(self):
        """Published flows must NOT be auto-unpublished. Raise typed error instead."""
        user = _make_user()
        repo = AsyncMock()
        flow_service = AsyncMock()

        flow_id = uuid4()
        plan = _make_plan(
            status=PlanStatus.APPROVED,
            tenant_id=user.tenant_id,
        )
        session = _make_session(
            session_id=plan.session_id,
            actor_user_id=user.id,
            tenant_id=user.tenant_id,
            target_kind=TargetKind.EDIT,
            flow_id=flow_id,
        )

        flow = MagicMock()
        flow.draft_revision = 1
        flow.space_id = session.space_id
        flow.published_version = 3
        flow.id = flow_id
        flow.steps = []
        flow_service.get_flow.return_value = flow

        repo.get_plan.return_value = plan
        repo.get_session.return_value = session

        service = _make_service(user=user, repo=repo, flow_service=flow_service)
        with pytest.raises(BadRequestException) as exc_info:
            await service.apply_plan(plan_id=plan.id, expected_revision=1)

        assert exc_info.value.code == "flow_is_published"
        # unpublish_flow must NOT have been called
        flow_service.unpublish_flow.assert_not_awaited()


class TestSendMessageStructuredQuestion:
    @pytest.mark.anyio
    async def test_question_tool_call_yields_question_event(self):
        """Model-authored structured questions are replaced by backend canonical questions."""
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

        question_args = {
            "question_id": "output_format",
            "question": "Which output format?",
            "options": [
                {"label": "JSON", "description": "Structured output"},
                {"label": "Text", "description": "Free text"},
            ],
            "selection_mode": "single",
            "allow_custom": True,
        }
        tc = _make_tool_call(
            name="ask_structured_question",
            arguments=question_args,
        )

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(content=None, tool_calls=[tc])
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Help me pick a format",
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        question_events = [e for e in events if e["event"] == SSE_EVENT_QUESTION]
        assert len(question_events) == 1

        data = json.loads(question_events[0]["data"])
        assert data["question_id"] == "final_output_mode"
        assert data["question"] == "What should the flow produce as the final output?"
        assert [option["id"] for option in data["options"]] == [
            "structured_text",
            "pdf_document",
            "docx_document",
            "structured_json",
        ]
        assert data["selection_mode"] == "single"
        assert data["allow_custom"] is True

        repo.append_session_messages.assert_called()
        saved_conversation = repo.append_session_messages.call_args[1]["conversation"]
        assert saved_conversation[1].metadata is not None
        assert (
            saved_conversation[1].metadata["planner_telemetry"]["tool_call_count"] == 1
        )
        assert (
            saved_conversation[1].metadata["session_telemetry"][
                "clarification_question_count"
            ]
            == 1
        )
        tool_msgs = [m for m in saved_conversation if m.role == "tool"]
        assert len(tool_msgs) >= 1
        assert tool_msgs[-1].tool_call_id.startswith("discovery_")
        repo.update_session_conversation.assert_not_called()

    @pytest.mark.anyio
    async def test_duplicate_output_question_alias_is_suppressed_when_budget_exhausted(
        self,
    ):
        """When the question budget is exhausted (5 answers given, budget is 3),
        a duplicate final_output_mode from the LLM is suppressed and no backend
        followup question is emitted either — the service falls through to
        non-question continuation.
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
                            "question_id": "input_material_mode",
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
                            "selected_option_ids": ["basic_case_metadata"],
                            "selected_values": ["basic_case_metadata"],
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
            "question_id": "final_output_mode",
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

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(content=None, tool_calls=[tc])
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="DOCX utan mall",
                    question_answer={
                        "question_id": "final_output_format",
                        "selected_option_ids": ["docx_generated"],
                        "selected_values": ["docx_generated"],
                        "answer": "docx_generated",
                        "ui_language": "sv",
                    },
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        question_events = [e for e in events if e["event"] == SSE_EVENT_QUESTION]
        assert len(question_events) == 0

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

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(content=None, tool_calls=[tc])
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Jag vill ladda upp flera PDF-filer och jämföra innehållet mellan dokumenten.",
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        question_events = [e for e in events if e["event"] == SSE_EVENT_QUESTION]
        assert len(question_events) == 1
        data = json.loads(question_events[0]["data"])
        assert data["question_id"] in {
            "processing_scope",
            "document_kind",
            "document_material_scope",
            "final_output_mode",
        }
        assert data["question_id"] != "multi_file_strategy"

    @pytest.mark.anyio
    async def test_supported_model_question_for_resolved_output_recovers_into_requirements_summary(
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
                    content="Jag vill bygga ett flöde som läser in dokument och skapar en textsammanfattning.",
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
                    content="Flera dokument för samma ärende",
                    metadata={
                        "question_answer": {
                            "question_id": "document_material_scope",
                            "selected_option_id": "multiple_documents_case",
                            "answer": "multiple_documents_case",
                        },
                        "ui_language": "sv",
                    },
                ),
                ConversationMessage(
                    role="user",
                    content="Lägg till grundläggande metadata",
                    metadata={
                        "question_answer": {
                            "question_id": "runtime_metadata_fields",
                            "selected_option_id": "basic_case_metadata",
                            "answer": "basic_case_metadata",
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

        model_question_args = {
            "question_id": "final_output_mode",
            "question": "Which result shape do you prefer?",
            "options": [
                {"id": "decision_memo_text", "label": "Text memo"},
                {"id": "decision_memo_docx", "label": "DOCX memo"},
            ],
            "selection_mode": "single",
            "allow_custom": True,
        }
        tc = _make_tool_call(
            name="ask_structured_question",
            arguments=model_question_args,
        )
        summary_tool = _make_tool_call(
            tool_call_id="call_requirements",
            name="confirm_requirements",
            arguments=_make_requirements_summary_payload().model_dump(mode="json"),
        )

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    _make_llm_response(content=None, tool_calls=[tc]),
                    _make_llm_response(content=None, tool_calls=[summary_tool]),
                ]
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Behåll samma riktning",
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        question_events = [e for e in events if e["event"] == SSE_EVENT_QUESTION]
        assert question_events == []
        summary_events = [
            e for e in events if e["event"] == SSE_EVENT_REQUIREMENTS_SUMMARY
        ]
        assert len(summary_events) == 1

    @pytest.mark.anyio
    async def test_unexpected_model_question_after_discovery_ready_triggers_requirements_summary_retry(
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
        repo.get_session.return_value = session

        completion_service = AsyncMock()
        adapter = _make_adapter()
        completion_service._get_adapter.return_value = adapter

        unexpected_question = _make_tool_call(
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
        summary_tool = _make_tool_call(
            tool_call_id="call_requirements",
            name="confirm_requirements",
            arguments=_make_requirements_summary_payload().model_dump(mode="json"),
        )

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    _make_llm_response(content=None, tool_calls=[unexpected_question]),
                    _make_llm_response(content=None, tool_calls=[summary_tool]),
                ]
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Bygg vidare",
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        question_events = [e for e in events if e["event"] == SSE_EVENT_QUESTION]
        assert question_events == []
        summary_events = [
            e for e in events if e["event"] == SSE_EVENT_REQUIREMENTS_SUMMARY
        ]
        assert len(summary_events) == 1

    @pytest.mark.anyio
    async def test_repeated_output_question_after_answer_recovers_without_internal_error(
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
                    content="Skapa en ljudfil transkriberare samt sammanfattare",
                    metadata={"ui_language": "sv"},
                ),
                ConversationMessage(
                    role="assistant",
                    content="Jag behöver förstå slutresultatet lite bättre innan jag kan bekräfta lösningen.",
                    tool_calls=[
                        {
                            "id": "call_q1",
                            "name": "ask_structured_question",
                            "arguments": {
                                "question_id": "final_output_mode",
                                "question": "Vad ska flödet producera som slutresultat?",
                                "options": [
                                    {
                                        "id": "structured_text",
                                        "label": "Strukturerat textresultat",
                                    },
                                    {"id": "pdf_document", "label": "PDF-dokument"},
                                    {"id": "docx_document", "label": "DOCX-dokument"},
                                    {
                                        "id": "structured_json",
                                        "label": "Strukturerad JSON",
                                    },
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
                    tool_call_id="call_q1",
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
        summary_tool = _make_tool_call(
            tool_call_id="call_requirements_audio_pdf",
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

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    _make_llm_response(content=None, tool_calls=[repeated_question]),
                    _make_llm_response(content=None, tool_calls=[summary_tool]),
                ]
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="PDF-dokument",
                    question_answer={
                        "question_id": "final_output_mode",
                        "selected_option_ids": ["pdf_document"],
                        "selected_values": ["pdf_document"],
                        "ui_language": "sv",
                    },
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        error_events = [e for e in events if e["event"] == SSE_EVENT_ERROR]
        assert error_events == []
        summary_events = [
            e for e in events if e["event"] == SSE_EVENT_REQUIREMENTS_SUMMARY
        ]
        assert len(summary_events) == 1

    @pytest.mark.anyio
    async def test_repeated_output_question_after_freeform_label_answer_continues_without_internal_error(
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
                    content="Skapa en ljudfil transkriberare samt sammanfattare",
                    metadata={"ui_language": "sv"},
                ),
                ConversationMessage(
                    role="assistant",
                    content="Jag behöver förstå slutresultatet lite bättre innan jag kan bekräfta lösningen.",
                    tool_calls=[
                        {
                            "id": "call_q1",
                            "name": "ask_structured_question",
                            "arguments": {
                                "question_id": "final_output_mode",
                                "question": "Vad ska flödet producera som slutresultat?",
                                "options": [
                                    {
                                        "id": "structured_text",
                                        "label": "Strukturerat textresultat",
                                    },
                                    {"id": "pdf_document", "label": "PDF-dokument"},
                                    {"id": "docx_document", "label": "DOCX-dokument"},
                                    {
                                        "id": "structured_json",
                                        "label": "Strukturerad JSON",
                                    },
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
                    tool_call_id="call_q1",
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
        summary_tool = _make_tool_call(
            tool_call_id="call_requirements_inferred_audio_pdf",
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

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    _make_llm_response(content=None, tool_calls=[repeated_question]),
                    _make_llm_response(content=None, tool_calls=[summary_tool]),
                ]
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="PDF-dokument",
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        error_events = [e for e in events if e["event"] == SSE_EVENT_ERROR]
        assert error_events == []
        non_terminal_events = {
            e["event"]
            for e in events
            if e["event"] in {SSE_EVENT_REQUIREMENTS_SUMMARY, SSE_EVENT_QUESTION}
        }
        assert non_terminal_events

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

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(
                    content=None, tool_calls=[repeated_question]
                )
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Ett ärende åt gången",
                    question_answer={
                        "question_id": "processing_scope",
                        "selected_option_ids": ["single_case"],
                        "selected_values": ["single_case"],
                        "ui_language": "sv",
                    },
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        error_events = [e for e in events if e["event"] == SSE_EVENT_ERROR]
        assert error_events == []
        question_events = [e for e in events if e["event"] == SSE_EVENT_QUESTION]
        assert len(question_events) == 1
        data = json.loads(question_events[0]["data"])
        assert data["question_id"] != "processing_scope"

    @pytest.mark.anyio
    async def test_question_recovery_exhausts_when_model_repeats_structured_question(
        self,
    ):
        user = _make_user()
        repo = AsyncMock()
        session = _make_session(
            status=SessionStatus.CHATTING,
            tenant_id=user.tenant_id,
            conversation=[
                ConversationMessage(
                    role="user", content="Jag vill bygga ett enkelt PDF-flöde."
                ),
                ConversationMessage(
                    role="user",
                    content="Ett ärende åt gången",
                    metadata={
                        "question_answer": {
                            "question_id": "processing_scope",
                            "selected_option_id": "single_case",
                            "answer": "single_case",
                        }
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
                        }
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
                        }
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
                        }
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
                        }
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
                        }
                    },
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

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[
                    _make_llm_response(content=None, tool_calls=[repeated_question]),
                    _make_llm_response(content=None, tool_calls=[repeated_question]),
                    _make_llm_response(content=None, tool_calls=[repeated_question]),
                ]
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Bygg vidare",
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        error_events = [e for e in events if e["event"] == SSE_EVENT_ERROR]
        assert len(error_events) == 1
        payload = json.loads(error_events[0]["data"])
        assert payload["code"] == "question_recovery_exhausted"

    @pytest.mark.anyio
    async def test_invalid_question_falls_back_to_text(self):
        """Malformed ask_structured_question args degrade to a plain text question."""
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

        # Only 1 option — too few
        bad_args = {
            "question": "Pick one",
            "options": [{"label": "Only one"}],
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

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(content=None, tool_calls=[tc])
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Help me",
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        error_events = [e for e in events if e["event"] == SSE_EVENT_ERROR]
        assert error_events == []

        text_events = [e for e in events if e["event"] == SSE_EVENT_TEXT]
        assert len(text_events) == 1
        text = json.loads(text_events[0]["data"])["text"]
        assert "Pick one" in text
        assert "Only one" in text
        assert "fri text" in text

        # No plan should be created
        repo.create_plan.assert_not_called()

        repo.append_session_messages.assert_called()
        saved_conversation = repo.append_session_messages.call_args[1]["conversation"]
        tool_msgs = [m for m in saved_conversation if m.role == "tool"]
        assert tool_msgs[-1].tool_call_id == tc.id
        assert "fallback" in (tool_msgs[-1].content or "")
        repo.update_session_conversation.assert_not_called()

    @pytest.mark.anyio
    async def test_unparseable_question_arguments_still_yield_error(self):
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

        tc = MagicMock()
        tc.id = "call_bad_json"
        tc.function.name = "ask_structured_question"
        tc.function.arguments = "{not json"

        service = _make_service(
            user=user,
            repo=repo,
            completion_service=completion_service,
        )

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(content=None, tool_calls=[tc])
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Help me",
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        error_events = [e for e in events if e["event"] == SSE_EVENT_ERROR]
        assert len(error_events) == 1
        assert "Invalid question" in json.loads(error_events[0]["data"])["error"]

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

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(content=None, tool_calls=[tc])
            )
            events = await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="Bygg ett flöde som sammanfattar ett dokument.",
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
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

    @pytest.mark.anyio
    async def test_structured_answer_metadata_is_preserved_on_user_message(self):
        user = _make_user()
        repo = AsyncMock()
        session = _make_session(status=SessionStatus.CHATTING, tenant_id=user.tenant_id)
        repo.get_session.return_value = session

        service = _make_service(user=user, repo=repo)

        with patch(
            "intric.flows.ai_builder.ai_builder_service.litellm"
        ) as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_make_llm_response(
                    content="Perfekt, då bygger jag för ett dokument i taget."
                )
            )
            await _collect_events(
                service.send_message(
                    session_id=session.id,
                    message="En PDF i taget",
                    question_answer={
                        "question_id": "pdf_count",
                        "selected_option_ids": ["single"],
                        "selected_values": [{"mode": "single"}],
                    },
                    litellm_model="openai/gpt-4",
                    litellm_kwargs={"api_key": "sk-test"},
                )
            )

        conversation = repo.commit_turn.call_args.kwargs["new_messages"]
        assert conversation[0].metadata == {
            "question_answer": {
                "question_id": "pdf_count",
                "selected_option_ids": ["single"],
                "selected_values": [{"mode": "single"}],
            }
        }
        repo.update_session_conversation.assert_not_called()


class TestReasoningLeakRegression:
    """Reasoning field must never be exposed in public API responses."""

    def test_plan_event_strips_reasoning(self):
        """Plan SSE events must not include reasoning."""
        from intric.flows.ai_builder.ai_builder_events import build_plan_event

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
        envelope = PlannerPlanEnvelope(
            spec=spec,
            assumptions=["Test"],
            reasoning="SECRET REASONING THAT SHOULD NOT LEAK",
        )

        event = build_plan_event(plan_id=uuid4(), envelope=envelope)
        assert "SECRET REASONING" not in event["data"]
        parsed = json.loads(event["data"])
        assert parsed.get("envelope", {}).get("reasoning") is None

    def test_append_plan_messages_strips_reasoning_from_conversation(self):
        """append_plan_messages must strip reasoning and store only a compact
        summary in the conversation. Full spec lives in BuilderPlans table."""
        from intric.flows.ai_builder.ai_builder_plan_store import append_plan_messages

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
            tool_name=CREATE_FLOW_TOOL_NAME,
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

    def test_session_response_with_compact_arguments_has_no_reasoning(self):
        """SessionResponse with compact arguments (from append_plan_messages)
        should never contain reasoning."""
        from intric.flows.ai_builder.ai_builder_models import SessionResponse

        # Simulate what append_plan_messages now stores (compact summary)
        conversation = [
            ConversationMessage(
                role="assistant",
                content="Here is a plan.",
                tool_calls=[
                    {
                        "id": "call_123",
                        "name": CREATE_FLOW_TOOL_NAME,
                        "arguments": {
                            "flow_name": "Test",
                            "step_count": 1,
                            "step_names": ["Step A"],
                            "plan_rationale": "Simple flow.",
                        },
                    }
                ],
            ),
        ]

        response = SessionResponse(
            session_id=uuid4(),
            status=SessionStatus.CHATTING,
            target_kind=TargetKind.CREATE,
            conversation=conversation,
        )
        serialized = response.model_dump_json()
        assert "reasoning" not in serialized
        assert "step_count" in serialized


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
        file_id=file_id, tenant_id=user.tenant_id, user_id=user.id
    )
    file_service.get_files_by_ids.return_value = [attached_file]
    completion_service.resolve_litellm_params.return_value = (
        "openai/gpt-5.4",
        {"api_key": "test"},
    )
    repo.list_session_file_ids.return_value = []

    context = await service.prepare_message_context(
        session=session,
        space=space,
        model_id=None,
        tenant_flow_settings=None,
        message_file_ids=[file_id],
    )

    repo.attach_session_files.assert_not_awaited()
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
        file_id=file_id, tenant_id=user.tenant_id, user_id=user.id
    )
    file_service.get_files_by_ids.return_value = [attached_file]
    completion_service.resolve_litellm_params.return_value = (
        "openai/gpt-5.4",
        {"api_key": "test"},
    )
    repo.list_session_file_ids.return_value = []

    context = await service.prepare_message_context(
        session=session,
        space=space,
        model_id=None,
        tenant_flow_settings=None,
        message_file_ids=[file_id],
    )

    repo.attach_session_files.assert_not_awaited()
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
    completion_service.resolve_litellm_params.return_value = ("openai/gpt-5.4", {})
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
async def test_cancel_session_detaches_session_files_before_cancelling() -> None:
    user = _make_user()
    repo = AsyncMock()
    session = _make_session(actor_user_id=user.id)
    repo.get_session.return_value = session
    service = _make_service(user=user, repo=repo)

    await service.cancel_session(session.id)

    repo.detach_session_files_for_sessions.assert_awaited_once_with(
        session_ids=[session.id],
        tenant_id=user.tenant_id,
    )
    repo.cancel_session.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_session_force_new_relies_on_repo_cancellation_cleanup() -> None:
    user = _make_user()
    repo = AsyncMock()
    cancelled_session_id = uuid4()
    repo.cancel_matching_active_sessions.return_value = [cancelled_session_id]
    created_session = _make_session(actor_user_id=user.id)
    repo.create_session.return_value = created_session
    service = _make_service(user=user, repo=repo)

    await service.create_session(
        space_id=created_session.space_id,
        target_kind=TargetKind.CREATE,
        force_new=True,
    )

    repo.detach_session_files_for_sessions.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_session_attachment_snapshot_returns_warning_when_some_files_missing() -> (
    None
):
    user = _make_user()
    repo = AsyncMock()
    file_service = AsyncMock()
    available_file = _make_file(
        file_id=uuid4(), tenant_id=user.tenant_id, user_id=user.id
    )
    repo.list_session_file_ids.return_value = [available_file.id, uuid4()]
    file_service.get_files_by_ids.return_value = [available_file]
    service = AIBuilderService(
        user=user,
        repo=repo,
        flow_service=AsyncMock(),
        completion_service=AsyncMock(),
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
        user_id=user.id,
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
        file_service=file_service,
    )

    snapshot = await service.get_session_attachment_snapshot(session_id=uuid4())

    assert snapshot.files == [unreadable_file]
    assert any("readable" in warning.lower() for warning in snapshot.warnings)
    assert any(unreadable_file.name in warning for warning in snapshot.warnings)
