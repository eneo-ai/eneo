from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.completion_models.infrastructure.context_builder import (
    build_files_string,
    count_tokens,
)
from intric.conversations.application.conversation_service import ConversationService
from intric.files.file_models import FileType
from intric.main.exceptions import BadRequestException


def _make_service(
    *,
    assistant=None,
    group_chat=None,
    session=None,
    files=None,
):
    assistant_service = AsyncMock()
    if assistant is not None:
        assistant_service.get_assistant = AsyncMock(return_value=(assistant, []))
        # Preflight resolves the model through the governance-aware path, which
        # returns the effective model directly (mirrors ask()).
        assistant_service.get_effective_completion_model = AsyncMock(
            return_value=assistant.completion_model
        )

    group_chat_service = AsyncMock()
    if group_chat is not None:
        group_chat_service.get_group_chat = AsyncMock(return_value=group_chat)
        first_model = (
            group_chat.assistants[0].assistant.completion_model
            if group_chat.assistants
            else None
        )
        group_chat_service.find_suitable_completion_model = AsyncMock(
            return_value=first_model
        )
        group_chat_service.create_assistant_selection_prompt = MagicMock(
            return_value="selector prompt"
        )

    session_service = AsyncMock()
    if session is not None:
        session_service.get_session_by_uuid = AsyncMock(return_value=session)

    file_service = AsyncMock()
    file_service.get_files_by_ids = AsyncMock(return_value=files or [])

    return ConversationService(
        assistant_service=assistant_service,
        group_chat_service=group_chat_service,
        session_service=session_service,
        completion_service=MagicMock(),
        space_service=MagicMock(),
        file_service=file_service,
    )


def _make_completion_model(name: str = "gpt-4o", token_limit: int = 128000):
    model = MagicMock()
    model.name = name
    model.token_limit = token_limit
    return model


def _make_assistant(model_name: str = "gpt-4o", token_limit: int = 128000):
    assistant = MagicMock()
    assistant.completion_model = _make_completion_model(model_name, token_limit)
    return assistant


@pytest.mark.asyncio
async def test_preflight_counts_input_only():
    """A bare text question without files yields input_tokens > 0, file_tokens = 0."""
    service = _make_service(assistant=_make_assistant())

    result = await service.preflight_tokens(
        question="Hello world, how many tokens am I?",
        file_ids=[],
        assistant_id=uuid4(),
    )

    assert result.input_tokens > 0
    assert result.file_tokens == 0
    assert result.model_name == "gpt-4o"
    assert result.context_window == 128000


@pytest.mark.asyncio
async def test_preflight_counts_zero_for_empty_question():
    """Defensive: count_tokens('') returns 0; service shouldn't crash.

    The router-level validator already rejects empty input — this protects
    direct service callers (e.g. future internal usage).
    """
    service = _make_service(assistant=_make_assistant())

    result = await service.preflight_tokens(
        question="",
        file_ids=[],
        assistant_id=uuid4(),
    )

    assert result.input_tokens == 0
    assert result.file_tokens == 0


@pytest.mark.asyncio
async def test_preflight_file_tokens_match_context_builder_output():
    """Text files contribute exactly what context_builder would tokenize.

    Frontend bases user-visible projections on this number, so it must
    match the wrapper string byte-for-byte rather than be a loose estimate.
    """
    text_file = MagicMock()
    text_file.file_type = FileType.TEXT
    text_file.text = "the quick brown fox"
    text_file.name = "fox.txt"

    service = _make_service(
        assistant=_make_assistant(),
        files=[text_file],
    )

    file_id = uuid4()
    result = await service.preflight_tokens(
        question="summarize this",
        file_ids=[file_id],
        assistant_id=uuid4(),
    )

    expected_tokens = count_tokens(build_files_string([text_file]), "gpt-4o")
    assert result.file_tokens == expected_tokens
    assert result.file_tokens > 0

    service.file_service.get_files_by_ids.assert_awaited_once_with(file_ids=[file_id])


@pytest.mark.asyncio
async def test_preflight_skips_non_text_files():
    """Image/binary files don't go through the input string path."""
    image_file = MagicMock()
    image_file.file_type = FileType.IMAGE
    image_file.text = None
    image_file.name = "cat.png"

    service = _make_service(
        assistant=_make_assistant(),
        files=[image_file],
    )

    result = await service.preflight_tokens(
        question="what is this",
        file_ids=[uuid4()],
        assistant_id=uuid4(),
    )

    assert result.file_tokens == 0


@pytest.mark.asyncio
async def test_preflight_resolves_session_assistant_model():
    """Session-id path goes through session → assistant → model."""
    session_id = uuid4()
    assistant_id = uuid4()

    session = MagicMock()
    session.group_chat_id = None
    session.assistant = MagicMock()
    session.assistant.id = assistant_id

    service = _make_service(
        session=session,
        assistant=_make_assistant(model_name="gpt-4o"),
    )

    result = await service.preflight_tokens(
        question="hello",
        file_ids=[],
        session_id=session_id,
    )

    assert result.input_tokens > 0
    assert result.model_name == "gpt-4o"
    service.session_service.get_session_by_uuid.assert_awaited_once_with(session_id)
    service.assistant_service.get_effective_completion_model.assert_awaited_once_with(
        assistant_id
    )


@pytest.mark.asyncio
async def test_preflight_resolves_session_to_group_chat_model():
    """A session whose `group_chat_id` is set must route through the group chat,
    not the (possibly stale) `session.assistant` field."""
    session_id = uuid4()
    group_chat_id = uuid4()

    session = MagicMock()
    session.group_chat_id = group_chat_id
    session.assistant = None

    member = MagicMock()
    member.assistant.completion_model = _make_completion_model(
        "claude-3-5-sonnet", token_limit=200000
    )

    group_chat = MagicMock()
    group_chat.assistants = [member]

    service = _make_service(session=session, group_chat=group_chat)

    result = await service.preflight_tokens(
        question="hi",
        file_ids=[],
        session_id=session_id,
    )

    assert result.model_name == "claude-3-5-sonnet"
    assert result.context_window == 200000
    service.group_chat_service.get_group_chat.assert_awaited_once_with(group_chat_id)


@pytest.mark.asyncio
async def test_preflight_rejects_assistant_without_model():
    """No completion model → 400, matching the actual chat path failure."""
    assistant = MagicMock()
    assistant.completion_model = None

    service = _make_service(assistant=assistant)

    with pytest.raises(BadRequestException):
        await service.preflight_tokens(
            question="hello",
            file_ids=[],
            assistant_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_preflight_rejects_empty_group_chat():
    """Group chat with no assistants → 400, matching ask_group_chat behavior."""
    group_chat = MagicMock()
    group_chat.assistants = []

    service = _make_service(group_chat=group_chat)

    with pytest.raises(BadRequestException):
        await service.preflight_tokens(
            question="hello",
            file_ids=[],
            group_chat_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_preflight_group_chat_uses_single_assistant_model():
    """Single-assistant group chat preflight tokenizes against that assistant's model."""
    member = MagicMock()
    member.assistant.completion_model = _make_completion_model("gpt-4o")

    group_chat = MagicMock()
    group_chat.assistants = [member]

    service = _make_service(group_chat=group_chat)

    result = await service.preflight_tokens(
        question="hello",
        file_ids=[],
        group_chat_id=uuid4(),
    )

    assert result.input_tokens > 0
    assert result.model_name == "gpt-4o"


@pytest.mark.asyncio
async def test_preflight_group_chat_counts_selector_tokens_and_uses_smallest_window():
    """Multi-assistant group chat includes selector prompt cost and projects conservatively."""
    first_member = MagicMock()
    first_member.assistant.completion_model = _make_completion_model(
        "gpt-4o", token_limit=128000
    )
    second_member = MagicMock()
    second_member.assistant.completion_model = _make_completion_model(
        "small-context-model", token_limit=4096
    )

    group_chat = MagicMock()
    group_chat.assistants = [first_member, second_member]

    service = _make_service(group_chat=group_chat)

    result = await service.preflight_tokens(
        question="hello",
        file_ids=[],
        group_chat_id=uuid4(),
    )

    expected_selector_tokens = count_tokens("selector prompt", "gpt-4o")
    expected_question_tokens = count_tokens("hello", "small-context-model")
    assert result.input_tokens == expected_question_tokens + expected_selector_tokens
    assert result.model_name == "small-context-model"
    assert result.context_window == 4096


@pytest.mark.asyncio
async def test_preflight_group_chat_mention_uses_target_assistant_model():
    """Mention-targeted group chat preflight mirrors the actual target assistant."""
    target_id = uuid4()
    first_member = MagicMock()
    first_member.assistant.id = uuid4()
    first_member.assistant.completion_model = _make_completion_model(
        "gpt-4o", token_limit=128000
    )
    target_member = MagicMock()
    target_member.assistant.id = target_id
    target_member.assistant.completion_model = _make_completion_model(
        "target-model", token_limit=32000
    )

    group_chat = MagicMock()
    group_chat.allow_mentions = True
    group_chat.assistants = [first_member, target_member]
    group_chat.get_assistant_by_id.return_value = target_member

    service = _make_service(group_chat=group_chat)

    result = await service.preflight_tokens(
        question="hello",
        file_ids=[],
        group_chat_id=uuid4(),
        tool_assistant_id=target_id,
    )

    assert result.input_tokens == count_tokens("hello", "target-model")
    assert result.model_name == "target-model"
    assert result.context_window == 32000
    service.group_chat_service.find_suitable_completion_model.assert_not_awaited()
