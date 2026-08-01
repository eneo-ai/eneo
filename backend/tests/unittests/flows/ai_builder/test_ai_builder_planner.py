from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncGenerator
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from eneo.authentication.principal_types import PrincipalType
from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.completion_models.infrastructure.completion_service import (
    ResolvedCompletionModelRoute,
)
from eneo.files.file_models import File, FileType
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AIBuilderAttachmentContext,
    AIBuilderAttachmentContextPolicy,
    AIBuilderAttachmentOutputSchemaDiscovery,
    build_ai_builder_attachment_context,
)
from eneo.flows.ai_builder.ai_builder_discovery_models import DiscoveryAnalysis
from eneo.flows.ai_builder.ai_builder_discovery_runtime import DiscoveryRuntimeResult
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    BuilderSession,
    BuilderTurnLifecycle,
    BuilderTurnState,
    ConversationMessage,
    SessionStatus,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
    AIBuilderKnownProviderRejectionException,
    build_ai_builder_error_event,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    AIBuilderStatus,
    AIBuilderStreamEvent,
    KeyDecisionPayload,
    RequirementsSummaryPayload,
)
from eneo.flows.ai_builder.ai_builder_events import (
    build_status_event,
    build_text_event,
    encode_ai_builder_stream_event,
)
from eneo.flows.ai_builder.ai_builder_output_schema_evidence import (
    OUTPUT_SCHEMA_MAX_JSON_BYTES,
)
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    RequestedOutputSections,
)
from eneo.flows.ai_builder.ai_builder_plan_edit_context import AIBuilderPlanEditContext
from eneo.flows.ai_builder.ai_builder_planner import (
    AIBuilderPlanner,
)
from eneo.flows.ai_builder.ai_builder_planner_request_preparation import (
    PlannerRequestPreparationInput,
    ProposalPrepared,
    ServerOutputPrepared,
    build_proposal_prepared,
    prepare_planner_request,
    validate_preprovider_output_schema_gate,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import ProposalTurnTelemetry
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ProposalMessageGroup,
    flatten_proposal_message_groups,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    RequirementsState,
    build_requirements_version,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableKnowledgeBaseResource,
    AIBuilderAvailableModelResource,
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_scoped_plan_revision import (
    ScopedPlanRevisionOutcome,
)
from eneo.flows.ai_builder.ai_builder_server_decision_dispatch import (
    ServerDecisionDispatchRequest,
    ServerDecisionDispatchResult,
    ServerDecisionProposalContinuation,
)
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionTurnClaim,
    SessionTurnClaimDisposition,
    SessionTurnPreflight,
    SessionTurnPreparationBaseline,
)
from eneo.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy
from eneo.flows.ai_builder.ai_builder_tools import build_propose_flow_tool_schema
from eneo.flows.ai_builder.ai_builder_turn_controller import (
    AskCanonicalQuestion,
    AskOutputSchemaConflict,
    CommitArchitecture,
    ConfirmRequirements,
    ReviseArchitecture,
    resolve_turn_control,
)
from eneo.flows.ai_builder.ai_builder_user_question_metadata import (
    prepare_user_question_metadata,
)
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    FileRoleEvidence,
    PlanningState,
    PlanningStatePayloadTooLargeError,
    ResolvedSlot,
    StepTriple,
)
from eneo.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
from eneo.flows.flow_authoring_spec import AssistantSpec
from eneo.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)
from eneo.main.exceptions import BadRequestException
from eneo.tokens.token_utils import count_message_tokens, count_tool_tokens


def _route(
    *,
    model: str = "openai/gpt-5.4",
    kwargs: dict[str, object] | None = None,
) -> ResolvedCompletionModelRoute:
    return ResolvedCompletionModelRoute(
        litellm_model=model,
        litellm_kwargs=kwargs or {},
        supported_model_kwargs=SupportedModelKwargs(
            temperature=ModelKwargCapability(supported=True)
        ),
    )


_TEST_CLIENT_TURN_ID = UUID("11111111-1111-4111-8111-111111111111")
_TEST_REQUEST_FINGERPRINT = "a" * 64


def _test_request_snapshot(message: str) -> FlowPersistedJsonObject:
    return {
        "client_turn_id": str(_TEST_CLIENT_TURN_ID),
        "message": message,
    }


def _make_planner() -> AIBuilderPlanner:
    planner = AIBuilderPlanner(
        user=MagicMock(tenant_id=uuid4()),
        repo=AsyncMock(),
        litellm_client=AsyncMock(),
        planner_temperature=0.1,
        self_correction_temperature=0.1,
        forced_proposal_temperature=0.1,
        quality_retry_warning_codes=set(),
    )

    async def accept_turn(**kwargs: object) -> SessionTurnClaim:
        acceptance = kwargs["acceptance"]
        user_message = cast(
            ConversationMessage,
            getattr(acceptance, "user_message"),
        )
        session = planner.repo.get_session.return_value
        if hasattr(session, "conversation"):
            session.conversation = [*session.conversation, user_message]
        return SessionTurnClaim(
            disposition=SessionTurnClaimDisposition.EXECUTE,
            user_message=user_message,
            base_planning_state_version=getattr(session, "planning_state_version", 0),
        )

    async def preflight_turn(**_: object) -> SessionTurnPreflight:
        session = planner.repo.get_session.return_value
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
                session_status=SessionStatus(session.status),
                latest_plan_id=getattr(session, "latest_plan_id", None),
                planning_state_version=getattr(session, "planning_state_version", 0),
                latest_turn_id=None,
                latest_turn_state=None,
                attachment_file_ids=(),
            ),
        )

    planner.repo.accept_session_turn.side_effect = accept_turn
    planner.repo.preflight_session_turn.side_effect = preflight_turn
    return planner


def _model_resource(
    local_id: str,
    name: str,
    *,
    provider: str = "test",
) -> AIBuilderAvailableModelResource:
    return {
        "id": local_id,
        "ref": local_id,
        "name": name,
        "display_name": name,
        "provider": provider,
    }


def _kb_resource(
    local_id: str,
    name: str,
    *,
    description: str = "",
) -> AIBuilderAvailableKnowledgeBaseResource:
    return {
        "id": local_id,
        "ref": local_id,
        "name": name,
        "display_name": name,
        "description": description,
    }


def _make_file(
    text: str = "Reference",
    *,
    name: str = "reference.txt",
    mimetype: str = "text/plain",
) -> File:
    return File(
        id=uuid4(),
        name=name,
        checksum="checksum",
        size=len(text.encode("utf-8")),
        mimetype=mimetype,
        file_type=FileType.TEXT,
        text=text,
        blob=None,
        transcription=None,
        owner_type=PrincipalType.USER,
        owner_user_id=uuid4(),
        tenant_id=uuid4(),
    )


def _runtime_result(
    discovery_analysis: DiscoveryAnalysis,
    planning_state: PlanningState,
) -> DiscoveryRuntimeResult:
    return DiscoveryRuntimeResult(
        discovery_analysis=discovery_analysis,
        planning_state=planning_state,
    )


def _discovery_analysis(
    *,
    mvs_met: bool = True,
    selected_question_ids: tuple[str, ...] = (),
    assumptions: tuple[str, ...] = (),
) -> DiscoveryAnalysis:
    return DiscoveryAnalysis(
        issues=(),
        mvs_met=mvs_met,
        selected_question_ids=selected_question_ids,
        assumptions=assumptions,
    )


async def _prepare_planner_request_for_test(
    planner: AIBuilderPlanner,
    *,
    conversation: list[ConversationMessage],
    completion_model_route: ResolvedCompletionModelRoute,
    available_models: list[AIBuilderAvailableModelResource] | None = None,
    available_kbs: list[AIBuilderAvailableKnowledgeBaseResource] | None = None,
    flow: object = None,
    assistant_snapshots: object = None,
    attachment_files: list[File] | None = None,
    max_input_tokens: int = 4096,
    max_output_tokens: int = 1024,
    budget_policy: AIBuilderBudgetPolicy | None = None,
    base_planning_state_version: int = 0,
    plan_edit_context: object = None,
    prior_plan_for_revision: BuilderPlan | None = None,
    persisted_planning_state: PlanningState | None = None,
    before_provider_call: AsyncMock | None = None,
    prepared_attachment_context: AIBuilderAttachmentContext | None = None,
    output_schema_gate_checked: bool = False,
):
    return await prepare_planner_request(
        PlannerRequestPreparationInput(
            conversation=conversation,
            litellm_client=planner.litellm_client,
            completion_model_route=completion_model_route,
            available_models=available_models,
            available_kbs=available_kbs,
            flow=cast(Any, flow),
            assistant_snapshots=cast(Any, assistant_snapshots),
            attachment_files=attachment_files or [],
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
            mapped_execution_policy=FlowMappedExecutionPolicy(),
            budget_policy=budget_policy
            or AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
            attachment_context_policy=AIBuilderAttachmentContextPolicy(),
            base_planning_state_version=base_planning_state_version,
            tenant_id=planner.user.tenant_id,
            plan_edit_context=cast(Any, plan_edit_context),
            prior_plan_for_revision=prior_plan_for_revision,
            persisted_planning_state=persisted_planning_state,
            current_turn_start=0,
            usage_tracker=ProposalTurnTelemetry(
                request_id="req-prepare-test",
                model=completion_model_route.litellm_model,
                target_kind=TargetKind.CREATE,
            ),
            before_provider_call=before_provider_call,
            prepared_attachment_context=prepared_attachment_context,
            output_schema_gate_checked=output_schema_gate_checked,
        )
    )


def _requirements_summary(version: str) -> RequirementsSummaryPayload:
    return RequirementsSummaryPayload(
        requirements_version=version,
        summary="Build a report flow.",
        key_decisions=[KeyDecisionPayload(topic="Input", decision="Use text input")],
        input_description="Text input.",
        output_description="Text output.",
        assumptions=[],
        manual_setup_notes=[],
    )


def _requirements_state_unconfirmed() -> RequirementsState:
    return RequirementsState()


def _requirements_state_confirmed(
    version: str = "requirements-v1",
) -> RequirementsState:
    return RequirementsState(
        latest_summary=_requirements_summary(version),
        latest_version=version,
        latest_attachment_evidence_fingerprint=hashlib.sha256(b"[]").hexdigest(),
        confirmed_version=version,
    )


def _requirements_state_confirmed_for(
    state: PlanningState,
    *,
    ui_language: str | None = "en",
    discovery_assumptions: tuple[str, ...] = (),
) -> RequirementsState:
    decision = resolve_turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        confirmed_attachment_evidence_fingerprint=None,
        ui_language=ui_language,
        discovery_assumptions=discovery_assumptions,
    ).decision
    assert isinstance(decision, ConfirmRequirements)
    version = build_requirements_version(decision.payload)
    return RequirementsState(
        latest_summary=decision.payload,
        latest_version=version,
        latest_attachment_evidence_fingerprint=(
            decision.attachment_evidence_fingerprint
        ),
        confirmed_version=version,
    )


def _architecture_commit() -> ArchitectureCommit:
    return ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=["input_text"],
        committed_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        architecture_hash="a" * 64,
    )


def _budget_policy() -> AIBuilderBudgetPolicy:
    return AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=128,
        minimum_conversation_budget_tokens=256,
    )


def _server_output_prepared() -> ServerOutputPrepared:
    return ServerOutputPrepared(
        requirements_state=_requirements_state_unconfirmed(),
        ui_language="sv",
        slot_classification_metadata=None,
        server_decision=AskCanonicalQuestion(
            slot_name="terminal_output",
            prompt="What should the flow produce?",
        ),
        discovery_analysis=DiscoveryAnalysis(issues=()),
        planning_state=PlanningState.empty(),
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[],
            available_kbs=[],
            prior_bindings=(),
        ),
        attachment_context=None,
        flow_context=None,
    )


def _configure_minimal_send_message(
    planner: AIBuilderPlanner,
    monkeypatch: pytest.MonkeyPatch,
    prepared_request: ProposalPrepared | ServerOutputPrepared,
) -> None:
    planner.repo.get_session.return_value = SimpleNamespace(
        conversation=[],
        status=SessionStatus.CHATTING,
        planning_state_version=1,
    )
    planner.repo.load_planning_state.return_value = None
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.resolve_plan_edit_context",
        AsyncMock(return_value=(None, None)),
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.prepare_planner_request",
        AsyncMock(return_value=prepared_request),
    )


async def _collect_send_message_events(
    planner: AIBuilderPlanner,
    *,
    session_id: UUID,
) -> list[dict[str, str]]:
    client_turn_id = uuid4()
    return [
        encode_ai_builder_stream_event(event)
        async for event in planner.send_message(
            session_id=session_id,
            client_turn_id=client_turn_id,
            request_fingerprint="a" * 64,
            request_snapshot={
                "client_turn_id": str(client_turn_id),
                "message": "Build a flow",
            },
            message="Build a flow",
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            attachment_files=None,
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=_budget_policy(),
        )
    ]


def _force_fast_send_lock_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_send_lease."
        "_send_lock_refresh_interval_seconds",
        lambda: 0,
    )


def test_prepare_user_question_metadata_preserves_requirements_confirmation_and_ui_language() -> (
    None
):
    result = prepare_user_question_metadata(
        conversation=[],
        message="",
        question_answer={
            "kind": "requirements_confirmation",
            "requirements_confirmed": True,
            "requirements_version": "req-v2",
            "ui_language": "en",
        },
    )

    assert result.is_requirements_confirmation is True
    assert result.metadata == {
        "requirements_confirmed": True,
        "requirements_version": "req-v2",
        "ui_language": "en",
    }


def test_prepare_user_question_metadata_ingests_structured_slot_answer() -> None:
    result = prepare_user_question_metadata(
        conversation=[],
        message="documents",
        question_answer={
            "kind": "structured_question_answer",
            "question_id": "primary_runtime_input",
            "selected_values": ["documents"],
        },
    )

    assert result.metadata == {
        "question_answer": {
            "question_id": "primary_runtime_input",
            "selected_values": ["documents"],
        }
    }
    state = build_planning_state_from_conversation(
        [
            ConversationMessage(
                role="user",
                content="documents",
                metadata=result.metadata,
            )
        ]
    )
    slot = state.resolved_slots["primary_runtime_input"]
    assert slot.value == "documents"
    assert slot.source == "structured_answer"


@pytest.mark.parametrize(
    ("question_answer", "reason"),
    [
        (
            {
                "kind": "structured_question_answer",
                "selected_values": ["documents"],
            },
            "missing_question_id",
        ),
        (
            {
                "kind": "structured_question_answer",
                "question_id": "multi_file_strategy",
                "selected_values": ["same_run"],
            },
            "unsupported_question_id",
        ),
        (
            {
                "kind": "structured_question_answer",
                "question_id": "output_style",
                "selected_values": ["formal"],
            },
            "unsupported_question_id",
        ),
        (
            {
                "kind": "structured_question_answer",
                "question_id": "output_tone",
                "selected_values": ["formal"],
            },
            "unsupported_question_id",
        ),
        (
            {
                "kind": "structured_question_answer",
                "question_id": "detail_level",
                "selected_values": ["detailed"],
            },
            "unsupported_question_id",
        ),
        (
            {
                "kind": "structured_question_answer",
                "question_id": "primary_runtime_input",
            },
            "empty_question_answer",
        ),
        (
            {
                "kind": "structured_question_answer",
                "question_id": "primary_runtime_input",
                "selected_values": ["banana"],
            },
            "unsupported_question_value",
        ),
        (
            {
                "kind": "structured_question_answer",
                "question_id": "document_material_scope",
                "selected_values": ["single_document_case", "banana"],
            },
            "unsupported_question_value",
        ),
    ],
)
def test_prepare_user_question_metadata_rejects_uningestable_structured_answers(
    question_answer: dict[str, object],
    reason: str,
) -> None:
    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        prepare_user_question_metadata(
            conversation=[],
            message="",
            question_answer=question_answer,
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD
    assert exc_info.value.context == {"reason": reason}


@pytest.mark.parametrize(
    "question_id",
    ["flow_input_architecture", "final_pdf_type"],
)
def test_prepare_user_question_metadata_keeps_supported_non_slot_questions(
    question_id: str,
) -> None:
    result = prepare_user_question_metadata(
        conversation=[],
        message="",
        question_answer={
            "kind": "structured_question_answer",
            "question_id": question_id,
            "selected_values": ["banana"],
        },
    )

    assert result.metadata == {
        "question_answer": {
            "question_id": question_id,
            "selected_values": ["banana"],
        }
    }


def test_prepare_user_question_metadata_accepts_output_schema_conflict_answer() -> None:
    fingerprint = "a" * 64

    prepared = prepare_user_question_metadata(
        conversation=[],
        message="",
        question_answer={
            "kind": "structured_question_answer",
            "question_id": "output_schema_conflict",
            "selected_values": [fingerprint],
        },
    )

    assert prepared.metadata == {
        "question_answer": {
            "question_id": "output_schema_conflict",
            "selected_values": [fingerprint],
        }
    }


def test_prepare_user_question_metadata_without_pending_question_is_neutral() -> None:
    prepared = prepare_user_question_metadata(
        conversation=[],
        message="Hello",
        question_answer=None,
    )

    assert prepared.metadata is None
    assert prepared.is_requirements_confirmation is False


@pytest.mark.asyncio
async def test_prepare_planner_request_skips_prompt_for_server_owned_action() -> None:
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build a flow")]
    requirements_state = _requirements_state_unconfirmed()
    discovery_analysis = _discovery_analysis()

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(discovery_analysis, PlanningState.empty()),
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.compute_conversation_token_budget",
            return_value=256,
        ) as compute_budget,
    ):
        prepared = await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
            base_planning_state_version=4,
        )

    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, AskCanonicalQuestion)
    assert not hasattr(prepared, "llm_messages")
    compute_budget.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_planner_request_asks_about_distinct_attachment_schemas_before_provider() -> (
    None
):
    planner = _make_planner()
    provider_callback = AsyncMock()

    prepared = await _prepare_planner_request_for_test(
        planner,
        conversation=[ConversationMessage(role="user", content="Build a flow")],
        completion_model_route=_route(),
        attachment_files=[
            _make_file(
                '{"type":"object","properties":{"decision":{"type":"string"}}}',
                name="first.schema.json",
                mimetype="application/json",
            ),
            _make_file(
                '{"type":"object","properties":{"count":{"type":"integer"}}}',
                name="second.schema.json",
                mimetype="application/json",
            ),
        ],
        before_provider_call=provider_callback,
    )

    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, AskOutputSchemaConflict)
    assert prepared.server_decision.question.question_data.question_id == (
        "output_schema_conflict"
    )
    assert len(prepared.server_decision.question.question_data.options) == 2
    provider_callback.assert_not_awaited()


def test_preprovider_gate_promotes_user_declared_schema_refusal() -> None:
    attachment = _make_file(
        name="expected-output.txt",
        text='{"description":"' + ("x" * OUTPUT_SCHEMA_MAX_JSON_BYTES) + '"}',
        mimetype="text/plain",
    )
    attachment_context = build_ai_builder_attachment_context([attachment])
    assert attachment_context is not None

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        validate_preprovider_output_schema_gate(
            conversation=[
                ConversationMessage(
                    role="user",
                    content="Use expected-output.txt as the output schema.",
                )
            ],
            attachment_context=attachment_context,
        )

    assert exc_info.value.code is AIBuilderErrorCode.OUTPUT_SCHEMA_LIMIT_EXCEEDED
    assert exc_info.value.context["file_id"] == str(attachment.id)


@pytest.mark.asyncio
async def test_prepare_planner_request_rejects_canonical_schema_expansion_before_provider() -> (
    None
):
    raw_json = (
        '{"type":"object","allOf":['
        + ",".join('{"default":1e9}' for _ in range(5_500))
        + "]}"
    )
    attachment = _make_file(
        name="expanded.schema.json",
        text=raw_json,
        mimetype="application/schema+json",
    )
    provider_callback = AsyncMock()

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        await _prepare_planner_request_for_test(
            _make_planner(),
            conversation=[ConversationMessage(role="user", content="Build a flow")],
            completion_model_route=_route(),
            attachment_files=[attachment],
            before_provider_call=provider_callback,
        )

    assert exc_info.value.code is AIBuilderErrorCode.OUTPUT_SCHEMA_LIMIT_EXCEEDED
    assert exc_info.value.context["reason"] == "canonical_bytes"
    assert exc_info.value.context["file_id"] == str(attachment.id)
    provider_callback.assert_not_awaited()


def test_preprovider_gate_keeps_unclassified_large_json_text_nonblocking() -> None:
    attachment = _make_file(
        name="large-example.txt",
        text='{"records":"' + ("x" * OUTPUT_SCHEMA_MAX_JSON_BYTES) + '"}',
        mimetype="text/plain",
    )
    attachment_context = build_ai_builder_attachment_context([attachment])
    assert attachment_context is not None

    conflict_pending = validate_preprovider_output_schema_gate(
        conversation=[
            ConversationMessage(
                role="user",
                content="Use the attachment as general reference material.",
            )
        ],
        attachment_context=attachment_context,
    )

    assert conflict_pending is False


@pytest.mark.asyncio
async def test_prepare_planner_request_reuses_checked_empty_attachment_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    rebuild_context = MagicMock(
        side_effect=AssertionError("checked attachment context must not be rebuilt")
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner_request_preparation."
        "build_ai_builder_attachment_context_for_model",
        rebuild_context,
    )

    prepared = await _prepare_planner_request_for_test(
        planner,
        conversation=[ConversationMessage(role="user", content="Build a flow")],
        completion_model_route=_route(),
        attachment_files=[],
        prepared_attachment_context=None,
        output_schema_gate_checked=True,
    )

    assert isinstance(prepared, ServerOutputPrepared)
    rebuild_context.assert_not_called()


@pytest.mark.asyncio
async def test_send_message_builds_attachment_context_once_before_request_preparation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    planner.repo.get_session.return_value = SimpleNamespace(
        conversation=[],
        status=SessionStatus.CHATTING,
        planning_state_version=1,
    )
    planner.repo.load_planning_state.return_value = None
    attachments = [
        _make_file(
            '{"type":"object","properties":{"decision":{"type":"string"}}}',
            name="first.schema.json",
            mimetype="application/json",
        ),
        _make_file(
            '{"type":"object","properties":{"count":{"type":"integer"}}}',
            name="second.schema.json",
            mimetype="application/json",
        ),
    ]
    prepared_context = build_ai_builder_attachment_context(attachments)
    build_context = MagicMock(return_value=prepared_context)
    captured_request: PlannerRequestPreparationInput | None = None

    async def stop_after_request(
        request: PlannerRequestPreparationInput,
    ) -> ServerOutputPrepared:
        nonlocal captured_request
        captured_request = request
        raise RuntimeError("request captured")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.resolve_plan_edit_context",
        AsyncMock(return_value=(None, None)),
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner."
        "build_ai_builder_attachment_context_for_model",
        build_context,
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.prepare_planner_request",
        stop_after_request,
    )
    stream = planner.send_message(
        session_id=uuid4(),
        client_turn_id=_TEST_CLIENT_TURN_ID,
        request_fingerprint=_TEST_REQUEST_FINGERPRINT,
        request_snapshot=_test_request_snapshot("Build a flow"),
        message="Build a flow",
        completion_model_route=_route(),
        attachment_files=attachments,
        max_input_tokens=4096,
        max_output_tokens=1024,
        budget_policy=_budget_policy(),
    )

    with pytest.raises(RuntimeError, match="request captured"):
        await anext(stream)

    build_context.assert_called_once_with(
        attachments,
        policy=AIBuilderAttachmentContextPolicy(),
        model_name="openai/gpt-5.4",
        max_input_tokens=4096,
        max_output_tokens=1024,
        safety_buffer_tokens=128,
        minimum_conversation_tokens=256,
    )
    assert captured_request is not None
    assert captured_request.prepared_attachment_context is prepared_context
    assert captured_request.output_schema_gate_checked is True
    planner.repo.mark_session_turn_processing.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_planner_request_requires_fresh_confirmation_after_attachment_change() -> (
    None
):
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build a report flow")]
    discovery_analysis = _discovery_analysis()
    state = PlanningState.empty()
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="document",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=["input_document"],
        committed_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        architecture_hash="a" * 64,
    )
    state.file_roles = [
        FileRoleEvidence(
            file_id=UUID(int=index + 1),
            filename=f"reference-{index}.pdf",
            file_type="document",
            mimetype="application/pdf",
            has_readable_text=True,
            coverage="fully_seen",
            role="context_only",
            source="heuristic",
            confidence="low",
        )
        for index in range(12)
    ]
    prior_confirmation = resolve_turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        confirmed_attachment_evidence_fingerprint=None,
        ui_language="en",
    ).decision
    assert isinstance(prior_confirmation, ConfirmRequirements)
    confirmed_version = build_requirements_version(prior_confirmation.payload)
    requirements_state = RequirementsState(
        latest_summary=prior_confirmation.payload,
        latest_version=confirmed_version,
        latest_attachment_evidence_fingerprint=(
            prior_confirmation.attachment_evidence_fingerprint
        ),
        confirmed_version=confirmed_version,
    )
    state.file_roles[11] = state.file_roles[11].model_copy(
        update={
            "coverage": "excerpt_truncated",
            "role": "reference_material",
            "source": "model",
            "confidence": "high",
        }
    )
    provider_callback = AsyncMock()

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(discovery_analysis, state),
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_plan_proposal_system_prompt",
            return_value="proposal prompt",
        ) as build_proposal_prompt,
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.compute_conversation_token_budget",
            return_value=256,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.trim_conversation_for_context",
            return_value=[{"role": "user", "content": "Build a report flow"}],
        ),
    ):
        prepared = await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            before_provider_call=provider_callback,
        )

    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, ConfirmRequirements)
    assert any(
        "2 additional attachments are omitted" in assumption
        for assumption in prepared.server_decision.payload.assumptions
    )
    build_proposal_prompt.assert_not_called()
    provider_callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_server_action_policy_overrides_stale_discovery_question() -> None:
    planner = _make_planner()
    conversation = [
        ConversationMessage(
            role="user",
            content=(
                "Skapa ett flöde som tar emot en kort text från användaren och "
                "sammanfattar den i tre tydliga punkter."
            ),
        )
    ]
    requirements_state = _requirements_state_unconfirmed()
    discovery_analysis = _discovery_analysis(
        mvs_met=False,
        selected_question_ids=("primary_runtime_input",),
    )
    planning_state = build_planning_state_from_conversation(conversation)

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(
                discovery_analysis,
                planning_state,
            ),
        ),
    ):
        prepared = await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
            base_planning_state_version=4,
        )

    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, CommitArchitecture)
    assert not hasattr(prepared, "llm_messages")


@pytest.mark.asyncio
async def test_prepare_planner_request_asks_for_model_medium_output_before_commit() -> (
    None
):
    planner = _make_planner()
    conversation = [
        ConversationMessage(
            role="user",
            content="Jag vill bygga ett transkriberingsflöde",
            metadata={"ui_language": "sv"},
        )
    ]
    requirements_state = _requirements_state_unconfirmed()
    discovery_analysis = _discovery_analysis()
    planning_state = PlanningState.empty()
    planning_state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="audio",
            source="heuristic",
            evidence=["heuristic:role-aware freeform analysis"],
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_text",
            source="model",
            evidence=["model:terminal_output:" + "a" * 64],
            confidence="medium",
        ),
    }
    assert planning_state.resolved_slots["terminal_output"].source == "model"
    assert planning_state.resolved_slots["terminal_output"].confidence == "medium"

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(
                discovery_analysis,
                planning_state,
            ),
        ),
    ):
        prepared = await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
            base_planning_state_version=4,
        )

    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, AskCanonicalQuestion)
    assert prepared.server_decision.slot_name == "terminal_output"
    assert not hasattr(prepared, "llm_messages")


@pytest.mark.asyncio
async def test_prepare_planner_request_passes_attachment_context_into_discovery_before_proposal() -> (
    None
):
    planner = _make_planner()
    conversation = [
        ConversationMessage(
            role="user",
            content="Jag vill bygga ett transkriberingsflöde.",
            metadata={"ui_language": "sv"},
        )
    ]
    requirements_state = _requirements_state_unconfirmed()
    discovery_analysis = _discovery_analysis()
    planning_state = PlanningState.empty()
    planning_state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="audio",
            source="heuristic",
            evidence=["heuristic:role-aware freeform analysis"],
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_text",
            source="model",
            evidence=["model:terminal_output:" + "a" * 64],
            confidence="medium",
        ),
    }
    attachment_context = AIBuilderAttachmentContext(
        context=None,
        evidence=(),
        included_file_ids=[],
        total_chars=0,
        truncated=False,
        output_schema_discovery=AIBuilderAttachmentOutputSchemaDiscovery(candidates=()),
    )

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation."
            "build_ai_builder_attachment_context_for_model",
            return_value=attachment_context,
        ) as build_attachment_context,
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(
                discovery_analysis,
                planning_state,
            ),
        ) as build_discovery_runtime_result,
    ):
        prepared = await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            attachment_files=[_make_file()],
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
            base_planning_state_version=4,
        )

    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, AskCanonicalQuestion)
    build_attachment_context.assert_called_once()
    assert (
        build_discovery_runtime_result.call_args.kwargs["attachment_context"]
        is attachment_context
    )


@pytest.mark.asyncio
async def test_prepare_planner_request_passes_attachment_context_into_proposal_prompt() -> (
    None
):
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build from this file")]
    discovery_analysis = _discovery_analysis()
    state = PlanningState.empty()
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="document",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=["input_document"],
        committed_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        architecture_hash="a" * 64,
    )
    requirements_state = _requirements_state_confirmed_for(state)
    requirements = RequirementsSummaryPayload(
        summary="Build from this file.",
        key_decisions=[],
        input_description="Attachment",
        output_description="Summary",
        assumptions=[],
        manual_setup_notes=[],
    )

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(discovery_analysis, state),
        ) as build_discovery_runtime_result,
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.latest_confirmed_requirements",
            return_value=requirements,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation."
            "build_ai_builder_attachment_context_for_model",
            return_value=AIBuilderAttachmentContext(
                context="attachment context",
                evidence=(),
                included_file_ids=[],
                total_chars=18,
                truncated=False,
                output_schema_discovery=AIBuilderAttachmentOutputSchemaDiscovery(
                    candidates=()
                ),
            ),
        ) as build_attachment_context,
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_plan_proposal_system_prompt",
            return_value="proposal prompt",
        ) as build_plan_proposal_system_prompt,
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.compute_conversation_token_budget",
            return_value=256,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.trim_conversation_for_context",
            return_value=[{"role": "user", "content": "Build from this file"}],
        ),
    ):
        await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            attachment_files=[_make_file()],
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
            base_planning_state_version=0,
        )

    build_attachment_context.assert_called_once()
    assert (
        build_discovery_runtime_result.call_args.kwargs["attachment_context"]
        is build_attachment_context.return_value
    )
    assert (
        build_plan_proposal_system_prompt.call_args.kwargs["attachment_context"]
        == "attachment context"
    )


@pytest.mark.asyncio
async def test_prepare_planner_request_uses_proposal_task_after_confirmation() -> None:
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build a report flow")]
    discovery_analysis = _discovery_analysis()
    state = PlanningState.empty()
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="document",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=["input_document"],
        committed_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        architecture_hash="a" * 64,
    )
    requirements_state = _requirements_state_confirmed_for(state)
    requirements = RequirementsSummaryPayload(
        summary="Build a report flow.",
        key_decisions=[
            KeyDecisionPayload(topic="Input", decision="Uploaded documents")
        ],
        input_description="Documents",
        output_description="Report",
        assumptions=[],
        manual_setup_notes=[],
    )

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(discovery_analysis, state),
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.latest_confirmed_requirements",
            return_value=requirements,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.compute_conversation_token_budget",
            return_value=256,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.trim_conversation_for_context",
            return_value=[{"role": "user", "content": "Build a report flow"}],
        ),
    ):
        prepared = await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            attachment_files=[],
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
            base_planning_state_version=4,
        )

    assert isinstance(prepared, ProposalPrepared)
    assert prepared.llm_messages[0]["role"] == "system"
    assert "Call exactly one `propose_flow` tool" in prepared.llm_messages[0]["content"]


def test_real_proposal_boundary_fits_attachments_and_protects_current_turn() -> None:
    model_name = "gpt-4o-mini"
    current_turn = ConversationMessage(
        role="user",
        content="Build the confirmed reporting flow from my attached source.",
    )
    history = ConversationMessage(role="user", content="old context " * 5_000)
    attachment_text = "ATTACHMENT-EVIDENCE " * 5_000
    attachment_context = build_ai_builder_attachment_context(
        [_make_file(attachment_text)]
    )
    assert attachment_context is not None
    catalog = build_ai_builder_resource_catalog(
        available_models=None,
        available_kbs=None,
    )
    policy = AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=64,
        minimum_conversation_budget_tokens=128,
    )
    common = {
        "requirements_state": RequirementsState(),
        "ui_language": "en",
        "slot_classification_metadata": None,
        "planning_state": PlanningState.empty(),
        "flow_context": None,
        "is_edit_mode": False,
        "resource_catalog": catalog,
        "current_steps": None,
        "plan_edit_context": None,
        "prior_plan_for_revision": None,
        "litellm_model": model_name,
        "max_output_tokens": 256,
        "budget_policy": policy,
        "attachment_file_count": 1,
    }
    baseline = build_proposal_prepared(
        **common,
        conversation=[current_turn],
        attachment_context=None,
        max_input_tokens=100_000,
        current_turn_start=0,
    )
    tool_schema = build_propose_flow_tool_schema(
        current_steps=None,
        resource_catalog=catalog,
    )
    irreducible_request_tokens = (
        count_message_tokens(baseline.llm_messages, model_name)
        + count_tool_tokens([tool_schema], model_name)
        + 256
        + policy.conversation_safety_buffer_tokens
    )
    tight_context_window = irreducible_request_tokens + 300

    prepared = build_proposal_prepared(
        **common,
        conversation=[history, current_turn],
        attachment_context=attachment_context,
        max_input_tokens=tight_context_window,
        current_turn_start=1,
    )

    assert prepared.request_budget is not None
    fitted_groups = prepared.request_budget.fit(
        message_groups=prepared.message_groups,
        tool_schemas=[tool_schema],
        model_name=model_name,
    )
    fitted_messages = flatten_proposal_message_groups(fitted_groups)
    final_request_tokens = (
        count_message_tokens(fitted_messages, model_name)
        + count_tool_tokens([tool_schema], model_name)
        + prepared.request_budget.output_reserve_tokens
        + prepared.request_budget.safety_buffer_tokens
    )
    assert final_request_tokens <= tight_context_window
    assert current_turn.content in [message["content"] for message in fitted_messages]
    system_content = fitted_messages[0]["content"]
    assert isinstance(system_content, str)
    assert attachment_text not in system_content
    assert "ATTACHMENT-EVIDENCE" in system_content

    assert baseline.request_budget is not None
    impossible_budget = replace(
        baseline.request_budget,
        context_window_tokens=irreducible_request_tokens - 1,
    )
    with pytest.raises(AIBuilderKnownProviderRejectionException):
        impossible_budget.fit(
            message_groups=baseline.message_groups,
            tool_schemas=[tool_schema],
            model_name=model_name,
        )


@pytest.mark.asyncio
async def test_prepare_planner_request_logs_prompt_metrics() -> None:
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build a report flow")]
    discovery_analysis = _discovery_analysis()
    state = PlanningState.empty()
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="document",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=["input_document"],
        committed_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        architecture_hash="a" * 64,
    )
    requirements_state = _requirements_state_confirmed_for(state)
    requirements = RequirementsSummaryPayload(
        summary="Build a report flow.",
        key_decisions=[],
        input_description="Documents",
        output_description="Report",
        assumptions=[],
        manual_setup_notes=[],
    )

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(discovery_analysis, state),
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.latest_confirmed_requirements",
            return_value=requirements,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.compute_conversation_token_budget",
            return_value=256,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.trim_conversation_for_context",
            return_value=[{"role": "user", "content": "Build a flow"}],
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.logger.info"
        ) as logger_info,
    ):
        await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            attachment_files=None,
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
            base_planning_state_version=0,
        )

    assert any(
        call.args and call.args[0] == "AI Builder plan proposal prompt metrics"
        for call in logger_info.call_args_list
    )


@pytest.mark.asyncio
async def test_send_message_rejects_when_another_send_is_already_in_progress() -> None:
    planner = _make_planner()
    planner.repo.accept_session_turn.side_effect = AIBuilderBadRequestException(
        "Another AI Builder message is already being processed for this session.",
        code=AIBuilderErrorCode.SESSION_MESSAGE_IN_PROGRESS,
    )
    planner.repo.get_session.return_value = SimpleNamespace(
        conversation=[],
        planning_state_version=0,
        status="chatting",
    )

    with pytest.raises(BadRequestException, match="already being processed"):
        async for _ in planner.send_message(
            session_id=uuid4(),
            client_turn_id=_TEST_CLIENT_TURN_ID,
            request_fingerprint=_TEST_REQUEST_FINGERPRINT,
            request_snapshot=_test_request_snapshot("Build a flow"),
            message="Build a flow",
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            attachment_files=None,
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
        ):
            pass


@pytest.mark.asyncio
async def test_send_message_converts_dispatch_lease_lost_exception_to_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    _configure_minimal_send_message(planner, monkeypatch, _server_output_prepared())

    async def fail_with_lease_lost(
        _: ServerDecisionDispatchRequest,
    ) -> ServerDecisionDispatchResult:
        raise AIBuilderBadRequestException(
            "lease lost",
            code=AIBuilderErrorCode.SESSION_SEND_LEASE_LOST,
        )

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.dispatch_server_decision",
        fail_with_lease_lost,
    )

    events = await _collect_send_message_events(planner, session_id=session_id)

    assert [event["event"] for event in events] == ["error", "done"]
    assert json.loads(events[0]["data"])["code"] == "session_send_lease_lost"
    planner.repo.release_session_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_commits_planning_state_payload_too_large_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    _configure_minimal_send_message(planner, monkeypatch, _server_output_prepared())

    async def reject_oversized_state(
        _: ServerDecisionDispatchRequest,
    ) -> ServerDecisionDispatchResult:
        raise PlanningStatePayloadTooLargeError(
            byte_size=131_073,
            cap_bytes=131_072,
        )

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.dispatch_server_decision",
        reject_oversized_state,
    )

    events = await _collect_send_message_events(planner, session_id=session_id)

    assert [event["event"] for event in events] == ["error", "done"]
    error = json.loads(events[0]["data"])
    assert error["code"] == "planning_state_payload_too_large"
    assert error["category"] == "bad_request"
    assert error["phase"] == "planner"
    assert error["details"] == {
        "payload_bytes": 131_073,
        "payload_cap_bytes": 131_072,
    }
    planner.repo.complete_session_turn.assert_awaited_once()
    assert (
        planner.repo.complete_session_turn.await_args.kwargs["error"].model_dump(
            mode="json",
            exclude_none=True,
        )
        == error
    )
    planner.repo.release_session_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_emits_lease_lost_when_refresh_fails_during_server_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    refresh_attempted = asyncio.Event()
    _configure_minimal_send_message(planner, monkeypatch, _server_output_prepared())
    _force_fast_send_lock_refresh(monkeypatch)

    async def refresh_fails(**_: object) -> bool:
        refresh_attempted.set()
        return False

    async def wait_for_refresh_loss(
        _: ServerDecisionDispatchRequest,
    ) -> ServerDecisionDispatchResult:
        await asyncio.wait_for(refresh_attempted.wait(), timeout=12)
        return ServerDecisionDispatchResult(
            action_kind="ask_question",
            events=(build_text_event("server result"),),
            new_planning_state_version=2,
        )

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_send_lease._refresh_session_send_lease",
        refresh_fails,
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.dispatch_server_decision",
        wait_for_refresh_loss,
    )

    events = await _collect_send_message_events(planner, session_id=session_id)

    assert [event["event"] for event in events] == ["error", "done"]
    assert json.loads(events[0]["data"])["code"] == "session_send_lease_lost"
    planner.repo.release_session_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_continues_to_proposal_after_confirmed_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    continuation_state = PlanningState.empty()
    _configure_minimal_send_message(
        planner,
        monkeypatch,
        replace(
            _server_output_prepared(),
            requirements_state=_requirements_state_confirmed(),
            server_decision=ReviseArchitecture(
                architecture_commit=_architecture_commit()
            ),
            planning_state=continuation_state,
        ),
    )

    async def fake_dispatch(
        request: ServerDecisionDispatchRequest,
    ) -> ServerDecisionDispatchResult:
        assert isinstance(request.decision, ReviseArchitecture)
        return ServerDecisionDispatchResult(
            action_kind="revise_architecture",
            events=(build_status_event(AIBuilderStatus.ARCHITECTURE_REVISED),),
            new_planning_state_version=9,
            proposal_continuation=ServerDecisionProposalContinuation(
                planning_state=continuation_state
            ),
        )

    captured: dict[str, object] = {}

    async def fake_propose_plan(
        **kwargs: object,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        captured.update(kwargs)
        yield build_text_event("proposal result")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.dispatch_server_decision",
        fake_dispatch,
    )
    monkeypatch.setattr(
        planner._proposal_submission,
        "run_active_submission_attempt",
        fake_propose_plan,
    )

    events = await _collect_send_message_events(planner, session_id=session_id)

    assert [event["event"] for event in events] == ["status", "text", "done"]
    assert json.loads(events[0]["data"])["status"] == "architecture_revised"
    assert events[1]["data"] == '{"text":"proposal result"}'
    assert captured["new_messages_start"] == 1
    message_groups = cast(tuple[object, ...], captured["message_groups"])
    current_turn_groups = [
        group for group in message_groups if getattr(group, "kind") == "current_turn"
    ]
    assert len(current_turn_groups) == 1
    assert getattr(current_turn_groups[0], "protected") is True
    assert captured["planning_state"] is continuation_state
    turn = cast(object, captured["turn"])
    assert getattr(turn, "base_planning_state_version") == 9
    planner.repo.complete_session_turn.assert_awaited_once()
    planner.repo.release_session_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_server_continuation_commits_the_exact_proposal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    continuation_state = PlanningState.empty()
    _configure_minimal_send_message(
        planner,
        monkeypatch,
        replace(
            _server_output_prepared(),
            requirements_state=_requirements_state_confirmed(),
            server_decision=ReviseArchitecture(
                architecture_commit=_architecture_commit()
            ),
            planning_state=continuation_state,
        ),
    )

    async def fake_dispatch(
        _: ServerDecisionDispatchRequest,
    ) -> ServerDecisionDispatchResult:
        return ServerDecisionDispatchResult(
            action_kind="revise_architecture",
            events=(build_status_event(AIBuilderStatus.ARCHITECTURE_REVISED),),
            new_planning_state_version=9,
            proposal_continuation=ServerDecisionProposalContinuation(
                planning_state=continuation_state
            ),
        )

    committed_error_event = build_ai_builder_error_event(
        message="Invalid proposal",
        code=AIBuilderErrorCode.PLANNER_REJECTED,
        request_id="proposal-error-request",
        diagnostic_context={"outcome_kind": "server_confirm_requirements"},
        details={"quality_failure_codes": "missing_source_refs"},
    )

    async def fake_propose_plan(
        **_: object,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        yield committed_error_event

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.dispatch_server_decision",
        fake_dispatch,
    )
    monkeypatch.setattr(
        planner._proposal_submission,
        "run_active_submission_attempt",
        fake_propose_plan,
    )

    events = await _collect_send_message_events(planner, session_id=uuid4())

    assert [event["event"] for event in events] == ["status", "error", "done"]
    planner.repo.complete_session_turn.assert_awaited_once()
    assert (
        planner.repo.complete_session_turn.await_args.kwargs["error"]
        == committed_error_event.data
    )


@pytest.mark.asyncio
async def test_send_message_proposal_branch_ignores_in_process_lease_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    refresh_attempted = asyncio.Event()
    _force_fast_send_lock_refresh(monkeypatch)
    _configure_minimal_send_message(
        planner,
        monkeypatch,
        ProposalPrepared(
            requirements_state=_requirements_state_confirmed(),
            ui_language="sv",
            message_groups=(
                ProposalMessageGroup(
                    messages=({"role": "system", "content": "proposal"},),
                    kind="system",
                    protected=True,
                ),
            ),
            system_prompt_hash="proposal-hash",
            prior_plan_for_revision=None,
            slot_classification_metadata=None,
            plan_edit_context=None,
            planning_state=PlanningState.empty(),
            requested_output_sections=RequestedOutputSections.empty(),
            resource_catalog=build_ai_builder_resource_catalog(
                available_models=[],
                available_kbs=[],
                prior_bindings=(),
            ),
        ),
    )

    async def refresh_fails(**_: object) -> bool:
        refresh_attempted.set()
        return False

    async def fake_propose_plan(
        **_: object,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        await asyncio.wait_for(refresh_attempted.wait(), timeout=12)
        yield build_text_event("proposal result")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_send_lease._refresh_session_send_lease",
        refresh_fails,
    )
    monkeypatch.setattr(
        planner._proposal_submission,
        "run_active_submission_attempt",
        fake_propose_plan,
    )

    events = await _collect_send_message_events(planner, session_id=session_id)

    assert [event["event"] for event in events] == ["text", "done"]
    assert events[0]["data"] == '{"text":"proposal result"}'
    planner.repo.release_session_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_releases_pre_provider_dispatch_failure_for_safe_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    _configure_minimal_send_message(planner, monkeypatch, _server_output_prepared())

    async def fail_dispatch(
        _: ServerDecisionDispatchRequest,
    ) -> ServerDecisionDispatchResult:
        raise RuntimeError("dispatch failed")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.dispatch_server_decision",
        fail_dispatch,
    )

    with pytest.raises(RuntimeError, match="dispatch failed"):
        await _collect_send_message_events(planner, session_id=session_id)

    planner.repo.mark_session_turn_processing.assert_not_awaited()
    planner.repo.release_session_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_releases_lease_when_request_preparation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    planner.repo.get_session.return_value = SimpleNamespace(
        conversation=[],
        status=SessionStatus.CHATTING,
        planning_state_version=1,
    )
    planner.repo.load_planning_state.return_value = None
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.resolve_plan_edit_context",
        AsyncMock(return_value=(None, None)),
    )

    async def fail_prepare(_: PlannerRequestPreparationInput) -> ServerOutputPrepared:
        raise RuntimeError("preparation failed")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.prepare_planner_request",
        fail_prepare,
    )
    stream = planner.send_message(
        session_id=session_id,
        client_turn_id=_TEST_CLIENT_TURN_ID,
        request_fingerprint=_TEST_REQUEST_FINGERPRINT,
        request_snapshot=_test_request_snapshot("Build a flow"),
        message="Build a flow",
        completion_model_route=_route(),
        available_models=None,
        available_kbs=None,
        flow=None,
        assistant_snapshots=None,
        attachment_files=None,
        max_input_tokens=4096,
        max_output_tokens=1024,
        budget_policy=_budget_policy(),
    )

    with pytest.raises(RuntimeError, match="preparation failed"):
        await anext(stream)

    planner.repo.release_session_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_rejects_legacy_mcp_revision_before_provider_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    plan_id = uuid4()
    planner.repo.get_session.return_value = SimpleNamespace(
        conversation=[],
        status=SessionStatus.AWAITING_APPROVAL,
        planning_state_version=1,
        latest_plan_id=plan_id,
    )
    planner.repo.load_planning_state.return_value = None
    with pytest.raises(ValidationError) as validation_error:
        AssistantSpec.model_validate(
            {
                "instructions": "Use the legacy tool.",
                "mcp_tool_refs": ["mcp_tool.legacy"],
            }
        )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.resolve_plan_edit_context",
        AsyncMock(side_effect=validation_error.value),
    )
    stream = planner.send_message(
        session_id=uuid4(),
        client_turn_id=_TEST_CLIENT_TURN_ID,
        request_fingerprint=_TEST_REQUEST_FINGERPRINT,
        request_snapshot=_test_request_snapshot("Revise the plan"),
        message="Revise the plan",
        edit_context=AIBuilderPlanEditContext(
            scope="whole_plan",
            plan_id=plan_id,
        ),
        completion_model_route=_route(),
        available_models=None,
        available_kbs=None,
        flow=None,
        assistant_snapshots=None,
        attachment_files=None,
        max_input_tokens=4096,
        max_output_tokens=1024,
        budget_policy=_budget_policy(),
    )

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        await anext(stream)

    assert exc_info.value.code is AIBuilderErrorCode.BAD_REQUEST
    planner.litellm_client.assert_not_awaited()
    planner.repo.accept_session_turn.assert_not_awaited()
    planner.repo.mark_session_turn_processing.assert_not_awaited()
    planner.repo.create_plan.assert_not_awaited()
    planner.repo.release_session_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_message_releases_lease_when_stream_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    _configure_minimal_send_message(
        planner,
        monkeypatch,
        ProposalPrepared(
            requirements_state=_requirements_state_confirmed(),
            ui_language="sv",
            message_groups=(
                ProposalMessageGroup(
                    messages=({"role": "system", "content": "proposal"},),
                    kind="system",
                    protected=True,
                ),
            ),
            system_prompt_hash="proposal-hash",
            prior_plan_for_revision=None,
            slot_classification_metadata=None,
            plan_edit_context=None,
            planning_state=PlanningState.empty(),
            requested_output_sections=RequestedOutputSections.empty(),
            resource_catalog=build_ai_builder_resource_catalog(
                available_models=[],
                available_kbs=[],
                prior_bindings=(),
            ),
        ),
    )

    proposal_started = asyncio.Event()

    async def fake_propose_plan(
        **_: object,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        proposal_started.set()
        await asyncio.Event().wait()
        yield build_text_event("unreachable")

    monkeypatch.setattr(
        planner._proposal_submission,
        "run_active_submission_attempt",
        fake_propose_plan,
    )
    stream = planner.send_message(
        session_id=session_id,
        client_turn_id=_TEST_CLIENT_TURN_ID,
        request_fingerprint=_TEST_REQUEST_FINGERPRINT,
        request_snapshot=_test_request_snapshot("Build a flow"),
        message="Build a flow",
        completion_model_route=_route(),
        available_models=None,
        available_kbs=None,
        flow=None,
        assistant_snapshots=None,
        attachment_files=None,
        max_input_tokens=4096,
        max_output_tokens=1024,
        budget_policy=_budget_policy(),
    )

    pending_event = asyncio.create_task(anext(stream))
    await asyncio.wait_for(proposal_started.wait(), timeout=1)
    pending_event.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending_event

    planner.repo.release_session_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_proposal_catalog_uses_prior_plan_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    session_id = uuid4()
    local_model_id = uuid4()
    prior_binding = LocalResourceBinding(
        slot_ref=ResourceSlotRef(
            kind=ResourceSlotKind.MODEL,
            slot="fast-model",
            label="Fast model",
        ),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=local_model_id,
    )
    prior_plan = SimpleNamespace(resource_bindings=(prior_binding,))
    planner.repo.get_session.return_value = SimpleNamespace(
        conversation=[],
        status=SessionStatus.CHATTING,
        planning_state_version=1,
    )
    planner.repo.load_planning_state.return_value = None

    async def fake_prepare(_: PlannerRequestPreparationInput) -> ProposalPrepared:
        return ProposalPrepared(
            requirements_state=_requirements_state_confirmed(),
            ui_language="sv",
            message_groups=(
                ProposalMessageGroup(
                    messages=({"role": "system", "content": "proposal"},),
                    kind="system",
                    protected=True,
                ),
            ),
            system_prompt_hash="proposal-hash",
            prior_plan_for_revision=cast(BuilderPlan, prior_plan),
            slot_classification_metadata=None,
            plan_edit_context=None,
            planning_state=PlanningState.empty(),
            requested_output_sections=RequestedOutputSections.empty(),
            resource_catalog=build_ai_builder_resource_catalog(
                available_models=[
                    _model_resource(str(local_model_id), "Renamed model")
                ],
                available_kbs=[],
                prior_bindings=(prior_binding,),
            ),
        )

    captured: dict[str, object] = {}

    async def fake_propose_plan(
        **kwargs: object,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        captured.update(kwargs)
        yield build_text_event("proposal")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.resolve_plan_edit_context",
        AsyncMock(return_value=(None, prior_plan)),
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.prepare_planner_request",
        fake_prepare,
    )
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.run_scoped_plan_revision_attempt",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        planner._proposal_submission,
        "run_active_submission_attempt",
        fake_propose_plan,
    )

    events = [
        encode_ai_builder_stream_event(event)
        async for event in planner.send_message(
            session_id=session_id,
            client_turn_id=_TEST_CLIENT_TURN_ID,
            request_fingerprint=_TEST_REQUEST_FINGERPRINT,
            request_snapshot=_test_request_snapshot("Revise the plan"),
            message="Revise the plan",
            completion_model_route=_route(),
            available_models=[_model_resource(str(local_model_id), "Renamed model")],
            available_kbs=[],
            flow=None,
            assistant_snapshots=None,
            attachment_files=None,
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
        )
    ]

    resource_catalog = cast(AIBuilderResourceCatalog, captured["resource_catalog"])
    assert resource_catalog.models[0].authoring_ref == "model.fast-model"
    assert resource_catalog.models[0].slot_ref.label == "Renamed model"
    assert events[-1] == {"event": "done", "data": ""}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected_text", "expected_scoped_calls", "expected_submission_calls"),
    [
        ("scoped_hit", "scoped", 1, 0),
        ("scoped_miss", "submission", 1, 1),
        ("edit_flow", "submission", 0, 1),
    ],
)
async def test_stream_proposal_events_dispatches_once_to_the_selected_owner(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_text: str,
    expected_scoped_calls: int,
    expected_submission_calls: int,
) -> None:
    planner = _make_planner()
    proposal_request = ProposalPrepared(
        requirements_state=_requirements_state_confirmed(),
        ui_language="sv",
        message_groups=(
            ProposalMessageGroup(
                messages=({"role": "system", "content": "proposal"},),
                kind="system",
                protected=True,
            ),
        ),
        system_prompt_hash="proposal-hash",
        prior_plan_for_revision=None,
        slot_classification_metadata=None,
        plan_edit_context=None,
        planning_state=PlanningState.empty(),
        requested_output_sections=RequestedOutputSections.empty(),
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[],
            available_kbs=[],
            prior_bindings=(),
        ),
    )
    scoped_result = (
        ScopedPlanRevisionOutcome(events=(build_text_event("scoped"),))
        if mode == "scoped_hit"
        else None
    )
    scoped_attempt = AsyncMock(return_value=scoped_result)
    submission_calls = 0

    async def run_submission_attempt(
        **_: object,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        nonlocal submission_calls
        submission_calls += 1
        yield build_text_event("submission")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.run_scoped_plan_revision_attempt",
        scoped_attempt,
    )
    monkeypatch.setattr(
        planner._proposal_submission,
        "run_active_submission_attempt",
        run_submission_attempt,
    )

    events = [
        event
        async for event in planner._stream_proposal_events(
            turn=cast(Any, SimpleNamespace()),
            conversation=[],
            new_messages_start=0,
            proposal_request=proposal_request,
            completion_model_route=_route(),
            max_output_tokens=1024,
            request_id="dispatch-owner-test",
            usage_tracker=ProposalTurnTelemetry(
                request_id="dispatch-owner-test",
                model="openai/gpt-5.4",
                target_kind=TargetKind.EDIT
                if mode == "edit_flow"
                else TargetKind.CREATE,
            ),
            flow=cast(Any, object()) if mode == "edit_flow" else None,
            assistant_snapshots=None,
            before_provider_call=AsyncMock(),
        )
    ]

    assert events == [build_text_event(expected_text)]
    assert scoped_attempt.await_count == expected_scoped_calls
    assert submission_calls == expected_submission_calls
    planner.repo.complete_session_turn.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_proposal_events_commits_planning_state_payload_too_large(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    turn = cast(Any, SimpleNamespace())
    proposal_request = ProposalPrepared(
        requirements_state=_requirements_state_confirmed(),
        ui_language="sv",
        message_groups=(
            ProposalMessageGroup(
                messages=({"role": "system", "content": "proposal"},),
                kind="system",
                protected=True,
            ),
        ),
        system_prompt_hash="proposal-hash",
        prior_plan_for_revision=None,
        slot_classification_metadata=None,
        plan_edit_context=None,
        planning_state=PlanningState.empty(),
        requested_output_sections=RequestedOutputSections.empty(),
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[],
            available_kbs=[],
            prior_bindings=(),
        ),
    )

    async def reject_oversized_state(
        **_: object,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        raise PlanningStatePayloadTooLargeError(
            byte_size=131_073,
            cap_bytes=131_072,
        )
        yield

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.run_scoped_plan_revision_attempt",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        planner._proposal_submission,
        "run_active_submission_attempt",
        reject_oversized_state,
    )

    events = [
        event
        async for event in planner._stream_proposal_events(
            turn=turn,
            conversation=[],
            new_messages_start=0,
            proposal_request=proposal_request,
            completion_model_route=_route(),
            max_output_tokens=1024,
            request_id="oversized-proposal-state",
            usage_tracker=ProposalTurnTelemetry(
                request_id="oversized-proposal-state",
                model="openai/gpt-5.4",
                target_kind=TargetKind.CREATE,
            ),
            flow=None,
            assistant_snapshots=None,
            before_provider_call=AsyncMock(),
        )
    ]

    assert len(events) == 1
    error_event = events[0]
    assert error_event.event == "error"
    assert error_event.data.code == AIBuilderErrorCode.PLANNING_STATE_PAYLOAD_TOO_LARGE
    assert error_event.data.details == {
        "payload_bytes": 131_073,
        "payload_cap_bytes": 131_072,
    }
    planner.repo.complete_session_turn.assert_awaited_once_with(
        turn=turn,
        error=error_event.data,
    )


@pytest.mark.asyncio
async def test_send_message_rejects_closed_session_before_claiming_lock() -> None:
    planner = _make_planner()
    planner.repo.get_session.return_value = SimpleNamespace(
        conversation=[],
        status=SessionStatus.CANCELLED,
    )

    with pytest.raises(BadRequestException, match="Cannot send messages"):
        async for _ in planner.send_message(
            session_id=uuid4(),
            client_turn_id=_TEST_CLIENT_TURN_ID,
            request_fingerprint=_TEST_REQUEST_FINGERPRINT,
            request_snapshot=_test_request_snapshot("Build a flow"),
            message="Build a flow",
            completion_model_route=_route(),
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            attachment_files=None,
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
            ),
        ):
            pass

    planner.repo.claim_session_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_message_replays_the_exact_committed_error_without_provider_work() -> (
    None
):
    planner = _make_planner()
    tenant_id = cast(UUID, planner.user.tenant_id)
    committed_error = build_ai_builder_error_event(
        message="The committed planner failure.",
        code=AIBuilderErrorCode.PLANNER_REJECTED,
        request_id="committed-request",
        diagnostic_context={"outcome_kind": "server_confirm_requirements"},
        details={"quality_failure_codes": "missing_source_refs"},
    ).data
    session = BuilderSession(
        id=uuid4(),
        tenant_id=tenant_id,
        space_id=uuid4(),
        target_kind=TargetKind.CREATE,
        latest_turn=BuilderTurnLifecycle(
            client_turn_id=_TEST_CLIENT_TURN_ID,
            request_fingerprint=_TEST_REQUEST_FINGERPRINT,
            request=_test_request_snapshot("Build a flow"),
            state=BuilderTurnState.COMMITTED,
            user_message_id=uuid4(),
            error=committed_error,
        ),
    )
    preflight = SessionTurnPreflight(
        session=session,
        baseline=SessionTurnPreparationBaseline(
            session_status=SessionStatus.CHATTING,
            latest_plan_id=None,
            planning_state_version=0,
            latest_turn_id=_TEST_CLIENT_TURN_ID,
            latest_turn_state=BuilderTurnState.COMMITTED,
            attachment_file_ids=(),
        ),
        replayed=True,
    )

    events = [
        encode_ai_builder_stream_event(event)
        async for event in planner.send_message(
            session_id=session.id,
            client_turn_id=_TEST_CLIENT_TURN_ID,
            request_fingerprint=_TEST_REQUEST_FINGERPRINT,
            request_snapshot=_test_request_snapshot("Build a flow"),
            message="Build a flow",
            completion_model_route=_route(),
            turn_preflight=preflight,
        )
    ]

    assert events == [
        {
            "event": "error",
            "data": committed_error.model_dump_json(exclude_none=True),
        },
        {"event": "done", "data": ""},
    ]
    planner.repo.accept_session_turn.assert_not_awaited()
    planner.litellm_client.assert_not_awaited()
