from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.files.file_models import File, FileType
from intric.flows.ai_builder.ai_builder_domain_models import BuilderPlan
from intric.flows.ai_builder.ai_builder_event_models import (
    KeyDecisionPayload,
    RequirementsSummaryPayload,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage, SessionStatus
from intric.flows.ai_builder.ai_builder_planner import (
    AIBuilderPlanner,
    PlannerMetadataResolution,
    PlannerPreparedRequest,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from intric.flows.ai_builder.ai_builder_semantic_adjudication import (
    PendingQuestionResolution,
)
from intric.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy
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
    """Backend-owned followup arms only when three conditions line up.

    Free discovery (requirements not confirmed, MVS not met, no
    discovery block) PLUS the last two assistant messages were free
    discovery without a structured answer PLUS the MVS forced-followup
    catalog has a priority question waiting. Any one of those missing
    and `send_message` must defer to the planner LLM instead of
    short-circuiting with a backend question.
    """
    planner = _make_planner()
    conversation = [
        ConversationMessage(
            role="assistant", content="What kind of input should I expect?"
        ),
        ConversationMessage(
            role="assistant", content="Can you clarify the desired output?"
        ),
    ]

    with patch(
        "intric.flows.ai_builder.ai_builder_planner._get_mvs_forced_followup",
        return_value="forced followup",
    ):
        armed = planner._should_emit_forced_followup(
            conversation=conversation,
            requirements_confirmed=False,
            is_requirements_confirmation=False,
            discovery_block_message=None,
            discovery_analysis=SimpleNamespace(mvs_met=False),
            flow=None,
        )

    assert armed is True


@pytest.mark.asyncio
async def test_prepare_planner_request_builds_llm_messages_with_system_prompt_header() -> (
    None
):
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build a flow")]
    requirements_state = SimpleNamespace(latest_summary=None, confirmed=False)
    discovery_analysis = SimpleNamespace(mvs_met=True)

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_planner.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_discovery_block_message_runtime",
            new_callable=AsyncMock,
            return_value=(None, discovery_analysis, PlanningState.empty()),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.latest_confirmed_requirements",
            return_value=None,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_server_planner_output",
            return_value=None,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_system_prompt",
            return_value="system prompt",
        ) as build_system_prompt,
        patch(
            "intric.flows.ai_builder.ai_builder_planner.compute_conversation_token_budget",
            return_value=256,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.trim_conversation_for_context",
            return_value=[{"role": "user", "content": "Build a flow"}],
        ),
    ):
        prepared = await planner._prepare_planner_request(
            conversation=conversation,
            message="Build a flow",
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            available_models=[
                {"id": "11111111-1111-4111-8111-111111111111", "name": "Model A"}
            ],
            available_kbs=[
                {"id": "22222222-2222-4222-8222-222222222222", "name": "KB A"}
            ],
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
            base_planning_state_version=0,
        )

    assert prepared.requirements_state is requirements_state
    assert prepared.should_emit_forced_followup is False
    assert prepared.llm_messages[0] == {"role": "system", "content": "system prompt"}
    assert build_system_prompt.call_args.kwargs["available_models"] == [
        {
            "ref": "model.model-a",
            "name": "Model A",
            "display_name": "Model A",
            "provider": "unknown",
        }
    ]
    assert build_system_prompt.call_args.kwargs["available_knowledge_bases"] == [
        {
            "ref": "knowledge.kb-a",
            "name": "KB A",
            "display_name": "KB A",
            "description": "",
        }
    ]


@pytest.mark.asyncio
async def test_prepare_planner_request_skips_prompt_for_server_owned_action() -> None:
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build a flow")]
    requirements_state = SimpleNamespace(latest_summary=None, confirmed=False)
    discovery_analysis = SimpleNamespace(mvs_met=True, selected_question_ids=())

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_planner.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_discovery_block_message_runtime",
            new_callable=AsyncMock,
            return_value=(None, discovery_analysis, PlanningState.empty()),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_system_prompt",
            return_value="system prompt",
        ) as build_system_prompt,
        patch(
            "intric.flows.ai_builder.ai_builder_planner.compute_conversation_token_budget",
            return_value=256,
        ) as compute_budget,
    ):
        prepared = await planner._prepare_planner_request(
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

    assert prepared.server_output is not None
    assert prepared.server_output.planner_action.kind == "ask_question"
    assert prepared.llm_messages == []
    build_system_prompt.assert_not_called()
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
    requirements_state = SimpleNamespace(latest_summary=None, confirmed=False)
    discovery_analysis = SimpleNamespace(
        mvs_met=False,
        selected_question_ids=("input_material_mode",),
    )
    planning_state = build_planning_state_from_conversation(conversation)

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_planner.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_discovery_block_message_runtime",
            new_callable=AsyncMock,
            return_value=(
                "legacy discovery question",
                discovery_analysis,
                planning_state,
            ),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_system_prompt",
            return_value="system prompt",
        ) as build_system_prompt,
    ):
        prepared = await planner._prepare_planner_request(
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

    assert prepared.server_output is not None
    assert prepared.server_output.planner_action.kind == "commit_architecture"
    assert prepared.discovery_block_message is None
    assert prepared.should_emit_forced_followup is False
    assert prepared.llm_messages == []
    build_system_prompt.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_planner_request_passes_attachment_context_into_system_prompt() -> (
    None
):
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build from this file")]
    requirements_state = SimpleNamespace(latest_summary=None, confirmed=False)
    discovery_analysis = SimpleNamespace(mvs_met=True)

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_planner.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_discovery_block_message_runtime",
            new_callable=AsyncMock,
            return_value=(None, discovery_analysis, PlanningState.empty()),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.latest_confirmed_requirements",
            return_value=None,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_server_planner_output",
            return_value=None,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_ai_builder_attachment_context",
            return_value=SimpleNamespace(
                context="attachment context",
                included_file_ids=[],
                total_chars=18,
                truncated=False,
            ),
        ) as build_attachment_context,
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_system_prompt",
            return_value="system prompt",
        ) as build_system_prompt,
        patch(
            "intric.flows.ai_builder.ai_builder_planner.compute_conversation_token_budget",
            return_value=256,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.trim_conversation_for_context",
            return_value=[{"role": "user", "content": "Build from this file"}],
        ),
    ):
        await planner._prepare_planner_request(
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
        build_system_prompt.call_args.kwargs["attachment_context"]
        == "attachment context"
    )


@pytest.mark.asyncio
async def test_prepare_planner_request_uses_proposal_task_after_confirmation() -> None:
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build a report flow")]
    requirements_state = SimpleNamespace(latest_summary=None, confirmed=True)
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
            "intric.flows.ai_builder.ai_builder_planner.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_discovery_block_message_runtime",
            new_callable=AsyncMock,
            return_value=(None, discovery_analysis, state),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.latest_confirmed_requirements",
            return_value=requirements,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_system_prompt",
            return_value="planner union prompt",
        ) as build_system_prompt,
        patch(
            "intric.flows.ai_builder.ai_builder_planner.compute_conversation_token_budget",
            return_value=256,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.trim_conversation_for_context",
            return_value=[{"role": "user", "content": "Build a report flow"}],
        ),
    ):
        prepared = await planner._prepare_planner_request(
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

    assert prepared.proposal_mode is True
    assert prepared.server_output is None
    assert prepared.llm_messages[0]["role"] == "system"
    assert "Call exactly one `outline_flow` tool" in prepared.llm_messages[0]["content"]
    build_system_prompt.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_planner_request_disables_discovery_semantic_adjudication_when_auxiliary_llm_already_used() -> (
    None
):
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build a flow")]
    requirements_state = SimpleNamespace(latest_summary=None, confirmed=False)
    discovery_analysis = SimpleNamespace(mvs_met=True)

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_planner.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_discovery_block_message_runtime",
            new_callable=AsyncMock,
            return_value=(None, discovery_analysis, PlanningState.empty()),
        ) as discovery_runtime,
        patch(
            "intric.flows.ai_builder.ai_builder_planner.latest_confirmed_requirements",
            return_value=None,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_server_planner_output",
            return_value=None,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_system_prompt",
            return_value="system prompt",
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.compute_conversation_token_budget",
            return_value=256,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.trim_conversation_for_context",
            return_value=[{"role": "user", "content": "Build a flow"}],
        ),
    ):
        await planner._prepare_planner_request(
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
    conversation = [ConversationMessage(role="user", content="Build a flow")]
    requirements_state = SimpleNamespace(latest_summary=None, confirmed=False)
    discovery_analysis = SimpleNamespace(mvs_met=True)

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_planner.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_discovery_block_message_runtime",
            new_callable=AsyncMock,
            return_value=(None, discovery_analysis, PlanningState.empty()),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.latest_confirmed_requirements",
            return_value=None,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_server_planner_output",
            return_value=None,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_system_prompt",
            return_value="system prompt",
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.compute_conversation_token_budget",
            return_value=256,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.trim_conversation_for_context",
            return_value=[{"role": "user", "content": "Build a flow"}],
        ),
        patch("intric.flows.ai_builder.ai_builder_planner.logger.info") as logger_info,
    ):
        await planner._prepare_planner_request(
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
        )

    assert any(
        call.args and call.args[0] == "AI Builder planner prompt metrics"
        for call in logger_info.call_args_list
    )


@pytest.mark.asyncio
async def test_prepare_planner_request_projects_pre_commit_into_system_prompt() -> None:
    """Pre-commit projection reaches the system prompt as a rendered block."""
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build a flow")]
    requirements_state = SimpleNamespace(latest_summary=None, confirmed=False)
    discovery_analysis = SimpleNamespace(mvs_met=True)

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_planner.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_discovery_block_message_runtime",
            new_callable=AsyncMock,
            return_value=(None, discovery_analysis, PlanningState.empty()),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.latest_confirmed_requirements",
            return_value=None,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_server_planner_output",
            return_value=None,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_system_prompt",
            return_value="system prompt",
        ) as build_system_prompt,
        patch(
            "intric.flows.ai_builder.ai_builder_planner.compute_conversation_token_budget",
            return_value=256,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.trim_conversation_for_context",
            return_value=[{"role": "user", "content": "Build a flow"}],
        ),
    ):
        await planner._prepare_planner_request(
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
            persisted_planning_state=None,
        )

    planning_state_block = build_system_prompt.call_args.kwargs["planning_state_block"]
    assert isinstance(planning_state_block, str)
    assert "pre_commit" in planning_state_block, (
        "pre-commit projection must label its stage so the planner can "
        "distinguish unconstrained exploration from post-commit narrowing"
    )
    # Every builder-exposed capability must appear in the rendered block
    # pre-commit — that is the projection contract.
    assert "input_text" in planning_state_block
    assert "output_mode_pass_through" in planning_state_block


@pytest.mark.asyncio
async def test_prepare_planner_request_threads_unresolved_core_slots_into_system_prompt() -> (
    None
):
    """Server-side phase lock: `_prepare_planner_request` must compute
    the core-slot commit gate from the rebuilt planning state and pass
    it into `build_system_prompt` so the prompt can restrict allowed
    actions BEFORE the LLM is called.

    This is the anti-regression rail for the
    `architecture_commit_premature_unresolved_choices` failure class
    (fingerprint `560a95ddd270`): a post-hoc orchestrator rejection is
    wasted work; the prompt must refuse the attempt in the first place.
    """
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build a flow")]
    requirements_state = SimpleNamespace(latest_summary=None, confirmed=False)
    discovery_analysis = SimpleNamespace(mvs_met=True)

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_planner.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_discovery_block_message_runtime",
            new_callable=AsyncMock,
            return_value=(None, discovery_analysis, PlanningState.empty()),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.latest_confirmed_requirements",
            return_value=None,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_server_planner_output",
            return_value=None,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_system_prompt",
            return_value="system prompt",
        ) as build_system_prompt,
        patch(
            "intric.flows.ai_builder.ai_builder_planner.compute_conversation_token_budget",
            return_value=256,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.trim_conversation_for_context",
            return_value=[{"role": "user", "content": "Build a flow"}],
        ),
    ):
        await planner._prepare_planner_request(
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
            persisted_planning_state=None,
        )

    unresolved = build_system_prompt.call_args.kwargs[
        "unresolved_architectural_choices"
    ]
    # A fresh conversation with one generic user message resolves no
    # core slots, so both core slots must block commit at this turn.
    assert unresolved == frozenset({"primary_runtime_input", "terminal_output"})


@pytest.mark.asyncio
async def test_prepare_planner_request_carries_forward_persisted_commit_into_prompt() -> (
    None
):
    """When a prior turn persisted an `architecture_commit`, the next
    turn's rendered prompt MUST surface that commit's fingerprint.

    This is the integration proof that `carry_forward_persisted_planner_state`
    runs before the projection and that the projection's post-commit
    narrowing actually reaches the planner LLM.
    """
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Refine step 1")]
    requirements_state = SimpleNamespace(latest_summary=None, confirmed=False)
    discovery_analysis = SimpleNamespace(mvs_met=True)
    committed_hash = "b" * 64
    persisted = PlanningState.empty()
    persisted.architecture_commit = ArchitectureCommit(
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
        architecture_hash=committed_hash,
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_planner.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_discovery_block_message_runtime",
            new_callable=AsyncMock,
            return_value=(None, discovery_analysis, PlanningState.empty()),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.latest_confirmed_requirements",
            return_value=None,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_server_planner_output",
            return_value=None,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_system_prompt",
            return_value="system prompt",
        ) as build_system_prompt,
        patch(
            "intric.flows.ai_builder.ai_builder_planner.compute_conversation_token_budget",
            return_value=256,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.trim_conversation_for_context",
            return_value=[{"role": "user", "content": "Refine step 1"}],
        ),
    ):
        await planner._prepare_planner_request(
            conversation=conversation,
            message="Refine step 1",
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
            persisted_planning_state=persisted,
        )

    planning_state_block = build_system_prompt.call_args.kwargs["planning_state_block"]
    assert isinstance(planning_state_block, str)
    assert "post_commit" in planning_state_block
    assert committed_hash in planning_state_block, (
        "post-commit projection must fingerprint the architecture_hash "
        "so the planner can verify it did not drift across turns"
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

    async def fake_prepare(**_: object) -> PlannerPreparedRequest:
        return PlannerPreparedRequest(
            requirements_state=SimpleNamespace(confirmed=True),
            ui_language="sv",
            discovery_block_message=None,
            llm_messages=[{"role": "system", "content": "proposal"}],
            should_emit_forced_followup=False,
            base_planning_state_version=0,
            rebuilt_planning_state=PlanningState.empty(),
            proposal_mode=True,
            prior_plan_for_revision=cast(BuilderPlan, prior_plan),
            proposal_resource_catalog=build_ai_builder_resource_catalog(
                available_models=[{"id": str(local_model_id), "name": "Renamed model"}],
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
    monkeypatch.setattr(planner, "_prepare_planner_request", fake_prepare)
    monkeypatch.setattr(planner, "_maintain_send_lock_lease", noop_lease)
    monkeypatch.setattr(planner.proposal_processor, "propose_plan", fake_propose_plan)

    events = [
        event
        async for event in planner.send_message(
            session_id=session_id,
            message="Revise the plan",
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            available_models=[{"id": str(local_model_id), "name": "Renamed model"}],
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
