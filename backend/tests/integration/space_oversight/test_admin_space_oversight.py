"""Tenant-admin oversight of shared spaces, end to end against PostgreSQL.

The overseer is a tenant admin who is a member of no space. They see
configuration, members and coarse usage of every shared space, manage
members without joining, and reach content only by joining with a reason.
Personal spaces, the organisation space and other tenants' spaces do not
exist for them.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from eneo.database.database import sessionmanager
from eneo.roles.permissions import Permission
from eneo.scim.app import scim_app
from eneo.scim.auth import require_scim_auth
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.spaces.oversight.exceptions import SpaceLastAdminError
from eneo.spaces.oversight.oversight_repo import last_activity_query
from eneo.spaces.oversight.oversight_service import SpaceOversightService
from eneo.spaces.space_init_service import SpaceInitService
from eneo.spaces.space_repo import SpaceRepository
from eneo.spaces.space_service import SpaceService
from tests.integration.space_oversight.support import (
    REASON,
    Person,
    add_group,
    add_member,
    admin_row,
    audit_rows,
    create_assistant,
    create_service_key,
    create_space,
    create_user_key,
    create_widget,
    days_ago,
    error_code,
    execute,
    fetch,
    hub_id,
    insert_assistant,
    insert_group,
    insert_question,
    insert_space,
    insert_tenant,
    insert_user,
    insert_widget,
    key,
    key_state,
    member_row,
    publish,
    scalar,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

OVERSIGHT_ACTIONS = (
    "space_oversight_joined",
    "space_oversight_left",
    "space_oversight_member_added",
    "space_oversight_member_role_changed",
    "space_oversight_member_removed",
)


def _routes(space_id: Any, target_id: Any = None) -> list[tuple[str, str, Any]]:
    """Every oversight route as (method, path, body)."""
    target = target_id or uuid4()
    base = f"/api/v1/admin/spaces/{space_id}"
    return [
        ("GET", "/api/v1/admin/spaces/", None),
        ("GET", f"{base}/", None),
        ("POST", f"{base}/members/", {"user_id": str(target), "role": "viewer"}),
        ("PATCH", f"{base}/members/{target}/", {"role": "editor"}),
        ("DELETE", f"{base}/members/{target}/", None),
        ("POST", f"{base}/group-members/", {"group_id": str(target), "role": "viewer"}),
        ("PATCH", f"{base}/group-members/{target}/", {"role": "editor"}),
        ("DELETE", f"{base}/group-members/{target}/", None),
        ("POST", f"{base}/join/", {"role": "viewer", "reason": REASON}),
        ("POST", f"{base}/leave/", None),
    ]


async def _detail(client, person: Person, space_id: Any) -> dict[str, Any]:
    resp = await client.get(f"/api/v1/admin/spaces/{space_id}/", headers=person.headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _items(client, person: Person) -> dict[str, dict[str, Any]]:
    resp = await client.get("/api/v1/admin/spaces/", headers=person.headers)
    assert resp.status_code == 200, resp.text
    return {item["id"]: item for item in resp.json()["items"]}


async def _join(client, person: Person, space_id: Any, role: str = "viewer"):
    return await client.post(
        f"/api/v1/admin/spaces/{space_id}/join/",
        json={"role": role, "reason": REASON},
        headers=person.headers,
    )


def _user(members: dict[str, Any], user_id: Any) -> dict[str, Any] | None:
    return next((u for u in members["users"] if u["id"] == str(user_id)), None)


async def _space_roles(space_id: Any) -> dict[UUID, str]:
    rows = await fetch(
        "SELECT user_id, role FROM spaces_users WHERE space_id = :s", s=str(space_id)
    )
    return {row[0]: row[1] for row in rows}


# --- access -------------------------------------------------------------------


ROUTE_NAMES = ("R1", "R2", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8")


@pytest.mark.parametrize("route", range(len(ROUTE_NAMES)), ids=ROUTE_NAMES)
async def test_non_admin_session_gets_403_everywhere(
    client, admin, make_person, route: int
):
    # A space admin who is not a tenant admin: running the space is not enough.
    space_admin = await make_person([Permission.ASSISTANTS], label="space-admin")
    space_id = await create_space(client, admin.token)
    await add_member(space_id, space_admin.id, "admin")
    method, path, body = _routes(space_id, admin.id)[route]

    resp = await client.request(method, path, json=body, headers=space_admin.headers)

    assert resp.status_code == 403, resp.text
    assert await _space_roles(space_id) == {admin.id: "admin", space_admin.id: "admin"}
    assert await audit_rows() == []


async def test_list_contains_only_the_tenants_shared_spaces(client, admin, overseer):
    _, tenant_id = await admin_row()
    shared = await create_space(client, admin.token)
    never_opened = str(await insert_space(tenant_id))
    resp = await client.get("/api/v1/spaces/type/personal/", headers=admin.headers)
    assert resp.status_code == 200, resp.text
    personal = resp.json()["id"]
    hub = str(await hub_id(tenant_id))
    foreign = str(await insert_space(await insert_tenant()))

    resp = await client.get("/api/v1/admin/spaces/", headers=overseer.headers)
    assert resp.status_code == 200, resp.text
    ids = [item["id"] for item in resp.json()["items"]]

    assert sorted(ids) == sorted([shared, never_opened])
    assert not {personal, hub, foreign} & set(ids)


async def test_personal_hub_and_other_tenant_ids_are_404_on_every_route(
    client, admin, overseer
):
    _, tenant_id = await admin_row()
    await create_space(client, admin.token)
    resp = await client.get("/api/v1/spaces/type/personal/", headers=admin.headers)
    personal = resp.json()["id"]
    hub = await hub_id(tenant_id)
    other_tenant = await insert_tenant()
    foreign = await insert_space(other_tenant)
    foreign_member = await insert_user(other_tenant)
    await add_member(foreign, foreign_member, "admin")

    # Tenant admins are members of the organisation space already.
    hub_members = await _space_roles(hub)
    bodies: dict[str, set[str]] = {}
    for target in (personal, hub, foreign, uuid4()):
        for method, path, body in _routes(target, admin.id)[1:]:
            resp = await client.request(
                method, path, json=body, headers=overseer.headers
            )
            assert resp.status_code == 404, (target, method, path, resp.text)
            route = f"{method} {path.replace(str(target), '{space_id}')}"
            bodies.setdefault(route, set()).add(resp.json()["message"])

    # The same answer whatever the id is: no existence oracle.
    assert all(len(messages) == 1 for messages in bodies.values()), bodies
    assert await _space_roles(hub) == hub_members
    assert await member_row(personal, overseer.id) is None
    assert await member_row(foreign, overseer.id) is None
    assert await audit_rows() == []


async def test_membership_column_distinguishes_direct_group_and_none(
    client, admin, overseer
):
    _, tenant_id = await admin_row()
    direct = await create_space(client, admin.token)
    via_group = await create_space(client, admin.token)
    both = await create_space(client, admin.token)
    none = await create_space(client, admin.token)
    group = await insert_group(tenant_id, [overseer.id], name="Tillsynsgruppen")
    await add_member(direct, overseer.id, "viewer")
    await add_group(via_group, group, "editor")
    await add_member(both, overseer.id, "viewer")
    await add_group(both, group, "admin")

    items = await _items(client, overseer)

    assert items[direct]["viewer_membership"] == {
        "role": "viewer",
        "via_group_only": False,
        "oversight_joined_at": None,
    }
    assert items[via_group]["viewer_membership"] == {
        "role": "editor",
        "via_group_only": True,
        "oversight_joined_at": None,
    }
    assert items[both]["viewer_membership"]["role"] == "admin"
    assert items[both]["viewer_membership"]["via_group_only"] is False
    assert items[none]["viewer_membership"] == {
        "role": None,
        "via_group_only": False,
        "oversight_joined_at": None,
    }

    viewer = (await _detail(client, overseer, via_group))["members"][
        "viewer_membership"
    ]
    assert viewer == {
        "role": "editor",
        "direct_role": None,
        "group_role": "editor",
        "via_groups": [{"id": str(group), "name": "Tillsynsgruppen"}],
        "oversight_joined_at": None,
        "joinable_roles": ["admin"],
        "can_leave": False,
    }


async def test_no_admin_attention_counts_manageable_admins_only(client, overseer):
    _, tenant_id = await admin_row()
    deleted_admin = await insert_user(tenant_id, deleted=True, label="deleted")
    inactive_admin = await insert_user(tenant_id, state="inactive", label="inactive")
    invited_admin = await insert_user(tenant_id, state="invited", label="invited")
    active = await insert_user(tenant_id, label="active")
    viewer = await insert_user(tenant_id, label="viewer")

    spaces: dict[str, UUID] = {}
    spaces["deleted_admin"] = await insert_space(tenant_id)
    await add_member(spaces["deleted_admin"], deleted_admin, "admin")
    await add_member(spaces["deleted_admin"], viewer, "viewer")
    spaces["inactive_admin"] = await insert_space(tenant_id)
    await add_member(spaces["inactive_admin"], inactive_admin, "admin")
    spaces["group_without_live_users"] = await insert_space(tenant_id)
    await add_group(
        spaces["group_without_live_users"],
        await insert_group(tenant_id, [inactive_admin, deleted_admin]),
        "admin",
    )
    spaces["deleted_group"] = await insert_space(tenant_id)
    await add_group(
        spaces["deleted_group"],
        await insert_group(tenant_id, [active], state="deleted"),
        "admin",
    )
    spaces["invited_admin"] = await insert_space(tenant_id)
    await add_member(spaces["invited_admin"], invited_admin, "admin")
    spaces["admin_group"] = await insert_space(tenant_id)
    admin_group = await insert_group(
        tenant_id, [active, inactive_admin], name="Förvaltare"
    )
    await add_group(spaces["admin_group"], admin_group, "admin")

    items = await _items(client, overseer)

    for name in (
        "deleted_admin",
        "inactive_admin",
        "group_without_live_users",
        "deleted_group",
    ):
        item = items[str(spaces[name])]
        assert item["attention"] == ["no_admin"], name
        assert item["admins"] == {"manageable": False, "count": 0, "principals": []}, (
            name
        )
    invited = items[str(spaces["invited_admin"])]
    assert invited["attention"] == []
    assert invited["admins"]["count"] == 1
    assert [p["id"] for p in invited["admins"]["principals"]] == [str(invited_admin)]
    grouped = items[str(spaces["admin_group"])]
    assert grouped["attention"] == []
    assert grouped["admins"] == {
        "manageable": True,
        "count": 1,
        "principals": [{"kind": "group", "id": str(admin_group), "name": "Förvaltare"}],
    }
    assert grouped["member_count"] == 2  # the inactive user is still a member
    # The list aggregates in SQL, the detail from the member rows: same answer.
    for name, space_id in spaces.items():
        detail = await _detail(client, overseer, space_id)
        item = items[str(space_id)]
        assert detail["members"]["admins"] == item["admins"], name
        assert detail["members"]["member_count"] == item["member_count"], name
        assert detail["members"]["group_count"] == item["group_count"], name
        assert detail["attention"] == item["attention"], name

    detail = await _detail(client, overseer, spaces["deleted_admin"])
    assert detail["attention"] == ["no_admin"]
    assert detail["members"]["admins"]["manageable"] is False
    assert [u["id"] for u in detail["members"]["users"]] == [str(viewer)]
    assert detail["members"]["member_count"] == 1

    # A deleted user's stale row cannot be changed, and they cannot be re-added.
    base = f"/api/v1/admin/spaces/{spaces['deleted_admin']}/members"
    for method, path, body in (
        ("PATCH", f"{base}/{deleted_admin}/", {"role": "viewer"}),
        ("DELETE", f"{base}/{deleted_admin}/", None),
        ("POST", f"{base}/", {"user_id": str(deleted_admin), "role": "admin"}),
    ):
        resp = await client.request(method, path, json=body, headers=overseer.headers)
        assert resp.status_code == 404, (method, resp.text)
    assert (await member_row(spaces["deleted_admin"], deleted_admin)).role == "admin"


async def test_reads_have_no_side_effects(client, overseer):
    _, tenant_id = await admin_row()
    member = await insert_user(tenant_id)
    space_id = await insert_space(tenant_id)
    await add_member(space_id, member, "admin")
    updated_at = await scalar("SELECT updated_at FROM spaces WHERE id = :s", s=space_id)

    for _ in range(2):
        assert str(space_id) in await _items(client, overseer)
        detail = await _detail(client, overseer, space_id)
        assert detail["assistants"] == []

    assert (
        await scalar("SELECT count(*) FROM assistants WHERE space_id = :s", s=space_id)
        == 0
    )
    assert (
        await scalar("SELECT updated_at FROM spaces WHERE id = :s", s=space_id)
        == updated_at
    )
    assert await _space_roles(space_id) == {member: "admin"}
    assert await audit_rows() == []


async def test_oversight_never_touches_the_aggregate_loader(
    client, admin, overseer, make_person, monkeypatch
):
    _, tenant_id = await admin_row()
    editor = await make_person(
        [Permission.WIDGETS, Permission.ASSISTANTS], label="widget-editor"
    )
    newcomer = await make_person([], label="newcomer")
    group = await insert_group(tenant_id, [newcomer.id])
    space_id = await create_space(client, admin.token)
    await add_member(space_id, editor.id, "editor")
    assistant_id = await create_assistant(client, admin.token, space_id)
    await publish(client, admin.token, assistant_id)
    widget = await create_widget(client, admin.token, space_id, assistant_id)
    resp = await client.post(
        f"/api/v1/widgets/{widget['id']}/activation-request/", headers=editor.headers
    )
    assert resp.status_code == 200, resp.text

    async def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("oversight must not load the space aggregate")

    for name in dir(SpaceRepository):
        if name in ("one", "one_or_none", "update") or name.startswith("get_space_by_"):
            monkeypatch.setattr(SpaceRepository, name, refuse)
    monkeypatch.setattr(SpaceService, "get_space", refuse)
    monkeypatch.setattr(SpaceInitService, "get_space", refuse)

    base = f"/api/v1/admin/spaces/{space_id}"
    calls: list[tuple[str, str, Any, int]] = [
        ("GET", "/api/v1/admin/spaces/", None, 200),
        ("GET", f"{base}/", None, 200),
        (
            "POST",
            f"{base}/members/",
            {"user_id": str(newcomer.id), "role": "viewer"},
            201,
        ),
        ("PATCH", f"{base}/members/{newcomer.id}/", {"role": "editor"}, 200),
        ("DELETE", f"{base}/members/{newcomer.id}/", None, 200),
        (
            "POST",
            f"{base}/group-members/",
            {"group_id": str(group), "role": "viewer"},
            201,
        ),
        ("PATCH", f"{base}/group-members/{group}/", {"role": "editor"}, 200),
        ("DELETE", f"{base}/group-members/{group}/", None, 200),
        ("POST", f"{base}/join/", {"role": "viewer", "reason": REASON}, 200),
        ("POST", f"{base}/leave/", None, 200),
        ("GET", f"/api/v1/admin/widgets/{widget['id']}/", None, 200),
        (
            "POST",
            f"/api/v1/widgets/{widget['id']}/activation-request/decline/",
            {"reason": "Lägg till en kontaktadress i undertexten."},
            200,
        ),
    ]
    for method, path, body, expected in calls:
        resp = await client.request(method, path, json=body, headers=overseer.headers)
        assert resp.status_code == expected, (method, path, resp.text)

    revision = resp.json()["revision"]
    for path, body in (
        (f"/api/v1/widgets/{widget['id']}/activate/", {"revision": revision}),
        (f"/api/v1/widgets/{widget['id']}/pause/", None),
        (f"/api/v1/widgets/{widget['id']}/archive/", None),
    ):
        resp = await client.post(path, json=body, headers=overseer.headers)
        assert resp.status_code == 200, (path, resp.text)
    assert resp.json()["status"] == "archived"


# --- statement budget ----------------------------------------------------------


async def _seed_busy_space(tenant_id: UUID, owner: UUID, model_id: UUID) -> UUID:
    """A shared space with a row in everything the list aggregates."""
    space_id = await insert_space(tenant_id)
    await add_member(space_id, owner, "admin")
    await add_group(space_id, await insert_group(tenant_id, [owner]), "viewer")
    assistant = await insert_assistant(space_id, owner, published=True)
    await insert_question(tenant_id, assistant, user_id=owner)
    await insert_widget(tenant_id, space_id, assistant, requested_by=owner)
    await execute(
        "INSERT INTO apps (id, name, tenant_id, user_id, space_id, published,"
        " completion_model_id) VALUES (:id, 'App', :t, :u, :s, false, :m)",
        id=uuid4(),
        t=tenant_id,
        u=owner,
        s=space_id,
        m=model_id,
    )
    return space_id


async def _decorate_assistant(
    tenant_id: UUID,
    owner: UUID,
    space_id: UUID,
    assistant_id: UUID,
    *,
    collection_id: UUID,
    mcp_server_id: UUID,
) -> None:
    prompt = uuid4()
    await execute(
        "INSERT INTO prompts (id, text, user_id, tenant_id) VALUES (:id, 'Svara kort.', :u, :t)",
        id=prompt,
        u=owner,
        t=tenant_id,
    )
    await execute(
        "INSERT INTO prompts_assistants (prompt_id, assistant_id, is_selected)"
        " VALUES (:p, :a, true)",
        p=prompt,
        a=assistant_id,
    )
    await execute(
        "INSERT INTO assistants_groups (group_id, assistant_id) VALUES (:g, :a)",
        g=collection_id,
        a=assistant_id,
    )
    file_id = uuid4()
    await execute(
        "INSERT INTO files (id, name, tenant_id, user_id) VALUES (:id, 'bilaga.txt', :t, :u)",
        id=file_id,
        t=tenant_id,
        u=owner,
    )
    await execute(
        "INSERT INTO assistants_files (assistant_id, file_id) VALUES (:a, :f)",
        a=assistant_id,
        f=file_id,
    )
    await execute(
        "INSERT INTO assistant_mcp_servers (assistant_id, mcp_server_id) VALUES (:a, :m)",
        a=assistant_id,
        m=mcp_server_id,
    )
    await execute(
        "INSERT INTO assistant_capabilities (assistant_id, purpose)"
        " VALUES (:a, 'web_search')",
        a=assistant_id,
    )
    await insert_widget(tenant_id, space_id, assistant_id)


async def _completion_model(tenant_id: UUID) -> UUID:
    return await scalar(
        "SELECT id FROM completion_models WHERE tenant_id = :t ORDER BY created_at LIMIT 1",
        t=tenant_id,
    )


async def _statements(
    db_container, user_id: UUID, call: Callable[[SpaceOversightService], Awaitable[Any]]
) -> list[str]:
    """The statements one oversight read issues, without authentication."""
    async with db_container() as container:
        user = await container.user_repo().get_user_by_id(user_id)
    statements: list[str] = []

    def record(_conn, _cursor, statement, _params, _context, _executemany) -> None:
        statements.append(statement)

    async with db_container(user=user) as container:
        engine = container.session().get_bind()
        sa.event.listen(engine, "before_cursor_execute", record)
        try:
            await call(container.space_oversight_service())
        finally:
            sa.event.remove(engine, "before_cursor_execute", record)
    return statements


async def test_statement_budget(db_container, overseer):
    owner, tenant_id = await admin_row()
    model_id = await _completion_model(tenant_id)
    first = await _seed_busy_space(tenant_id, owner, model_id)

    async def list_spaces(service: SpaceOversightService) -> Any:
        return await service.list_spaces()

    one_space = await _statements(db_container, overseer.id, list_spaces)
    for _ in range(24):
        await _seed_busy_space(tenant_id, owner, model_id)
    many_spaces = await _statements(db_container, overseer.id, list_spaces)
    assert len(one_space) == len(many_spaces) <= 10, many_spaces

    collection = uuid4()
    await execute(
        "INSERT INTO groups (id, name, tenant_id, user_id, space_id, size)"
        " VALUES (:id, 'Samling', :t, :u, :s, 0)",
        id=collection,
        t=tenant_id,
        u=owner,
        s=first,
    )
    mcp_server = uuid4()
    await execute(
        "INSERT INTO mcp_servers (id, tenant_id, name, http_url)"
        " VALUES (:id, :t, 'Kalender', 'https://mcp.example.com')",
        id=mcp_server,
        t=tenant_id,
    )
    target = await insert_assistant(first, owner)
    await _decorate_assistant(
        tenant_id,
        owner,
        first,
        target,
        collection_id=collection,
        mcp_server_id=mcp_server,
    )

    async def detail(service: SpaceOversightService) -> Any:
        return await service.get_space(first)

    one_assistant = await _statements(db_container, overseer.id, detail)
    for _ in range(9):
        assistant = await insert_assistant(first, owner)
        await _decorate_assistant(
            tenant_id,
            owner,
            first,
            assistant,
            collection_id=collection,
            mcp_server_id=mcp_server,
        )
    ten_assistants = await _statements(db_container, overseer.id, detail)
    assert len(one_assistant) == len(ten_assistants) <= 25, ten_assistants


# --- usage --------------------------------------------------------------------


async def test_usage_is_suppressed_below_five_active_users(client, admin, overseer):
    _, tenant_id = await admin_row()
    space_id = await create_space(client, admin.token)
    assistant = await insert_assistant(space_id, admin.id)
    users = [await insert_user(tenant_id) for _ in range(5)]
    for user in users[:4]:
        await insert_question(tenant_id, assistant, user_id=user)
    # Never counted: outside the window, and a session without a signed-in user.
    await insert_question(
        tenant_id, assistant, user_id=users[4], created_at=days_ago(40)
    )
    await insert_question(
        tenant_id,
        assistant,
        widget_id=await insert_widget(tenant_id, space_id, assistant),
    )
    app_id = uuid4()
    await execute(
        "INSERT INTO apps (id, name, tenant_id, user_id, space_id, published)"
        " VALUES (:id, 'Protokoll', :t, :u, :s, false)",
        id=app_id,
        t=tenant_id,
        u=admin.id,
        s=space_id,
    )
    await execute(
        "INSERT INTO app_runs (tenant_id, user_id, app_id, completion_model_id)"
        " VALUES (:t, :u, :a, :m)",
        t=tenant_id,
        u=users[0],
        a=app_id,
        m=await _completion_model(tenant_id),
    )

    usage = (await _detail(client, overseer, space_id))["usage"]
    assert usage == {
        "window_days": 30,
        "threshold": 5,
        "suppressed": True,
        "questions": None,
        "app_runs": None,
        "active_users": None,
        # The only widget has never been active.
        "widget_questions": None,
        "last_activity": "past_week",
        "knowledge_bytes": 0,
    }

    # Five people asked, one ran the app: that one person's run stays hidden.
    await insert_question(tenant_id, assistant, user_id=users[4])
    usage = (await _detail(client, overseer, space_id))["usage"]
    assert usage["suppressed"] is True
    assert (usage["questions"], usage["app_runs"], usage["active_users"]) == (
        5,
        None,
        5,
    )

    for user in users[1:]:
        await execute(
            "INSERT INTO app_runs (tenant_id, user_id, app_id, completion_model_id)"
            " VALUES (:t, :u, :a, :m)",
            t=tenant_id,
            u=user,
            a=app_id,
            m=await _completion_model(tenant_id),
        )
    usage = (await _detail(client, overseer, space_id))["usage"]
    assert usage["suppressed"] is False
    assert (usage["questions"], usage["app_runs"], usage["active_users"]) == (5, 5, 5)


async def test_one_persons_count_is_hidden_next_to_four_others(client, admin, overseer):
    """Four people run the app and one asks seven questions: five active
    users, but the question count is that one person's."""
    _, tenant_id = await admin_row()
    space_id = await create_space(client, admin.token)
    assistant = await insert_assistant(space_id, admin.id)
    users = [await insert_user(tenant_id) for _ in range(5)]
    for _ in range(7):
        await insert_question(tenant_id, assistant, user_id=users[0])
    app_id = uuid4()
    await execute(
        "INSERT INTO apps (id, name, tenant_id, user_id, space_id, published)"
        " VALUES (:id, 'Transkribering', :t, :u, :s, false)",
        id=app_id,
        t=tenant_id,
        u=admin.id,
        s=space_id,
    )
    for user in users[1:]:
        await execute(
            "INSERT INTO app_runs (tenant_id, user_id, app_id, completion_model_id)"
            " VALUES (:t, :u, :a, :m)",
            t=tenant_id,
            u=user,
            a=app_id,
            m=await _completion_model(tenant_id),
        )

    usage = (await _detail(client, overseer, space_id))["usage"]
    assert usage["active_users"] == 5
    assert usage["questions"] is None
    assert usage["app_runs"] is None
    assert usage["suppressed"] is True


async def test_last_activity_is_only_a_bucket(client, admin, overseer):
    _, tenant_id = await admin_row()
    idle = await create_space(client, admin.token)
    quiet = await create_space(client, admin.token)
    dormant = await create_space(client, admin.token)
    await insert_question(
        tenant_id,
        await insert_assistant(quiet, admin.id),
        user_id=admin.id,
        created_at=days_ago(45),
    )
    await insert_question(
        tenant_id,
        await insert_assistant(dormant, admin.id),
        user_id=admin.id,
        created_at=days_ago(120),
    )

    # Spaces used only through an app: a run long ago still tells an old
    # space from one never used.
    app_spaces = {}
    for label, age in (("app_recent", 45), ("app_old", 120), ("app_unused", None)):
        app_spaces[label] = await create_space(client, admin.token)
        app_id = uuid4()
        await execute(
            "INSERT INTO apps (id, name, tenant_id, user_id, space_id, published)"
            " VALUES (:id, 'Transkribering', :t, :u, :s, false)",
            id=app_id,
            t=tenant_id,
            u=admin.id,
            s=app_spaces[label],
        )
        if age is not None:
            await execute(
                "INSERT INTO app_runs (tenant_id, user_id, app_id,"
                " completion_model_id, created_at) VALUES (:t, :u, :a, :m, :c)",
                t=tenant_id,
                u=admin.id,
                a=app_id,
                m=await _completion_model(tenant_id),
                c=days_ago(age),
            )

    items = await _items(client, overseer)
    assert [items[space]["last_activity"] for space in (idle, quiet, dormant)] == [
        "none",
        "past_quarter",
        "older",
    ]
    assert {
        label: items[space]["last_activity"] for label, space in app_spaces.items()
    } == {
        "app_recent": "past_quarter",
        "app_old": "older",
        "app_unused": "none",
    }
    detail = await _detail(client, overseer, quiet)
    assert detail["usage"]["last_activity"] == "past_quarter"
    detail = await _detail(client, overseer, app_spaces["app_old"])
    assert detail["usage"]["last_activity"] == "older"


async def test_last_activity_reads_one_index_entry_per_assistant_and_app():
    """The space list reads each assistant's latest question and each app's
    latest run with one backward index probe. A range over the tenant's runs
    would read every run in it on every list load. With sequential scans and
    sorts penalised, the plan is only cheap if the indexes on (assistant_id,
    created_at) and (app_id, created_at) give the order, whatever the table
    size."""
    _, tenant_id = await admin_row()
    compiled = last_activity_query(tenant_id).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    async with sessionmanager.session() as session, session.begin():
        await session.execute(sa.text("SET LOCAL enable_seqscan = off"))
        await session.execute(sa.text("SET LOCAL enable_sort = off"))
        plan = "\n".join(
            row[0] for row in await session.execute(sa.text(f"EXPLAIN {compiled}"))
        )

    lines = plan.splitlines()
    run_scans = [line for line in lines if " on app_runs" in line]
    question_scans = [line for line in lines if " on questions" in line]
    assert run_scans, plan
    assert all(
        "Backward using ix_app_runs_app_created " in line for line in run_scans
    ), plan
    assert question_scans, plan
    assert all(
        "Backward using" in line and "_questions_assistant_created " in line
        for line in question_scans
    ), plan


async def test_usage_counts_widget_questions_separately(client, admin, overseer):
    _, tenant_id = await admin_row()
    space_id = await create_space(client, admin.token)
    other_space = await create_space(client, admin.token)
    widget = await insert_widget(
        tenant_id, space_id, await insert_assistant(space_id, admin.id)
    )
    other_widget = await insert_widget(
        tenant_id, other_space, await insert_assistant(other_space, admin.id)
    )
    for widget_id, day, questions in (
        (widget, days_ago(0).date(), 7),
        (widget, days_ago(10).date(), 3),
        (widget, days_ago(40).date(), 100),
        (other_widget, days_ago(0).date(), 50),
    ):
        await execute(
            "INSERT INTO widget_daily_usage (widget_id, day, questions)"
            " VALUES (:w, :d, :q)",
            w=widget_id,
            d=day,
            q=questions,
        )

    # Only the editors test a widget that has never been active.
    usage = (await _detail(client, overseer, space_id))["usage"]
    assert usage["widget_questions"] is None

    await execute(
        "UPDATE widgets SET status = 'paused', activated_at = now() - interval"
        " '5 days', paused_at = now() WHERE id = :w",
        w=widget,
    )
    draft = await insert_widget(
        tenant_id, space_id, await insert_assistant(space_id, admin.id)
    )
    await execute(
        "INSERT INTO widget_daily_usage (widget_id, day, questions)"
        " VALUES (:w, :d, 23)",
        w=draft,
        d=days_ago(0).date(),
    )
    usage = (await _detail(client, overseer, space_id))["usage"]
    # Not held to the threshold of signed-in people; the draft's tests are
    # left out.
    assert usage["suppressed"] is True
    assert usage["widget_questions"] == 10


async def test_an_assistant_lists_every_widget_it_serves(client, admin, overseer):
    _, tenant_id = await admin_row()
    space_id = await create_space(client, admin.token)
    assistant = await insert_assistant(space_id, admin.id)
    other = await insert_assistant(space_id, admin.id)
    ids = {
        name: await insert_widget(
            tenant_id, space_id, assistant, name=name, status=status
        )
        for name, status in (
            ("Alfa", "draft"),
            ("Beta", "active"),
            ("Gamma", "paused"),
            ("Delta", "archived"),
            ("Epsilon", "active"),
        )
    }

    detail = await _detail(client, overseer, space_id)
    cards = {card["id"]: card for card in detail["assistants"]}
    # An active widget never hides behind a draft that sorts after it.
    assert [(w["name"], w["status"]) for w in cards[str(assistant)]["widgets"]] == [
        ("Beta", "active"),
        ("Epsilon", "active"),
        ("Gamma", "paused"),
        ("Alfa", "draft"),
    ]
    assert cards[str(assistant)]["widgets"][0]["id"] == str(ids["Beta"])
    assert cards[str(other)]["widgets"] == []


async def test_change_times_of_the_space_knowledge_and_assistants_are_days(
    client, admin, overseer
):
    """A space created, or an upload or edit made, late at night in a
    one-person space shows as a day, not as the minute that person worked."""
    _, tenant_id = await admin_row()
    space_id = await create_space(client, admin.token)
    assistant = await insert_assistant(space_id, admin.id)
    collection = uuid4()
    await execute(
        "INSERT INTO groups (id, name, tenant_id, user_id, space_id, size,"
        " updated_at) VALUES (:id, 'Samling', :t, :u, :s, 0,"
        " '2026-09-24 23:41:07+00')",
        id=collection,
        t=tenant_id,
        u=admin.id,
        s=space_id,
    )
    await execute(
        "UPDATE assistants SET updated_at = '2026-09-25 01:41:07+02' WHERE id = :a",
        a=assistant,
    )
    await execute(
        "UPDATE spaces SET created_at = '2026-09-25 01:41:07+02',"
        " updated_at = '2026-09-25 01:41:07+02' WHERE id = :s",
        s=space_id,
    )

    detail = await _detail(client, overseer, space_id)
    assert (detail["created_at"], detail["updated_at"]) == ("2026-09-24", "2026-09-24")
    resp = await client.get("/api/v1/admin/spaces/", headers=overseer.headers)
    assert resp.status_code == 200, resp.text
    (item,) = [i for i in resp.json()["items"] if i["id"] == space_id]
    assert item["created_at"] == "2026-09-24"
    (card,) = [a for a in detail["assistants"] if a["id"] == str(assistant)]
    assert card["updated_at"] == "2026-09-24"
    (source,) = detail["knowledge"]
    assert source["updated_at"] == "2026-09-24"

    widget = await insert_widget(tenant_id, space_id, assistant)
    resp = await client.get(
        f"/api/v1/admin/widgets/{widget}/", headers=overseer.headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["target"]["assistant"]["updated_at"] == "2026-09-24"


async def test_activation_requests_are_listed_tenant_wide_and_linked_by_kind(
    client, admin, overseer
):
    """The request list covers every space; only shared spaces are list items
    that can be opened, so only they are flagged, and the widget overview
    says which kind each widget's space is."""
    owner, tenant_id = await admin_row()
    shared = await create_space(client, admin.token)
    hub = await hub_id(tenant_id)
    requested = {
        "shared": await insert_widget(
            tenant_id, shared, await insert_assistant(shared, owner), requested_by=owner
        ),
        "organization": await insert_widget(
            tenant_id, hub, await insert_assistant(hub, owner), requested_by=owner
        ),
    }

    resp = await client.get("/api/v1/admin/spaces/", headers=overseer.headers)
    assert resp.status_code == 200, resp.text
    listed = resp.json()
    assert {
        request["widget_id"]: request["space"]["id"]
        for request in listed["widget_requests"]
    } == {
        str(requested["shared"]): shared,
        str(requested["organization"]): str(hub),
    }
    items = {item["id"]: item for item in listed["items"]}
    assert str(hub) not in items
    assert items[shared]["attention"] == ["widget_activation_requested"]
    assert items[shared]["widgets"]["awaiting_activation"] == 1

    resp = await client.get("/api/v1/admin/widgets/", headers=overseer.headers)
    assert resp.status_code == 200, resp.text
    kinds = {item["id"]: item["space_kind"] for item in resp.json()["items"]}
    assert kinds[str(requested["shared"])] == "shared"
    assert kinds[str(requested["organization"])] == "organization"


# --- member management --------------------------------------------------------


async def test_admin_manages_members_without_membership(
    client, admin, overseer, make_person
):
    _, tenant_id = await admin_row()
    person = await make_person([], label="kollega")
    group = await insert_group(tenant_id, [person.id, admin.id], name="Handläggare")
    space_id = await create_space(client, admin.token)
    base = f"/api/v1/admin/spaces/{space_id}"

    resp = await client.post(
        f"{base}/members/",
        json={"user_id": str(person.id), "role": "viewer"},
        headers=overseer.headers,
    )
    assert resp.status_code == 201, resp.text
    assert _user(resp.json(), person.id)["role"] == "viewer"
    resp = await client.patch(
        f"{base}/members/{person.id}/",
        json={"role": "editor"},
        headers=overseer.headers,
    )
    assert resp.status_code == 200, resp.text
    assert _user(resp.json(), person.id)["role"] == "editor"
    resp = await client.delete(f"{base}/members/{person.id}/", headers=overseer.headers)
    assert resp.status_code == 200, resp.text
    assert _user(resp.json(), person.id) is None

    resp = await client.post(
        f"{base}/group-members/",
        json={"group_id": str(group), "role": "viewer"},
        headers=overseer.headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["groups"] == [
        {"id": str(group), "name": "Handläggare", "role": "viewer", "user_count": 2}
    ]
    resp = await client.patch(
        f"{base}/group-members/{group}/",
        json={"role": "editor"},
        headers=overseer.headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["groups"][0]["role"] == "editor"
    resp = await client.delete(
        f"{base}/group-members/{group}/", headers=overseer.headers
    )
    assert resp.status_code == 200, resp.text
    members = resp.json()
    assert members["groups"] == []
    assert members["viewer_membership"]["role"] is None

    assert await _space_roles(space_id) == {admin.id: "admin"}
    resp = await client.get(f"/api/v1/spaces/{space_id}/", headers=overseer.headers)
    assert resp.status_code == 403, resp.text

    rows = await audit_rows(entity_id=space_id)
    assert [row["action"] for row in rows] == [
        "space_oversight_member_added",
        "space_oversight_member_role_changed",
        "space_oversight_member_removed",
        "space_oversight_member_added",
        "space_oversight_member_role_changed",
        "space_oversight_member_removed",
    ]
    assert {row["actor_id"] for row in rows} == {overseer.id}
    for row in rows:
        assert row["metadata"]["extra"]["oversight"] == {
            "actor_is_member": False,
            "actor_role": None,
        }
        assert row["metadata"]["target"]["id"] == space_id
    member = {"id": str(person.id), "name": person.username, "email": person.email}
    added, changed, removed = (row["metadata"] for row in rows[:3])
    assert added["extra"]["member"] == member
    assert added["extra"]["role"] == "viewer"
    assert changed["changes"] == {"role": {"old": "viewer", "new": "editor"}}
    assert removed["extra"]["member"] == member
    assert removed["extra"]["api_keys_revoked"] == 0
    group_added, group_changed, _ = (row["metadata"] for row in rows[3:])
    assert group_added["extra"]["group"] == {
        "id": str(group),
        "name": "Handläggare",
        "user_count": 2,
    }
    assert "member" not in group_added["extra"]
    assert group_changed["changes"] == {"role": {"old": "viewer", "new": "editor"}}


async def test_role_change_does_not_rewrite_other_rows(client, admin, overseer):
    _, tenant_id = await admin_row()
    space_id = await create_space(client, admin.token)
    first, second = await insert_user(tenant_id), await insert_user(tenant_id)
    await add_member(space_id, first, "viewer", created_at=days_ago(30))
    await add_member(space_id, second, "viewer", created_at=days_ago(20))
    before = {
        row[0]: row[1]
        for row in await fetch(
            "SELECT user_id, created_at FROM spaces_users WHERE space_id = :s",
            s=space_id,
        )
    }

    resp = await client.patch(
        f"/api/v1/admin/spaces/{space_id}/members/{first}/",
        json={"role": "editor"},
        headers=overseer.headers,
    )
    assert resp.status_code == 200, resp.text

    after = {
        row[0]: row[1]
        for row in await fetch(
            "SELECT user_id, created_at FROM spaces_users WHERE space_id = :s",
            s=space_id,
        )
    }
    assert after == before
    assert await _space_roles(space_id) == {
        admin.id: "admin",
        first: "editor",
        second: "viewer",
    }


async def test_self_and_group_self_escalation_are_refused(client, admin, overseer):
    _, tenant_id = await admin_row()
    base_space = await create_space(client, admin.token)
    base = f"/api/v1/admin/spaces/{base_space}"

    resp = await client.post(
        f"{base}/members/",
        json={"user_id": str(overseer.id), "role": "admin"},
        headers=overseer.headers,
    )
    assert (resp.status_code, error_code(resp)) == (400, 9067), resp.text

    await add_member(base_space, overseer.id, "viewer")
    for method, body in (("PATCH", {"role": "admin"}), ("DELETE", None)):
        resp = await client.request(
            method,
            f"{base}/members/{overseer.id}/",
            json=body,
            headers=overseer.headers,
        )
        assert (resp.status_code, error_code(resp)) == (400, 9067), resp.text
    assert (await member_row(base_space, overseer.id)).role == "viewer"

    group_space = await create_space(client, admin.token)
    groups = f"/api/v1/admin/spaces/{group_space}/group-members"
    own_group = await insert_group(tenant_id, [overseer.id])
    resp = await client.post(
        f"{groups}/",
        json={"group_id": str(own_group), "role": "viewer"},
        headers=overseer.headers,
    )
    assert (resp.status_code, error_code(resp)) == (400, 9067), resp.text

    await add_group(group_space, own_group, "editor")
    resp = await client.patch(
        f"{groups}/{own_group}/", json={"role": "admin"}, headers=overseer.headers
    )
    assert (resp.status_code, error_code(resp)) == (400, 9067), resp.text
    # Lowering or removing a group you belong to takes access away: allowed.
    resp = await client.patch(
        f"{groups}/{own_group}/", json={"role": "viewer"}, headers=overseer.headers
    )
    assert resp.status_code == 200, resp.text
    resp = await client.delete(f"{groups}/{own_group}/", headers=overseer.headers)
    assert resp.status_code == 200, resp.text

    # A group that contains you but does not raise your role is no escalation.
    await add_member(group_space, overseer.id, "editor")
    resp = await client.post(
        f"{groups}/",
        json={"group_id": str(own_group), "role": "viewer"},
        headers=overseer.headers,
    )
    assert resp.status_code == 201, resp.text


async def test_another_tenant_admin_reaches_content_only_by_joining(
    client, admin, overseer, make_person
):
    """Adding or promoting a tenant admin would give them content without the
    reason and marker a join records; lowering or removing takes access away,
    and a group that contains one stays the group's business."""
    _, tenant_id = await admin_row()
    colleague = await make_person([Permission.ADMIN], label="kollega-admin")
    space_id = await create_space(client, admin.token)
    base = f"/api/v1/admin/spaces/{space_id}"

    for role in ("viewer", "admin"):
        resp = await client.post(
            f"{base}/members/",
            json={"user_id": str(colleague.id), "role": role},
            headers=overseer.headers,
        )
        assert (resp.status_code, error_code(resp)) == (400, 9068), resp.text
    assert await member_row(space_id, colleague.id) is None

    # Already a member (added by the space itself): raising is refused.
    await add_member(space_id, colleague.id, "editor")
    resp = await client.patch(
        f"{base}/members/{colleague.id}/",
        json={"role": "admin"},
        headers=overseer.headers,
    )
    assert (resp.status_code, error_code(resp)) == (400, 9068), resp.text
    assert (await member_row(space_id, colleague.id)).role == "editor"
    resp = await client.patch(
        f"{base}/members/{colleague.id}/",
        json={"role": "viewer"},
        headers=overseer.headers,
    )
    assert resp.status_code == 200, resp.text
    resp = await client.delete(
        f"{base}/members/{colleague.id}/", headers=overseer.headers
    )
    assert resp.status_code == 200, resp.text

    group = await insert_group(tenant_id, [colleague.id, await insert_user(tenant_id)])
    resp = await client.post(
        f"{base}/group-members/",
        json={"group_id": str(group), "role": "editor"},
        headers=overseer.headers,
    )
    assert resp.status_code == 201, resp.text

    assert [row["action"] for row in await audit_rows(entity_id=space_id)] == [
        "space_oversight_member_role_changed",
        "space_oversight_member_removed",
        "space_oversight_member_added",
    ]


async def test_last_admin_is_protected(client, admin, overseer):
    _, tenant_id = await admin_row()
    only_admin = await create_space(client, admin.token)
    base = f"/api/v1/admin/spaces/{only_admin}"
    for method, body in (("PATCH", {"role": "editor"}), ("DELETE", None)):
        resp = await client.request(
            method, f"{base}/members/{admin.id}/", json=body, headers=overseer.headers
        )
        assert (resp.status_code, error_code(resp)) == (409, 9065), resp.text

    group_space = await insert_space(tenant_id)
    admin_group = await insert_group(tenant_id, [admin.id])
    await add_group(group_space, admin_group, "admin")
    groups = f"/api/v1/admin/spaces/{group_space}/group-members/{admin_group}/"
    for method, body in (("PATCH", {"role": "viewer"}), ("DELETE", None)):
        resp = await client.request(method, groups, json=body, headers=overseer.headers)
        assert (resp.status_code, error_code(resp)) == (409, 9065), resp.text

    # Leave: the overseer joins as admin, the creator steps down, and the
    # overseer is now the last one.
    assert (await _join(client, overseer, only_admin, "admin")).status_code == 200
    resp = await client.patch(
        f"{base}/members/{admin.id}/", json={"role": "viewer"}, headers=overseer.headers
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(f"{base}/leave/", headers=overseer.headers)
    assert (resp.status_code, error_code(resp)) == (409, 9065), resp.text

    assert await _space_roles(only_admin) == {admin.id: "viewer", overseer.id: "admin"}
    assert (
        await scalar(
            "SELECT role FROM spaces_user_groups WHERE user_group_id = :g",
            g=admin_group,
        )
        == "admin"
    )


async def test_zero_admin_space_can_still_be_fixed(client, overseer):
    _, tenant_id = await admin_row()
    space_id = await insert_space(tenant_id)
    stranded = await insert_user(tenant_id, state="inactive")
    viewer = await insert_user(tenant_id)
    colleague = await insert_user(tenant_id)
    await add_member(space_id, stranded, "admin")
    await add_member(space_id, viewer, "viewer")
    base = f"/api/v1/admin/spaces/{space_id}"

    # 0 -> 0 is no loss: the rule only refuses taking the last admin away.
    resp = await client.delete(f"{base}/members/{stranded}/", headers=overseer.headers)
    assert resp.status_code == 200, resp.text
    assert (await _join(client, overseer, space_id)).status_code == 200
    resp = await client.post(f"{base}/leave/", headers=overseer.headers)
    assert resp.status_code == 200, resp.text

    resp = await client.patch(
        f"{base}/members/{viewer}/", json={"role": "admin"}, headers=overseer.headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["admins"]["manageable"] is True
    resp = await client.post(
        f"{base}/members/",
        json={"user_id": str(colleague), "role": "admin"},
        headers=overseer.headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["admins"]["count"] == 2
    assert (await _detail(client, overseer, space_id))["attention"] == []


async def test_concurrent_demotions_cannot_remove_both_admins(
    client, db_container, admin, overseer, make_person
):
    second = await make_person([], label="second-admin")
    space_id = UUID(await create_space(client, admin.token))
    await add_member(space_id, second.id, "admin")
    async with db_container() as container:
        user = await container.user_repo().get_user_by_id(overseer.id)

    racer_pid: asyncio.Queue[int] = asyncio.Queue()

    async def demote_the_second_admin() -> None:
        async with db_container(user=user) as container:
            pid = await container.session().scalar(sa.text("SELECT pg_backend_pid()"))
            racer_pid.put_nowait(pid)
            await container.space_oversight_service().change_member_role(
                space_id, second.id, SpaceRoleValue.VIEWER
            )

    racer: asyncio.Task[None] | None = None
    try:
        async with db_container(user=user) as container:
            await container.space_oversight_service().change_member_role(
                space_id, admin.id, SpaceRoleValue.VIEWER
            )
            racer = asyncio.create_task(demote_the_second_admin())
            async with asyncio.timeout(10):
                while racer_pid.empty():
                    if racer.done():
                        racer.result()
                    await asyncio.sleep(0.01)
                pid = racer_pid.get_nowait()
                # pg_blocking_pids reads the live lock graph (pg_stat_activity
                # would be frozen for this transaction).
                while not (
                    await container.session().execute(
                        sa.text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                        {"pid": pid},
                    )
                ).scalar_one():
                    if racer.done():
                        raise AssertionError(
                            "the second demotion did not wait for the first"
                        )
                    await asyncio.sleep(0.01)
        with pytest.raises(SpaceLastAdminError):
            await asyncio.wait_for(racer, timeout=10)
    finally:
        if racer is not None and not racer.done():
            racer.cancel()
            await asyncio.gather(racer, return_exceptions=True)

    assert await _space_roles(space_id) == {admin.id: "viewer", second.id: "admin"}
    changes = await audit_rows(action="space_oversight_member_role_changed")
    assert [row["metadata"]["extra"]["member"]["id"] for row in changes] == [
        str(admin.id)
    ]


async def test_a_stale_space_save_never_brings_back_a_removed_member(
    client, db_container, admin, overseer
):
    """A space loaded before an oversight removal and saved after it (a
    description edit, a new assistant) keeps the removal."""
    _, tenant_id = await admin_row()
    space_id = UUID(await create_space(client, admin.token))
    removed = await insert_user(tenant_id)
    await add_member(space_id, removed, "editor")
    group = await insert_group(tenant_id, [await insert_user(tenant_id)])
    await add_group(space_id, group, "editor")

    async with db_container() as container:
        repo = container.space_repo()
        stale = await repo.one(space_id)
        base = f"/api/v1/admin/spaces/{space_id}"
        for path in (f"{base}/members/{removed}/", f"{base}/group-members/{group}/"):
            resp = await client.delete(path, headers=overseer.headers)
            assert resp.status_code == 200, resp.text
        stale.description = "Uppdaterad beskrivning"
        await repo.update(stale)

    assert await member_row(space_id, removed) is None
    assert (
        await scalar(
            "SELECT count(*) FROM spaces_user_groups WHERE space_id = :s", s=space_id
        )
        == 0
    )
    assert (
        await scalar("SELECT description FROM spaces WHERE id = :s", s=space_id)
        == "Uppdaterad beskrivning"
    )


@pytest.mark.parametrize("kind", ["user", "group"])
async def test_a_member_change_waits_for_an_oversight_removal_and_keeps_it(
    client, db_container, admin, overseer, kind: str
):
    """A space admin's member change that starts while an oversight removal
    is uncommitted loads the members only after it commits, so its save
    cannot write the removed member back."""
    _, tenant_id = await admin_row()
    space_id = UUID(await create_space(client, admin.token))
    if kind == "user":
        removed, added = await insert_user(tenant_id), await insert_user(tenant_id)
        await add_member(space_id, removed, "editor")
    else:
        removed = await insert_group(tenant_id, [await insert_user(tenant_id)])
        added = await insert_group(tenant_id, [await insert_user(tenant_id)])
        await add_group(space_id, removed, "editor")
    async with db_container() as container:
        space_admin = await container.user_repo().get_user_by_id(admin.id)
        oversight_user = await container.user_repo().get_user_by_id(overseer.id)

    racer_pid: asyncio.Queue[int] = asyncio.Queue()

    async def space_admin_adds_a_member() -> None:
        async with db_container(user=space_admin) as container:
            pid = await container.session().scalar(sa.text("SELECT pg_backend_pid()"))
            racer_pid.put_nowait(pid)
            service = container.space_service()
            if kind == "user":
                await service.add_member(space_id, added, SpaceRoleValue.VIEWER)
            else:
                await service.add_group_member(space_id, added, SpaceRoleValue.VIEWER)

    racer: asyncio.Task[None] | None = None
    try:
        async with db_container(user=oversight_user) as container:
            oversight = container.space_oversight_service()
            if kind == "user":
                await oversight.remove_member(space_id, removed)
            else:
                await oversight.remove_group(space_id, removed)
            racer = asyncio.create_task(space_admin_adds_a_member())
            async with asyncio.timeout(10):
                while racer_pid.empty():
                    if racer.done():
                        racer.result()
                    await asyncio.sleep(0.01)
                pid = racer_pid.get_nowait()
                while not (
                    await container.session().execute(
                        sa.text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                        {"pid": pid},
                    )
                ).scalar_one():
                    if racer.done():
                        raise AssertionError(
                            "the member change did not wait for the removal"
                        )
                    await asyncio.sleep(0.01)
        await asyncio.wait_for(racer, timeout=10)
    finally:
        if racer is not None and not racer.done():
            racer.cancel()
            await asyncio.gather(racer, return_exceptions=True)

    if kind == "user":
        assert await _space_roles(space_id) == {admin.id: "admin", added: "viewer"}
    else:
        rows = await fetch(
            "SELECT user_group_id, role FROM spaces_user_groups WHERE space_id = :s",
            s=space_id,
        )
        assert {row[0]: row[1] for row in rows} == {added: "viewer"}


async def test_removal_revokes_the_members_space_keys(
    client, admin, overseer, make_person
):
    member = await make_person([Permission.API_KEYS], label="kollega")
    removed_from = await create_space(client, admin.token)
    kept_in = await create_space(client, admin.token)
    for space_id in (removed_from, kept_in):
        resp = await client.post(
            f"/api/v1/spaces/{space_id}/members/",
            json={"id": str(member.id), "role": "admin"},
            headers=admin.headers,
        )
        assert resp.status_code == 200, resp.text
    revoked = await create_user_key(
        client, member.token, scope_type="space", scope_id=removed_from
    )
    kept = await create_user_key(
        client, member.token, scope_type="space", scope_id=kept_in
    )

    resp = await client.delete(
        f"/api/v1/admin/spaces/{removed_from}/members/{member.id}/",
        headers=overseer.headers,
    )
    assert resp.status_code == 200, resp.text

    assert await key_state(revoked["id"]) == "revoked"
    assert await key_state(kept["id"]) == "active"
    resp = await client.get("/api/v1/admin/spaces/", headers=key(revoked["secret"]))
    assert resp.status_code in (401, 403), resp.text
    (row,) = await audit_rows(action="space_oversight_member_removed")
    assert row["metadata"]["extra"]["api_keys_revoked"] == 1


# --- join and leave -----------------------------------------------------------


async def _content_status(client, person: Person, space_id: str) -> list[int]:
    return [
        (await client.get(path, headers=person.headers)).status_code
        for path in (
            f"/api/v1/spaces/{space_id}/",
            f"/api/v1/spaces/{space_id}/knowledge/",
            f"/api/v1/spaces/{space_id}/applications/",
        )
    ]


async def _listed(client, person: Person, space_id: str) -> bool:
    resp = await client.get("/api/v1/spaces/", headers=person.headers)
    assert resp.status_code == 200, resp.text
    return space_id in {space["id"] for space in resp.json()["items"]}


async def test_join_leave_roundtrip(client, admin, overseer):
    space_id = await create_space(client, admin.token)
    assert await _content_status(client, overseer, space_id) == [403, 403, 403]
    assert not await _listed(client, overseer, space_id)

    # As admin: minting a space-scoped key needs it.
    resp = await _join(client, overseer, space_id, "admin")
    assert resp.status_code == 200, resp.text
    members = resp.json()
    own = _user(members, overseer.id)
    assert own["role"] == "admin"
    assert own["is_tenant_admin"] is True
    assert own["oversight_join"]["reason"] == REASON
    viewer = members["viewer_membership"]
    assert (viewer["role"], viewer["direct_role"], viewer["group_role"]) == (
        "admin",
        "admin",
        None,
    )
    assert viewer["oversight_joined_at"] == own["oversight_join"]["joined_at"]
    assert (viewer["joinable_roles"], viewer["can_leave"]) == ([], True)

    assert await _content_status(client, overseer, space_id) == [200, 200, 200]
    assert await _listed(client, overseer, space_id)
    own_key = await create_user_key(
        client, overseer.token, scope_type="space", scope_id=space_id
    )

    resp = await client.post(
        f"/api/v1/admin/spaces/{space_id}/leave/", headers=overseer.headers
    )
    assert resp.status_code == 200, resp.text
    assert _user(resp.json(), overseer.id) is None
    assert await _content_status(client, overseer, space_id) == [403, 403, 403]
    assert not await _listed(client, overseer, space_id)
    assert await key_state(own_key["id"]) == "revoked"

    joined, left = await audit_rows(entity_id=space_id)
    assert joined["action"] == "space_oversight_joined"
    assert joined["metadata"]["extra"] == {
        "oversight": {"actor_is_member": False, "actor_role": None},
        "role": "admin",
        "reason": REASON,
        "prior_group_role": None,
    }
    assert REASON not in joined["description"]
    assert left["action"] == "space_oversight_left"
    assert left["metadata"]["extra"] == {
        "oversight": {"actor_is_member": True, "actor_role": "admin"},
        "was_oversight_join": True,
        "remaining_group_role": None,
        "api_keys_revoked": 1,
    }


async def test_join_marker_is_visible_to_members_and_reason_only_to_space_admins(
    client, admin, overseer, make_person
):
    viewer = await make_person([], label="viewer")
    space_id = await create_space(client, admin.token)
    await add_member(space_id, viewer.id, "viewer")
    assert (await _join(client, overseer, space_id, "editor")).status_code == 200

    def marker(space: dict[str, Any]) -> dict[str, Any]:
        (member,) = [
            m for m in space["members"]["items"] if m["id"] == str(overseer.id)
        ]
        assert member["role"] == "editor"
        return member["oversight_join"]

    resp = await client.get(f"/api/v1/spaces/{space_id}/", headers=viewer.headers)
    assert resp.status_code == 200, resp.text
    seen_by_viewer = marker(resp.json())
    assert seen_by_viewer["joined_at"] is not None
    assert seen_by_viewer["reason"] is None

    resp = await client.get(f"/api/v1/spaces/{space_id}/", headers=admin.headers)
    assert resp.status_code == 200, resp.text
    assert marker(resp.json()) == {
        "joined_at": seen_by_viewer["joined_at"],
        "reason": REASON,
    }


async def test_members_still_see_a_join_after_the_admin_has_left(
    client, admin, overseer, make_person
):
    viewer = await make_person([], label="viewer")
    space_id = await create_space(client, admin.token)
    await add_member(space_id, viewer.id, "viewer")

    assert (await _join(client, overseer, space_id, "editor")).status_code == 200
    resp = await client.post(
        f"/api/v1/admin/spaces/{space_id}/leave/", headers=overseer.headers
    )
    assert resp.status_code == 200, resp.text

    for reader, reason in ((viewer, None), (admin, REASON)):
        resp = await client.get(f"/api/v1/spaces/{space_id}/", headers=reader.headers)
        assert resp.status_code == 200, resp.text
        (visit,) = resp.json()["oversight_visits"]
        assert visit["person"] == {"id": str(overseer.id), "name": overseer.username}
        assert visit["role"] == "editor"
        assert visit["left_at"] is not None
        assert visit["joined_at"] <= visit["left_at"]
        assert visit["reason"] == reason


async def test_a_visit_ends_however_the_membership_goes(
    client, admin, overseer, make_person
):
    colleague = await make_person([Permission.ADMIN], label="second-overseer")
    space_id = await create_space(client, admin.token)

    # Removed by another tenant admin, then by the space's own admin.
    assert (await _join(client, overseer, space_id)).status_code == 200
    resp = await client.delete(
        f"/api/v1/admin/spaces/{space_id}/members/{overseer.id}/",
        headers=colleague.headers,
    )
    assert resp.status_code == 200, resp.text
    assert (await _join(client, overseer, space_id, "admin")).status_code == 200
    resp = await client.delete(
        f"/api/v1/spaces/{space_id}/members/{overseer.id}/", headers=admin.headers
    )
    assert resp.status_code == 204, resp.text

    rows = await fetch(
        "SELECT role, reason, joined_at, left_at FROM space_oversight_visits"
        " WHERE space_id = :s AND user_id = :u ORDER BY joined_at",
        s=space_id,
        u=overseer.id,
    )
    assert [(row[0], row[1]) for row in rows] == [
        ("viewer", REASON),
        ("admin", REASON),
    ]
    assert all(row[3] is not None and row[3] >= row[2] for row in rows)


async def _delete_account(how: str, client, admin: Person, db_container, user_id: UUID):
    if how == "admin_api":
        resp = await client.delete(
            f"/api/v1/users/admin/{user_id}/", headers=admin.headers
        )
        assert resp.status_code == 204, resp.text
    elif how == "hard_delete":
        async with db_container() as container:
            await container.user_repo().hard_delete(user_id)
    else:
        _, tenant_id = await admin_row()
        scim_app.dependency_overrides[require_scim_auth] = lambda: tenant_id
        try:
            if how == "scim_delete":
                resp = await client.delete(f"/scim/v2/Users/{user_id}")
                assert resp.status_code == 204, resp.text
            else:
                resp = await client.patch(
                    f"/scim/v2/Users/{user_id}",
                    json={
                        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                        "Operations": [
                            {"op": "replace", "path": "active", "value": False}
                        ],
                    },
                )
                assert resp.status_code == 200, resp.text
        finally:
            scim_app.dependency_overrides.pop(require_scim_auth, None)


@pytest.mark.parametrize(
    "how", ["admin_api", "scim_delete", "scim_patch_inactive", "hard_delete"]
)
async def test_a_visit_ends_when_the_account_is_deleted(
    client, admin, overseer, db_container, how
):
    space_id = await create_space(client, admin.token)
    other_space_id = await create_space(client, admin.token)
    await add_member(other_space_id, overseer.id, "editor")
    assert (await _join(client, overseer, space_id)).status_code == 200

    await _delete_account(how, client, admin, db_container, overseer.id)

    (visit_row,) = await fetch(
        "SELECT joined_at, left_at FROM space_oversight_visits WHERE space_id = :s",
        s=space_id,
    )
    assert visit_row.left_at is not None
    assert visit_row.left_at >= visit_row.joined_at
    # A restored account does not come back through its oversight join.
    assert await member_row(space_id, overseer.id) is None
    if how != "hard_delete":
        other = await member_row(other_space_id, overseer.id)
        assert other is not None and other.role == "editor"

    resp = await client.get(f"/api/v1/spaces/{space_id}/", headers=admin.headers)
    assert resp.status_code == 200, resp.text
    (visit,) = resp.json()["oversight_visits"]
    assert (visit["person"], visit["role"], visit["reason"]) == (
        None,
        "viewer",
        REASON,
    )
    assert visit["left_at"] is not None


async def test_members_see_visits_that_ended_in_the_last_ninety_days(
    client, admin, overseer
):
    _, tenant_id = await admin_row()
    space_id = await create_space(client, admin.token)
    # Visits left open by an account deleted before deletion closed them.
    deleted = await insert_user(tenant_id, deleted=True)
    deleted_long_ago = await insert_user(tenant_id, deleted=True)
    await execute(
        "UPDATE users SET deleted_at = :d WHERE id = :u",
        d=days_ago(95),
        u=deleted_long_ago,
    )
    for user_id, role, joined, left in (
        (overseer.id, "viewer", days_ago(130), days_ago(100)),
        (overseer.id, "editor", days_ago(100), days_ago(80)),
        (deleted, "admin", days_ago(10), None),
        (deleted_long_ago, "viewer", days_ago(120), None),
    ):
        await execute(
            "INSERT INTO space_oversight_visits (tenant_id, space_id, user_id,"
            " role, reason, joined_at, left_at)"
            " VALUES (:t, :s, :u, :r, :reason, :j, :l)",
            t=tenant_id,
            s=space_id,
            u=user_id,
            r=role,
            reason=REASON,
            j=joined,
            l=left,
        )

    resp = await client.get(f"/api/v1/spaces/{space_id}/", headers=admin.headers)
    assert resp.status_code == 200, resp.text
    # A deleted person's visit ended with the account.
    assert [
        (visit["role"], visit["person"], visit["left_at"] is None)
        for visit in resp.json()["oversight_visits"]
    ] == [
        ("admin", None, False),
        ("editor", {"id": str(overseer.id), "name": overseer.username}, False),
    ]


async def test_normal_space_update_keeps_the_marker(client, admin, overseer):
    space_id = await create_space(client, admin.token)
    assert (await _join(client, overseer, space_id)).status_code == 200
    joined = await member_row(space_id, overseer.id)
    assert joined.oversight_join_reason == REASON

    resp = await client.patch(
        f"/api/v1/spaces/{space_id}/",
        json={"description": "Uppdaterad beskrivning"},
        headers=admin.headers,
    )
    assert resp.status_code == 200, resp.text
    row = await member_row(space_id, overseer.id)
    assert (row.oversight_joined_at, row.oversight_join_reason) == (
        joined.oversight_joined_at,
        REASON,
    )

    resp = await client.patch(
        f"/api/v1/spaces/{space_id}/members/{overseer.id}/",
        json={"role": "editor"},
        headers=admin.headers,
    )
    assert resp.status_code == 200, resp.text
    row = await member_row(space_id, overseer.id)
    assert row.role == "editor"
    assert (row.oversight_joined_at, row.oversight_join_reason) == (
        joined.oversight_joined_at,
        REASON,
    )
    detail = await _detail(client, overseer, space_id)
    assert _user(detail["members"], overseer.id)["oversight_join"]["reason"] == REASON

    resp = await client.delete(
        f"/api/v1/spaces/{space_id}/members/{overseer.id}/", headers=admin.headers
    )
    assert resp.status_code == 204, resp.text
    assert await member_row(space_id, overseer.id) is None
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/members/",
        json={"id": str(overseer.id), "role": "viewer"},
        headers=admin.headers,
    )
    assert resp.status_code == 200, resp.text
    row = await member_row(space_id, overseer.id)
    assert (row.oversight_joined_at, row.oversight_join_reason) == (None, None)


async def test_group_only_member_can_join_above_group_role(client, admin, overseer):
    _, tenant_id = await admin_row()
    space_id = await create_space(client, admin.token)
    group = await insert_group(tenant_id, [overseer.id])
    await add_group(space_id, group, "viewer")
    viewer = (await _detail(client, overseer, space_id))["members"]["viewer_membership"]
    assert viewer["joinable_roles"] == ["editor", "admin"]

    resp = await _join(client, overseer, space_id, "editor")
    assert resp.status_code == 200, resp.text
    viewer = resp.json()["viewer_membership"]
    assert (viewer["role"], viewer["direct_role"], viewer["group_role"]) == (
        "editor",
        "editor",
        "viewer",
    )
    assert viewer["joinable_roles"] == []
    (joined,) = await audit_rows(action="space_oversight_joined")
    assert joined["metadata"]["extra"]["prior_group_role"] == "viewer"
    assert joined["metadata"]["extra"]["oversight"] == {
        "actor_is_member": True,
        "actor_role": "viewer",
    }

    resp = await client.post(
        f"/api/v1/admin/spaces/{space_id}/leave/", headers=overseer.headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["viewer_membership"]["role"] == "viewer"
    (left,) = await audit_rows(action="space_oversight_left")
    assert left["metadata"]["extra"]["remaining_group_role"] == "viewer"


async def test_group_only_member_joining_below_is_refused(client, admin, overseer):
    _, tenant_id = await admin_row()
    space_id = await create_space(client, admin.token)
    group = await insert_group(tenant_id, [overseer.id])
    await add_group(space_id, group, "editor")

    for role in ("viewer", "editor"):
        resp = await _join(client, overseer, space_id, role)
        assert resp.status_code == 400, resp.text
    await execute(
        "UPDATE spaces_user_groups SET role = 'admin' WHERE user_group_id = :g", g=group
    )
    viewer = (await _detail(client, overseer, space_id))["members"]["viewer_membership"]
    assert viewer["joinable_roles"] == []
    assert (await _join(client, overseer, space_id, "admin")).status_code == 400
    resp = await client.post(
        f"/api/v1/admin/spaces/{space_id}/leave/", headers=overseer.headers
    )
    assert resp.status_code == 400, resp.text

    await add_member(space_id, overseer.id, "viewer")
    resp = await _join(client, overseer, space_id, "admin")
    assert (resp.status_code, error_code(resp)) == (409, 9066), resp.text
    assert await member_row(space_id, overseer.id) is not None
    assert await audit_rows() == []


# --- audit ----------------------------------------------------------------------


async def test_oversight_actions_are_always_logged(
    client, db_container, admin, overseer, make_person
):
    _, tenant_id = await admin_row()
    person = await make_person([], label="kollega")
    group = await insert_group(tenant_id, [person.id])
    space_id = await create_space(client, admin.token)
    await execute(
        "UPDATE global_feature_flags SET enabled = false"
        " WHERE name = 'audit_logging_enabled'"
    )
    await execute(
        "INSERT INTO audit_category_config (id, tenant_id, category, enabled,"
        " action_overrides)"
        " VALUES (gen_random_uuid(), :t, 'admin_actions', false, CAST(:o AS jsonb))"
        " ON CONFLICT (tenant_id, category) DO UPDATE"
        " SET enabled = false, action_overrides = EXCLUDED.action_overrides",
        t=tenant_id,
        o=json.dumps({action: False for action in OVERSIGHT_ACTIONS}),
    )

    # Control: with these settings an ordinary admin action is not logged.
    async with db_container() as container:
        admin_user = await container.user_repo().get_user_by_id(admin.id)
        written = await container.audit_service().log(
            tenant_id=tenant_id,
            user=admin_user,
            action=ActionType.WIDGET_ACTIVATION_REQUESTED,
            entity_type=EntityType.WIDGET,
            entity_id=uuid4(),
            description="control",
            metadata={},
        )
    assert written is None

    base = f"/api/v1/admin/spaces/{space_id}"
    for method, path, body in (
        ("POST", f"{base}/members/", {"user_id": str(person.id), "role": "viewer"}),
        ("PATCH", f"{base}/members/{person.id}/", {"role": "editor"}),
        ("DELETE", f"{base}/members/{person.id}/", None),
        ("POST", f"{base}/group-members/", {"group_id": str(group), "role": "viewer"}),
        ("DELETE", f"{base}/group-members/{group}/", None),
        ("POST", f"{base}/join/", {"role": "viewer", "reason": REASON}),
        ("POST", f"{base}/leave/", None),
    ):
        resp = await client.request(method, path, json=body, headers=overseer.headers)
        assert resp.status_code in (200, 201), (path, resp.text)

    assert [row["action"] for row in await audit_rows(entity_id=space_id)] == [
        "space_oversight_member_added",
        "space_oversight_member_role_changed",
        "space_oversight_member_removed",
        "space_oversight_member_added",
        "space_oversight_member_removed",
        "space_oversight_joined",
        "space_oversight_left",
    ]


async def test_audit_failure_rolls_back_the_change(
    raw_client, admin, overseer, monkeypatch
):
    _, tenant_id = await admin_row()
    space_id = await create_space(raw_client, admin.token)
    member = await insert_user(tenant_id)
    await add_member(space_id, member, "viewer")

    async def unavailable(self: object, *args: object, **kwargs: object) -> None:
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(AuditLogRepositoryImpl, "create", unavailable)

    resp = await _join(raw_client, overseer, space_id)
    assert resp.status_code == 500, resp.text
    assert await member_row(space_id, overseer.id) is None

    resp = await raw_client.delete(
        f"/api/v1/admin/spaces/{space_id}/members/{member}/", headers=overseer.headers
    )
    assert resp.status_code == 500, resp.text
    assert (await member_row(space_id, member)).role == "viewer"
    assert await audit_rows() == []


async def test_a_rolled_back_removal_leaves_no_key_revocation_entry(
    raw_client, admin, overseer, make_person, monkeypatch
):
    member = await make_person([Permission.API_KEYS], label="kollega")
    space_id = await create_space(raw_client, admin.token)
    resp = await raw_client.post(
        f"/api/v1/spaces/{space_id}/members/",
        json={"id": str(member.id), "role": "admin"},
        headers=admin.headers,
    )
    assert resp.status_code == 200, resp.text
    member_key = await create_user_key(
        raw_client, member.token, scope_type="space", scope_id=space_id
    )

    queued: list[ActionType] = []
    log_async = AuditService.log_async

    async def record(self: AuditService, **kwargs: Any) -> Any:
        queued.append(kwargs["action"])
        return await log_async(self, **kwargs)

    async def unavailable(self: object, **kwargs: object) -> None:
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(AuditService, "log_async", record)
    monkeypatch.setattr(AuditService, "log_required", unavailable)

    resp = await raw_client.delete(
        f"/api/v1/admin/spaces/{space_id}/members/{member.id}/",
        headers=overseer.headers,
    )
    assert resp.status_code == 500, resp.text
    assert await key_state(member_key["id"]) == "active"
    assert (await member_row(space_id, member.id)).role == "admin"
    assert ActionType.API_KEY_REVOKED not in queued
    assert (
        await scalar("SELECT count(*) FROM audit_logs WHERE action = 'api_key_revoked'")
        == 0
    )


async def test_reason_is_normalised_in_audit_and_column(client, admin, overseer):
    space_id = await create_space(client, admin.token)
    base = f"/api/v1/admin/spaces/{space_id}"
    for too_short_or_long in (
        "  kort\u200b\r\n ",
        "x" * 501,
        # Nine once the zero-width space is gone and e + U+0301 composes: a
        # 422, never an IntegrityError from the CHECK on the stored reason.
        "abcdefgh" + "e\u200b\u0301",
        "\u2060" * 10,
        "\ufeff" * 10,
        "\u2800" * 10,
    ):
        resp = await client.post(
            f"{base}/join/",
            json={"role": "viewer", "reason": too_short_or_long},
            headers=overseer.headers,
        )
        assert resp.status_code == 422, resp.text

    raw = "  Ärende KS\r\n2026/123\tkontroll av​‪ underlag\u0007  "
    resp = await client.post(
        f"{base}/join/",
        json={"role": "viewer", "reason": raw},
        headers=overseer.headers,
    )
    assert resp.status_code == 200, resp.text

    expected = "Ärende KS 2026/123 kontroll av underlag"
    assert (await member_row(space_id, overseer.id)).oversight_join_reason == expected
    assert _user(resp.json(), overseer.id)["oversight_join"]["reason"] == expected
    (joined,) = await audit_rows(action="space_oversight_joined")
    assert joined["metadata"]["extra"]["reason"] == expected
    assert "underlag" not in joined["description"]


# --- API keys -----------------------------------------------------------------


async def test_admin_api_key_can_read(client, admin):
    space_id = await create_space(client, admin.token)
    assistant_id = await create_assistant(client, admin.token, space_id)
    widget = await create_widget(client, admin.token, space_id, assistant_id)
    tenant_admin_key = key(await create_service_key(client, admin.token))
    space_key = key(
        await create_service_key(
            client, admin.token, scope_type="space", scope_id=space_id
        )
    )

    for path in (
        "/api/v1/admin/spaces/",
        f"/api/v1/admin/spaces/{space_id}/",
        f"/api/v1/admin/widgets/{widget['id']}/",
    ):
        resp = await client.get(path, headers=tenant_admin_key)
        assert resp.status_code == 200, (path, resp.text)
        resp = await client.get(path, headers=space_key)
        assert resp.status_code == 403, (path, resp.text)


MUTATION_ROUTES = range(ROUTE_NAMES.index("M1"), len(ROUTE_NAMES))


@pytest.mark.parametrize(
    "route", MUTATION_ROUTES, ids=[ROUTE_NAMES[i] for i in MUTATION_ROUTES]
)
async def test_admin_api_key_cannot_mutate(client, admin, overseer, route):
    """Every member change and the join are session-only: a tenant-admin key
    is refused before anything is read or written."""
    space_id = await create_space(client, admin.token)
    group = await insert_group((await admin_row())[1], [overseer.id])
    await add_group(space_id, group, "viewer")
    tenant_admin_key = key(await create_service_key(client, admin.token))
    method, path, body = _routes(space_id, overseer.id)[route]
    if ROUTE_NAMES[route] in ("M4", "M5", "M6"):
        method, path, body = _routes(space_id, group)[route]

    resp = await client.request(method, path, json=body, headers=tenant_admin_key)
    assert resp.status_code == 403, (path, resp.text)
    assert "session_auth_required" in resp.text, resp.text

    assert await _space_roles(space_id) == {admin.id: "admin"}
    assert (
        await scalar(
            "SELECT role FROM spaces_user_groups WHERE space_id = :s", s=space_id
        )
        == "viewer"
    )
    assert await audit_rows() == []
