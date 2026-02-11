from datetime import date, datetime, timezone
from unittest.mock import ANY, AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from intric.ai_models.completion_models.completion_model import (
    CompletionModel,
)
from intric.ai_models.model_enums import ModelFamily, ModelHostingLocation, ModelStability
from intric.analysis.analysis import AnalysisProcessingMode
from intric.analysis.analysis_service import (
    ASYNC_AUTO_QUESTION_THRESHOLD,
    NO_QUESTIONS_ANSWER,
    AnalysisService,
)
from intric.main.exceptions import BadRequestException, UnauthorizedException
from intric.roles.permissions import Permission
from tests.fixtures import TEST_UUID


def _make_completion_model() -> CompletionModel:
    """Create a minimal valid CompletionModel for tests."""
    return CompletionModel(
        id=uuid4(),
        name="test-model",
        nickname="test",
        family=ModelFamily.GPT,
        token_limit=4096,
        is_deprecated=False,
        stability=ModelStability.STABLE,
        hosting=ModelHostingLocation.USA,
        vision=False,
        reasoning=False,
    )


@pytest.fixture(name="user")
def user():
    return MagicMock(tenant_id=TEST_UUID)


@pytest.fixture(name="mock_actor")
def mock_actor():
    """Create a mock actor with the necessary methods."""
    actor = MagicMock()
    actor.can_access_insights.return_value = True
    return actor


@pytest.fixture(name="mock_space_service")
def mock_space_service(mock_actor):
    """Create a properly configured mock space service."""
    service = AsyncMock()

    # Configure actor manager
    service.actor_manager = MagicMock()
    service.actor_manager.get_space_actor_from_space.return_value = mock_actor

    # Configure space
    mock_space = MagicMock()
    service.get_space_by_assistant.return_value = mock_space
    service.get_space_by_group_chat.return_value = mock_space
    service.get_space.return_value = mock_space

    return service


@pytest.fixture(name="service")
def analysis_service(user, mock_space_service):
    """Create the analysis service with proper mocks."""
    assistant_service = AsyncMock()
    repo = AsyncMock()
    repo.get_assistant_question_texts_since.return_value = []
    repo.get_group_chat_question_texts_since.return_value = []
    repo.count_assistant_questions_since.return_value = 0
    repo.count_group_chat_questions_since.return_value = 0

    # Configure assistant for insight checks
    mock_assistant = AsyncMock()
    mock_assistant.insight_enabled = True

    # Configure group_chat_service
    group_chat_service = AsyncMock()
    mock_group_chat = MagicMock()
    mock_group_chat.insight_enabled = True
    group_chat_service.get_group_chat.return_value = (mock_group_chat, MagicMock())

    # Configure assistant_service
    assistant_service.get_assistant.return_value = (mock_assistant, MagicMock())

    return AnalysisService(
        user=user,
        repo=repo,
        assistant_service=assistant_service,
        question_repo=AsyncMock(),
        session_repo=AsyncMock(),
        space_service=mock_space_service,
        session_service=AsyncMock(),
        group_chat_service=group_chat_service,
        completion_service=AsyncMock(),
    )


async def test_ask_question_not_in_space(service: AnalysisService):
    service.assistant_service.get_assistant.return_value = (
        AsyncMock(space_id=None, user=service.user, completion_model=_make_completion_model()),
        MagicMock(),
    )

    from_date = date.today()
    to_date = from_date
    await service.ask_question_on_questions(
        question="Test",
        stream=False,
        assistant_id=uuid4(),
        from_date=from_date,
        to_date=to_date,
    )


async def test_ask_question_personal_space_no_access(service: AnalysisService):
    service.space_service.get_space.return_value = MagicMock(user_id=uuid4())
    service.assistant_service.get_assistant.return_value = (
        MagicMock(space_id=uuid4(), user=service.user),
        MagicMock(),
    )
    with pytest.raises(UnauthorizedException):
        from_date = date.today()
        to_date = from_date
        await service.ask_question_on_questions(
            question="Test",
            stream=False,
            assistant_id=uuid4(),
            from_date=from_date,
            to_date=to_date,
        )


async def test_ask_question_personal_space_with_access(service: AnalysisService):
    user = MagicMock(tenant_id=TEST_UUID, permissions=[Permission.INSIGHTS])

    service.space_service.get_space.return_value = MagicMock(user_id=uuid4())
    service.user = user
    service.assistant_service.get_assistant.return_value = (
        AsyncMock(space_id=uuid4(), user=service.user, completion_model=_make_completion_model()),
        MagicMock(),
    )

    from_date = date.today()
    to_date = from_date
    await service.ask_question_on_questions(
        question="Test",
        stream=False,
        assistant_id=uuid4(),
        from_date=from_date,
        to_date=to_date,
    )


async def test_get_questions_since_passes_tenant_id(service: AnalysisService):
    assistant_id = uuid4()
    from_date = date.today()
    to_date = from_date

    service.assistant_service.get_assistant.return_value = (
        AsyncMock(space_id=None, user=service.user),
        MagicMock(),
    )
    service.repo.get_assistant_sessions_since = AsyncMock(return_value=[])

    await service.get_questions_since(
        assistant_id=assistant_id,
        from_date=from_date,
        to_date=to_date,
    )

    service.repo.get_assistant_sessions_since.assert_awaited_once_with(
        assistant_id=assistant_id,
        from_date=from_date,
        to_date=to_date,
        tenant_id=service.user.tenant_id,
    )


async def test_get_questions_from_group_chat_passes_tenant_id(
    service: AnalysisService,
):
    group_chat_id = uuid4()
    from_date = date.today()
    to_date = from_date

    service.repo.get_group_chat_sessions_since = AsyncMock(return_value=[])

    await service.get_questions_from_group_chat(
        group_chat_id=group_chat_id,
        from_date=from_date,
        to_date=to_date,
    )

    service.repo.get_group_chat_sessions_since.assert_awaited_once_with(
        group_chat_id=group_chat_id,
        from_date=from_date,
        to_date=to_date,
        tenant_id=service.user.tenant_id,
    )


async def test_get_conversation_stats_no_id(service: AnalysisService):
    """Test that an exception is raised when neither assistant_id nor group_chat_id is provided."""
    user = MagicMock(tenant_id=TEST_UUID, permissions=[Permission.INSIGHTS])
    service.user = user

    with pytest.raises(BadRequestException):
        await service.get_conversation_stats(
            assistant_id=None,
            group_chat_id=None,
        )


async def test_get_conversation_stats_both_ids(service: AnalysisService):
    """Test that an exception is raised when both assistant_id and group_chat_id are provided."""
    user = MagicMock(tenant_id=TEST_UUID, permissions=[Permission.INSIGHTS])
    service.user = user

    with pytest.raises(BadRequestException):
        await service.get_conversation_stats(
            assistant_id=uuid4(),
            group_chat_id=uuid4(),
        )


async def test_get_conversation_stats_assistant(service: AnalysisService):
    """Test getting conversation stats for an assistant."""
    user = MagicMock(tenant_id=TEST_UUID, permissions=[Permission.INSIGHTS])
    service.user = user

    assistant_id = uuid4()

    # Mock assistant service response
    service.assistant_service.get_assistant.return_value = (
        AsyncMock(space_id=None, user=service.user),
        MagicMock(),
    )

    # Mock repository response - now using optimized count method
    service.repo.get_assistant_conversation_counts.return_value = (2, 3)

    # Call the service method
    result = await service.get_conversation_stats(
        assistant_id=assistant_id,
    )

    # Verify results
    assert result.total_conversations == 2
    assert result.total_questions == 3
    service.repo.get_assistant_conversation_counts.assert_called_once_with(
        assistant_id=assistant_id,
        from_date=ANY,
        to_date=ANY,
        tenant_id=service.user.tenant_id,
    )


async def test_get_conversation_stats_group_chat(service: AnalysisService):
    """Test getting conversation stats for a group chat."""
    user = MagicMock(tenant_id=TEST_UUID, permissions=[Permission.INSIGHTS])
    service.user = user

    group_chat_id = uuid4()

    # Mock repository response - now using optimized count method
    service.repo.get_group_chat_conversation_counts.return_value = (3, 4)

    # Call the service method
    result = await service.get_conversation_stats(
        group_chat_id=group_chat_id,
    )

    # Verify results
    assert result.total_conversations == 3
    assert result.total_questions == 4


async def test_get_assistant_question_history_page_passes_tenant_and_cursor(
    service: AnalysisService,
):
    assistant_id = uuid4()
    cursor = "2026-02-10T12:30:00+00:00|3fa85f64-5717-4562-b3fc-2c963f66afa6"
    service.assistant_service.get_assistant.return_value = (
        AsyncMock(space_id=None, user=service.user),
        MagicMock(),
    )
    row = MagicMock(
        id=uuid4(),
        question="test question",
        created_at=datetime(2026, 2, 11, 11, 0, 0),
        session_id=uuid4(),
    )
    service.repo.get_assistant_question_history_page = AsyncMock(
        return_value=([row], 123, True)
    )

    items, total_count, next_cursor = await service.get_assistant_question_history_page(
        assistant_id=assistant_id,
        from_date=datetime(2026, 2, 1),
        to_date=datetime(2026, 2, 11),
        include_followups=False,
        limit=100,
        query="foo",
        cursor=cursor,
    )

    assert total_count == 123
    assert len(items) == 1
    assert items[0].question == "test question"
    assert next_cursor is not None

    service.repo.get_assistant_question_history_page.assert_awaited_once_with(
        assistant_id=assistant_id,
        from_date=datetime(2026, 2, 1),
        to_date=datetime(2026, 2, 11),
        include_followups=False,
        tenant_id=service.user.tenant_id,
        limit=100,
        query="foo",
        cursor_created_at=datetime(2026, 2, 10, 12, 30, 0, tzinfo=timezone.utc),
        cursor_id=UUID("3fa85f64-5717-4562-b3fc-2c963f66afa6"),
    )


async def test_get_assistant_question_history_page_invalid_cursor_raises(
    service: AnalysisService,
):
    service.assistant_service.get_assistant.return_value = (
        AsyncMock(space_id=None, user=service.user),
        MagicMock(),
    )

    with pytest.raises(BadRequestException):
        await service.get_assistant_question_history_page(
            assistant_id=uuid4(),
            from_date=datetime(2026, 2, 1),
            to_date=datetime(2026, 2, 11),
            include_followups=False,
            limit=50,
            cursor="not-a-valid-cursor",
        )


async def test_get_conversation_stats_with_date_range(service: AnalysisService):
    """Test getting conversation stats with date range filters."""
    user = MagicMock(tenant_id=TEST_UUID, permissions=[Permission.INSIGHTS])
    service.user = user

    group_chat_id = uuid4()
    start_time = datetime(2023, 1, 1, 0, 0)
    end_time = datetime(2023, 1, 31, 23, 59)

    # Mock repository response - now using optimized count method
    service.repo.get_group_chat_conversation_counts.return_value = (1, 1)

    # Call the service method
    result = await service.get_conversation_stats(
        group_chat_id=group_chat_id,
        start_time=start_time,
        end_time=end_time,
    )

    # Verify results
    assert result.total_conversations == 1
    assert result.total_questions == 1
    service.repo.get_group_chat_conversation_counts.assert_called_once_with(
        group_chat_id=group_chat_id,
        from_date=start_time,
        to_date=end_time,
        tenant_id=service.user.tenant_id,
    )


async def test_get_assistant_insight_sessions_passes_tenant_id(
    service: AnalysisService,
):
    assistant_id = uuid4()
    service.session_repo.get_metadata_by_assistant = AsyncMock(return_value=([], 0))

    await service.get_assistant_insight_sessions(assistant_id=assistant_id)

    service.session_repo.get_metadata_by_assistant.assert_awaited_once_with(
        assistant_id=assistant_id,
        limit=ANY,
        cursor=ANY,
        previous=ANY,
        name_filter=ANY,
        start_date=ANY,
        end_date=ANY,
        tenant_id=service.user.tenant_id,
    )


async def test_get_group_chat_insight_sessions_passes_tenant_id(
    service: AnalysisService,
):
    group_chat_id = uuid4()
    service.session_repo.get_metadata_by_group_chat = AsyncMock(return_value=([], 0))

    await service.get_group_chat_insight_sessions(group_chat_id=group_chat_id)

    service.session_repo.get_metadata_by_group_chat.assert_awaited_once_with(
        group_chat_id=group_chat_id,
        limit=ANY,
        cursor=ANY,
        previous=ANY,
        name_filter=ANY,
        start_date=ANY,
        end_date=ANY,
        tenant_id=service.user.tenant_id,
    )


async def test_should_queue_unified_analysis_job_auto(service: AnalysisService):
    assistant_id = uuid4()
    service.repo.count_assistant_questions_since.return_value = (
        ASYNC_AUTO_QUESTION_THRESHOLD + 10
    )

    should_queue = await service.should_queue_unified_analysis_job(
        assistant_id=assistant_id,
        group_chat_id=None,
        from_date=datetime(2026, 1, 1, 0, 0),
        to_date=datetime(2026, 1, 31, 23, 59),
        mode=AnalysisProcessingMode.AUTO,
    )

    assert should_queue is True


async def test_should_queue_unified_analysis_job_sync(service: AnalysisService):
    should_queue = await service.should_queue_unified_analysis_job(
        assistant_id=uuid4(),
        group_chat_id=None,
        from_date=datetime(2026, 1, 1, 0, 0),
        to_date=datetime(2026, 1, 31, 23, 59),
        mode=AnalysisProcessingMode.SYNC,
    )

    assert should_queue is False


async def test_no_data_short_circuit_non_stream(service: AnalysisService):
    """When no questions exist, returns NO_QUESTIONS_ANSWER without calling the model."""
    assistant_id = uuid4()
    mock_assistant = AsyncMock(space_id=None, user=service.user)
    mock_assistant.completion_model = _make_completion_model()
    mock_assistant.get_response = AsyncMock()
    service.assistant_service.get_assistant.return_value = (mock_assistant, MagicMock())
    service.repo.get_assistant_question_texts_since.return_value = []

    response = await service.ask_question_on_questions(
        question="What are the trends?",
        stream=False,
        assistant_id=assistant_id,
        from_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        to_date=datetime(2026, 1, 31, tzinfo=timezone.utc),
    )

    assert response.completion.text == NO_QUESTIONS_ANSWER
    assert response.total_token_count == 0
    mock_assistant.get_response.assert_not_awaited()


async def test_no_data_short_circuit_stream(service: AnalysisService):
    """When no questions exist and stream=True, yields one Completion then stops."""
    assistant_id = uuid4()
    mock_assistant = AsyncMock(space_id=None, user=service.user)
    mock_assistant.completion_model = _make_completion_model()
    mock_assistant.get_response = AsyncMock()
    service.assistant_service.get_assistant.return_value = (mock_assistant, MagicMock())
    service.repo.get_assistant_question_texts_since.return_value = []

    response = await service.ask_question_on_questions(
        question="What are the trends?",
        stream=True,
        assistant_id=assistant_id,
        from_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        to_date=datetime(2026, 1, 31, tzinfo=timezone.utc),
    )

    chunks = [chunk async for chunk in response.completion]
    assert len(chunks) == 1
    assert chunks[0].text == NO_QUESTIONS_ANSWER
    assert chunks[0].stop is True
    mock_assistant.get_response.assert_not_awaited()


def test_deduplicate_questions():
    """Identical questions are collapsed with frequency counts, ordered by frequency."""
    result = AnalysisService._deduplicate_questions(["a", "a", "a", "b", "c", "c"])
    assert result == ["[x3] a", "[x2] c", "b"]


def test_deduplicate_questions_all_unique():
    """All unique questions are returned as-is without counts."""
    result = AnalysisService._deduplicate_questions(["x", "y", "z"])
    assert result == ["x", "y", "z"]


async def test_adaptive_budget_direct_path(service: AnalysisService):
    """Small question set takes the direct path (single LLM call)."""
    assistant_id = uuid4()
    mock_assistant = AsyncMock(space_id=None, user=service.user)
    mock_assistant.completion_model = MagicMock()
    mock_response = MagicMock()
    mock_response.completion.text = "Analysis result"
    mock_assistant.get_response = AsyncMock(return_value=mock_response)
    service.assistant_service.get_assistant.return_value = (mock_assistant, MagicMock())

    rows = [MagicMock(question=f"Question {i}") for i in range(5)]
    service.repo.get_assistant_question_texts_since.return_value = rows

    response = await service.ask_question_on_questions(
        question="Summarize",
        stream=False,
        assistant_id=assistant_id,
        from_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        to_date=datetime(2026, 1, 31, tzinfo=timezone.utc),
    )

    assert response.completion.text == "Analysis result"
    mock_assistant.get_response.assert_awaited_once()


async def test_chunk_partial_failure(service: AnalysisService):
    """When one chunk fails, other chunks' summaries are still returned."""
    call_count = 0

    async def mock_get_response(*, question, completion_service, prompt, stream):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TimeoutError("chunk timed out")
        result = MagicMock()
        result.completion.text = f"Summary {call_count}"
        return result

    mock_model = AsyncMock()
    mock_model.get_response = mock_get_response

    questions = [f"Question {i}" for i in range(200)]
    summaries = await service._summarize_question_chunks(
        model=mock_model, questions=questions, days=30
    )

    assert len(summaries) >= 1
    assert all("Summary" in s for s in summaries)
