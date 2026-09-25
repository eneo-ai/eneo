"""User group membership is always logged.

A group's role in a space gives every member of the group that space's
content, so adding yourself to a group is a route to content that bypasses
the oversight join. It needs only the admin permission; what makes it
reviewable is an audit entry the tenant cannot turn off, written in the
change's transaction, that names the spaces the group reaches.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from eneo.audit.application.audit_service import AuditService
from eneo.roles.permissions import Permission
from tests.integration.space_oversight.support import (
    Person,
    add_group,
    admin_row,
    create_space,
    execute,
    fetch,
    insert_group,
    insert_user,
    new_person,
    scalar,
    seeded_admin,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

MEMBER_ACTIONS = ("user_group_member_added", "user_group_member_removed")


@pytest.fixture
async def admin(db_container, patch_auth_service_jwt) -> Person:
    return await seeded_admin(db_container)


@pytest.fixture
async def overseer(db_container, patch_auth_service_jwt) -> Person:
    """A tenant admin who is a member of no space and no group."""
    return await new_person(db_container, [Permission.ADMIN], label="overseer")


@pytest.fixture
async def raw_client(app) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test.local",
    ) as client:
        yield client


async def _entries() -> list[dict[str, Any]]:
    rows = await fetch(
        "SELECT action, entity_type, entity_id, actor_id, description, metadata"
        " FROM audit_logs WHERE action LIKE 'user_group_member_%'"
        " ORDER BY timestamp, id"
    )
    columns = ("action", "entity_type", "entity_id", "actor_id", "description")
    return [{**dict(zip(columns, row[:5])), "metadata": row[5]} for row in rows]


async def _silence_audit(tenant_id: UUID) -> None:
    """The kill switch off and every admin action turned off."""
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
        o=json.dumps({action: False for action in MEMBER_ACTIONS}),
    )


async def _group_members(group_id: UUID) -> set[UUID]:
    rows = await fetch(
        "SELECT user_id FROM usergroups_users WHERE user_group_id = :g", g=group_id
    )
    return {row[0] for row in rows}


async def test_adding_yourself_to_a_group_with_a_space_role_is_always_logged(
    client, admin, overseer
):
    _, tenant_id = await admin_row()
    space_id = await create_space(client, admin.token, name="Socialtjänst IFO")
    group = await insert_group(tenant_id, [], name="IFO-handläggare")
    await add_group(space_id, group, "editor")
    await _silence_audit(tenant_id)
    space = f"/api/v1/spaces/{space_id}/"
    membership = f"/api/v1/user-groups/{group}/users/{overseer.id}/"

    assert (await client.get(space, headers=overseer.headers)).status_code == 403
    resp = await client.post(membership, headers=overseer.headers)
    assert resp.status_code == 200, resp.text
    assert (await client.get(space, headers=overseer.headers)).status_code == 200
    resp = await client.delete(membership, headers=overseer.headers)
    assert resp.status_code == 200, resp.text
    assert (await client.get(space, headers=overseer.headers)).status_code == 403

    added, removed = await _entries()
    member = {
        "id": str(overseer.id),
        "name": overseer.username,
        "email": overseer.email,
    }
    reach = [{"id": space_id, "name": "Socialtjänst IFO", "role": "editor"}]
    for entry, action in (
        (added, "user_group_member_added"),
        (removed, "user_group_member_removed"),
    ):
        assert entry["action"] == action
        assert (entry["entity_type"], entry["entity_id"]) == ("user_group", group)
        assert entry["actor_id"] == overseer.id
        assert entry["metadata"]["target"]["name"] == "IFO-handläggare"
        assert entry["metadata"]["extra"] == {"member": member, "spaces": reach}
    assert added["description"] == (
        f"Added {overseer.username} to user group 'IFO-handläggare'"
    )


async def test_replacing_a_groups_users_logs_everyone_added_and_removed(
    client, admin, overseer
):
    _, tenant_id = await admin_row()
    kept = await insert_user(tenant_id)
    dropped = await insert_user(tenant_id)
    joined = await insert_user(tenant_id)
    group = await insert_group(tenant_id, [kept, dropped], name="Ekonomistöd")

    resp = await client.post(
        f"/api/v1/user-groups/{group}/",
        json={"users": [{"id": str(kept)}, {"id": str(joined)}]},
        headers=overseer.headers,
    )
    assert resp.status_code == 200, resp.text

    assert await _group_members(group) == {kept, joined}
    assert [
        (entry["action"], UUID(entry["metadata"]["extra"]["member"]["id"]))
        for entry in await _entries()
    ] == [("user_group_member_added", joined), ("user_group_member_removed", dropped)]
    assert all(entry["metadata"]["extra"]["spaces"] == [] for entry in await _entries())


async def test_a_membership_change_without_its_audit_entry_is_not_made(
    raw_client, overseer, monkeypatch
):
    _, tenant_id = await admin_row()
    member = await insert_user(tenant_id)
    group = await insert_group(tenant_id, [member])

    async def unavailable(self: object, **kwargs: object) -> None:
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(AuditService, "log_required", unavailable)

    resp = await raw_client.post(
        f"/api/v1/user-groups/{group}/users/{overseer.id}/", headers=overseer.headers
    )
    assert resp.status_code == 500, resp.text
    resp = await raw_client.delete(
        f"/api/v1/user-groups/{group}/users/{member}/", headers=overseer.headers
    )
    assert resp.status_code == 500, resp.text

    assert await _group_members(group) == {member}
    assert (
        await scalar(
            "SELECT count(*) FROM audit_logs WHERE action LIKE 'user_group_member_%'"
        )
        == 0
    )
