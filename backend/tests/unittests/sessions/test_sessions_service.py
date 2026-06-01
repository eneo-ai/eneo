from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.assistants.api.assistant_models import AssistantSparse
from intric.main.exceptions import NotFoundException, UnauthorizedException
from intric.sessions.session import SessionInDB, SessionUpdate
from intric.sessions.session_service import SessionService
from tests.fixtures import TEST_USER, TEST_UUID

TEST_ASSISTANT = AssistantSparse(
    name="test_assistant",
    id=TEST_UUID,
    user_id=TEST_UUID,
    type="assistant",
)


@pytest.fixture
async def service():
    session_repo = AsyncMock()
    question_repo = AsyncMock()

    service = SessionService(
        session_repo=session_repo,
        question_repo=question_repo,
        user=TEST_USER,
    )

    return service


async def test_get_error_when_session_does_not_exist(service: SessionService):
    service.session_repo.get.return_value = None

    with pytest.raises(NotFoundException, match="not found"):
        await service.get_session_by_uuid(1)


async def test_get_error_when_user_not_owner_of_session(service: SessionService):
    service.session_repo.get.return_value = SessionInDB(
        user_id=uuid4(),
        name="test_session",
        id=TEST_UUID,
    )

    with pytest.raises(UnauthorizedException, match="belongs to other principal"):
        await service.get_session_by_uuid(1)


async def test_get_error_when_session_does_not_belong_to_assistant(
    service: SessionService,
):
    service.session_repo.get.return_value = SessionInDB(
        user_id=TEST_USER.id,
        name="test_session",
        id=TEST_UUID,
        assistant=TEST_ASSISTANT,
    )

    with pytest.raises(NotFoundException, match="belongs to another assistant"):
        await service.get_session_by_uuid(TEST_UUID, assistant_id=uuid4())


async def test_succeeds_with_assistant_id(service: SessionService):
    session = SessionInDB(
        user_id=TEST_USER.id,
        name="test_session",
        assistant=TEST_ASSISTANT,
        id=TEST_UUID,
    )
    service.session_repo.get.return_value = session

    session_in_db = await service.get_session_by_uuid(
        TEST_UUID, assistant_id=TEST_ASSISTANT.id
    )

    assert session_in_db == session


async def test_update_error_when_session_does_not_exist(service: SessionService):
    service.session_repo.update.return_value = None
    session_upsert = SessionUpdate(name="new_test_name", id=TEST_UUID)

    with pytest.raises(NotFoundException, match="not found"):
        await service.update_session(session_upsert)


async def test_update_error_when_user_is_not_owner_of_session(service: SessionService):
    service.session_repo.update.return_value = SessionInDB(
        user_id=uuid4(),
        name="test_session",
        id=TEST_UUID,
    )
    session_upsert = SessionUpdate(name="new_test_name", id=TEST_UUID)

    with pytest.raises(UnauthorizedException, match="belongs to other principal"):
        await service.update_session(session_upsert)


async def test_delete_error_when_session_does_not_exist(service: SessionService):
    service.session_repo.get.return_value = None

    with pytest.raises(NotFoundException, match="not found"):
        await service.delete(1)


async def test_delete_error_when_user_not_owner_of_session(service: SessionService):
    service.session_repo.get.return_value = SessionInDB(
        user_id=uuid4(),
        name="test_session",
        id=TEST_UUID,
    )

    with pytest.raises(UnauthorizedException, match="belongs to other principal"):
        await service.delete(1)
