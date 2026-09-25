from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

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
