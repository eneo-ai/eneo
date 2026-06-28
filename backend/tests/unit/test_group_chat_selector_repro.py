"""Tests for the group-chat selector contract.

Background — the original production crash:

    File ".../group_chat/application/group_chat_service.py", line 399, in ask_group_chat
        response_from_selector = selection_result.response_str
    AttributeError: 'NoneType' object has no attribute 'response_str'

`_is_match` did `re.search(r"(\\d+)", text)` with no bounds-check and accepted
any digit anywhere in the selector model's response. Out-of-range digits (a
year like "2024", a hallucinated index, a list marker) fell through a nested
if/else and returned None implicitly, crashing the caller.

The fix moves the selector to a strict sentinel contract: the model must
reply with exactly `ASSISTANT=<n>` to route. Anything else — bare digits,
prose containing numbers, out-of-range sentinels — is treated as
clarification text and surfaced to the user. This eliminates both the crash
class and the silent false-positive routing class.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from eneo.ai_models.completion_models.completion_model import Completion
from eneo.group_chat.application.group_chat_service import GroupChatService
from eneo.group_chat.domain.entities.group_chat import GroupChatAssistant


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


def _two_assistants() -> list[GroupChatAssistant]:
    return [
        _make_assistant("Knowledge", "Looks up policy docs"),
        _make_assistant("Reasoning", "Performs multi-step reasoning"),
    ]


# --- routing happy path ---------------------------------------------------


@pytest.mark.asyncio
async def test_sentinel_routes_to_named_assistant():
    service = _make_service(selector_text="ASSISTANT=2")
    assistants = _two_assistants()

    result = await service._select_assistant_with_completion_model(
        question="Walk me through this proof",
        assistants=assistants,
    )

    assert result is not None
    assert result.assistant is assistants[1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selector_text",
    [
        "ASSISTANT=2",
        "assistant=2",
        "Assistant = 2",
        "  ASSISTANT=2  ",
        "ASSISTANT = 2\n",
    ],
)
async def test_sentinel_tolerates_whitespace_and_case(selector_text: str):
    service = _make_service(selector_text=selector_text)
    assistants = _two_assistants()

    result = await service._select_assistant_with_completion_model(
        question="…",
        assistants=assistants,
    )

    assert result is not None
    assert result.assistant is assistants[1]


# --- regressions for the original crash class -----------------------------


@pytest.mark.asyncio
async def test_bare_out_of_range_digit_does_not_crash():
    """Original crash repro: model emits '3' with 2 assistants.

    Pre-fix: implicit None return → AttributeError in caller.
    Post-fix: no sentinel match → clarification, no crash.
    """
    service = _make_service(selector_text="3")
    assistants = _two_assistants()

    result = await service._select_assistant_with_completion_model(
        question="Who should answer this?",
        assistants=assistants,
    )

    assert result is not None
    assert result.assistant is None


@pytest.mark.asyncio
async def test_stray_year_in_prose_does_not_crash():
    """`\\d+` used to grab '2024' from any clarification text.

    Pre-fix: out of range → implicit None → caller crash.
    Post-fix: no sentinel → clarification surfaced as-is.
    """
    service = _make_service(
        selector_text="Regarding your 2024 budget question, please clarify."
    )
    assistants = _two_assistants()

    result = await service._select_assistant_with_completion_model(
        question="Tell me about taxes",
        assistants=assistants,
    )

    assert result is not None
    assert result.assistant is None
    assert "clarify" in result.response_str


@pytest.mark.asyncio
async def test_out_of_range_sentinel_falls_through_to_clarification():
    """Even with the right token, an out-of-range index must not route."""
    service = _make_service(selector_text="ASSISTANT=5")
    assistants = _two_assistants()

    result = await service._select_assistant_with_completion_model(
        question="…",
        assistants=assistants,
    )

    assert result is not None
    assert result.assistant is None


# --- new in-range false-positive class (the sentinel's main win) ---------


@pytest.mark.asyncio
async def test_numbered_list_in_clarification_does_not_route():
    """Pre-sentinel, this routed to assistant 1 because `\\d+` matched '1)'.

    The user was being asked to clarify, but the parser silently picked an
    assistant and answered as if the question were unambiguous.
    """
    service = _make_service(
        selector_text="Could you specify if you mean 1) tax questions or 2) HR questions?"
    )
    assistants = _two_assistants()

    result = await service._select_assistant_with_completion_model(
        question="help",
        assistants=assistants,
    )

    assert result is not None
    assert result.assistant is None
    assert "specify" in result.response_str


@pytest.mark.asyncio
async def test_bare_digit_without_sentinel_does_not_route():
    """Strict contract: a number alone is not a routing decision."""
    service = _make_service(selector_text="2")
    assistants = _two_assistants()

    result = await service._select_assistant_with_completion_model(
        question="…",
        assistants=assistants,
    )

    assert result is not None
    assert result.assistant is None


# --- pure clarification path -----------------------------------------------


@pytest.mark.asyncio
async def test_clarification_text_with_no_digits():
    service = _make_service(
        selector_text="Could you be more specific about what you need?"
    )
    assistants = _two_assistants()

    result = await service._select_assistant_with_completion_model(
        question="help",
        assistants=assistants,
    )

    assert result is not None
    assert result.assistant is None
    assert "specific" in result.response_str


# --- single-assistant shortcut (no model call) ----------------------------


@pytest.mark.asyncio
async def test_single_assistant_shortcut_bypasses_selector():
    service = _make_service(selector_text="<should not be read>")
    only = _make_assistant("Solo", "Handles everything")

    result = await service._select_assistant_with_completion_model(
        question="anything",
        assistants=[only],
    )

    assert result is not None
    assert result.assistant is only
    service.completion_service.get_response.assert_not_called()
