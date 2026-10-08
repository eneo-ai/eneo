"""Settings share the session lifecycle and use PostgreSQL compare-and-swap."""

import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.sessions_table import Sessions
from eneo.main.exceptions import ConversationSettingsConflictException
from eneo.sessions.conversation_settings import ConversationSettings
from eneo.sessions.sessions_repo import SessionRepository


@pytest.mark.parametrize("initial_revision", [0, 1])
async def test_concurrent_settings_writes_have_one_winner(
    db_container, db_session, initial_revision
):
    async with db_container() as container:
        saved = await container.session_service().create_session(name="Settings")
        other = await container.session_service().create_session(name="Other")
    if initial_revision:
        async with db_session() as session:
            await SessionRepository(session).update_settings(
                saved.id, ConversationSettings(), 0
            )

    server_id = uuid4()
    choices = [
        ConversationSettings(mcp_server_states={server_id: enabled})
        for enabled in (True, False)
    ]

    async def write(settings):
        try:
            async with db_session() as session:
                return await SessionRepository(session).update_settings(
                    saved.id, settings, initial_revision
                )
        except ConversationSettingsConflictException:
            return None

    async with asyncio.timeout(10):
        results = await asyncio.gather(*(write(settings) for settings in choices))
    winners = [state for state in results if state is not None]
    assert len(winners) == 1
    assert winners[0].revision == initial_revision + 1

    async with db_session() as session:
        stored = await session.scalar(
            sa.select(Sessions.settings).where(Sessions.id == saved.id)
        )
        untouched = await session.scalar(
            sa.select(Sessions.settings).where(Sessions.id == other.id)
        )
    assert stored == winners[0].model_dump(mode="json")
    assert untouched is None

    async with db_container() as container:
        await container.session_service().delete(saved.id)
    async with db_session() as session:
        assert (
            await session.scalar(sa.select(Sessions.id).where(Sessions.id == saved.id))
            is None
        )


async def test_settings_update_is_independent_of_history_hydration(
    db_container, db_session, monkeypatch
):
    async with db_container() as container:
        saved = await container.session_service().create_session(name="Metadata only")
        tenant_id = container.user().tenant_id

    async def unavailable_history(*_args, **_kwargs):
        raise AssertionError("Settings must not hydrate chat history or file contents")

    monkeypatch.setattr(SessionRepository, "_hydrate_sessions", unavailable_history)
    async with db_container() as container:
        state = await container.session_service().update_settings(
            saved.id, ConversationSettings(require_tool_approval=True), 0
        )
        context = await container.session_service().get_context(saved.id)
    assert context.settings == state
    async with db_session() as session:
        repo = SessionRepository(session)
        assert (await repo.get_context(saved.id, tenant_id)).settings == state
        assert await repo.get_context(saved.id, uuid4()) is None
