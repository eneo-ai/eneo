from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.analysis.analysis_service import AnalysisService
from intric.main.exceptions import BadRequestException, UnauthorizedException
from intric.roles.permissions import Permission
from tests.fixtures import TEST_UUID


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
        repo=AsyncMock(),
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
        AsyncMock(space_id=None, user=service.user),
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
        AsyncMock(space_id=uuid4(), user=service.user),
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
    service.repo.get_assistant_conversation_counts.assert_called_once()


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
    service.repo.get_group_chat_conversation_counts.assert_called_once()


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
    )
