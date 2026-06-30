"""Integration tests for ``HelperRunRepo``.

Round-trips every method against a real Postgres (testcontainers) and pins
the tenant-scoping contract: each read/write that takes a ``tenant_id``
applies it as a WHERE clause, so a row written for tenant A is invisible
to a query passing tenant B's id. The lone exception is
``is_helper_session`` — intentionally global, used by the session-exclusion
filter (step 013) which itself runs inside a tenant-scoped query.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import psycopg2
import pytest
import sqlalchemy as sa

from init_db import add_tenant_user
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.help_assistant_runs_table import HelpAssistantRuns
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces
from eneo.help_assistants.domain.helper_kind import HelperKind
from eneo.help_assistants.domain.helper_run_status import HelperRunStatus


@pytest.fixture
async def second_tenant_user(db_container, test_settings):
    """Spin up a second tenant + user pair via the psycopg2 init_db path
    that other integration tests use, then resolve the user via the
    test container. Used for cross-tenant isolation assertions.
    """
    suffix = uuid4().hex[:8]
    email = f"helper_run_repo_user_{suffix}@example.com"
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    add_tenant_user(
        conn,
        tenant_name=f"helper_run_repo_tenant_{suffix}",
        quota_limit=1_000_000,
        user_name=f"helper_run_repo_user_{suffix}",
        user_email=email,
        user_password="test_password",
    )
    conn.close()

    async with db_container() as container:
        user_repo = container.user_repo()
        return await user_repo.get_user_by_email(email)


async def _get_org_space(
    session: sa.ext.asyncio.AsyncSession, *, tenant_id: UUID
) -> UUID:
    """Return the org-space seeded for ``tenant_id`` by ``add_tenant_user``."""
    row = await session.scalar(
        sa.select(Spaces.id).where(
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
    )
    assert row is not None, "Expected an org-space seeded by add_tenant_user"
    return row


async def _insert_assistant(
    session: sa.ext.asyncio.AsyncSession,
    *,
    owner_user_id: UUID,
    space_id: UUID,
) -> UUID:
    assistant_id = uuid4()
    await session.execute(
        sa.insert(Assistants).values(
            id=assistant_id,
            name=f"assistant-{assistant_id.hex[:8]}",
            user_id=owner_user_id,
            space_id=space_id,
            completion_model_id=None,
            logging_enabled=False,
            is_default=False,
            published=False,
        )
    )
    return assistant_id


async def _insert_session(
    session: sa.ext.asyncio.AsyncSession,
    *,
    user_id: UUID,
    assistant_id: UUID,
) -> UUID:
    session_id = uuid4()
    suffix = secrets.token_hex(4)
    await session.execute(
        sa.insert(Sessions).values(
            id=session_id,
            name=f"helper-session-{suffix}",
            user_id=user_id,
            assistant_id=assistant_id,
        )
    )
    return session_id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_add_then_get_by_id_round_trips_all_fields(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        repo = container.helper_run_repo()
        factory = container.helper_assistants_factory()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        helper_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )
        target_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )
        session_id = await _insert_session(
            session, user_id=admin_user.id, assistant_id=helper_id
        )

        run = factory.create_helper_run(
            tenant_id=admin_user.tenant_id,
            org_space_id=space_id,
            kind=HelperKind.PROMPT_GUIDE,
            assistant_id=helper_id,
            target_type="assistant",
            target_id=target_id,
            session_id=session_id,
            actor_user_id=admin_user.id,
        )

        added = await repo.add(run)

        assert added.id is not None
        assert added.tenant_id == admin_user.tenant_id
        assert added.org_space_id == space_id
        assert added.kind == HelperKind.PROMPT_GUIDE
        assert added.assistant_id == helper_id
        assert added.target_type == "assistant"
        assert added.target_id == target_id
        assert added.session_id == session_id
        assert added.actor_user_id == admin_user.id
        assert added.status == HelperRunStatus.IN_PROGRESS
        assert added.completed_at is None
        assert added.created_at is not None
        assert added.updated_at is not None

        fetched = await repo.get_by_id(added.id, tenant_id=admin_user.tenant_id)
        assert fetched is not None
        assert fetched.id == added.id
        assert fetched.session_id == session_id
        assert fetched.status == HelperRunStatus.IN_PROGRESS


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_by_id_returns_none_for_other_tenant(
    db_container, admin_user, second_tenant_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.helper_run_repo()
        factory = container.helper_assistants_factory()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        helper_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )
        session_id = await _insert_session(
            session, user_id=admin_user.id, assistant_id=helper_id
        )

        added = await repo.add(
            factory.create_helper_run(
                tenant_id=admin_user.tenant_id,
                org_space_id=space_id,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=helper_id,
                target_type="assistant",
                target_id=helper_id,
                session_id=session_id,
                actor_user_id=admin_user.id,
            )
        )

        assert (
            await repo.get_by_id(added.id, tenant_id=second_tenant_user.tenant_id)
        ) is None
        assert (
            await repo.get_by_id(added.id, tenant_id=admin_user.tenant_id)
        ) is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_by_id_returns_none_when_missing(db_container, admin_user):
    async with db_container() as container:
        repo = container.helper_run_repo()
        assert (await repo.get_by_id(uuid4(), tenant_id=admin_user.tenant_id)) is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_by_session_id_returns_run(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        repo = container.helper_run_repo()
        factory = container.helper_assistants_factory()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        helper_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )
        session_id = await _insert_session(
            session, user_id=admin_user.id, assistant_id=helper_id
        )

        added = await repo.add(
            factory.create_helper_run(
                tenant_id=admin_user.tenant_id,
                org_space_id=space_id,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=helper_id,
                target_type="assistant",
                target_id=helper_id,
                session_id=session_id,
                actor_user_id=admin_user.id,
            )
        )

        fetched = await repo.get_by_session_id(
            session_id, tenant_id=admin_user.tenant_id
        )

        assert fetched is not None
        assert fetched.id == added.id
        assert fetched.session_id == session_id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_by_session_id_returns_none_for_other_tenant(
    db_container, admin_user, second_tenant_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.helper_run_repo()
        factory = container.helper_assistants_factory()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        helper_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )
        session_id = await _insert_session(
            session, user_id=admin_user.id, assistant_id=helper_id
        )

        await repo.add(
            factory.create_helper_run(
                tenant_id=admin_user.tenant_id,
                org_space_id=space_id,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=helper_id,
                target_type="assistant",
                target_id=helper_id,
                session_id=session_id,
                actor_user_id=admin_user.id,
            )
        )

        assert (
            await repo.get_by_session_id(
                session_id, tenant_id=second_tenant_user.tenant_id
            )
        ) is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_status_to_completed_persists_completed_at(
    db_container, admin_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.helper_run_repo()
        factory = container.helper_assistants_factory()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        helper_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )
        session_id = await _insert_session(
            session, user_id=admin_user.id, assistant_id=helper_id
        )

        added = await repo.add(
            factory.create_helper_run(
                tenant_id=admin_user.tenant_id,
                org_space_id=space_id,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=helper_id,
                target_type="assistant",
                target_id=helper_id,
                session_id=session_id,
                actor_user_id=admin_user.id,
            )
        )
        assert added.completed_at is None

        completed_at = datetime.now(timezone.utc)
        updated = await repo.update_status(
            added.id,
            tenant_id=admin_user.tenant_id,
            status=HelperRunStatus.COMPLETED,
            completed_at=completed_at,
        )

        assert updated.status == HelperRunStatus.COMPLETED
        assert updated.completed_at is not None

        fetched = await repo.get_by_id(added.id, tenant_id=admin_user.tenant_id)
        assert fetched is not None
        assert fetched.status == HelperRunStatus.COMPLETED
        assert fetched.completed_at is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_status_to_in_progress_leaves_completed_at_null(
    db_container, admin_user
):
    """``IN_PROGRESS`` is the only non-terminal status; callers must be able
    to keep ``completed_at`` NULL by passing ``None`` even after the row
    has temporarily moved through a terminal state in tests."""
    async with db_container() as container:
        session = container.session()
        repo = container.helper_run_repo()
        factory = container.helper_assistants_factory()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        helper_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )
        session_id = await _insert_session(
            session, user_id=admin_user.id, assistant_id=helper_id
        )

        added = await repo.add(
            factory.create_helper_run(
                tenant_id=admin_user.tenant_id,
                org_space_id=space_id,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=helper_id,
                target_type="assistant",
                target_id=helper_id,
                session_id=session_id,
                actor_user_id=admin_user.id,
            )
        )

        updated = await repo.update_status(
            added.id,
            tenant_id=admin_user.tenant_id,
            status=HelperRunStatus.IN_PROGRESS,
            completed_at=None,
        )

        assert updated.status == HelperRunStatus.IN_PROGRESS
        assert updated.completed_at is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_status_does_not_touch_other_tenants_rows(
    db_container, admin_user, second_tenant_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.helper_run_repo()
        factory = container.helper_assistants_factory()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        helper_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )
        session_id = await _insert_session(
            session, user_id=admin_user.id, assistant_id=helper_id
        )

        added = await repo.add(
            factory.create_helper_run(
                tenant_id=admin_user.tenant_id,
                org_space_id=space_id,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=helper_id,
                target_type="assistant",
                target_id=helper_id,
                session_id=session_id,
                actor_user_id=admin_user.id,
            )
        )

        # Wrong tenant: no row matches the (id, tenant_id) filter, so the
        # UPDATE is a no-op that returns None — it must not raise and must
        # not touch the owning tenant's row.
        result = await repo.update_status(
            added.id,
            tenant_id=second_tenant_user.tenant_id,
            status=HelperRunStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
        )
        assert result is None

        unchanged = await repo.get_by_id(added.id, tenant_id=admin_user.tenant_id)
        assert unchanged is not None
        assert unchanged.status == HelperRunStatus.IN_PROGRESS
        assert unchanged.completed_at is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_by_tenant_excludes_other_tenants(
    db_container, admin_user, second_tenant_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.helper_run_repo()
        factory = container.helper_assistants_factory()

        # tenant A run
        space_a = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        helper_a = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_a
        )
        session_a = await _insert_session(
            session, user_id=admin_user.id, assistant_id=helper_a
        )
        added_a = await repo.add(
            factory.create_helper_run(
                tenant_id=admin_user.tenant_id,
                org_space_id=space_a,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=helper_a,
                target_type="assistant",
                target_id=helper_a,
                session_id=session_a,
                actor_user_id=admin_user.id,
            )
        )

        # tenant B run
        space_b = await _get_org_space(session, tenant_id=second_tenant_user.tenant_id)
        helper_b = await _insert_assistant(
            session, owner_user_id=second_tenant_user.id, space_id=space_b
        )
        session_b = await _insert_session(
            session, user_id=second_tenant_user.id, assistant_id=helper_b
        )
        added_b = await repo.add(
            factory.create_helper_run(
                tenant_id=second_tenant_user.tenant_id,
                org_space_id=space_b,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=helper_b,
                target_type="assistant",
                target_id=helper_b,
                session_id=session_b,
                actor_user_id=second_tenant_user.id,
            )
        )

        rows_a = await repo.list_by_tenant(tenant_id=admin_user.tenant_id)
        ids_a = {r.id for r in rows_a}
        assert added_a.id in ids_a
        assert added_b.id not in ids_a

        rows_b = await repo.list_by_tenant(tenant_id=second_tenant_user.tenant_id)
        ids_b = {r.id for r in rows_b}
        assert added_b.id in ids_b
        assert added_a.id not in ids_b


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_by_tenant_filters_by_status(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        repo = container.helper_run_repo()
        factory = container.helper_assistants_factory()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        helper_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )
        session_in_progress = await _insert_session(
            session, user_id=admin_user.id, assistant_id=helper_id
        )
        session_completed = await _insert_session(
            session, user_id=admin_user.id, assistant_id=helper_id
        )

        in_progress = await repo.add(
            factory.create_helper_run(
                tenant_id=admin_user.tenant_id,
                org_space_id=space_id,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=helper_id,
                target_type="assistant",
                target_id=helper_id,
                session_id=session_in_progress,
                actor_user_id=admin_user.id,
            )
        )
        completed = await repo.add(
            factory.create_helper_run(
                tenant_id=admin_user.tenant_id,
                org_space_id=space_id,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=helper_id,
                target_type="assistant",
                target_id=helper_id,
                session_id=session_completed,
                actor_user_id=admin_user.id,
            )
        )
        await repo.update_status(
            completed.id,
            tenant_id=admin_user.tenant_id,
            status=HelperRunStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
        )

        in_progress_rows = await repo.list_by_tenant(
            tenant_id=admin_user.tenant_id, status=HelperRunStatus.IN_PROGRESS
        )
        completed_rows = await repo.list_by_tenant(
            tenant_id=admin_user.tenant_id, status=HelperRunStatus.COMPLETED
        )

        assert [r.id for r in in_progress_rows] == [in_progress.id]
        assert [r.id for r in completed_rows] == [completed.id]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_older_than_purges_only_below_threshold_for_tenant(
    db_container, admin_user, second_tenant_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.helper_run_repo()
        factory = container.helper_assistants_factory()

        space_a = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        helper_a = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_a
        )
        space_b = await _get_org_space(session, tenant_id=second_tenant_user.tenant_id)
        helper_b = await _insert_assistant(
            session, owner_user_id=second_tenant_user.id, space_id=space_b
        )

        old_session_a = await _insert_session(
            session, user_id=admin_user.id, assistant_id=helper_a
        )
        new_session_a = await _insert_session(
            session, user_id=admin_user.id, assistant_id=helper_a
        )
        old_session_b = await _insert_session(
            session, user_id=second_tenant_user.id, assistant_id=helper_b
        )

        old_a = await repo.add(
            factory.create_helper_run(
                tenant_id=admin_user.tenant_id,
                org_space_id=space_a,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=helper_a,
                target_type="assistant",
                target_id=helper_a,
                session_id=old_session_a,
                actor_user_id=admin_user.id,
            )
        )
        new_a = await repo.add(
            factory.create_helper_run(
                tenant_id=admin_user.tenant_id,
                org_space_id=space_a,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=helper_a,
                target_type="assistant",
                target_id=helper_a,
                session_id=new_session_a,
                actor_user_id=admin_user.id,
            )
        )
        old_b = await repo.add(
            factory.create_helper_run(
                tenant_id=second_tenant_user.tenant_id,
                org_space_id=space_b,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=helper_b,
                target_type="assistant",
                target_id=helper_b,
                session_id=old_session_b,
                actor_user_id=second_tenant_user.id,
            )
        )

        # Back-date the "old" rows so they fall below the threshold. We can't
        # control created_at via the repo (server_default), so we patch
        # directly in SQL for the test's purpose.
        backdated = datetime.now(timezone.utc) - timedelta(days=30)
        await session.execute(
            sa.update(HelpAssistantRuns)
            .where(HelpAssistantRuns.id.in_([old_a.id, old_b.id]))
            .values(created_at=backdated)
        )

        threshold = datetime.now(timezone.utc) - timedelta(days=7)
        purged = await repo.delete_older_than(
            tenant_id=admin_user.tenant_id, threshold=threshold
        )

        assert purged == 1  # only old_a is purged
        assert (await repo.get_by_id(old_a.id, tenant_id=admin_user.tenant_id)) is None
        assert (
            await repo.get_by_id(new_a.id, tenant_id=admin_user.tenant_id)
        ) is not None
        assert (
            await repo.get_by_id(old_b.id, tenant_id=second_tenant_user.tenant_id)
        ) is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_is_helper_session_true_for_existing_row(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        repo = container.helper_run_repo()
        factory = container.helper_assistants_factory()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        helper_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )
        session_id = await _insert_session(
            session, user_id=admin_user.id, assistant_id=helper_id
        )

        await repo.add(
            factory.create_helper_run(
                tenant_id=admin_user.tenant_id,
                org_space_id=space_id,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=helper_id,
                target_type="assistant",
                target_id=helper_id,
                session_id=session_id,
                actor_user_id=admin_user.id,
            )
        )

        assert await repo.is_helper_session(session_id) is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_is_helper_session_false_for_unknown_session(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        repo = container.helper_run_repo()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        helper_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )
        non_helper_session = await _insert_session(
            session, user_id=admin_user.id, assistant_id=helper_id
        )

        assert await repo.is_helper_session(non_helper_session) is False
        assert await repo.is_helper_session(uuid4()) is False
