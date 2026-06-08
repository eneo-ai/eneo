"""Integration tests for the chat-stream-abort persistence flow (issue #349).

These tests exercise the new placeholder + update persistence path against a real
PostgreSQL database. The streaming generator and SSE infrastructure are exercised
end-to-end at the unit level (tests/unit/test_chat_stream_abort_persistence.py); this
file focuses on the DB-level behavior that those unit tests can't validate with mocks:

1. The placeholder Question row is durably persisted before any stream begins.
2. The late update_with_answer call correctly updates the same row.
3. The abort-path `persist_partial_question_answer` works through a fresh sessionmanager
   session and refuses to write across tenants (defense-in-depth on the WHERE clause).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.database import sessionmanager
from intric.database.tables.questions_table import Questions
from intric.sessions.session_service import persist_partial_question_answer


@dataclass
class QuestionSnapshot:
    id: UUID
    question: str
    answer: str
    num_tokens_question: int
    num_tokens_answer: int
    tenant_id: UUID
    session_id: UUID | None


async def _create_space(client, bearer_token: str) -> str:
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"abort-space-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_assistant(client, bearer_token: str, space_id: str) -> str:
    response = await client.post(
        "/api/v1/assistants/",
        json={"name": f"abort-assistant-{uuid4().hex[:8]}", "space_id": space_id},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


@pytest.fixture
async def default_user(db_container):
    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.get_user_by_email("test@example.com")
    return user


@pytest.fixture
async def default_user_token(db_container, patch_auth_service_jwt, default_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        token = auth_service.create_access_token_for_user(default_user)
    return token


async def _get_question_row(question_id: UUID) -> QuestionSnapshot | None:
    async with sessionmanager.session() as session, session.begin():
        result = await session.execute(
            sa.select(Questions).where(Questions.id == question_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        # Snapshot the fields while the session is still open — otherwise the ORM
        # object becomes detached and attribute access raises.
        return QuestionSnapshot(
            id=row.id,
            question=row.question,
            answer=row.answer,
            num_tokens_question=row.num_tokens_question,
            num_tokens_answer=row.num_tokens_answer,
            tenant_id=row.tenant_id,
            session_id=row.session_id,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_placeholder_persists_user_question_before_stream(
    client, db_container, default_user, default_user_token
):
    """Phase 1: a placeholder row with the user's question and empty answer must be
    durably written to the DB by `create_question_placeholder`. This is the linchpin
    of the fix — if the stream is aborted before the assistant replies, the user's
    message must still be queryable on the next refresh."""

    space_id = await _create_space(client, default_user_token)
    assistant_id = await _create_assistant(client, default_user_token, space_id)

    async with db_container() as container:
        session_service = container.session_service()
        chat_session = await session_service.create_session(
            name="abort-test", assistant_id=UUID(assistant_id)
        )
        question_id = await session_service.create_question_placeholder(
            question="What happens if I press ESC?",
            session=chat_session,
            files=None,
            assistant_id=UUID(assistant_id),
            completion_model=None,
        )

    row = await _get_question_row(question_id)
    assert row is not None
    assert row.question == "What happens if I press ESC?"
    assert row.answer == ""
    assert row.num_tokens_question == 0
    assert row.num_tokens_answer == 0
    assert row.tenant_id == default_user.tenant_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_complete_question_with_answer_updates_existing_row(
    client, db_container, default_user, default_user_token
):
    """Phase 2 (normal completion): the placeholder row is updated in-place, not
    duplicated."""

    space_id = await _create_space(client, default_user_token)
    assistant_id = await _create_assistant(client, default_user_token, space_id)

    async with db_container() as container:
        session_service = container.session_service()
        chat_session = await session_service.create_session(
            name="abort-test", assistant_id=UUID(assistant_id)
        )
        question_id = await session_service.create_question_placeholder(
            question="hi",
            session=chat_session,
            files=None,
            assistant_id=UUID(assistant_id),
            completion_model=None,
        )

        await session_service.complete_question_with_answer(
            question_id=question_id,
            answer="hello back",
            num_tokens_question=5,
            num_tokens_answer=3,
            completion_model=None,
            info_blob_chunks=[],
            generated_files=None,
            logging_details=None,
            web_search_results=None,
            tool_calls=None,
        )

    row = await _get_question_row(question_id)
    assert row is not None
    assert row.question == "hi"
    assert row.answer == "hello back"
    assert row.num_tokens_question == 5
    assert row.num_tokens_answer == 3

    # Confirm we have ONE row, not a duplicate from a stale INSERT path.
    async with sessionmanager.session() as session, session.begin():
        result = await session.execute(
            sa.select(sa.func.count())
            .select_from(Questions)
            .where(Questions.session_id == chat_session.id)
        )
        assert result.scalar_one() == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_persist_partial_question_answer_writes_via_fresh_session(
    client, db_container, default_user, default_user_token
):
    """Phase 2 (abort path): the fire-and-forget helper uses a fresh DB session and
    correctly updates the answer text + token count on the existing placeholder."""

    space_id = await _create_space(client, default_user_token)
    assistant_id = await _create_assistant(client, default_user_token, space_id)

    async with db_container() as container:
        session_service = container.session_service()
        chat_session = await session_service.create_session(
            name="abort-test", assistant_id=UUID(assistant_id)
        )
        question_id = await session_service.create_question_placeholder(
            question="why did it stop?",
            session=chat_session,
            files=None,
            assistant_id=UUID(assistant_id),
            completion_model=None,
        )

    # Simulate the streaming generator's `finally`: open a fresh session
    # (sessionmanager.session()) and update with the partial answer.
    await persist_partial_question_answer(
        tenant_id=default_user.tenant_id,
        question_id=question_id,
        answer="partial reply before the user pressed ESC",
        num_tokens_answer=9,
        completion_model_id=None,
    )

    row = await _get_question_row(question_id)
    assert row is not None
    assert row.question == "why did it stop?"
    assert row.answer == "partial reply before the user pressed ESC"
    assert row.num_tokens_answer == 9


@pytest.mark.integration
@pytest.mark.asyncio
async def test_persist_partial_question_answer_refuses_cross_tenant_write(
    client, db_container, default_user, default_user_token
):
    """Tenancy guard: even if a caller fabricates a question_id, the WHERE-clause
    tenant filter must prevent any update under another tenant's id."""

    space_id = await _create_space(client, default_user_token)
    assistant_id = await _create_assistant(client, default_user_token, space_id)

    async with db_container() as container:
        session_service = container.session_service()
        chat_session = await session_service.create_session(
            name="abort-test", assistant_id=UUID(assistant_id)
        )
        question_id = await session_service.create_question_placeholder(
            question="real tenant's question",
            session=chat_session,
            files=None,
            assistant_id=UUID(assistant_id),
            completion_model=None,
        )

    # A different tenant tries to overwrite the real tenant's row via the helper.
    # Must NOT raise (it's best-effort), but must NOT update either.
    foreign_tenant_id = uuid4()
    assert foreign_tenant_id != default_user.tenant_id
    await persist_partial_question_answer(
        tenant_id=foreign_tenant_id,
        question_id=question_id,
        answer="cross-tenant attempt",
        num_tokens_answer=99,
    )

    row = await _get_question_row(question_id)
    assert row is not None
    assert row.answer == "", "cross-tenant write must be filtered out by WHERE clause"
    assert row.num_tokens_answer == 0
