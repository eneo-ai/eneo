"""Integration tests for ``OrgSpaceAssistantRoleRepo``.

Round-trips each repo method against a real Postgres (testcontainers) and
pins the ``UNIQUE(org_space_id, kind)`` constraint as an ``IntegrityError``
at the repo boundary. Service-level invariants (assistant must live in the
same org-space, audit-trail writes) are covered in the role-assignment
service tests added in a later step.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from intric.database.tables.assistant_table import Assistants
from intric.database.tables.org_space_assistant_roles_table import (
    OrgSpaceAssistantRoles,
)
from intric.database.tables.spaces_table import Spaces
from intric.help_assistants.domain.helper_kind import HelperKind


async def _get_org_space(
    session: sa.ext.asyncio.AsyncSession, *, tenant_id: UUID
) -> UUID:
    """Return the org-space id for ``tenant_id``.

    ``add_tenant_user`` already creates exactly one org-space per tenant in
    the cleanup_database autouse fixture, and the partial unique index
    ``idx_unique_org_space_per_tenant`` forbids creating a second. Tests
    therefore look up the existing one instead of inserting a new row.
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
async def test_add_then_get_by_id_round_trips_all_fields(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        repo = container.org_space_assistant_role_repo()
        factory = container.helper_assistants_factory()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        assistant_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )

        assignment = factory.create_role_assignment(
            org_space_id=space_id,
            kind=HelperKind.PROMPT_GUIDE,
            assistant_id=assistant_id,
            is_enabled=True,
            is_visible_to_users=False,
            created_by_user_id=admin_user.id,
        )

        added = await repo.add(assignment)

        assert added.id is not None
        assert added.org_space_id == space_id
        assert added.kind == HelperKind.PROMPT_GUIDE
        assert added.assistant_id == assistant_id
        assert added.is_enabled is True
        assert added.is_visible_to_users is False
        assert added.created_by_user_id == admin_user.id
        assert added.updated_by_user_id is None
        assert added.created_at is not None
        assert added.updated_at is not None

        fetched = await repo.get_by_id(added.id)
        assert fetched is not None
        assert fetched.id == added.id
        assert fetched.org_space_id == space_id
        assert fetched.kind == HelperKind.PROMPT_GUIDE
        assert fetched.assistant_id == assistant_id
        assert fetched.is_visible_to_users is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_by_id_returns_none_when_missing(db_container, admin_user):
    async with db_container() as container:
        repo = container.org_space_assistant_role_repo()
        assert await repo.get_by_id(uuid4()) is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_by_org_space_and_kind_returns_assignment(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        repo = container.org_space_assistant_role_repo()
        factory = container.helper_assistants_factory()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        assistant_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )

        await repo.add(
            factory.create_role_assignment(
                org_space_id=space_id,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=assistant_id,
            )
        )

        fetched = await repo.get_by_org_space_and_kind(
            org_space_id=space_id, kind=HelperKind.PROMPT_GUIDE
        )

        assert fetched is not None
        assert fetched.org_space_id == space_id
        assert fetched.kind == HelperKind.PROMPT_GUIDE
        assert fetched.assistant_id == assistant_id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_by_org_space_and_kind_returns_none_when_missing(
    db_container, admin_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.org_space_assistant_role_repo()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)

        assert (
            await repo.get_by_org_space_and_kind(
                org_space_id=space_id, kind=HelperKind.PROMPT_GUIDE
            )
            is None
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_for_org_space_returns_only_that_spaces_rows(
    db_container, admin_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.org_space_assistant_role_repo()
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
            factory.create_role_assignment(
                org_space_id=space_a,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=assistant_a,
            )
        )
        await repo.add(
            factory.create_role_assignment(
                org_space_id=space_b,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=assistant_b,
            )
        )

        rows_for_a = await repo.list_for_org_space(space_a)

        assert len(rows_for_a) == 1
        assert rows_for_a[0].org_space_id == space_a
        assert rows_for_a[0].assistant_id == assistant_a


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_persists_field_changes(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        repo = container.org_space_assistant_role_repo()
        factory = container.helper_assistants_factory()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        original_assistant_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )
        replacement_assistant_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )

        added = await repo.add(
            factory.create_role_assignment(
                org_space_id=space_id,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=original_assistant_id,
                is_enabled=True,
                is_visible_to_users=True,
                created_by_user_id=admin_user.id,
            )
        )

        # Reassignment is a plain attribute change now (no domain helper):
        # the repo.update round-trip is what this test pins.
        added.assistant_id = replacement_assistant_id
        added.set_enabled(False, actor_user_id=admin_user.id)
        added.set_visible_to_users(False, actor_user_id=admin_user.id)

        updated = await repo.update(added)

        assert updated.assistant_id == replacement_assistant_id
        assert updated.is_enabled is False
        assert updated.is_visible_to_users is False
        assert updated.updated_by_user_id == admin_user.id

        fetched = await repo.get_by_id(added.id)
        assert fetched is not None
        assert fetched.assistant_id == replacement_assistant_id
        assert fetched.is_enabled is False
        assert fetched.is_visible_to_users is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_removes_assignment(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        repo = container.org_space_assistant_role_repo()
        factory = container.helper_assistants_factory()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        assistant_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )

        added = await repo.add(
            factory.create_role_assignment(
                org_space_id=space_id,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=assistant_id,
            )
        )

        await repo.delete(added.id)

        assert await repo.get_by_id(added.id) is None
        remaining = await session.execute(
            sa.select(OrgSpaceAssistantRoles).where(
                OrgSpaceAssistantRoles.id == added.id
            )
        )
        assert remaining.scalar_one_or_none() is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_exists_active_for_assistant_true_when_assigned_false_after_delete(
    db_container, admin_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.org_space_assistant_role_repo()
        factory = container.helper_assistants_factory()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        helper_assistant_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )
        unrelated_assistant_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )

        # No row yet -> both assistants are "not active helpers".
        assert await repo.exists_active_for_assistant(helper_assistant_id) is False
        assert await repo.exists_active_for_assistant(unrelated_assistant_id) is False

        added = await repo.add(
            factory.create_role_assignment(
                org_space_id=space_id,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=helper_assistant_id,
            )
        )

        # Only the assigned assistant is active.
        assert await repo.exists_active_for_assistant(helper_assistant_id) is True
        assert await repo.exists_active_for_assistant(unrelated_assistant_id) is False

        # Deleting the assignment clears the active state.
        await repo.delete(added.id)
        assert await repo.exists_active_for_assistant(helper_assistant_id) is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_duplicate_kind_for_org_space_raises_integrity_error(
    db_container, admin_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.org_space_assistant_role_repo()
        factory = container.helper_assistants_factory()

        space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        first_assistant_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )
        second_assistant_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=space_id
        )

        await repo.add(
            factory.create_role_assignment(
                org_space_id=space_id,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=first_assistant_id,
            )
        )

        with pytest.raises(IntegrityError):
            await repo.add(
                factory.create_role_assignment(
                    org_space_id=space_id,
                    kind=HelperKind.PROMPT_GUIDE,
                    assistant_id=second_assistant_id,
                )
            )
