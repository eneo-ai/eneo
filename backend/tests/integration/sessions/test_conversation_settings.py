"""Settings share the session lifecycle and use PostgreSQL compare-and-swap."""

import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.sessions_table import Sessions
from eneo.main.exceptions import ConversationSettingsConflictException
from eneo.sessions.conversation_settings import ConversationSettings
from eneo.sessions.sessions_repo import SessionRepository


@pytest.mark.parametrize(
    "change_settings", [False, True], ids=["rename", "rename-and-settings"]
)
async def test_renaming_still_advances_activity(
    db_container, db_session, change_settings
):
    async with db_container() as container:
        saved = await container.session_service().create_session(name="Original")

    async with db_session() as session:
        # Pin the timestamp so only the database trigger can advance it.
        statement = (
            sa.update(Sessions)
            .where(Sessions.id == saved.id)
            .values(name="Renamed", updated_at=Sessions.updated_at)
        )
        if change_settings:
            statement = statement.values(settings={"revision": 1, "settings": {}})
        updated_at = await session.scalar(statement.returning(Sessions.updated_at))

    assert saved.updated_at is not None
    assert updated_at is not None
    assert updated_at > saved.updated_at


@pytest.mark.parametrize("initial_revision", [0, 1])
async def test_concurrent_settings_writes_have_one_winner(
    db_container, db_session, initial_revision
):
    async with db_container() as container:
        saved = await container.session_service().create_session(name="Settings")
        other = await container.session_service().create_session(name="Other")
        tenant_id = container.user().tenant_id
        context = await container.session_service().get_context(saved.id)
    if initial_revision:
        async with db_session() as session:
            await SessionRepository(session).update_settings(
                context, tenant_id, ConversationSettings(), 0
            )

    async with db_container() as container:
        context = await container.session_service().get_context(saved.id)
    server_id = uuid4()
    choices = [
        ConversationSettings(mcp_server_states={server_id: enabled})
        for enabled in (True, False)
    ]

    async def write(settings):
        try:
            async with db_session() as session:
                return await SessionRepository(session).update_settings(
                    context, tenant_id, settings, initial_revision
                )
        except ConversationSettingsConflictException:
            return None

    async with asyncio.timeout(10):
        results = await asyncio.gather(*(write(settings) for settings in choices))
    winners = [state for state in results if state is not None]
    assert len(winners) == 1
    assert winners[0].revision == initial_revision + 1

    async with db_session() as session:
        stored, updated_at = (
            await session.execute(
                sa.select(Sessions.settings, Sessions.updated_at).where(
                    Sessions.id == saved.id
                )
            )
        ).one()
        untouched = await session.scalar(
            sa.select(Sessions.settings).where(Sessions.id == other.id)
        )
    assert stored == winners[0].model_dump(mode="json")
    assert untouched is None
    assert saved.updated_at is not None
    assert updated_at == saved.updated_at

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


async def test_known_settings_update_preserves_retired_capability(
    db_container, db_session
):
    async with db_container() as container:
        saved = await container.session_service().create_session(
            name="Retired capability"
        )
    async with db_session() as session:
        await session.execute(
            sa.update(Sessions)
            .where(Sessions.id == saved.id)
            .values(
                settings={
                    "revision": 1,
                    "settings": {
                        "capability_states": {"retired_tool": True, "charts": False}
                    },
                }
            )
        )
    async with db_container() as container:
        state = await container.session_service().update_settings(
            saved.id, ConversationSettings(require_tool_approval=True), 1
        )
        assert state.revision == 2
    async with db_session() as session:
        stored = await session.scalar(
            sa.select(Sessions.settings).where(Sessions.id == saved.id)
        )
    assert stored["settings"]["capability_states"] == {"retired_tool": True}
    assert stored["settings"]["require_tool_approval"] is True
