"""Integration tests for ``AssistantRepository._exclude_helper_assistants``.

Pins the unified filter that hides helper assistants from every list-returning
method in ``assistant_repo`` (PRD §4):

  - Active helpers (rows in ``org_space_assistant_roles``) are excluded.
  - Former helpers (rows in ``help_assistant_assignment_history``) are excluded.
  - ``published = true`` does NOT override the exclusion — helper-ness is
    independent of regular publish visibility.
  - Non-helper assistants — both personal and published — pass through
    untouched.

Mirrors the integration patterns established in
``test_org_space_assistant_role_repo.py`` and
``test_help_assistant_assignment_history_repo.py``: real Postgres via
testcontainers, ``add_tenant_user`` provides one org-space per tenant, and a
child space is used when a second space is needed (the partial unique index
``idx_unique_org_space_per_tenant`` forbids inserting a second org-space).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.spaces_table import Spaces
from eneo.help_assistants.domain.assignment_history_reason import (
    AssignmentHistoryReason,
)
from eneo.help_assistants.domain.helper_kind import HelperKind


async def _get_org_space(
    session: sa.ext.asyncio.AsyncSession, *, tenant_id: UUID
) -> UUID:
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
    published: bool = False,
    name: str | None = None,
) -> UUID:
    assistant_id = uuid4()
    await session.execute(
        sa.insert(Assistants).values(
            id=assistant_id,
            name=name or f"assistant-{assistant_id.hex[:8]}",
            user_id=owner_user_id,
            space_id=space_id,
            completion_model_id=None,
            logging_enabled=False,
            is_default=False,
            published=published,
        )
    )
    return assistant_id


async def _assign_helper_role(
    container,
    *,
    org_space_id: UUID,
    assistant_id: UUID,
    actor_user_id: UUID,
) -> None:
    repo = container.org_space_assistant_role_repo()
    factory = container.helper_assistants_factory()
    await repo.add(
        factory.create_role_assignment(
            org_space_id=org_space_id,
            kind=HelperKind.PROMPT_GUIDE,
            assistant_id=assistant_id,
            created_by_user_id=actor_user_id,
        )
    )


async def _record_helper_history(
    container,
    *,
    org_space_id: UUID,
    assistant_id: UUID,
    actor_user_id: UUID,
    name_snapshot: str = "legacy",
) -> None:
    repo = container.help_assistant_assignment_history_repo()
    factory = container.helper_assistants_factory()
    await repo.add(
        factory.create_assignment_history_entry(
            org_space_id=org_space_id,
            kind=HelperKind.PROMPT_GUIDE,
            assistant_id=assistant_id,
            assistant_name_snapshot=name_snapshot,
            replaced_by_assistant_id=None,
            reason=AssignmentHistoryReason.RESET_TO_DEFAULT,
            actor_user_id=actor_user_id,
        )
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_for_user_excludes_active_helper(db_container, admin_user):
    async with db_container() as container:
        session = container.session()

        org_space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        helper_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=org_space_id
        )
        non_helper_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=org_space_id
        )

        await _assign_helper_role(
            container,
            org_space_id=org_space_id,
            assistant_id=helper_id,
            actor_user_id=admin_user.id,
        )

        await session.flush()

        assistants = await container.assistant_repo().get_for_user(admin_user.id)
        returned_ids = {a.id for a in assistants}

        assert helper_id not in returned_ids
        assert non_helper_id in returned_ids


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_for_tenant_excludes_active_helper(db_container, admin_user):
    async with db_container() as container:
        session = container.session()

        org_space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        helper_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=org_space_id
        )
        non_helper_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=org_space_id
        )

        await _assign_helper_role(
            container,
            org_space_id=org_space_id,
            assistant_id=helper_id,
            actor_user_id=admin_user.id,
        )

        await session.flush()

        assistants = await container.assistant_repo().get_for_tenant(
            admin_user.tenant_id
        )
        returned_ids = {a.id for a in assistants}

        assert helper_id not in returned_ids
        assert non_helper_id in returned_ids


@pytest.mark.asyncio
@pytest.mark.integration
async def test_excludes_former_helper_with_history_only(db_container, admin_user):
    """Former helper: history row exists, no active role.

    Assistants that were once helpers must stay out of regular lists even
    after their role assignment is gone. Verified against both list methods
    so that neither code path treats history-only rows as "regular again".
    """
    async with db_container() as container:
        session = container.session()

        org_space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        former_helper_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=org_space_id
        )
        non_helper_id = await _insert_assistant(
            session, owner_user_id=admin_user.id, space_id=org_space_id
        )

        await _record_helper_history(
            container,
            org_space_id=org_space_id,
            assistant_id=former_helper_id,
            actor_user_id=admin_user.id,
        )

        await session.flush()

        repo = container.assistant_repo()
        for_user_ids = {a.id for a in await repo.get_for_user(admin_user.id)}
        for_tenant_ids = {a.id for a in await repo.get_for_tenant(admin_user.tenant_id)}

        assert former_helper_id not in for_user_ids
        assert former_helper_id not in for_tenant_ids
        assert non_helper_id in for_user_ids
        assert non_helper_id in for_tenant_ids


@pytest.mark.asyncio
@pytest.mark.integration
async def test_returns_published_non_helper(db_container, admin_user):
    """A published assistant that is not a helper must still appear.

    Baseline for the regression guard below: confirms ``published=true`` on
    its own is not what removes an assistant from lists.
    """
    async with db_container() as container:
        session = container.session()

        org_space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        published_id = await _insert_assistant(
            session,
            owner_user_id=admin_user.id,
            space_id=org_space_id,
            published=True,
            name="published-non-helper",
        )

        await session.flush()

        repo = container.assistant_repo()
        for_user_ids = {a.id for a in await repo.get_for_user(admin_user.id)}
        for_tenant_ids = {a.id for a in await repo.get_for_tenant(admin_user.tenant_id)}

        assert published_id in for_user_ids
        assert published_id in for_tenant_ids


@pytest.mark.asyncio
@pytest.mark.integration
async def test_returns_regular_personal_assistant(db_container, admin_user):
    """Plain personal (unpublished, non-helper) assistant passes through."""
    async with db_container() as container:
        session = container.session()

        org_space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        personal_id = await _insert_assistant(
            session,
            owner_user_id=admin_user.id,
            space_id=org_space_id,
            published=False,
            name="personal-non-helper",
        )

        await session.flush()

        repo = container.assistant_repo()
        for_user_ids = {a.id for a in await repo.get_for_user(admin_user.id)}
        for_tenant_ids = {a.id for a in await repo.get_for_tenant(admin_user.tenant_id)}

        assert personal_id in for_user_ids
        assert personal_id in for_tenant_ids


@pytest.mark.asyncio
@pytest.mark.integration
async def test_published_does_not_override_helper_exclusion(db_container, admin_user):
    """Regression guard for PRD §4: ``published=true`` does NOT override.

    Helper-ness is independent of publish visibility. An assistant that is
    both published and currently filling a helper role must still be hidden
    from every list-returning method.
    """
    async with db_container() as container:
        session = container.session()

        org_space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        published_helper_id = await _insert_assistant(
            session,
            owner_user_id=admin_user.id,
            space_id=org_space_id,
            published=True,
            name="published-helper",
        )

        await _assign_helper_role(
            container,
            org_space_id=org_space_id,
            assistant_id=published_helper_id,
            actor_user_id=admin_user.id,
        )

        await session.flush()

        repo = container.assistant_repo()
        for_user_ids = {a.id for a in await repo.get_for_user(admin_user.id)}
        for_tenant_ids = {a.id for a in await repo.get_for_tenant(admin_user.tenant_id)}

        assert published_helper_id not in for_user_ids
        assert published_helper_id not in for_tenant_ids
