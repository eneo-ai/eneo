"""Critical test #2 — ``assistant_service.ask`` refuses to run a Help Assistant.

Pins PRD §6 "Why a separate service": even with all the routing in place,
the regular ``POST /assistants/{id}/sessions[/{session_id}]/`` endpoints
must reject any assistant that fills (or has ever filled) a Help Assistant
role. The guard short-circuits before any session row is created, so a
stale client, a misuse of the assistant API, or a future refactor cannot
quietly run a helper outside :class:`HelperRunService`.

Both router entry points (``ask_assistant`` and ``ask_followup``) flow
through ``service.ask`` — so guarding that method covers both paths. The
HTTP tests below exercise the wire end-to-end; the direct ``ask`` call in
:func:`test_guard_does_not_block_regular_assistant` proves the guard does
not over-block (a regression assertion against future false-positives).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.assistant_table import Assistants
from intric.database.tables.sessions_table import Sessions
from intric.help_assistants.domain.assignment_history_reason import (
    AssignmentHistoryReason,
)
from intric.help_assistants.domain.helper_kind import HelperKind
from intric.main.exceptions import UnauthorizedException


async def _get_org_space(
    session: sa.ext.asyncio.AsyncSession, *, tenant_id: UUID
) -> UUID:
    from intric.database.tables.spaces_table import Spaces

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
    name: str,
) -> UUID:
    assistant_id = uuid4()
    await session.execute(
        sa.insert(Assistants).values(
            id=assistant_id,
            name=name,
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
    name: str,
    user_id: UUID,
    assistant_id: UUID,
) -> UUID:
    session_id = uuid4()
    await session.execute(
        sa.insert(Sessions).values(
            id=session_id,
            name=name,
            user_id=user_id,
            assistant_id=assistant_id,
        )
    )
    return session_id


async def _assign_helper_role(
    container,
    *,
    org_space_id: UUID,
    assistant_id: UUID,
    actor_user_id: UUID,
) -> None:
    role_repo = container.org_space_assistant_role_repo()
    factory = container.helper_assistants_factory()
    await role_repo.add(
        factory.create_role_assignment(
            org_space_id=org_space_id,
            kind=HelperKind.PROMPT_GUIDE,
            assistant_id=assistant_id,
            created_by_user_id=actor_user_id,
        )
    )


async def _record_helper_run(
    container,
    *,
    tenant_id: UUID,
    org_space_id: UUID,
    helper_assistant_id: UUID,
    target_id: UUID,
    session_id: UUID,
    actor_user_id: UUID,
) -> None:
    repo = container.helper_run_repo()
    factory = container.helper_assistants_factory()
    await repo.add(
        factory.create_helper_run(
            tenant_id=tenant_id,
            org_space_id=org_space_id,
            kind=HelperKind.PROMPT_GUIDE,
            assistant_id=helper_assistant_id,
            target_type="assistant",
            target_id=target_id,
            session_id=session_id,
            actor_user_id=actor_user_id,
        )
    )


async def _record_history_entry(
    container,
    *,
    org_space_id: UUID,
    former_helper_id: UUID,
    actor_user_id: UUID,
    snapshot_name: str,
) -> None:
    history_repo = container.help_assistant_assignment_history_repo()
    factory = container.helper_assistants_factory()
    await history_repo.add(
        factory.create_assignment_history_entry(
            org_space_id=org_space_id,
            kind=HelperKind.PROMPT_GUIDE,
            assistant_id=former_helper_id,
            assistant_name_snapshot=snapshot_name,
            replaced_by_assistant_id=None,
            reason=AssignmentHistoryReason.UNASSIGNED,
            actor_user_id=actor_user_id,
        )
    )


async def _sessions_row_count(
    session: sa.ext.asyncio.AsyncSession, *, assistant_id: UUID
) -> int:
    count = await session.scalar(
        sa.select(sa.func.count(Sessions.id)).where(
            Sessions.assistant_id == assistant_id
        )
    )
    return int(count or 0)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ask_active_helper_returns_403_and_creates_no_session(
    db_container, admin_user, client, patch_auth_service_jwt
):
    """``POST /assistants/{helper_id}/sessions/`` is blocked by the guard,
    and no ``sessions`` row is written for the helper assistant."""

    helper_assistant_id: UUID

    async with db_container() as container:
        # Mirror production lazy-init so admin_user is a member of the org space.
        space_service = container.space_service()
        await space_service.get_or_create_tenant_space()

        session = container.session()
        org_space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        helper_assistant_id = await _insert_assistant(
            session,
            owner_user_id=admin_user.id,
            space_id=org_space_id,
            name="prompt-guide-helper",
        )
        await _assign_helper_role(
            container,
            org_space_id=org_space_id,
            assistant_id=helper_assistant_id,
            actor_user_id=admin_user.id,
        )
        await session.flush()

        auth_service = container.auth_service()
        token = auth_service.create_access_token_for_user(admin_user)

    response = await client.post(
        f"/api/v1/assistants/{helper_assistant_id}/sessions/",
        json={"question": "hi", "stream": False},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403, response.text
    body = response.json()
    # The "auth_layer" context tag lets ops distinguish guard hits from
    # other 403s in audit / monitoring (see exception_handlers.py).
    context = body.get("context") or {}
    assert context.get("auth_layer") == "helper_assistant_guard"

    async with db_container() as container:
        session = container.session()
        rows = await _sessions_row_count(session, assistant_id=helper_assistant_id)
        assert rows == 0, (
            f"Guard should short-circuit before any sessions row is "
            f"inserted; found {rows} for helper assistant"
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ask_followup_against_helper_returns_403(
    db_container, admin_user, client, patch_auth_service_jwt
):
    """``POST /assistants/{helper_id}/sessions/{session_id}/`` (follow-up
    turn) is blocked. The session belongs to a real helper run, so this
    asserts the guard fires before the session-lookup path too."""

    helper_assistant_id: UUID
    helper_session_id: UUID

    async with db_container() as container:
        space_service = container.space_service()
        await space_service.get_or_create_tenant_space()

        session = container.session()
        org_space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        helper_assistant_id = await _insert_assistant(
            session,
            owner_user_id=admin_user.id,
            space_id=org_space_id,
            name="prompt-guide-helper",
        )
        target_assistant_id = await _insert_assistant(
            session,
            owner_user_id=admin_user.id,
            space_id=org_space_id,
            name="target-assistant",
        )
        await _assign_helper_role(
            container,
            org_space_id=org_space_id,
            assistant_id=helper_assistant_id,
            actor_user_id=admin_user.id,
        )

        helper_session_id = await _insert_session(
            session,
            name="helper-session",
            user_id=admin_user.id,
            assistant_id=helper_assistant_id,
        )
        await _record_helper_run(
            container,
            tenant_id=admin_user.tenant_id,
            org_space_id=org_space_id,
            helper_assistant_id=helper_assistant_id,
            target_id=target_assistant_id,
            session_id=helper_session_id,
            actor_user_id=admin_user.id,
        )
        await session.flush()

        before = await _sessions_row_count(session, assistant_id=helper_assistant_id)

        auth_service = container.auth_service()
        token = auth_service.create_access_token_for_user(admin_user)

    response = await client.post(
        f"/api/v1/assistants/{helper_assistant_id}/sessions/{helper_session_id}/",
        json={"question": "more please", "stream": False},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403, response.text

    async with db_container() as container:
        session = container.session()
        after = await _sessions_row_count(session, assistant_id=helper_assistant_id)
        # Only the helper-run-tagged session exists; no new row from the
        # blocked follow-up request.
        assert after == before == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ask_former_helper_returns_403_and_creates_no_session(
    db_container, admin_user, client, patch_auth_service_jwt
):
    """A former helper — one row in ``help_assistant_assignment_history`` and
    no active row in ``org_space_assistant_roles`` — is still blocked."""

    former_helper_id: UUID

    async with db_container() as container:
        space_service = container.space_service()
        await space_service.get_or_create_tenant_space()

        session = container.session()
        org_space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        former_helper_id = await _insert_assistant(
            session,
            owner_user_id=admin_user.id,
            space_id=org_space_id,
            name="former-helper",
        )
        await _record_history_entry(
            container,
            org_space_id=org_space_id,
            former_helper_id=former_helper_id,
            actor_user_id=admin_user.id,
            snapshot_name="former-helper",
        )
        await session.flush()

        auth_service = container.auth_service()
        token = auth_service.create_access_token_for_user(admin_user)

    response = await client.post(
        f"/api/v1/assistants/{former_helper_id}/sessions/",
        json={"question": "hi", "stream": False},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403, response.text
    context = response.json().get("context") or {}
    assert context.get("helper_state") == "former", (
        "Guard must distinguish former from active helpers in the audit "
        "trail so ops can tell apart 'still assigned' vs 'history-only'."
    )

    async with db_container() as container:
        session = container.session()
        rows = await _sessions_row_count(session, assistant_id=former_helper_id)
        assert rows == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_guard_does_not_block_regular_assistant(db_container, admin_user):
    """Regression: a normal assistant — never assigned to a helper role and
    never in history — passes the guard. Pairs with the 403 tests above so
    they remain a real signal, not vacuous truth."""

    async with db_container() as container:
        space_service = container.space_service()
        await space_service.get_or_create_tenant_space()

        session = container.session()
        org_space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        regular_assistant_id = await _insert_assistant(
            session,
            owner_user_id=admin_user.id,
            space_id=org_space_id,
            name="regular-assistant",
        )
        # Also assign an unrelated helper so the role table is non-empty;
        # this guarantees the guard does a real assistant_id comparison
        # rather than answering "False" via empty-table short-circuit.
        unrelated_helper_id = await _insert_assistant(
            session,
            owner_user_id=admin_user.id,
            space_id=org_space_id,
            name="unrelated-helper",
        )
        await _assign_helper_role(
            container,
            org_space_id=org_space_id,
            assistant_id=unrelated_helper_id,
            actor_user_id=admin_user.id,
        )
        await session.flush()

        from intric.help_assistants.application.ask_guard import (
            assert_not_helper_assistant,
        )

        role_repo = container.org_space_assistant_role_repo()
        history_repo = container.help_assistant_assignment_history_repo()

        # No raise -> the guard accepts a regular assistant.
        await assert_not_helper_assistant(
            assistant_id=regular_assistant_id,
            role_repo=role_repo,
            history_repo=history_repo,
        )

        # Sanity counter-check: the same guard does reject the helper. If
        # this assertion ever flips, the previous "no raise" check is
        # meaningless (it might just be that the guard is broken in both
        # directions). Pinning both branches in one test keeps the pair
        # honest.
        with pytest.raises(UnauthorizedException) as excinfo:
            await assert_not_helper_assistant(
                assistant_id=unrelated_helper_id,
                role_repo=role_repo,
                history_repo=history_repo,
            )
        assert excinfo.value.code == "forbidden_action"
        assert excinfo.value.context is not None
        assert excinfo.value.context.get("auth_layer") == ("helper_assistant_guard")
