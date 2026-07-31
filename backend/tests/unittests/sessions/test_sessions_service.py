from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import eneo.sessions.session_service as session_service_module
from eneo.assistants.api.assistant_models import AssistantSparse
from eneo.main.exceptions import NotFoundException, UnauthorizedException
from eneo.sessions.session import SessionInDB, SessionUpdate
from eneo.sessions.session_service import SessionService
from eneo.skills.domain.skill import (
    SkillActivationEvidenceV1,
    SkillExecutionReference,
    SkillTurnEffectiveMode,
)
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


async def test_delete_terminates_remote_mcp_sessions_before_local_delete():
    session = SessionInDB(
        user_id=TEST_USER.id,
        name="test_session",
        id=TEST_UUID,
    )
    session_repo = AsyncMock()
    session_repo.get.return_value = session
    session_repo.delete.return_value = session
    lifecycle_service = AsyncMock()
    service = SessionService(
        session_repo=session_repo,
        question_repo=AsyncMock(),
        user=TEST_USER,
        mcp_session_lifecycle_service=lifecycle_service,
    )

    deleted = await service.delete(TEST_UUID)

    assert deleted == session
    lifecycle_service.terminate_for_chat_session.assert_awaited_once_with(TEST_UUID)
    session_repo.delete.assert_awaited_once_with(TEST_UUID)


async def test_question_placeholder_persists_selected_skill_revision(
    service: SessionService,
    monkeypatch: pytest.MonkeyPatch,
):
    reference = SkillExecutionReference(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        revision_number=2,
        content_digest="a" * 64,
        position=0,
    )
    activation = SkillActivationEvidenceV1(
        effective_mode=SkillTurnEffectiveMode.EAGER,
        available=(),
        blocked=(),
        initially_active=(),
        selected_model_id=uuid4(),
        selected_model_route="gpt-4o",
        skill_context_tokens=0,
        skill_context_token_limit=12_800,
        token_count_source="litellm",
    )
    question_id = uuid4()
    fresh_session = MagicMock()
    fresh_question_repo = AsyncMock()
    fresh_question_repo.add.return_value = MagicMock(id=question_id)

    @asynccontextmanager
    async def _fresh_session_scope():
        yield fresh_session

    @asynccontextmanager
    async def _begin():
        yield

    fresh_session.begin.return_value = _begin()
    monkeypatch.setattr(
        session_service_module.sessionmanager,
        "session",
        _fresh_session_scope,
    )
    question_repo_factory = MagicMock(return_value=fresh_question_repo)
    monkeypatch.setattr(
        session_service_module,
        "QuestionRepository",
        question_repo_factory,
    )
    session = SessionInDB(
        user_id=TEST_USER.id,
        name="test_session",
        id=TEST_UUID,
    )

    result, _created_at = await service.create_question_placeholder(
        question="Question",
        session=session,
        skill_provenance=(reference,),
        skill_activation=activation,
    )

    question_repo_factory.assert_called_once_with(fresh_session)
    question_add = fresh_question_repo.add.await_args.args[0]
    assert question_add.skill_provenance == [reference]
    assert question_add.skill_activation == activation
    assert result == question_id
