from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from eneo.files.file_models import File, FileType
from eneo.flows.ai_builder.ai_builder_discovery_models import (
    BackendQuestion,
    DiscoveryAnalysis,
)
from eneo.flows.ai_builder.ai_builder_discovery_runtime import (
    DiscoveryRuntimeResult,
    _should_emit_forced_followup,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
    SessionStatus,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    AIBuilderStreamEvent,
    KeyDecisionPayload,
    RequirementsSummaryPayload,
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_events import (
    build_text_event,
    encode_ai_builder_stream_event,
)
from eneo.flows.ai_builder.ai_builder_planner import (
    AIBuilderPlanner,
)
from eneo.flows.ai_builder.ai_builder_planner_request_preparation import (
    PlannerRequestPreparationInput,
    ProposalPrepared,
    ServerOutputPrepared,
    prepare_planner_request,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import RequirementsState
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableKnowledgeBaseResource,
    AIBuilderAvailableModelResource,
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_semantic_adjudication import (
    PendingQuestionResolution,
)
from eneo.flows.ai_builder.ai_builder_server_decision_dispatch import (
    ServerDecisionDispatchRequest,
    ServerDecisionDispatchResult,
)
from eneo.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy
from eneo.flows.ai_builder.ai_builder_turn_controller import (
    AskCanonicalQuestion,
    CommitArchitecture,
)
from eneo.flows.ai_builder.ai_builder_user_question_metadata import (
    resolve_user_question_metadata,
)
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    PlanningState,
    ResolvedSlot,
    StepTriple,
)
from eneo.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
)
from eneo.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)
from eneo.main.exceptions import BadRequestException


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
    planner.repo.claim_session_send.return_value = True
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


def _make_file(text: str = "Reference") -> File:
    return File(
        id=uuid4(),
        name="reference.txt",
        checksum="checksum",
        size=len(text.encode("utf-8")),
        mimetype="text/plain",
        file_type=FileType.TEXT,
        text=text,
        blob=None,
        transcription=None,
        owner_type=None,
        owner_user_id=uuid4(),
        owner_api_key_id=None,
        user_id=uuid4(),
        tenant_id=uuid4(),
    )


def _runtime_result(
    discovery_block_message: str | None,
    discovery_analysis: object,
    planning_state: PlanningState,
    *,
    followup: BackendQuestion | None = None,
    should_emit_forced_followup: bool = False,
) -> DiscoveryRuntimeResult:
    return DiscoveryRuntimeResult(
        discovery_block_message=discovery_block_message,
        discovery_analysis=cast(DiscoveryAnalysis, discovery_analysis),
        planning_state=planning_state,
        followup=followup,
        should_emit_forced_followup=should_emit_forced_followup,
    )


def _backend_question() -> BackendQuestion:
    return BackendQuestion(
        question_data=StructuredQuestionPayload.model_validate(
            {
                "question_id": "terminal_output",
                "question": "Vilket slutresultat vill du ha?",
                "options": [
                    {
                        "id": "text",
                        "label": "Text",
                        "description": "Svara med text.",
                        "value": "text",
                    }
                ],
                "selection_mode": "single",
                "allow_custom": True,
            }
        ),
        assistant_text="Vilket slutresultat vill du ha?",
    )


async def _prepare_planner_request_for_test(
    planner: AIBuilderPlanner,
    *,
    conversation: list[ConversationMessage],
    message: str,
    litellm_model: str = "openai/gpt-5.4",
    litellm_kwargs: dict[str, object] | None = None,
    available_models: list[AIBuilderAvailableModelResource] | None = None,
    available_kbs: list[AIBuilderAvailableKnowledgeBaseResource] | None = None,
    available_mcps: object = None,
    flow: object = None,
    assistant_snapshots: object = None,
    attachment_files: list[File] | None = None,
    max_input_tokens: int = 4096,
    max_output_tokens: int = 1024,
    budget_policy: AIBuilderBudgetPolicy | None = None,
    is_requirements_confirmation: bool = False,
    base_planning_state_version: int = 0,
    plan_edit_context: object = None,
    prior_plan_for_revision: BuilderPlan | None = None,
    allow_discovery_semantic_adjudication: bool = True,
    persisted_planning_state: PlanningState | None = None,
):
    return await prepare_planner_request(
        PlannerRequestPreparationInput(
            conversation=conversation,
            message=message,
            litellm_client=planner.litellm_client,
            litellm_model=litellm_model,
            litellm_kwargs=dict(litellm_kwargs or {}),
            available_models=available_models,
            available_kbs=available_kbs,
            available_mcps=available_mcps,
            flow=cast(Any, flow),
            assistant_snapshots=cast(Any, assistant_snapshots),
            attachment_files=attachment_files or [],
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
            budget_policy=budget_policy
            or AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
                unknown_model_context_window_tokens=8192,
            ),
            is_requirements_confirmation=is_requirements_confirmation,
            base_planning_state_version=base_planning_state_version,
            tenant_id=planner.user.tenant_id,
            plan_edit_context=cast(Any, plan_edit_context),
            prior_plan_for_revision=prior_plan_for_revision,
            allow_discovery_semantic_adjudication=allow_discovery_semantic_adjudication,
            persisted_planning_state=persisted_planning_state,
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
        confirmed_version=version,
    )


def _budget_policy() -> AIBuilderBudgetPolicy:
    return AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=128,
        minimum_conversation_budget_tokens=256,
        unknown_model_context_window_tokens=8192,
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
    return [
        encode_ai_builder_stream_event(event)
        async for event in planner.send_message(
            session_id=session_id,
            message="Build a flow",
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
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


@pytest.mark.asyncio
async def test_resolve_user_question_metadata_uses_freeform_inference_before_adjudication() -> (
    None
):
    planner = _make_planner()
    inferred_answer = {
        "question_id": "input_material_mode",
        "selected_values": ["documents"],
    }

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_user_question_metadata."
            "infer_question_answer_from_freeform",
            return_value=inferred_answer,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_user_question_metadata."
            "adjudicate_pending_question_answer",
            new_callable=AsyncMock,
        ) as adjudicate,
    ):
        result = await resolve_user_question_metadata(
            litellm_client=planner.litellm_client,
            conversation=[],
            message="Use uploaded documents.",
            question_answer=None,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
        )

    assert result.is_requirements_confirmation is False
    assert result.metadata == {"question_answer": inferred_answer}
    adjudicate.assert_not_awaited()
    assert result.used_auxiliary_llm is False


@pytest.mark.asyncio
async def test_resolve_user_question_metadata_preserves_requirements_confirmation_and_ui_language() -> (
    None
):
    planner = _make_planner()

    result = await resolve_user_question_metadata(
        litellm_client=planner.litellm_client,
        conversation=[],
        message="Yes",
        question_answer={
            "kind": "requirements_confirmation",
            "requirements_confirmed": True,
            "requirements_version": "req-v2",
            "ui_language": "en",
        },
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
    )

    assert result.is_requirements_confirmation is True
    assert result.metadata == {
        "requirements_confirmed": True,
        "requirements_version": "req-v2",
        "ui_language": "en",
    }
    assert result.used_auxiliary_llm is False


@pytest.mark.asyncio
async def test_resolve_user_question_metadata_ingests_structured_slot_answer() -> None:
    planner = _make_planner()

    result = await resolve_user_question_metadata(
        litellm_client=planner.litellm_client,
        conversation=[],
        message="documents",
        question_answer={
            "kind": "structured_question_answer",
            "question_id": "input_material_mode",
            "selected_values": ["documents"],
        },
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
    )

    assert result.metadata == {
        "question_answer": {
            "question_id": "input_material_mode",
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


@pytest.mark.asyncio
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
                "question_id": "input_material_mode",
            },
            "empty_question_answer",
        ),
        (
            {
                "kind": "structured_question_answer",
                "question_id": "input_material_mode",
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
async def test_resolve_user_question_metadata_rejects_uningestable_structured_answers(
    question_answer: dict[str, object],
    reason: str,
) -> None:
    planner = _make_planner()

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        await resolve_user_question_metadata(
            litellm_client=planner.litellm_client,
            conversation=[],
            message="documents",
            question_answer=question_answer,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD
    assert exc_info.value.context == {"reason": reason}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question_id",
    ["flow_input_architecture", "final_pdf_type"],
)
async def test_resolve_user_question_metadata_keeps_supported_non_slot_questions(
    question_id: str,
) -> None:
    planner = _make_planner()

    result = await resolve_user_question_metadata(
        litellm_client=planner.litellm_client,
        conversation=[],
        message="banana",
        question_answer={
            "kind": "structured_question_answer",
            "question_id": question_id,
            "selected_values": ["banana"],
        },
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
    )

    assert result.metadata == {
        "question_answer": {
            "question_id": question_id,
            "selected_values": ["banana"],
        }
    }


@pytest.mark.asyncio
async def test_resolve_user_question_metadata_does_not_adjudicate_without_pending_question() -> (
    None
):
    planner = _make_planner()

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_user_question_metadata."
            "infer_question_answer_from_freeform",
            return_value=None,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_user_question_metadata."
            "adjudicate_pending_question_answer",
            new_callable=AsyncMock,
        ) as adjudicate,
    ):
        result = await resolve_user_question_metadata(
            litellm_client=planner.litellm_client,
            conversation=[],
            message="Bygg ett flöde som skapar en DOCX-rapport från ljud.",
            question_answer=None,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
        )

    assert result.metadata is None
    assert result.used_auxiliary_llm is False
    adjudicate.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_user_question_metadata_marks_auxiliary_llm_when_pending_answer_adjudication_runs() -> (
    None
):
    planner = _make_planner()
    conversation = [
        ConversationMessage(
            role="assistant",
            content="What should the flow produce?",
            tool_calls=[
                {
                    "id": "call_q1",
                    "name": "ask_structured_question",
                    "arguments": {
                        "question_id": "final_output_mode",
                        "question": "What should the flow produce?",
                        "options": [
                            {"id": "structured_text", "label": "Structured text"},
                            {"id": "pdf_document", "label": "PDF"},
                        ],
                        "selection_mode": "single",
                    },
                }
            ],
        )
    ]

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_user_question_metadata."
            "infer_question_answer_from_freeform",
            return_value=None,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_user_question_metadata."
            "adjudicate_pending_question_answer",
            new_callable=AsyncMock,
            return_value=PendingQuestionResolution(
                question_id="final_output_mode",
                selected_option_ids=("pdf_document",),
                selected_values=("pdf_document",),
            ),
        ),
    ):
        result = await resolve_user_question_metadata(
            litellm_client=planner.litellm_client,
            conversation=conversation,
            message="Make it a PDF",
            question_answer=None,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
        )

    assert result.used_auxiliary_llm is True


@pytest.mark.asyncio
async def test_resolve_user_question_metadata_infers_final_output_answer_from_structured_label() -> (
    None
):
    planner = _make_planner()
    conversation = [
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
                        ],
                        "selection_mode": "single",
                        "allow_custom": True,
                    },
                }
            ],
        )
    ]

    result = await resolve_user_question_metadata(
        litellm_client=planner.litellm_client,
        conversation=conversation,
        message="PDF-dokument",
        question_answer=None,
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
    )

    assert result.is_requirements_confirmation is False
    assert result.metadata == {
        "question_answer": {
            "question_id": "final_output_mode",
            "selected_option_id": "pdf_document",
            "selected_value": "pdf_document",
            "answer": "pdf_document",
        }
    }


def test_should_emit_forced_followup_arms_after_two_free_discovery_turns_with_catalog_hit() -> (
    None
):
    conversation = [
        ConversationMessage(
            role="assistant", content="What kind of input should I expect?"
        ),
        ConversationMessage(
            role="assistant", content="Can you clarify the desired output?"
        ),
    ]

    armed = _should_emit_forced_followup(
        conversation=conversation,
        requirements_confirmed=False,
        is_requirements_confirmation=False,
        discovery_block_message=None,
        discovery_analysis=SimpleNamespace(mvs_met=False),
        flow=None,
        followup=_backend_question(),
    )

    assert armed is True


@pytest.mark.asyncio
async def test_prepare_planner_request_skips_prompt_for_server_owned_action() -> None:
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build a flow")]
    requirements_state = _requirements_state_unconfirmed()
    discovery_analysis = SimpleNamespace(mvs_met=True, selected_question_ids=())

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(
                None, discovery_analysis, PlanningState.empty()
            ),
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.compute_conversation_token_budget",
            return_value=256,
        ) as compute_budget,
    ):
        prepared = await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            message="Build a flow",
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
                unknown_model_context_window_tokens=8192,
            ),
            is_requirements_confirmation=False,
            base_planning_state_version=4,
        )

    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, AskCanonicalQuestion)
    assert not hasattr(prepared, "llm_messages")
    compute_budget.assert_not_called()


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
    discovery_analysis = SimpleNamespace(
        mvs_met=False,
        selected_question_ids=("input_material_mode",),
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
                "legacy discovery question",
                discovery_analysis,
                planning_state,
            ),
        ),
    ):
        prepared = await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            message=conversation[0].content,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
                unknown_model_context_window_tokens=8192,
            ),
            is_requirements_confirmation=False,
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
    discovery_analysis = SimpleNamespace(mvs_met=True, selected_question_ids=())
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
                None,
                discovery_analysis,
                planning_state,
            ),
        ),
    ):
        prepared = await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            message=conversation[0].content,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            available_models=None,
            available_kbs=None,
            flow=None,
            assistant_snapshots=None,
            max_input_tokens=4096,
            max_output_tokens=1024,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=128,
                minimum_conversation_budget_tokens=256,
                unknown_model_context_window_tokens=8192,
            ),
            is_requirements_confirmation=False,
            base_planning_state_version=4,
        )

    assert isinstance(prepared, ServerOutputPrepared)
    assert isinstance(prepared.server_decision, AskCanonicalQuestion)
    assert prepared.server_decision.slot_name == "terminal_output"
    assert not hasattr(prepared, "llm_messages")


@pytest.mark.asyncio
async def test_prepare_planner_request_passes_attachment_context_into_proposal_prompt() -> (
    None
):
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build from this file")]
    requirements_state = _requirements_state_confirmed()
    discovery_analysis = SimpleNamespace(mvs_met=True, selected_question_ids=())
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
            return_value=_runtime_result(None, discovery_analysis, state),
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.latest_confirmed_requirements",
            return_value=requirements,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_ai_builder_attachment_context",
            return_value=SimpleNamespace(
                context="attachment context",
                included_file_ids=[],
                total_chars=18,
                truncated=False,
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
            message="Build from this file",
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
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
                unknown_model_context_window_tokens=8192,
            ),
            is_requirements_confirmation=False,
            base_planning_state_version=0,
        )

    build_attachment_context.assert_called_once()
    assert (
        build_plan_proposal_system_prompt.call_args.kwargs["attachment_context"]
        == "attachment context"
    )


@pytest.mark.asyncio
async def test_prepare_planner_request_uses_proposal_task_after_confirmation() -> None:
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build a report flow")]
    requirements_state = _requirements_state_confirmed()
    discovery_analysis = SimpleNamespace(mvs_met=True, selected_question_ids=())
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
            return_value=_runtime_result(None, discovery_analysis, state),
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
            message="Build a report flow",
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
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
                unknown_model_context_window_tokens=8192,
            ),
            is_requirements_confirmation=False,
            base_planning_state_version=4,
        )

    assert isinstance(prepared, ProposalPrepared)
    assert prepared.llm_messages[0]["role"] == "system"
    assert "Call exactly one `propose_flow` tool" in prepared.llm_messages[0]["content"]


@pytest.mark.asyncio
async def test_prepare_planner_request_disables_discovery_semantic_adjudication_when_auxiliary_llm_already_used() -> (
    None
):
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build a flow")]
    requirements_state = _requirements_state_unconfirmed()
    discovery_analysis = DiscoveryAnalysis(issues=())

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(
                None, discovery_analysis, PlanningState.empty()
            ),
        ) as discovery_runtime,
    ):
        await _prepare_planner_request_for_test(
            planner,
            conversation=conversation,
            message="Build a flow",
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
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
                unknown_model_context_window_tokens=8192,
            ),
            is_requirements_confirmation=False,
            base_planning_state_version=0,
            allow_discovery_semantic_adjudication=False,
        )

    assert discovery_runtime.await_args.kwargs["allow_semantic_adjudication"] is False


@pytest.mark.asyncio
async def test_prepare_planner_request_logs_prompt_metrics() -> None:
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build a report flow")]
    requirements_state = _requirements_state_confirmed()
    discovery_analysis = SimpleNamespace(mvs_met=True, selected_question_ids=())
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
            return_value=_runtime_result(None, discovery_analysis, state),
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
            message="Build a report flow",
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
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
                unknown_model_context_window_tokens=8192,
            ),
            is_requirements_confirmation=False,
            base_planning_state_version=0,
        )

    assert any(
        call.args and call.args[0] == "AI Builder plan proposal prompt metrics"
        for call in logger_info.call_args_list
    )


@pytest.mark.asyncio
async def test_send_message_rejects_when_another_send_is_already_in_progress() -> None:
    planner = _make_planner()
    planner.repo.claim_session_send.return_value = False
    planner.repo.get_session.return_value = SimpleNamespace(
        conversation=[],
        planning_state_version=0,
        status="chatting",
    )

    with pytest.raises(BadRequestException, match="already being processed"):
        async for _ in planner.send_message(
            session_id=uuid4(),
            message="Build a flow",
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
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
                unknown_model_context_window_tokens=8192,
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

    planner.repo.refresh_session_send_lease.side_effect = refresh_fails
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.dispatch_server_decision",
        wait_for_refresh_loss,
    )

    events = await _collect_send_message_events(planner, session_id=session_id)

    assert [event["event"] for event in events] == ["error", "done"]
    assert json.loads(events[0]["data"])["code"] == "session_send_lease_lost"
    planner.repo.release_session_send.assert_awaited_once()


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
            llm_messages=[{"role": "system", "content": "proposal"}],
            system_prompt_hash="proposal-hash",
            prior_plan_for_revision=None,
            slot_classification_metadata=None,
            plan_edit_context=None,
            planning_state=PlanningState.empty(),
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

    planner.repo.refresh_session_send_lease.side_effect = refresh_fails
    monkeypatch.setattr(planner.proposal_processor, "propose_plan", fake_propose_plan)

    events = await _collect_send_message_events(planner, session_id=session_id)

    assert [event["event"] for event in events] == ["text", "done"]
    assert events[0]["data"] == '{"text":"proposal result"}'
    planner.repo.release_session_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_releases_lease_after_server_dispatch_exception(
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

    events = await _collect_send_message_events(planner, session_id=session_id)

    assert [event["event"] for event in events] == ["error", "done"]
    assert json.loads(events[0]["data"])["code"] == "planner_upstream_error"
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
        message="Build a flow",
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
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
async def test_send_message_releases_lease_when_stream_is_closed(
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
            llm_messages=[{"role": "system", "content": "proposal"}],
            system_prompt_hash="proposal-hash",
            prior_plan_for_revision=None,
            slot_classification_metadata=None,
            plan_edit_context=None,
            planning_state=PlanningState.empty(),
            resource_catalog=build_ai_builder_resource_catalog(
                available_models=[],
                available_kbs=[],
                prior_bindings=(),
            ),
        ),
    )

    async def fake_propose_plan(
        **_: object,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        yield build_text_event("first chunk")
        await asyncio.Event().wait()

    monkeypatch.setattr(planner.proposal_processor, "propose_plan", fake_propose_plan)
    stream = planner.send_message(
        session_id=session_id,
        message="Build a flow",
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        available_models=None,
        available_kbs=None,
        flow=None,
        assistant_snapshots=None,
        attachment_files=None,
        max_input_tokens=4096,
        max_output_tokens=1024,
        budget_policy=_budget_policy(),
    )

    first = encode_ai_builder_stream_event(await anext(stream))
    await asyncio.wait_for(stream.aclose(), timeout=1)

    assert first == {"event": "text", "data": '{"text":"first chunk"}'}
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
            llm_messages=[{"role": "system", "content": "proposal"}],
            system_prompt_hash="proposal-hash",
            prior_plan_for_revision=cast(BuilderPlan, prior_plan),
            slot_classification_metadata=None,
            plan_edit_context=None,
            planning_state=PlanningState.empty(),
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
    monkeypatch.setattr(planner.proposal_processor, "propose_plan", fake_propose_plan)

    events = [
        encode_ai_builder_stream_event(event)
        async for event in planner.send_message(
            session_id=session_id,
            message="Revise the plan",
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
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
                unknown_model_context_window_tokens=8192,
            ),
        )
    ]

    resource_catalog = cast(AIBuilderResourceCatalog, captured["resource_catalog"])
    assert resource_catalog.models[0].authoring_ref == "model.fast-model"
    assert resource_catalog.models[0].slot_ref.label == "Renamed model"
    assert events[-1] == {"event": "done", "data": ""}


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
            message="Build a flow",
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
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
                unknown_model_context_window_tokens=8192,
            ),
        ):
            pass

    planner.repo.claim_session_send.assert_not_awaited()
