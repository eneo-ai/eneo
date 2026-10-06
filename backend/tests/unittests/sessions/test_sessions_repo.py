from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from eneo.questions.question import MessageFeedback
from eneo.sessions.sessions_repo import OwnedChatPartner, SessionRepository


async def test_hydrates_all_info_blobs_without_file_loader(monkeypatch):
    blobs = [MagicMock(), MagicMock()]
    hydrate = AsyncMock()
    monkeypatch.setattr(
        "eneo.sessions.sessions_repo.InfoBlobRepository.hydrate_original_availability",
        hydrate,
    )
    repo = SessionRepository(AsyncMock())

    await repo._hydrate_sessions(
        [
            SimpleNamespace(
                questions=[SimpleNamespace(info_blobs=blobs, questions_files=[])]
            )
        ]
    )

    hydrate.assert_awaited_once_with(blobs)


async def test_update_hydrates_info_blob_availability(monkeypatch):
    blob = MagicMock()
    updated = SimpleNamespace(
        questions=[SimpleNamespace(info_blobs=[blob], questions_files=[])]
    )
    hydrate = AsyncMock()
    monkeypatch.setattr(
        "eneo.sessions.sessions_repo.InfoBlobRepository.hydrate_original_availability",
        hydrate,
    )
    repo = SessionRepository(AsyncMock())
    repo.delegate.update = AsyncMock(return_value=updated)

    result = await repo.update(MagicMock())

    assert result is updated
    hydrate.assert_awaited_once_with([blob])


async def test_owned_chat_partner_read_is_scalar_tenant_and_owner_scoped():
    session_id = uuid4()
    tenant_id = uuid4()
    user_id = uuid4()
    assistant_id = uuid4()
    session = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = SimpleNamespace(
        assistant_id=assistant_id,
        group_chat_id=None,
    )
    session.execute.return_value = result
    file_loader = MagicMock()
    repo = SessionRepository(session, file_content_loader=file_loader)

    partner = await repo.get_owned_chat_partner(
        session_id=session_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )

    assert partner == OwnedChatPartner(assistant_id, None)
    file_loader.assert_not_called()
    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert sql.startswith("SELECT sessions.assistant_id, sessions.group_chat_id")
    assert "JOIN users ON sessions.user_id = users.id" in sql
    assert "sessions.id =" in sql
    assert "sessions.user_id =" in sql
    assert "users.tenant_id =" in sql
    assert "help_assistant_runs" in sql
    assert "sessions.name" not in sql
    assert "questions" not in sql
    assert {session_id, tenant_id, user_id}.issubset(set(compiled.params.values()))


async def test_owned_chat_partner_returns_none_for_an_inaccessible_session():
    session = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = None
    session.execute.return_value = result
    repo = SessionRepository(session)

    partner = await repo.get_owned_chat_partner(
        session_id=uuid4(),
        tenant_id=uuid4(),
        user_id=uuid4(),
    )

    assert partner is None


def _repo_returning(row: object) -> tuple[SessionRepository, AsyncMock]:
    session = AsyncMock()
    result = MagicMock()
    result.one_or_none.return_value = row
    session.execute.return_value = result
    return SessionRepository(session), session


def _compiled(session: AsyncMock):
    statement = session.execute.await_args.args[0]
    return statement.compile(dialect=postgresql.dialect())


async def test_owned_message_partner_is_scoped_to_the_message_owner_and_tenant():
    session_id, message_id, tenant_id, user_id = uuid4(), uuid4(), uuid4(), uuid4()
    assistant_id = uuid4()
    repo, session = _repo_returning(
        SimpleNamespace(assistant_id=assistant_id, group_chat_id=None)
    )

    partner = await repo.get_owned_message_partner(
        session_id=session_id,
        message_id=message_id,
        tenant_id=tenant_id,
        user_id=user_id,
        api_key_id=None,
    )

    assert partner == OwnedChatPartner(assistant_id, None)
    compiled = _compiled(session)
    sql = str(compiled)
    assert "questions.id =" in sql
    assert "questions.session_id =" in sql
    assert "questions.tenant_id =" in sql
    assert "sessions.user_id =" in sql
    assert "sessions.api_key_id" not in sql
    assert "help_assistant_runs" in sql
    assert {session_id, message_id, tenant_id, user_id}.issubset(
        set(compiled.params.values())
    )


async def test_owned_message_partner_matches_a_service_key_principal():
    api_key_id = uuid4()
    repo, session = _repo_returning(None)

    partner = await repo.get_owned_message_partner(
        session_id=uuid4(),
        message_id=uuid4(),
        tenant_id=uuid4(),
        user_id=None,
        api_key_id=api_key_id,
    )

    assert partner is None
    compiled = _compiled(session)
    assert "sessions.api_key_id =" in str(compiled)
    assert "sessions.user_id =" not in str(compiled)
    assert api_key_id in compiled.params.values()


async def test_a_request_without_a_principal_owns_no_message():
    repo, session = _repo_returning(None)

    await repo.get_owned_message_partner(
        session_id=uuid4(),
        message_id=uuid4(),
        tenant_id=uuid4(),
        user_id=None,
        api_key_id=None,
    )

    sql = str(_compiled(session))
    assert "false" in sql
    assert "sessions.user_id =" not in sql
    assert "sessions.api_key_id =" not in sql


async def test_set_message_feedback_upserts_only_an_owned_message():
    user_id, message_id = uuid4(), uuid4()
    repo, session = _repo_returning(SimpleNamespace(value=-1, text="Fel paragraf"))

    stored = await repo.set_message_feedback(
        session_id=uuid4(),
        message_id=message_id,
        tenant_id=uuid4(),
        user_id=user_id,
        api_key_id=None,
        feedback=MessageFeedback(value=-1, text="Fel paragraf"),
    )

    assert stored == MessageFeedback(value=-1, text="Fel paragraf")
    compiled = _compiled(session)
    sql = str(compiled)
    assert sql.startswith("INSERT INTO question_feedback")
    assert "SELECT questions.id" in sql
    assert "sessions.user_id =" in sql
    assert "ON CONFLICT (question_id) DO UPDATE" in sql
    assert "updated_at = now()" in sql
    assert {user_id, message_id, -1, "Fel paragraf"}.issubset(
        set(compiled.params.values())
    )


async def test_set_message_feedback_writes_nothing_for_a_foreign_message():
    repo, _ = _repo_returning(None)

    stored = await repo.set_message_feedback(
        session_id=uuid4(),
        message_id=uuid4(),
        tenant_id=uuid4(),
        user_id=uuid4(),
        api_key_id=None,
        feedback=MessageFeedback(value=1),
    )

    assert stored is None


async def test_delete_message_feedback_is_scoped_to_the_owner():
    user_id, message_id = uuid4(), uuid4()
    session = AsyncMock()
    repo = SessionRepository(session)

    await repo.delete_message_feedback(
        session_id=uuid4(),
        message_id=message_id,
        tenant_id=uuid4(),
        user_id=user_id,
        api_key_id=None,
    )

    compiled = _compiled(session)
    sql = str(compiled)
    assert sql.startswith("DELETE FROM question_feedback")
    assert "question_feedback.question_id IN (SELECT questions.id" in sql
    assert "sessions.user_id =" in sql
    assert {user_id, message_id}.issubset(set(compiled.params.values()))
