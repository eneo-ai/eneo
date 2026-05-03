from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.flows.ai_builder import ai_builder_discovery_runtime as runtime
from intric.flows.ai_builder.ai_builder_discovery_runtime import (
    build_runtime_planning_state,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
    EvidenceRef,
    PlanningState,
    ResolvedSlot,
)


def _make_response(content: str) -> MagicMock:
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _resolved_state() -> PlanningState:
    return PlanningState(
        fcm_version=FCM_VERSION,
        planner_contract_version=PLANNER_CONTRACT_VERSION,
        builder_schema_version=BUILDER_SCHEMA_VERSION,
        phase="discovering",
        evidence=EvidenceRef(),
        resolved_slots={
            "primary_runtime_input": _slot("primary_runtime_input", "text"),
            "terminal_output": _slot("terminal_output", "structured_text"),
            "document_material_scope": _slot(
                "document_material_scope",
                "single_uploaded_document",
            ),
            "structured_analysis_need": _slot(
                "structured_analysis_need",
                "text_only_analysis",
            ),
            "runtime_metadata_fields": _slot(
                "runtime_metadata_fields",
                "no_extra_metadata",
            ),
        },
    )


def _slot(name: str, value: str) -> ResolvedSlot:
    return ResolvedSlot(
        name=name,
        value=value,
        source="structured_answer",
        evidence=[f"question_answer:{name}"],
        confidence="high",
    )


@pytest.mark.asyncio
async def test_runtime_planning_state_skips_model_when_resolvable_slots_are_strong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    litellm_client = AsyncMock()
    monkeypatch.setattr(
        runtime,
        "build_planning_state_from_conversation",
        lambda *_args, **_kwargs: _resolved_state(),
    )

    state = await build_runtime_planning_state(
        [ConversationMessage(role="user", content="Skapa ett komplett flöde.")],
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
    )

    assert state.resolved_slots.keys() == _resolved_state().resolved_slots.keys()
    litellm_client.acompletion.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_planning_state_classifies_weak_existing_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weak_state = _resolved_state()
    weak_state.resolved_slots["runtime_metadata_fields"] = ResolvedSlot(
        name="runtime_metadata_fields",
        value="no_extra_metadata",
        source="policy_default",
        evidence=["policy_default:runtime_metadata_fields=no_extra_metadata"],
        confidence="medium",
    )
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "runtime_metadata_fields",
                        "value": "detailed_case_metadata",
                        "confidence": "high",
                        "reason": "runtime fields requested",
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(
        runtime,
        "build_planning_state_from_conversation",
        lambda *_args, **_kwargs: weak_state,
    )

    state = await build_runtime_planning_state(
        [
            ConversationMessage(
                role="user",
                content="Användaren ska ange målgrupp och detaljnivå vid körning.",
            )
        ],
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
    )

    assert state.resolved_slots["runtime_metadata_fields"].source == "model"
    assert state.resolved_slots["runtime_metadata_fields"].value == (
        "detailed_case_metadata"
    )


@pytest.mark.asyncio
async def test_runtime_planning_state_skips_model_when_freeform_text_is_empty() -> None:
    litellm_client = AsyncMock()

    await build_runtime_planning_state(
        [ConversationMessage(role="user", content="   ")],
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
    )

    litellm_client.acompletion.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_planning_state_skips_model_when_classification_is_disabled() -> (
    None
):
    litellm_client = AsyncMock()

    await build_runtime_planning_state(
        [ConversationMessage(role="user", content="Bygg ett sammanfattningsflöde.")],
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        allow_classification=False,
    )

    litellm_client.acompletion.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_planning_state_overlays_model_slots() -> None:
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "primary_runtime_input",
                        "value": "text",
                        "confidence": "high",
                        "reason": "mentions text input",
                    },
                    {
                        "slot_name": "terminal_output",
                        "value": "structured_text",
                        "confidence": "medium",
                        "reason": "asks for a summary",
                    },
                ]
            }
        )
    )

    state = await build_runtime_planning_state(
        [
            ConversationMessage(
                role="user",
                content="Jag vill beskriva ett ärende i text och få en tydlig sammanfattning.",
            )
        ],
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        ui_language="sv",
    )

    assert state.resolved_slots["primary_runtime_input"].source == "model"
    assert state.resolved_slots["primary_runtime_input"].value == "text"
    assert state.resolved_slots["terminal_output"].source == "model"
    assert state.resolved_slots["terminal_output"].value == "structured_text"
