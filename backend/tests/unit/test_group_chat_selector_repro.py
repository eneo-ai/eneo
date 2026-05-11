"""Reproduction for the group-chat selector NoneType crash.

Production traceback (see incident notes):

    File ".../group_chat/application/group_chat_service.py", line 399, in ask_group_chat
        response_from_selector = selection_result.response_str
    AttributeError: 'NoneType' object has no attribute 'response_str'

Root cause is in `_select_assistant_with_completion_model`:

    if assistant_match:
        if 1 <= assistant_match <= len(assistants):
            return GroupChatAssistantSelectionResult(...)
        # ← no else: falls through to implicit None
    else:
        return GroupChatAssistantSelectionResult(assistant=None, ...)

`_is_match` does no bounds-check — it returns the first digit run found in
the selector model's response. When that run is outside `1..len(assistants)`
the function silently returns None and the caller crashes.

These tests cover the cases that can hit it in prod:
- model picks an index strictly greater than len(assistants)
- model embeds a stray year / large number in clarification prose
- happy paths must keep working (sanity)
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from intric.ai_models.completion_models.completion_model import Completion
from intric.group_chat.application.group_chat_service import GroupChatService
from intric.group_chat.domain.entities.group_chat import GroupChatAssistant


def _make_assistant(name: str, description: str) -> GroupChatAssistant:
    completion_model = SimpleNamespace(name="gpt-test")
    assistant = SimpleNamespace(
        id=f"assistant-{name}",
        name=name,
        description=description,
        completion_model=completion_model,
    )
    return GroupChatAssistant(assistant=assistant, user_description=None)


def _make_service(selector_text: str) -> GroupChatService:
    completion_response = SimpleNamespace(
        completion=Completion(text=selector_text),
    )
    completion_service = MagicMock()
    completion_service.get_response = AsyncMock(return_value=completion_response)

    return GroupChatService(
        user=MagicMock(),
        space_service=MagicMock(),
        space_repo=MagicMock(),
        actor_manager=MagicMock(),
        assistant_service=MagicMock(),
        session_service=MagicMock(),
        completion_service=completion_service,
        icon_repo=MagicMock(),
    )


@pytest.mark.asyncio
async def test_selector_returns_index_greater_than_assistant_count():
    """Selector picks '3' with only 2 assistants — current code returns None."""
    service = _make_service(selector_text="3")
    assistants = [
        _make_assistant("Knowledge", "Looks up policy docs"),
        _make_assistant("Reasoning", "Performs multi-step reasoning"),
    ]

    result = await service._select_assistant_with_completion_model(
        question="Who should answer this?",
        assistants=assistants,
    )

    # FAILS today (returns None) — proves the missing-else fall-through.
    # Expected after fix: a result with assistant=None so the clarification
    # branch in ask_group_chat runs instead of crashing.
    assert result is not None, (
        "Out-of-range selector index returned None — caller will crash on "
        ".response_str at group_chat_service.py:449"
    )
    assert result.assistant is None


@pytest.mark.asyncio
async def test_selector_response_contains_stray_year():
    """Selector emits prose like 'Regarding your 2024 budget question' — `\\d+`
    picks up 2024, which is out of range and crashes."""
    service = _make_service(
        selector_text="Regarding your 2024 budget question, please clarify."
    )
    assistants = [
        _make_assistant("Knowledge", "Looks up policy docs"),
        _make_assistant("Reasoning", "Performs multi-step reasoning"),
    ]

    result = await service._select_assistant_with_completion_model(
        question="Tell me about taxes",
        assistants=assistants,
    )

    assert result is not None
    assert result.assistant is None
    # The full prose should still be available so the clarification branch
    # can surface it back to the user.
    assert "clarify" in result.response_str


@pytest.mark.asyncio
async def test_selector_picks_valid_index():
    """Sanity: '2' with 2 assistants must keep working."""
    service = _make_service(selector_text="2")
    a1 = _make_assistant("Knowledge", "Looks up policy docs")
    a2 = _make_assistant("Reasoning", "Performs multi-step reasoning")

    result = await service._select_assistant_with_completion_model(
        question="Walk me through this proof",
        assistants=[a1, a2],
    )

    assert result is not None
    assert result.assistant is a2


@pytest.mark.asyncio
async def test_selector_returns_no_digit_goes_to_clarification():
    """Sanity: pure clarification text (no digits) must keep working."""
    service = _make_service(
        selector_text="Could you be more specific about what you need?"
    )
    assistants = [
        _make_assistant("Knowledge", "Looks up policy docs"),
        _make_assistant("Reasoning", "Performs multi-step reasoning"),
    ]

    result = await service._select_assistant_with_completion_model(
        question="help",
        assistants=assistants,
    )

    assert result is not None
    assert result.assistant is None
    assert "specific" in result.response_str
