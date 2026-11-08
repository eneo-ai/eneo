"""A space's group members carry their user count without loading the users."""

import re
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import usergroups_users_table
from tests.integration.flows.statement_capture_support import (
    CapturedStatement,
    capture_queries,
)

pytestmark = pytest.mark.integration

# A group's users loaded as rows: user columns read through the group link.
# The caller's own groups, read as group columns through the same link, are not.
_GROUP_USER_ROWS = re.compile(r"\busers(_\d+)?\.email AS\b")


@pytest.fixture
async def owner_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _group_user_reads(queries: list[CapturedStatement]) -> list[str]:
    return [
        query.sql
        for query in queries
        if "usergroups_users" in query.sql and _GROUP_USER_ROWS.search(query.sql)
    ]


async def test_group_user_count_is_counted_not_loaded(
    client, db_container, admin_user, owner_token, user_factory
) -> None:
    created = await client.post(
        "/api/v1/spaces/",
        json={"name": f"groups-{uuid4().hex[:6]}"},
        headers=_auth(owner_token),
    )
    assert created.status_code == 201, created.text
    space_id = created.json()["id"]

    async with db_container() as container:
        session = container.session()
        members = [await user_factory(session) for _ in range(3)]
        # A soft-deleted member still counts, as it did when the users were loaded.
        members.append(
            await user_factory(session, deleted_at=datetime.now(timezone.utc))
        )
        large = UserGroups(name=f"large-{uuid4()}", tenant_id=admin_user.tenant_id)
        empty = UserGroups(name=f"empty-{uuid4()}", tenant_id=admin_user.tenant_id)
        session.add_all([large, empty])
        await session.flush()
        await session.execute(
            sa.insert(usergroups_users_table),
            [dict(user_id=user.id, user_group_id=large.id) for user in members],
        )
        large_id, empty_id = str(large.id), str(empty.id)

    async with db_container() as container:
        bind = container.session().sync_session.bind
    assert bind is not None

    with capture_queries(bind.engine) as added_queries:
        added = await client.post(
            f"/api/v1/spaces/{space_id}/group-members/",
            json={"id": large_id, "role": "editor"},
            headers=_auth(owner_token),
        )
    assert added.status_code == 201, added.text
    assert added.json()["user_count"] == 4

    added_empty = await client.post(
        f"/api/v1/spaces/{space_id}/group-members/",
        json={"id": empty_id, "role": "viewer"},
        headers=_auth(owner_token),
    )
    assert added_empty.status_code == 201, added_empty.text
    assert added_empty.json()["user_count"] == 0

    with capture_queries(bind.engine) as read_queries:
        read = await client.get(
            f"/api/v1/spaces/{space_id}/", headers=_auth(owner_token)
        )
    assert read.status_code == 200, read.text
    counts = {
        item["id"]: item["user_count"] for item in read.json()["group_members"]["items"]
    }
    assert counts == {large_id: 4, empty_id: 0}

    listed = await client.get(
        f"/api/v1/spaces/{space_id}/group-members/", headers=_auth(owner_token)
    )
    assert listed.status_code == 200, listed.text
    assert {item["id"]: item["user_count"] for item in listed.json()["items"]} == counts

    assert _group_user_reads(added_queries) == []
    assert _group_user_reads(read_queries) == []
