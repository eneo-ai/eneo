"""HTTP integration tests for the help-assistant admin router (step 021).

Pins the wiring contract for ``/api/v1/admin/help-assistants``:

  * Every endpoint is reachable and returns the documented shape.
  * Every mutation is rejected with 403 for a non-admin caller — the
    ``OrgSpaceAssistantRoleService`` enforces ``Permission.ADMIN`` at the
    service layer and the FastAPI exception handler maps
    ``UnauthorizedException`` → 403.
  * ``POST /roles/{kind}/assign`` rejects an assistant that lives outside
    the calling tenant's org-space with a 4xx.
  * Every mutation triggers ``audit_service.log_async`` — verified by
    spying on ``job_manager.enqueue`` (the audit dispatch sink), since
    the ARQ worker that persists rows does not run inside the test
    container.

The service-layer unit tests (step 015–017) already cover the audit
metadata shape and the reset/archive side-effects in detail; the tests
here verify the HTTP wrapper, not the underlying behavior.
"""

from __future__ import annotations

import secrets
from uuid import UUID, uuid4

import psycopg2
import pytest
import sqlalchemy as sa

from init_db import add_tenant_user
from intric.audit.domain.action_types import ActionType
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


@pytest.fixture
async def second_tenant_user(db_container, test_settings):
    """Second tenant + user via the psycopg2 init_db path."""
    suffix = uuid4().hex[:8]
    email = f"admin_router_user_{suffix}@example.com"
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    add_tenant_user(
        conn,
        tenant_name=f"admin_router_tenant_{suffix}",
        quota_limit=1_000_000,
        user_name=f"admin_router_user_{suffix}",
        user_email=email,
        user_password=secrets.token_urlsafe(16),
    )
    conn.close()

    async with db_container() as container:
        user_repo = container.user_repo()
        return await user_repo.get_user_by_email(email)


@pytest.fixture
def captured_audit_dispatches(monkeypatch):
    """Spy on ``job_manager.enqueue`` to capture audit dispatch calls.

    The ARQ worker doesn't run synchronously in tests, so the
    ``audit_logs`` table never receives rows. Capturing at the dispatch
    boundary is the closest behavioral assertion we can make without
    spinning up the worker.
    """
    from intric.jobs import job_manager as job_manager_module

    calls: list[dict[str, object]] = []
    original = job_manager_module.job_manager.enqueue

    async def fake_enqueue(task, job_id, params):  # type: ignore[no-untyped-def]
        calls.append({"task": task, "job_id": job_id, "params": params})
        return None

    monkeypatch.setattr(job_manager_module.job_manager, "enqueue", fake_enqueue)
    yield calls
    monkeypatch.setattr(job_manager_module.job_manager, "enqueue", original)


def _audit_actions(captured: list[dict[str, object]]) -> list[str]:
    return [c["params"]["action"] for c in captured if c["task"] == "log_audit_event"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_full_lifecycle_round_trip(
    client,
    db_container,
    admin_user,
    admin_token,
    captured_audit_dispatches,
):
    """Walk every endpoint once, asserting status codes and shapes.

    Order: assign → list/get → toggle enabled/visible → reset-instructions
    → reset-to-default (replaces helper) → list archivable (now contains
    the original) → archive → list history → unassign.
    """
    async with db_container() as container:
        assistant_id = await _seed_assistant_in_org_space(
            container, admin_user, name="Prompt Guide Helper"
        )

    headers = {"Authorization": f"Bearer {admin_token}"}
    kind = HelperKind.PROMPT_GUIDE.value

    # POST /assign
    resp = await client.post(
        f"/api/v1/admin/help-assistants/roles/{kind}/assign",
        headers=headers,
        json={"assistant_id": str(assistant_id)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == kind
    assert body["assistant_id"] == str(assistant_id)
    assert body["is_enabled"] is True
    assert body["is_visible_to_users"] is True

    # GET /roles/
    resp = await client.get(
        "/api/v1/admin/help-assistants/roles/", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] >= 1
    kinds = {item["kind"] for item in body["items"]}
    assert kind in kinds
    # The read endpoints resolve the assistant's display name for the admin
    # table (mutation responses leave it null — the UI re-fetches the list).
    prompt_guide_item = next(item for item in body["items"] if item["kind"] == kind)
    assert prompt_guide_item["assistant_name"] == "Prompt Guide Helper"

    # GET /roles/{kind}/
    resp = await client.get(
        f"/api/v1/admin/help-assistants/roles/{kind}/", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["assistant_id"] == str(assistant_id)
    assert body["assistant_name"] == "Prompt Guide Helper"

    # PATCH /enabled
    resp = await client.patch(
        f"/api/v1/admin/help-assistants/roles/{kind}/enabled",
        headers=headers,
        json={"value": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_enabled"] is False

    # PATCH /visible
    resp = await client.patch(
        f"/api/v1/admin/help-assistants/roles/{kind}/visible",
        headers=headers,
        json={"value": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_visible_to_users"] is False

    # POST /reset-instructions
    resp = await client.post(
        f"/api/v1/admin/help-assistants/roles/{kind}/reset-instructions",
        headers=headers,
    )
    assert resp.status_code == 204, resp.text

    # POST /reset-to-default — replaces the helper with a fresh one.
    resp = await client.post(
        f"/api/v1/admin/help-assistants/roles/{kind}/reset-to-default",
        headers=headers,
    )
    assert resp.status_code == 204, resp.text

    # GET /history — at least the reset-to-default reassignment is logged.
    resp = await client.get(
        f"/api/v1/admin/help-assistants/roles/{kind}/history", headers=headers
    )
    assert resp.status_code == 200, resp.text
    history = resp.json()["items"]
    assert any(h["reason"] == "reset_to_default" for h in history), history

    # GET /archivable — the original assistant is now archivable.
    resp = await client.get(
        f"/api/v1/admin/help-assistants/roles/{kind}/archivable", headers=headers
    )
    assert resp.status_code == 200, resp.text
    archivable = resp.json()["items"]
    archivable_ids = {item["id"] for item in archivable}
    assert str(assistant_id) in archivable_ids

    # POST /archive/{assistant_id}
    resp = await client.post(
        f"/api/v1/admin/help-assistants/roles/{kind}/archive/{assistant_id}",
        headers=headers,
    )
    assert resp.status_code == 204, resp.text

    # DELETE /roles/{kind}/
    resp = await client.delete(
        f"/api/v1/admin/help-assistants/roles/{kind}/", headers=headers
    )
    assert resp.status_code == 204, resp.text

    # Audit-dispatch contract: every mutation enqueued an audit event.
    actions = _audit_actions(captured_audit_dispatches)
    assert ActionType.HELP_ASSISTANT_ROLE_ASSIGNED.value in actions
    assert ActionType.HELP_ASSISTANT_ROLE_TOGGLED_ENABLED.value in actions
    assert ActionType.HELP_ASSISTANT_ROLE_TOGGLED_VISIBLE.value in actions
    assert ActionType.HELP_ASSISTANT_RESET_INSTRUCTIONS.value in actions
    assert ActionType.HELP_ASSISTANT_RESET_TO_DEFAULT.value in actions
    assert ActionType.HELP_ASSISTANT_ARCHIVED.value in actions
    assert ActionType.HELP_ASSISTANT_ROLE_UNASSIGNED.value in actions


MUTATION_REQUESTS = [
    (
        "assign",
        lambda kind, aid: (
            "POST",
            f"/api/v1/admin/help-assistants/roles/{kind}/assign",
            {"assistant_id": str(aid)},
        ),
    ),
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
        "reset_instructions",
        lambda kind, _aid: (
            "POST",
            f"/api/v1/admin/help-assistants/roles/{kind}/reset-instructions",
            None,
        ),
    ),
    (
        "reset_to_default",
        lambda kind, _aid: (
            "POST",
            f"/api/v1/admin/help-assistants/roles/{kind}/reset-to-default",
            None,
        ),
    ),
    (
        "unassign",
        lambda kind, _aid: (
            "DELETE",
            f"/api/v1/admin/help-assistants/roles/{kind}/",
            None,
        ),
    ),
    (
        "archive",
        lambda kind, aid: (
            "POST",
            f"/api/v1/admin/help-assistants/roles/{kind}/archive/{aid}",
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


async def test_assign_rejects_assistant_outside_org_space(
    client,
    db_container,
    admin_user,
    admin_token,
    second_tenant_user,
):
    """Assigning an assistant from another tenant's space returns 4xx.

    The service tries to load the assistant via ``assistant_service.get_assistant``;
    cross-tenant access raises ``UnauthorizedException`` (403). If a future
    refactor expands the load surface, the same call still hits the
    ``space_id != org_space_id`` guard, raising ``BadRequestException``
    (400). The test pins the contract as "any 4xx".
    """
    # Insert an assistant in the *second* tenant's org-space.
    async with db_container() as container:
        session = container.session()
        other_org_space = await _get_org_space(
            session, tenant_id=second_tenant_user.tenant_id
        )
        cross_tenant_assistant = await _insert_assistant(
            session,
            owner_user_id=second_tenant_user.id,
            space_id=other_org_space,
        )
        await session.flush()

    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post(
        f"/api/v1/admin/help-assistants/roles/{HelperKind.PROMPT_GUIDE.value}/assign",
        headers=headers,
        json={"assistant_id": str(cross_tenant_assistant)},
    )
    assert 400 <= resp.status_code < 500, resp.text


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
