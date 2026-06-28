"""Integration tests for ``HelpAssistantAssignmentHistoryRepo``.

Round-trips each repo method against a real Postgres (testcontainers). The
repo is intentionally append-only — there is no ``update()`` / ``delete()``
to exercise, so coverage focuses on the read methods that the role-assignment
service and the helper-assistant exclusion filter rely on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.help_assistant_assignment_history_table import (
    HelpAssistantAssignmentHistory,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.help_assistants.domain.assignment_history_reason import (
    AssignmentHistoryReason,
)
from eneo.help_assistants.domain.helper_kind import HelperKind


async def _get_org_space(
    session: sa.ext.asyncio.AsyncSession, *, tenant_id: UUID
) -> UUID:
    """Return the org-space id seeded for ``tenant_id``.

    Mirrors the helper in ``test_org_space_assistant_role_repo.py``:
    ``add_tenant_user`` creates exactly one org-space per tenant and the
    partial unique index ``idx_unique_org_space_per_tenant`` forbids a
    second, so tests look up the existing one.
    """
    row = await session.scalar(
        sa.select(Spaces.id).where(
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
    )
    assert row is not None, "Expected an org-space seeded by add_tenant_user"
    return row


async def _insert_child_space(
    session: sa.ext.asyncio.AsyncSession,
    *,
    tenant_id: UUID,
    parent_org_space_id: UUID,
) -> UUID:
    space_id = uuid4()
    await session.execute(
        sa.insert(Spaces).values(
            id=space_id,
            name=f"child-space-{space_id.hex[:8]}",
            tenant_id=tenant_id,
            user_id=None,
            tenant_space_id=parent_org_space_id,
        )
    )
    return space_id


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


@pytest.mark.asyncio
@pytest.mark.integration
async def test_add_then_list_by_org_space_and_kind_returns_row(
    db_container, admin_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.help_assistant_assignment_history_repo()
        factory = container.helper_assistants_factory()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        old_assistant_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )
        new_assistant_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )

        entry = factory.create_assignment_history_entry(
            org_space_id=space_id,
            kind=HelperKind.PROMPT_GUIDE,
            assistant_id=old_assistant_id,
            assistant_name_snapshot="Prompt Guide (legacy)",
            replaced_by_assistant_id=new_assistant_id,
            reason=AssignmentHistoryReason.REASSIGNED,
            actor_user_id=admin_user.id,
        )

        added = await repo.add(entry)

        assert added.id is not None
        assert added.org_space_id == space_id
        assert added.kind == HelperKind.PROMPT_GUIDE
        assert added.assistant_id == old_assistant_id
        assert added.assistant_name_snapshot == "Prompt Guide (legacy)"
        assert added.replaced_by_assistant_id == new_assistant_id
        assert added.reason == AssignmentHistoryReason.REASSIGNED
        assert added.actor_user_id == admin_user.id
        assert added.replaced_at is not None  # filled by server_default

        rows = await repo.list_by_org_space_and_kind(
            org_space_id=space_id, kind=HelperKind.PROMPT_GUIDE
        )

        assert len(rows) == 1
        assert rows[0].id == added.id
        assert rows[0].assistant_id == old_assistant_id
        assert rows[0].replaced_by_assistant_id == new_assistant_id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_by_org_space_and_kind_orders_by_replaced_at_desc(
    db_container, admin_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.help_assistant_assignment_history_repo()
        factory = container.helper_assistants_factory()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        assistant_a = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )
        assistant_b = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )

        now = datetime.now(timezone.utc)
        older = factory.create_assignment_history_entry(
            org_space_id=space_id,
            kind=HelperKind.PROMPT_GUIDE,
            assistant_id=assistant_a,
            assistant_name_snapshot="A",
            replaced_by_assistant_id=None,
            reason=AssignmentHistoryReason.UNASSIGNED,
            actor_user_id=admin_user.id,
            replaced_at=now - timedelta(hours=2),
        )
        newer = factory.create_assignment_history_entry(
            org_space_id=space_id,
            kind=HelperKind.PROMPT_GUIDE,
            assistant_id=assistant_b,
            assistant_name_snapshot="B",
            replaced_by_assistant_id=None,
            reason=AssignmentHistoryReason.UNASSIGNED,
            actor_user_id=admin_user.id,
            replaced_at=now - timedelta(hours=1),
        )

        await repo.add(older)
        await repo.add(newer)

        rows = await repo.list_by_org_space_and_kind(
            org_space_id=space_id, kind=HelperKind.PROMPT_GUIDE
        )

        assert [r.assistant_name_snapshot for r in rows] == ["B", "A"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_by_org_space_and_kind_filters_by_org_space(
    db_container, admin_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.help_assistant_assignment_history_repo()
        factory = container.helper_assistants_factory()

        space_a = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        space_b = await _insert_child_space(
            session,
            tenant_id=admin_user.tenant_id,
            parent_org_space_id=space_a,
        )
        assistant_a = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_a
        )
        assistant_b = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_b
        )

        await repo.add(
            factory.create_assignment_history_entry(
                org_space_id=space_a,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=assistant_a,
                assistant_name_snapshot="A",
                replaced_by_assistant_id=None,
                reason=AssignmentHistoryReason.RESET_TO_DEFAULT,
                actor_user_id=admin_user.id,
            )
        )
        await repo.add(
            factory.create_assignment_history_entry(
                org_space_id=space_b,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=assistant_b,
                assistant_name_snapshot="B",
                replaced_by_assistant_id=None,
                reason=AssignmentHistoryReason.RESET_TO_DEFAULT,
                actor_user_id=admin_user.id,
            )
        )

        rows_for_a = await repo.list_by_org_space_and_kind(
            org_space_id=space_a, kind=HelperKind.PROMPT_GUIDE
        )

        assert len(rows_for_a) == 1
        assert rows_for_a[0].org_space_id == space_a
        assert rows_for_a[0].assistant_id == assistant_a


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_replaced_assistant_ids_dedupes_and_ignores_null(
    db_container, admin_user
):
    """``assistant_id`` can repeat across rows (same helper reset twice) and
    can be NULL after the underlying assistant is archived (FK SET NULL).
    Both cases must be excluded from the returned set.
    """
    async with db_container() as container:
        session = container.session()
        repo = container.help_assistant_assignment_history_repo()
        factory = container.helper_assistants_factory()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        recurring_assistant = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )
        archived_assistant = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )

        # Same assistant_id twice → must dedupe.
        await repo.add(
            factory.create_assignment_history_entry(
                org_space_id=space_id,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=recurring_assistant,
                assistant_name_snapshot="recurring v1",
                replaced_by_assistant_id=None,
                reason=AssignmentHistoryReason.RESET_TO_DEFAULT,
                actor_user_id=admin_user.id,
            )
        )
        await repo.add(
            factory.create_assignment_history_entry(
                org_space_id=space_id,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=recurring_assistant,
                assistant_name_snapshot="recurring v2",
                replaced_by_assistant_id=None,
                reason=AssignmentHistoryReason.REASSIGNED,
                actor_user_id=admin_user.id,
            )
        )

        # Third row points at an assistant that we will then archive — FK
        # ON DELETE SET NULL leaves assistant_id NULL.
        await repo.add(
            factory.create_assignment_history_entry(
                org_space_id=space_id,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=archived_assistant,
                assistant_name_snapshot="archived",
                replaced_by_assistant_id=None,
                reason=AssignmentHistoryReason.UNASSIGNED,
                actor_user_id=admin_user.id,
            )
        )
        await session.execute(
            sa.delete(Assistants).where(Assistants.id == archived_assistant)
        )

        ids = await repo.list_replaced_assistant_ids_by_org_space(space_id)

        assert ids == {recurring_assistant}

        # Sanity: the NULL row is still present in the table, it was just
        # excluded from the returned set.
        remaining = await session.scalar(
            sa.select(sa.func.count()).select_from(HelpAssistantAssignmentHistory)
        )
        assert remaining == 3


@pytest.mark.asyncio
@pytest.mark.integration
async def test_exists_for_assistant_matches_both_columns(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        repo = container.help_assistant_assignment_history_repo()
        factory = container.helper_assistants_factory()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        replaced_assistant = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )
        replacement_assistant = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )
        unrelated_assistant = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )

        await repo.add(
            factory.create_assignment_history_entry(
                org_space_id=space_id,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=replaced_assistant,
                assistant_name_snapshot="old",
                replaced_by_assistant_id=replacement_assistant,
                reason=AssignmentHistoryReason.REASSIGNED,
                actor_user_id=admin_user.id,
            )
        )

        assert await repo.exists_for_assistant(replaced_assistant) is True
        assert await repo.exists_for_assistant(replacement_assistant) is True
        assert await repo.exists_for_assistant(unrelated_assistant) is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_exists_for_assistant_false_when_unknown(db_container, admin_user):
    async with db_container() as container:
        repo = container.help_assistant_assignment_history_repo()
        assert await repo.exists_for_assistant(uuid4()) is False
