"""Scope contract for ``AssistantService.get_help_assistant`` (step 099 fix).

The fix lets non-admin end users use the Prompt Guide: the availability
pre-flight and ``HelperRunService`` load the org-space *helper* assistant via a
privileged read (``get_help_assistant``) that skips the space-actor read gate —
because the helper lives in the org-space, of which end users are not members,
yet PRD §5/§6/§10 make the Prompt Guide usable by any user with EDIT on the
*target*.

This file pins the bypass's **scope** (step 099 test #4 — the over-broad
exposure guard): only the assistant designated by an *active* (or *former*)
help-assistant role is readable this way. An arbitrary org-space assistant —
for example a future published "Intranet" assistant — must NOT be, or the
bypass would expose every org-space assistant to every user.

``get_help_assistant`` does not consult the calling user (there is no actor
check by design), so the scope it enforces holds for every caller, admin or
not. The non-admin end-to-end coverage of the same fix lives in
``test_availability.py`` and ``test_run_router.py``.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.spaces_table import Spaces
from eneo.help_assistants.domain.assignment_history_reason import (
    AssignmentHistoryReason,
)
from eneo.help_assistants.domain.helper_kind import HelperKind
from eneo.main.exceptions import NotFoundException

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# DB / fixture helpers — mirror neighbouring test files
# ---------------------------------------------------------------------------


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


async def _get_default_completion_model_id(
    session: sa.ext.asyncio.AsyncSession, *, tenant_id: UUID
) -> UUID:
    row = await session.scalar(
        sa.select(CompletionModels.id).where(
            CompletionModels.tenant_id == tenant_id,
            CompletionModels.is_enabled.is_(True),
        )
    )
    assert row is not None, "Expected seed_default_models to provide a model"
    return row


async def _insert_assistant(
    session: sa.ext.asyncio.AsyncSession,
    *,
    owner_user_id: UUID,
    space_id: UUID,
    completion_model_id: UUID,
    name: str,
) -> UUID:
    assistant_id = uuid4()
    await session.execute(
        sa.insert(Assistants).values(
            id=assistant_id,
            name=name,
            user_id=owner_user_id,
            space_id=space_id,
            completion_model_id=completion_model_id,
            logging_enabled=False,
            is_default=False,
            published=False,
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
    role_repo = container.org_space_assistant_role_repo()
    factory = container.helper_assistants_factory()
    role = factory.create_role_assignment(
        org_space_id=org_space_id,
        kind=HelperKind.PROMPT_GUIDE,
        assistant_id=assistant_id,
        is_enabled=True,
        is_visible_to_users=True,
        created_by_user_id=actor_user_id,
    )
    await role_repo.add(role)


async def _insert_history_row(
    container,
    *,
    org_space_id: UUID,
    assistant_id: UUID,
    actor_user_id: UUID,
) -> None:
    repo = container.help_assistant_assignment_history_repo()
    factory = container.helper_assistants_factory()
    entry = factory.create_assignment_history_entry(
        org_space_id=org_space_id,
        kind=HelperKind.PROMPT_GUIDE,
        assistant_id=assistant_id,
        assistant_name_snapshot="former-prompt-guide",
        replaced_by_assistant_id=None,
        reason=AssignmentHistoryReason.REASSIGNED,
        actor_user_id=actor_user_id,
    )
    await repo.add(entry)


async def _seed_org_space_assistants(container, admin_user) -> tuple[UUID, UUID, UUID]:
    """Seed the org-space with one active helper and one ordinary assistant.

    Returns ``(org_space_id, active_helper_id, plain_assistant_id)``:

      * ``active_helper_id`` — has an enabled + visible active role.
      * ``plain_assistant_id`` — an ordinary org-space assistant with neither
        an active role nor an assignment-history row (the stand-in for "any
        other org-space assistant").
    """
    space_service = container.space_service()
    await space_service.get_or_create_tenant_space()

    session = container.session()
    org_space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
    completion_model_id = await _get_default_completion_model_id(
        session, tenant_id=admin_user.tenant_id
    )
    helper_id = await _insert_assistant(
        session,
        owner_user_id=admin_user.id,
        space_id=org_space_id,
        completion_model_id=completion_model_id,
        name="prompt-guide-helper",
    )
    plain_id = await _insert_assistant(
        session,
        owner_user_id=admin_user.id,
        space_id=org_space_id,
        completion_model_id=completion_model_id,
        name="ordinary-org-space-assistant",
    )
    await _assign_helper_role(
        container,
        org_space_id=org_space_id,
        assistant_id=helper_id,
        actor_user_id=admin_user.id,
    )
    await session.flush()
    return org_space_id, helper_id, plain_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_returns_designated_active_helper(db_container, admin_user):
    """The assistant an active role points at is readable via the bypass."""
    async with db_container() as container:
        _, helper_id, _ = await _seed_org_space_assistants(container, admin_user)

        helper = await container.assistant_service().get_help_assistant(helper_id)

        assert helper.id == helper_id


async def test_refuses_non_helper_org_space_assistant(db_container, admin_user):
    """Over-broad-exposure guard (step 099 test #4).

    A plain org-space assistant — no active role, no assignment-history row —
    is refused with ``NotFoundException``. This is what keeps the privileged
    read from becoming a generic "read any org-space assistant" bypass: only
    the assistant the role designates is reachable, never its neighbours.
    """
    async with db_container() as container:
        _, _, plain_id = await _seed_org_space_assistants(container, admin_user)

        with pytest.raises(NotFoundException):
            await container.assistant_service().get_help_assistant(plain_id)


async def test_refuses_unknown_assistant_id(db_container, admin_user):
    """An id that is not an assistant at all is refused, not a 500."""
    async with db_container() as container:
        await _seed_org_space_assistants(container, admin_user)

        with pytest.raises(NotFoundException):
            await container.assistant_service().get_help_assistant(uuid4())


async def test_returns_former_helper(db_container, admin_user):
    """A *former* helper (history row, no active role) is still readable.

    ``HelperRunService.continue_turn`` loads ``run.assistant_id``, which may be
    a helper an admin reassigned away mid-conversation — now a former helper
    with an assignment-history row but no active role. The privileged read must
    still surface it (the history branch of the guard), or follow-up turns
    would break after a reassign.
    """
    async with db_container() as container:
        org_space_id, _, former_id = await _seed_org_space_assistants(
            container, admin_user
        )
        await _insert_history_row(
            container,
            org_space_id=org_space_id,
            assistant_id=former_id,
            actor_user_id=admin_user.id,
        )

        former = await container.assistant_service().get_help_assistant(former_id)

        assert former.id == former_id
