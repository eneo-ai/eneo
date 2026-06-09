"""HTTP integration tests for ``GET /api/v1/help-assistants/availability``
(step 023).

The endpoint is the pre-flight check the frontend hits before rendering
the prompt-guide toolbar button. Each test pins one branch of the
``disabled_reason`` ladder so a future refactor cannot silently widen the
"available" set:

  * ``no_edit_rights`` — both the "no read access" and the "unknown
    target id" paths collapse here so the endpoint cannot be used as an
    assistant-existence probe.
  * ``no_assignment`` — no row in ``org_space_assistant_roles`` for the
    requested ``kind``.
  * ``role_disabled`` — admin turned ``is_enabled`` off.
  * ``role_not_visible`` — admin turned ``is_visible_to_users`` off.
  * ``no_completion_model`` — helper assistant exists but has no
    completion model (also covers the ``can_access=False`` variant via
    the same response).
  * Happy path — every gate passes, ``available=True``.

One shape assertion covers the "do not leak the helper id" invariant
(PRD §5, §10): the JSON payload must never contain an ``assistant_id``
key. Verified across every branch (happy + each disabled_reason) since
the leak risk is independent of which branch the endpoint exits through.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.ai_models_table import CompletionModels
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.spaces_table import Spaces
from intric.help_assistants.domain.helper_kind import HelperKind
from intric.main.models import ModelId
from intric.roles.permissions import Permission
from intric.roles.role import RoleCreate
from intric.users.user import UserAdd, UserState

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
    completion_model_id: UUID | None,
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
    is_enabled: bool = True,
    is_visible_to_users: bool = True,
) -> None:
    role_repo = container.org_space_assistant_role_repo()
    factory = container.helper_assistants_factory()
    role = factory.create_role_assignment(
        org_space_id=org_space_id,
        kind=HelperKind.PROMPT_GUIDE,
        assistant_id=assistant_id,
        is_enabled=is_enabled,
        is_visible_to_users=is_visible_to_users,
        created_by_user_id=actor_user_id,
    )
    await role_repo.add(role)


async def _seed_helper_and_target(
    container,
    admin_user,
    *,
    role_enabled: bool = True,
    role_visible_to_users: bool = True,
    helper_has_completion_model: bool = True,
    assign_role: bool = True,
) -> tuple[UUID, UUID]:
    """Insert helper + target assistants and (optionally) the role assignment.

    Returns ``(helper_assistant_id, target_assistant_id)``.
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
        completion_model_id=(
            completion_model_id if helper_has_completion_model else None
        ),
        name="prompt-guide-helper",
    )
    target_id = await _insert_assistant(
        session,
        owner_user_id=admin_user.id,
        space_id=org_space_id,
        completion_model_id=completion_model_id,
        name="target-assistant",
    )
    if assign_role:
        await _assign_helper_role(
            container,
            org_space_id=org_space_id,
            assistant_id=helper_id,
            actor_user_id=admin_user.id,
            is_enabled=role_enabled,
            is_visible_to_users=role_visible_to_users,
        )
    await session.flush()
    return helper_id, target_id


async def _create_member_target(db_container, member_user) -> UUID:
    """A target assistant a non-admin member owns and can edit (personal space).

    Mirrors the real end-user flow (PRD §11): the user creates an assistant in
    their own personal space, where ``space_actor._get_role`` resolves them to
    ``OWNER``. Note the user still needs the tenant-level ``assistants``
    permission — ``can_perform_action`` gates every assistant action on it on
    top of the space role (see the ``member_*`` fixtures). ``_seed_helper_and_target``
    puts its target in the *admin-owned* org-space, so a non-admin fails the
    target-edit gate (``no_edit_rights``) before the helper read is ever
    reached — which is exactly why the org-space *helper* read 403 (step 099)
    escaped the suite.
    """
    async with db_container(user=member_user) as container:
        space_service = container.space_service()
        personal_space = await space_service.create_personal_space()
        session = container.session()
        completion_model_id = await _get_default_completion_model_id(
            session, tenant_id=member_user.tenant_id
        )
        target_id = await _insert_assistant(
            session,
            owner_user_id=member_user.id,
            space_id=personal_space.id,
            completion_model_id=completion_model_id,
            name="member-personal-target",
        )
        await session.flush()
    return target_id


# ---------------------------------------------------------------------------
# Auth fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(admin_user)


@pytest.fixture
async def non_admin_role(db_container, admin_user):
    async with db_container() as container:
        role_repo = container.role_repo()
        return await role_repo.create_role(
            RoleCreate(
                name=f"non-admin-{uuid4().hex[:8]}",
                permissions=[],
                tenant_id=admin_user.tenant_id,
            )
        )


@pytest.fixture
async def non_admin_user(db_container, admin_user, non_admin_role):
    async with db_container() as container:
        user_repo = container.user_repo()
        return await user_repo.add(
            UserAdd(
                email=f"non-admin-{uuid4().hex[:8]}@example.com",
                username=f"non_admin_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=non_admin_role.id)],
            )
        )


@pytest.fixture
async def non_admin_token(db_container, patch_auth_service_jwt, non_admin_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(non_admin_user)


@pytest.fixture
async def member_role(db_container, admin_user):
    """A non-admin "Member" role: the ordinary ``assistants`` capability, no
    ``admin``. Matches the repro's Member role — enough to create/edit one's
    own assistants, but not an org-space member.
    """
    async with db_container() as container:
        role_repo = container.role_repo()
        return await role_repo.create_role(
            RoleCreate(
                name=f"member-{uuid4().hex[:8]}",
                permissions=[Permission.ASSISTANTS],
                tenant_id=admin_user.tenant_id,
            )
        )


@pytest.fixture
async def member_user(db_container, admin_user, member_role):
    async with db_container() as container:
        user_repo = container.user_repo()
        return await user_repo.add(
            UserAdd(
                email=f"member-{uuid4().hex[:8]}@example.com",
                username=f"member_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=member_role.id)],
            )
        )


@pytest.fixture
async def member_token(db_container, patch_auth_service_jwt, member_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(member_user)


# ---------------------------------------------------------------------------
# Helpers — request + shape assertions reused across branches
# ---------------------------------------------------------------------------


async def _get_availability(
    client,
    *,
    token: str,
    kind: HelperKind,
    target_id: UUID,
):
    return await client.get(
        "/api/v1/help-assistants/availability",
        params={"kind": kind.value, "target_id": str(target_id)},
        headers={"Authorization": f"Bearer {token}"},
    )


def _assert_response_shape(body: dict) -> None:
    """Pin the wire contract: exactly two keys, no helper id leak.

    PRD §5/§10 require this endpoint to never expose the helper
    assistant id (the frontend already does not need it — resolution is
    server-side). A field-level assertion guards against any future
    response model that accidentally serializes it.
    """
    assert set(body.keys()) == {"available", "disabled_reason"}, body
    assert "assistant_id" not in body
    assert "helper_assistant_id" not in body


# ---------------------------------------------------------------------------
# Tests — each disabled_reason branch + happy path
# ---------------------------------------------------------------------------


async def test_no_edit_rights_when_caller_cannot_read_target(
    client,
    db_container,
    admin_user,
    non_admin_user,  # noqa: ARG001 — non_admin_token depends on it
    non_admin_token,
):
    """Caller is not an org-space member → cannot read target → no_edit_rights.

    The non-admin user has no roles and no org-space membership, so
    ``assistant_service.get_assistant`` raises ``UnauthorizedException``.
    The router collapses that into ``no_edit_rights`` so this endpoint
    cannot double as an assistant-existence probe.
    """
    async with db_container() as container:
        _, target_id = await _seed_helper_and_target(container, admin_user)

    resp = await _get_availability(
        client,
        token=non_admin_token,
        kind=HelperKind.PROMPT_GUIDE,
        target_id=target_id,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"available": False, "disabled_reason": "no_edit_rights"}
    _assert_response_shape(body)


async def test_no_edit_rights_when_target_does_not_exist(
    client,
    db_container,
    admin_user,
    admin_token,
):
    """Unknown target id → no_edit_rights (not 404).

    A 404 would let an unauthenticated probe enumerate assistants by id.
    Collapsing "unknown" into "no edit rights" hides existence behind the
    same response shape as a real permission failure.
    """
    async with db_container() as container:
        # Seed an org-space + assignment so the only failing gate is the
        # target lookup itself, not anything downstream.
        await _seed_helper_and_target(container, admin_user)

    resp = await _get_availability(
        client,
        token=admin_token,
        kind=HelperKind.PROMPT_GUIDE,
        target_id=uuid4(),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"available": False, "disabled_reason": "no_edit_rights"}
    _assert_response_shape(body)


async def test_no_assignment_when_role_unassigned(
    client,
    db_container,
    admin_user,
    admin_token,
):
    """Target editable but no role row exists → no_assignment."""
    async with db_container() as container:
        _, target_id = await _seed_helper_and_target(
            container, admin_user, assign_role=False
        )

    resp = await _get_availability(
        client,
        token=admin_token,
        kind=HelperKind.PROMPT_GUIDE,
        target_id=target_id,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"available": False, "disabled_reason": "no_assignment"}
    _assert_response_shape(body)


async def test_role_disabled_branch(
    client,
    db_container,
    admin_user,
    admin_token,
):
    """``is_enabled=False`` → role_disabled."""
    async with db_container() as container:
        _, target_id = await _seed_helper_and_target(
            container, admin_user, role_enabled=False
        )

    resp = await _get_availability(
        client,
        token=admin_token,
        kind=HelperKind.PROMPT_GUIDE,
        target_id=target_id,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"available": False, "disabled_reason": "role_disabled"}
    _assert_response_shape(body)


async def test_role_not_visible_branch(
    client,
    db_container,
    admin_user,
    admin_token,
):
    """``is_visible_to_users=False`` → role_not_visible.

    Distinct from ``role_disabled``: ``is_enabled`` gates whether helpers
    run at all, ``is_visible_to_users`` hides them from the toolbar even
    when they still work. Admins can flip either independently.
    """
    async with db_container() as container:
        _, target_id = await _seed_helper_and_target(
            container, admin_user, role_visible_to_users=False
        )

    resp = await _get_availability(
        client,
        token=admin_token,
        kind=HelperKind.PROMPT_GUIDE,
        target_id=target_id,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"available": False, "disabled_reason": "role_not_visible"}
    _assert_response_shape(body)


async def test_no_completion_model_branch(
    client,
    db_container,
    admin_user,
    admin_token,
):
    """Helper assistant exists but has ``completion_model_id=NULL``.

    Pins the safety net for the ``install_helper`` warning path in
    ``OrgSpaceAssistantRoleService.install_helper``: when no tenant
    model is eligible, install leaves the helper with NULL — the
    availability endpoint must report ``no_completion_model`` so the
    button stays hidden until an admin picks one.
    """
    async with db_container() as container:
        _, target_id = await _seed_helper_and_target(
            container, admin_user, helper_has_completion_model=False
        )

    resp = await _get_availability(
        client,
        token=admin_token,
        kind=HelperKind.PROMPT_GUIDE,
        target_id=target_id,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "available": False,
        "disabled_reason": "no_completion_model",
    }
    _assert_response_shape(body)


async def test_happy_path(
    client,
    db_container,
    admin_user,
    admin_token,
):
    """Every gate passes → ``available=True`` with no disabled_reason."""
    async with db_container() as container:
        _, target_id = await _seed_helper_and_target(container, admin_user)

    resp = await _get_availability(
        client,
        token=admin_token,
        kind=HelperKind.PROMPT_GUIDE,
        target_id=target_id,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"available": True, "disabled_reason": None}
    _assert_response_shape(body)


# ---------------------------------------------------------------------------
# Tests — non-admin end users (step 099 regression)
# ---------------------------------------------------------------------------


async def test_non_admin_happy_path_on_own_target(
    client,
    db_container,
    admin_user,
    member_user,
    member_token,
):
    """Non-admin who owns + can edit their own target → ``available=True``.

    Step 099 regression. The helper assistant lives in the org-space, of which
    non-admins are never members, so the pre-flight's *helper* read used to
    403 through the permission-enforcing ``get_assistant`` — even though the
    caller holds EDIT on their own target and the role is enabled + visible.
    PRD §5/§6/§10 make the Prompt Guide usable by any such user; the privileged
    helper load now lets the pre-flight reach ``available=True``.
    """
    async with db_container() as container:
        # Seeds the org-space helper + an enabled, visible active role.
        await _seed_helper_and_target(container, admin_user)
    target_id = await _create_member_target(db_container, member_user)

    resp = await _get_availability(
        client,
        token=member_token,
        kind=HelperKind.PROMPT_GUIDE,
        target_id=target_id,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"available": True, "disabled_reason": None}
    _assert_response_shape(body)


async def test_non_admin_role_not_visible_stays_hidden(
    client,
    db_container,
    admin_user,
    member_user,
    member_token,
):
    """``is_visible_to_users=False`` → ``role_not_visible`` for a non-admin.

    Visibility is the end-user gate, checked *before* the helper read, so the
    fix must not weaken it: an editable target plus a hidden role still yields
    ``role_not_visible`` (button stays hidden) — never ``available=True`` and
    never a leaked org-space 403.
    """
    async with db_container() as container:
        await _seed_helper_and_target(
            container, admin_user, role_visible_to_users=False
        )
    target_id = await _create_member_target(db_container, member_user)

    resp = await _get_availability(
        client,
        token=member_token,
        kind=HelperKind.PROMPT_GUIDE,
        target_id=target_id,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"available": False, "disabled_reason": "role_not_visible"}
    _assert_response_shape(body)
