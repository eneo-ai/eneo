from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_planner import (
    AIBuilderPlanner,
    PlannerToolSelection,
)
from intric.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy


def _make_planner() -> AIBuilderPlanner:
    return AIBuilderPlanner(
        user=MagicMock(tenant_id=uuid4()),
        repo=AsyncMock(),
        litellm_client=AsyncMock(),
        planner_temperature=0.1,
        self_correction_temperature=0.1,
        forced_proposal_temperature=0.1,
        quality_retry_warning_codes=set(),
    )


@pytest.mark.asyncio
async def test_resolve_message_metadata_uses_freeform_inference_before_adjudication() -> None:
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


@pytest.mark.asyncio
async def test_resolve_message_metadata_preserves_requirements_confirmation_and_ui_language() -> None:
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


@pytest.mark.asyncio
async def test_resolve_message_metadata_infers_final_output_answer_from_structured_label() -> None:
    planner = _make_planner()
    conversation = [
        ConversationMessage(
            role="assistant",
            content="Jag behöver förstå slutresultatet lite bättre innan jag kan bekräfta lösningen.",
            tool_calls=[{
                "id": "call_q1",
                "name": "ask_structured_question",
                "arguments": {
                    "question_id": "final_output_mode",
                    "question": "Vad ska flödet producera som slutresultat?",
                    "options": [
                        {"id": "structured_text", "label": "Strukturerat beslutsunderlag som text"},
                        {"id": "pdf_document", "label": "PDF-dokument"},
                        {"id": "docx_document", "label": "DOCX-dokument"},
                    ],
                    "selection_mode": "single",
                    "allow_custom": True,
                },
            }],
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


def test_select_tool_schemas_marks_forced_followup_after_free_discovery_turn_limit() -> None:
    planner = _make_planner()
    conversation = [
        ConversationMessage(role="assistant", content="What kind of input should I expect?"),
        ConversationMessage(role="assistant", content="Can you clarify the desired output?"),
    ]

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_planner._get_mvs_forced_followup",
            return_value="forced followup",
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_free_discovery_tool_schemas",
            return_value=[{"function": {"name": "ask_structured_question"}}],
        ),
    ):
        result = planner._select_tool_schemas(
            conversation=conversation,
            requirements_confirmed=False,
            is_requirements_confirmation=False,
            user_message="I need a flow",
            discovery_block_message=None,
            discovery_analysis=SimpleNamespace(mvs_met=False),
            flow=None,
            is_edit_mode=False,
            available_models=None,
            available_kbs=None,
        )

    assert result.is_free_discovery is True
    assert result.should_force_requirements_summary is False
    assert result.should_emit_forced_followup is True


@pytest.mark.asyncio
async def test_prepare_planner_request_collects_refs_and_tool_selection() -> None:
    planner = _make_planner()
    conversation = [ConversationMessage(role="user", content="Build a flow")]
    requirements_state = SimpleNamespace(latest_summary=None, confirmed=False)
    discovery_analysis = SimpleNamespace(mvs_met=True)
    tool_selection = PlannerToolSelection(
        tool_schemas=[{"function": {"name": "confirm_requirements"}}],
        should_force_requirements_summary=True,
        is_free_discovery=False,
        should_emit_forced_followup=False,
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_planner.resolve_requirements_state",
            return_value=requirements_state,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_discovery_block_message_runtime",
            new_callable=AsyncMock,
            return_value=(None, discovery_analysis),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.latest_confirmed_requirements",
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
        patch.object(planner, "_select_tool_schemas", return_value=tool_selection),
    ):
        prepared = await planner._prepare_planner_request(
            conversation=conversation,
            message="Build a flow",
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            available_models=[{"ref": "model-a"}],
            available_kbs=[{"ref": "kb-a"}],
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
        )

    assert prepared.requirements_state is requirements_state
    assert prepared.tool_selection is tool_selection
    assert prepared.available_model_refs == {"model-a"}
    assert prepared.available_kb_refs == {"kb-a"}
    assert prepared.llm_messages[0] == {"role": "system", "content": "system prompt"}
