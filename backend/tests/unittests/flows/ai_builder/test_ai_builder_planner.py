from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.files.file_models import File, FileType
from intric.flows.ai_builder.ai_builder_discovery_models import (
    BackendQuestion,
    DiscoveryAnalysis,
)
from intric.flows.ai_builder.ai_builder_discovery_runtime import (
    DiscoveryRuntimeResult,
    _should_emit_forced_followup,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
    SessionStatus,
)
from intric.flows.ai_builder.ai_builder_event_models import (
    KeyDecisionPayload,
    RequirementsSummaryPayload,
    StructuredQuestionPayload,
)
from intric.flows.ai_builder.ai_builder_planner import (
    AIBuilderPlanner,
    PlannerMetadataResolution,
)
from intric.flows.ai_builder.ai_builder_planner_request_preparation import (
    PlannerRequestPreparationInput,
    ProposalPrepared,
    ServerOutputPrepared,
    prepare_planner_request,
)
from intric.flows.ai_builder.ai_builder_requirements_state import RequirementsState
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableKnowledgeBaseResource,
    AIBuilderAvailableModelResource,
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from intric.flows.ai_builder.ai_builder_semantic_adjudication import (
    PendingQuestionResolution,
)
from intric.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy
from intric.flows.ai_builder.ai_builder_turn_controller import (
    AskCanonicalQuestion,
    CommitArchitecture,
)
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    PlanningState,
    StepTriple,
)
from intric.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
)
from intric.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)
from intric.main.exceptions import BadRequestException


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


@pytest.mark.asyncio
async def test_resolve_message_metadata_uses_freeform_inference_before_adjudication() -> (
    None
):
    planner = _make_planner()
    inferred_answer = {
        "question_id": "input_material_mode",
        "selected_values": ["documents"],
    }

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_planner.infer_question_answer_from_freeform",
            return_value=inferred_answer,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.adjudicate_pending_question_answer",
            new_callable=AsyncMock,
        ) as adjudicate,
    ):
        result = await planner._resolve_message_metadata(
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
async def test_resolve_message_metadata_preserves_requirements_confirmation_and_ui_language() -> (
    None
):
    planner = _make_planner()

    result = await planner._resolve_message_metadata(
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
async def test_resolve_message_metadata_does_not_adjudicate_without_pending_question() -> (
    None
):
    planner = _make_planner()

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_planner.infer_question_answer_from_freeform",
            return_value=None,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.adjudicate_pending_question_answer",
            new_callable=AsyncMock,
        ) as adjudicate,
    ):
        result = await planner._resolve_message_metadata(
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
async def test_resolve_message_metadata_marks_auxiliary_llm_when_pending_answer_adjudication_runs() -> (
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
            "intric.flows.ai_builder.ai_builder_planner.infer_question_answer_from_freeform",
            return_value=None,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.adjudicate_pending_question_answer",
            new_callable=AsyncMock,
            return_value=PendingQuestionResolution(
                question_id="final_output_mode",
                selected_option_ids=("pdf_document",),
                selected_values=("pdf_document",),
            ),
        ),
    ):
        result = await planner._resolve_message_metadata(
            conversation=conversation,
            message="Make it a PDF",
            question_answer=None,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
        )

    assert result.used_auxiliary_llm is True


@pytest.mark.asyncio
async def test_resolve_message_metadata_infers_final_output_answer_from_structured_label() -> (
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

    result = await planner._resolve_message_metadata(
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
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(
                None, discovery_analysis, PlanningState.empty()
            ),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.compute_conversation_token_budget",
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
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
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
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(None, discovery_analysis, state),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.latest_confirmed_requirements",
            return_value=requirements,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.build_ai_builder_attachment_context",
            return_value=SimpleNamespace(
                context="attachment context",
                included_file_ids=[],
                total_chars=18,
                truncated=False,
            ),
        ) as build_attachment_context,
        patch(
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.build_plan_proposal_system_prompt",
            return_value="proposal prompt",
        ) as build_plan_proposal_system_prompt,
        patch(
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.compute_conversation_token_budget",
            return_value=256,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.trim_conversation_for_context",
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
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(None, discovery_analysis, state),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.latest_confirmed_requirements",
            return_value=requirements,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.compute_conversation_token_budget",
            return_value=256,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.trim_conversation_for_context",
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
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
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
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.build_discovery_runtime_result",
            new_callable=AsyncMock,
            return_value=_runtime_result(None, discovery_analysis, state),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.latest_confirmed_requirements",
            return_value=requirements,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.compute_conversation_token_budget",
            return_value=256,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.trim_conversation_for_context",
            return_value=[{"role": "user", "content": "Build a flow"}],
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner_request_preparation.logger.info"
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

    async def noop_lease(**_: object) -> None:
        return None

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
            discovery_runtime=_runtime_result(
                None,
                DiscoveryAnalysis(issues=()),
                PlanningState.empty(),
            ),
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
    ) -> AsyncGenerator[dict[str, str], None]:
        captured.update(kwargs)
        yield {"event": "proposal", "data": "{}"}

    monkeypatch.setattr(
        "intric.flows.ai_builder.ai_builder_planner.resolve_plan_edit_context",
        AsyncMock(return_value=(None, prior_plan)),
    )
    monkeypatch.setattr(
        planner,
        "_resolve_message_metadata",
        AsyncMock(
            return_value=PlannerMetadataResolution(
                metadata=None,
                is_requirements_confirmation=False,
                used_auxiliary_llm=False,
            )
        ),
    )
    monkeypatch.setattr(
        "intric.flows.ai_builder.ai_builder_planner.prepare_planner_request",
        fake_prepare,
    )
    monkeypatch.setattr(planner, "_maintain_send_lock_lease", noop_lease)
    monkeypatch.setattr(planner.proposal_processor, "propose_plan", fake_propose_plan)

    events = [
        event
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
