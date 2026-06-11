"""HTTP integration tests for the help-assistant admin router (step 021).

Pins the wiring contract for ``/api/v1/admin/help-assistants``:

  * Every mutation is rejected with 403 for a non-admin caller — the
    ``OrgSpaceAssistantRoleService`` enforces ``Permission.ADMIN`` at the
    service layer and the FastAPI exception handler maps
    ``UnauthorizedException`` → 403.
  * ``GET /roles/{kind}/`` returns ``null`` when no role is assigned.

The service-layer unit tests already cover the audit metadata shape and
the install/uninstall side-effects in detail; the tests here verify the
HTTP wrapper, not the underlying behavior.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.assistant_table import Assistants
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.users_table import Users
from intric.help_assistants.domain.helper_kind import HelperKind
from intric.main.models import ModelId
from intric.roles.role import RoleCreate
from intric.users.user import UserAdd, UserState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Helpers — mirror the seed-migration shape so each test gets the system
# user + assistant prerequisites the router endpoints expect.
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


async def _insert_system_user(
    session: sa.ext.asyncio.AsyncSession, *, tenant_id: UUID
) -> UUID:
    """Insert a per-tenant system user mirroring the seed migration.

    Uses ``@example.com`` instead of the production ``@eneo.local`` domain
    because the test-fixture path may surface the row through Pydantic's
    email validator, which rejects ``.local``. See the precedent set in
    ``tests/integration/repositories/test_user_repo_system_user_guards.py``.
    """
    user_id = uuid4()
    suffix = user_id.hex[:8]
    await session.execute(
        sa.insert(Users).values(
            id=user_id,
            email=f"system+{suffix}@example.com",
            username=f"system+{suffix}",
            email_verified=False,
            salt=None,
            password=None,
            is_active=False,
            state=UserState.INACTIVE.value,
            used_tokens=0,
            tenant_id=tenant_id,
            quota_limit=None,
            is_system_user=True,
        )
    )
    return user_id


async def _insert_assistant(
    session: sa.ext.asyncio.AsyncSession,
    *,
    owner_user_id: UUID,
    space_id: UUID,
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
            published=False,
        )
    )
    return assistant_id


async def _seed_assistant_in_org_space(
    container, admin_user, *, name: str | None = None
) -> UUID:
    """Insert system user + an assistant in the tenant's org-space."""
    session = container.session()
    org_space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
    await _insert_system_user(session, tenant_id=admin_user.tenant_id)
    assistant_id = await _insert_assistant(
        session, owner_user_id=admin_user.id, space_id=org_space_id, name=name
    )
    await session.flush()
    return assistant_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(admin_user)


@pytest.fixture
async def non_admin_role(db_container, admin_user):
    """Role with no permissions — baseline tenant user."""
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


MUTATION_REQUESTS = [
    (
        "toggle_enabled",
        lambda kind, _aid: (
            "PATCH",
            f"/api/v1/admin/help-assistants/roles/{kind}/enabled",
            {"value": True},
        ),
    ),
    (
        "toggle_visible",
        lambda kind, _aid: (
            "PATCH",
            f"/api/v1/admin/help-assistants/roles/{kind}/visible",
            {"value": True},
        ),
    ),
    (
        "install",
        lambda kind, _aid: (
            "POST",
            f"/api/v1/admin/help-assistants/roles/{kind}/",
            None,
        ),
    ),
    (
        "uninstall",
        lambda kind, _aid: (
            "DELETE",
            f"/api/v1/admin/help-assistants/roles/{kind}/",
            None,
        ),
    ),
]


@pytest.mark.parametrize(
    "name,build_request",
    MUTATION_REQUESTS,
    ids=[case[0] for case in MUTATION_REQUESTS],
)
async def test_non_admin_blocked_on_every_mutation(
    client,
    db_container,
    admin_user,
    non_admin_token,
    name,
    build_request,
):
    """Every mutation surface requires ``Permission.ADMIN``.

    The service-layer ``validate_permission`` raises
    ``UnauthorizedException`` → 403. The exception handler turns the
    ``UnauthorizedException`` from auth/key checks into the same code.
    """
    async with db_container() as container:
        assistant_id = await _seed_assistant_in_org_space(container, admin_user)

    method, path, body = build_request(HelperKind.PROMPT_GUIDE.value, assistant_id)
    headers = {"Authorization": f"Bearer {non_admin_token}"}

    if method == "POST":
        resp = await client.post(path, headers=headers, json=body)
    elif method == "PATCH":
        resp = await client.patch(path, headers=headers, json=body)
    elif method == "DELETE":
        resp = await client.delete(path, headers=headers)
    else:
        raise AssertionError(f"unexpected method {method}")

    assert resp.status_code == 403, f"{name}: {resp.status_code} {resp.text}"


async def test_get_active_returns_null_when_unassigned(
    client,
    admin_user,  # noqa: ARG001 — tenant ownership comes via the admin_token JWT
    admin_token,
):
    """Calling ``GET /roles/{kind}/`` with no active assignment returns ``null``.

    The autouse ``cleanup_database`` fixture truncated
    ``org_space_assistant_roles`` and re-seeded only tenant + user via
    ``add_tenant_user`` — the alembic seed migration's row for this kind
    is gone, so the endpoint exercises the "no active assignment" branch.
    """
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.get(
        f"/api/v1/admin/help-assistants/roles/{HelperKind.PROMPT_GUIDE.value}/",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() is None
