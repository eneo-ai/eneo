"""Integration tests for SCIM group repository and HTTP endpoints.

Repository tests create groups and users directly in the DB (with all required
fields including tenant_id) and query via ScimGroupRepository.
All ORM attribute access happens inside the session context to avoid
DetachedInstanceError (SQLAlchemy expires objects after session closes).

HTTP tests exercise the full stack through the mounted scim_app.
Known implementation gaps are documented with pytest.mark.xfail.

Implementation gaps found during these tests:
- UserGroups table has no 'members' attribute; it is called 'users'.
  _to_scim_group() iterates model.members → AttributeError on any response that
  includes a group.
- ScimGroupRepository.delete() performs a hard delete; groups should probably be
  soft-deleted to preserve history.
"""

import uuid

import pytest
from dependency_injector import providers
from sqlalchemy import func, select

from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import Users, usergroups_users_table
from eneo.main.container.container import Container
from eneo.scim.repositories.group_repository import ScimGroupRepository
from eneo.scim.schemas.common import ScimFilter, ScimSort
from eneo.tenants.tenant import TenantBase

# ---------------------------------------------------------------------------
# Repository-level integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_returns_all_groups(db_session, test_tenant):
    """list() returns groups for the given tenant."""
    async with db_session() as session:
        session.add(UserGroups(name="Group Alpha", tenant_id=test_tenant.id))
        session.add(UserGroups(name="Group Beta", tenant_id=test_tenant.id))

    async with db_session() as session:
        repo = ScimGroupRepository(session)
        groups = await repo.list(tenant_id=test_tenant.id)
        names = {g.name for g in groups}

    assert "Group Alpha" in names
    assert "Group Beta" in names


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_filter_displayname_eq(db_session, test_tenant):
    """list() with eq filter on displayName returns only the matching group."""
    async with db_session() as session:
        session.add(UserGroups(name="Engineering", tenant_id=test_tenant.id))
        session.add(UserGroups(name="Marketing", tenant_id=test_tenant.id))

    async with db_session() as session:
        repo = ScimGroupRepository(session)
        groups = await repo.list(
            tenant_id=test_tenant.id,
            scim_filter=ScimFilter(
                attribute="displayName", operator="eq", value="Engineering"
            ),
        )
        count = len(groups)
        first_name = groups[0].name if groups else None

    assert count == 1
    assert first_name == "Engineering"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_filter_displayname_co(db_session, test_tenant):
    """list() with co (contains) filter on displayName performs case-insensitive match."""
    async with db_session() as session:
        session.add(UserGroups(name="Product Owners", tenant_id=test_tenant.id))
        session.add(UserGroups(name="Product Managers", tenant_id=test_tenant.id))
        session.add(UserGroups(name="Sales", tenant_id=test_tenant.id))

    async with db_session() as session:
        repo = ScimGroupRepository(session)
        groups = await repo.list(
            tenant_id=test_tenant.id,
            scim_filter=ScimFilter(
                attribute="displayName", operator="co", value="Product"
            ),
        )
        names = {g.name for g in groups}

    assert "Product Owners" in names
    assert "Product Managers" in names
    assert "Sales" not in names


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_filter_unsupported_attribute_raises_invalid_filter(
    db_session, test_tenant
):
    """RFC 7644 §3.4.2.2: unsupported filter attributes must surface as 400
    invalidFilter rather than silently returning all groups in the tenant."""
    from eneo.scim.domain.errors import ScimInvalidFilterError

    async with db_session() as session:
        repo = ScimGroupRepository(session)
        with pytest.raises(ScimInvalidFilterError, match="members.value"):
            await repo.list(
                tenant_id=test_tenant.id,
                scim_filter=ScimFilter(
                    attribute="members.value", operator="eq", value="some-user-id"
                ),
            )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_sort_ascending_by_displayname(db_session, test_tenant):
    """list() with sort ascending on displayName returns results in ascending order."""
    async with db_session() as session:
        for name in ("Zebra", "Apple", "Mango"):
            session.add(UserGroups(name=name, tenant_id=test_tenant.id))

    async with db_session() as session:
        repo = ScimGroupRepository(session)
        groups = await repo.list(
            tenant_id=test_tenant.id,
            scim_sort=ScimSort(attribute="displayName", order="ascending"),
        )
        names = [g.name for g in groups if g.name in ("Zebra", "Apple", "Mango")]

    assert names == sorted(names)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_by_id_returns_group(db_session, scim_group):
    """get_by_id() returns the group with the given UUID."""
    async with db_session() as session:
        repo = ScimGroupRepository(session)
        result = await repo.get_by_id(scim_group.id, tenant_id=scim_group.tenant_id)
        found_id = result.id if result else None
        found_name = result.name if result else None

    assert found_id == scim_group.id
    assert found_name == scim_group.name


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_by_id_returns_none_for_unknown(db_session, test_tenant):
    """get_by_id() returns None for a UUID that doesn't exist."""
    async with db_session() as session:
        repo = ScimGroupRepository(session)
        result = await repo.get_by_id(uuid.uuid4(), tenant_id=test_tenant.id)

    assert result is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_by_id_returns_none_for_wrong_tenant(db_session, scim_group):
    """get_by_id() returns None when tenant_id doesn't match the group's tenant."""
    async with db_session() as session:
        repo = ScimGroupRepository(session)
        result = await repo.get_by_id(scim_group.id, tenant_id=uuid.uuid4())

    assert result is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_by_name_returns_group(db_session, scim_group):
    """get_by_name() returns the group with the given name."""
    async with db_session() as session:
        repo = ScimGroupRepository(session)
        result = await repo.get_by_name(scim_group.name, tenant_id=scim_group.tenant_id)
        found_name = result.name if result else None

    assert found_name == scim_group.name


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_user_ids_in_tenant_excludes_other_tenants(db_session, test_tenant):
    """get_user_ids_in_tenant() only returns IDs owned by the requested tenant."""
    async with db_session() as session:
        container = Container(session=providers.Object(session))
        tenant_service = container.tenant_service()
        other_tenant = await tenant_service.create_tenant(
            TenantBase(name="tenant_member_scope_scim", slug="tenant-member-scope-scim")
        )
        same_tenant_user = Users(
            email="same-tenant-member@example.com",
            username="same.tenant.member",
            state="active",
            tenant_id=test_tenant.id,
        )
        other_tenant_user = Users(
            email="other-tenant-member@example.com",
            username="other.tenant.member",
            state="active",
            tenant_id=other_tenant.id,
        )
        session.add(same_tenant_user)
        session.add(other_tenant_user)
        await session.flush()
        same_tenant_user_id = same_tenant_user.id
        other_tenant_user_id = other_tenant_user.id

    async with db_session() as session:
        repo = ScimGroupRepository(session)
        result = await repo.get_user_ids_in_tenant(
            [same_tenant_user_id, other_tenant_user_id],
            tenant_id=test_tenant.id,
        )

    assert same_tenant_user_id in result
    assert other_tenant_user_id not in result


@pytest.mark.asyncio
@pytest.mark.integration
async def test_add_member_links_user_to_group(db_session, scim_user, scim_group):
    """add_member() inserts a row in the usergroups_users junction table."""
    async with db_session() as session:
        repo = ScimGroupRepository(session)
        await repo.add_member(
            scim_group.id, scim_user.id, tenant_id=scim_group.tenant_id
        )

    async with db_session() as session:
        result = await session.execute(
            select(usergroups_users_table).where(
                usergroups_users_table.c.user_group_id == scim_group.id,
                usergroups_users_table.c.user_id == scim_user.id,
            )
        )
        row_exists = result.first() is not None

    assert row_exists, "Junction row must exist after add_member"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_add_member_is_idempotent(db_session, scim_user, scim_group):
    """add_member() called twice does not create duplicate junction rows."""
    async with db_session() as session:
        repo = ScimGroupRepository(session)
        await repo.add_member(
            scim_group.id, scim_user.id, tenant_id=scim_group.tenant_id
        )

    async with db_session() as session:
        repo = ScimGroupRepository(session)
        await repo.add_member(
            scim_group.id, scim_user.id, tenant_id=scim_group.tenant_id
        )

    async with db_session() as session:
        result = await session.execute(
            select(func.count()).where(
                usergroups_users_table.c.user_group_id == scim_group.id,
                usergroups_users_table.c.user_id == scim_user.id,
            )
        )
        count = result.scalar_one()

    assert count == 1, "ON CONFLICT DO NOTHING must prevent duplicates"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_remove_member_unlinks_user(db_session, scim_user, scim_group):
    """remove_member() deletes the junction row between user and group."""
    async with db_session() as session:
        repo = ScimGroupRepository(session)
        await repo.add_member(
            scim_group.id, scim_user.id, tenant_id=scim_group.tenant_id
        )

    async with db_session() as session:
        repo = ScimGroupRepository(session)
        await repo.remove_member(
            scim_group.id, scim_user.id, tenant_id=scim_group.tenant_id
        )

    async with db_session() as session:
        result = await session.execute(
            select(usergroups_users_table).where(
                usergroups_users_table.c.user_group_id == scim_group.id,
                usergroups_users_table.c.user_id == scim_user.id,
            )
        )
        row_exists = result.first() is not None

    assert not row_exists, "Junction row must be gone after remove_member"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_set_members_replaces_all_members(db_session, test_tenant, scim_group):
    """set_members() replaces the full member list atomically."""
    async with db_session() as session:
        user_a = Users(
            email="member-a@example.com",
            username="member.a",
            state="active",
            tenant_id=test_tenant.id,
        )
        user_b = Users(
            email="member-b@example.com",
            username="member.b",
            state="active",
            tenant_id=test_tenant.id,
        )
        session.add(user_a)
        session.add(user_b)
        await session.flush()
        uid_a = user_a.id
        uid_b = user_b.id

    async with db_session() as session:
        repo = ScimGroupRepository(session)
        await repo.set_members(scim_group.id, [uid_a], tenant_id=scim_group.tenant_id)

    async with db_session() as session:
        repo = ScimGroupRepository(session)
        await repo.set_members(scim_group.id, [uid_b], tenant_id=scim_group.tenant_id)

    async with db_session() as session:
        result = await session.execute(
            select(usergroups_users_table.c.user_id).where(
                usergroups_users_table.c.user_group_id == scim_group.id
            )
        )
        member_ids = {row[0] for row in result}

    assert uid_b in member_ids, "set_members() should add user_b"
    assert uid_a not in member_ids, "set_members() should remove user_a"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_set_members_with_empty_list_removes_all(
    db_session, scim_user, scim_group
):
    """set_members([]) removes all members from the group."""
    async with db_session() as session:
        repo = ScimGroupRepository(session)
        await repo.add_member(
            scim_group.id, scim_user.id, tenant_id=scim_group.tenant_id
        )

    async with db_session() as session:
        repo = ScimGroupRepository(session)
        await repo.set_members(scim_group.id, [], tenant_id=scim_group.tenant_id)

    async with db_session() as session:
        result = await session.execute(
            select(func.count()).where(
                usergroups_users_table.c.user_group_id == scim_group.id
            )
        )
        count = result.scalar_one()

    assert count == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_removes_group_row(db_session, scim_group):
    """delete() performs a hard delete — the group row is gone from the table."""
    async with db_session() as session:
        repo = ScimGroupRepository(session)
        await repo.delete(scim_group.id, tenant_id=scim_group.tenant_id)

    async with db_session() as session:
        repo = ScimGroupRepository(session)
        result = await repo.get_by_id(scim_group.id, tenant_id=scim_group.tenant_id)
        exists = result is not None

    assert not exists, "Hard delete must remove the row"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_add_member_ignores_group_in_another_tenant(
    db_session, scim_user, scim_group
):
    """Defensive tenant scoping: add_member() must not touch a group that does
    not belong to the supplied tenant, even though the junction table itself
    carries no tenant_id column."""
    wrong_tenant = uuid.uuid4()
    async with db_session() as session:
        repo = ScimGroupRepository(session)
        await repo.add_member(scim_group.id, scim_user.id, tenant_id=wrong_tenant)

    async with db_session() as session:
        result = await session.execute(
            select(usergroups_users_table).where(
                usergroups_users_table.c.user_group_id == scim_group.id,
                usergroups_users_table.c.user_id == scim_user.id,
            )
        )
        row_exists = result.first() is not None

    assert not row_exists, "add_member must be a no-op for a foreign-tenant group"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_set_members_ignores_group_in_another_tenant(
    db_session, scim_user, scim_group
):
    """set_members() with a foreign tenant must neither add nor remove rows."""
    async with db_session() as session:
        repo = ScimGroupRepository(session)
        await repo.add_member(
            scim_group.id, scim_user.id, tenant_id=scim_group.tenant_id
        )

    # Attempt to wipe members using the wrong tenant — must be ignored.
    async with db_session() as session:
        repo = ScimGroupRepository(session)
        await repo.set_members(scim_group.id, [], tenant_id=uuid.uuid4())

    async with db_session() as session:
        result = await session.execute(
            select(func.count()).where(
                usergroups_users_table.c.user_group_id == scim_group.id
            )
        )
        count = result.scalar_one()

    assert count == 1, "set_members must not clear members of a foreign-tenant group"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_ignores_group_in_another_tenant(db_session, scim_group):
    """delete() with a foreign tenant must leave the group untouched."""
    async with db_session() as session:
        repo = ScimGroupRepository(session)
        await repo.delete(scim_group.id, tenant_id=uuid.uuid4())

    async with db_session() as session:
        repo = ScimGroupRepository(session)
        result = await repo.get_by_id(scim_group.id, tenant_id=scim_group.tenant_id)

    assert result is not None, "delete must be a no-op for a foreign-tenant group"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_filters_by_tenant(db_session, test_tenant):
    """list() returns only groups for the given tenant_id — no cross-tenant leakage."""
    async with db_session() as session:
        container = Container(session=providers.Object(session))
        tenant_service = container.tenant_service()
        tenant_c = await tenant_service.create_tenant(
            TenantBase(name="tenant_c_scim", slug="tenant-c-scim")
        )
        session.add(UserGroups(name="Tenant-C Group", tenant_id=tenant_c.id))
        tenant_c_id = tenant_c.id

    async with db_session() as session:
        repo = ScimGroupRepository(session)
        groups_a = await repo.list(tenant_id=test_tenant.id)
        groups_c = await repo.list(tenant_id=tenant_c_id)
        names_a = {g.name for g in groups_a}
        names_c = {g.name for g in groups_c}

    assert "Tenant-C Group" not in names_a, "Tenant A must not see Tenant C's groups"
    assert "Tenant-C Group" in names_c


# ---------------------------------------------------------------------------
# HTTP smoke tests (via main app with bypass_scim_auth)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_groups_empty_returns_200(client, bypass_scim_auth):
    """GET /scim/v2/Groups returns 200 with empty Resources when no groups exist."""
    response = await client.get("/scim/v2/Groups")
    assert response.status_code == 200
    body = response.json()
    assert body["totalResults"] == 0
    assert body["Resources"] == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_group_http(client, bypass_scim_auth):
    """POST /scim/v2/Groups creates a group and returns 201."""
    payload = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
        "displayName": "New SCIM Group",
        "members": [],
    }
    response = await client.post("/scim/v2/Groups", json=payload)
    assert response.status_code == 201


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_group_http_rejects_other_tenant_member(
    client,
    db_session,
    test_tenant,
    bypass_scim_auth,
):
    """POST /scim/v2/Groups rejects member IDs outside the authenticated tenant."""
    async with db_session() as session:
        container = Container(session=providers.Object(session))
        tenant_service = container.tenant_service()
        other_tenant = await tenant_service.create_tenant(
            TenantBase(
                name="tenant_http_member_scope_scim",
                slug="tenant-http-member-scope-scim",
            )
        )
        other_tenant_user = Users(
            email="http-other-tenant-member@example.com",
            username="http.other.tenant.member",
            state="active",
            tenant_id=other_tenant.id,
        )
        session.add(other_tenant_user)
        await session.flush()
        other_tenant_user_id = other_tenant_user.id

    payload = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
        "displayName": "Cross Tenant Member Group",
        "members": [{"value": str(other_tenant_user_id)}],
    }
    response = await client.post("/scim/v2/Groups", json=payload)

    assert response.status_code == 400
    body = response.json()
    assert body["scimType"] == "invalidValue"
    assert "Group members must belong to the authenticated tenant" in body["detail"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_group_http(client, bypass_scim_auth, scim_group):
    """GET /scim/v2/Groups/{id} returns a ScimGroup.

    Marked xfail: response serialization fails because UserGroups.members
    does not exist (the relationship is named 'users').
    """
    response = await client.get(f"/scim/v2/Groups/{scim_group.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(scim_group.id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_group_with_active_duplicate_returns_409(
    client, bypass_scim_auth, scim_group
):
    """POST /Groups with displayName matching an active group → 409 uniqueness."""
    payload = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
        "displayName": scim_group.name,
        "members": [],
    }
    response = await client.post("/scim/v2/Groups", json=payload)
    assert response.status_code == 409
    assert response.json()["scimType"] == "uniqueness"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_group_is_idempotent(
    db_session, client, bypass_scim_auth, scim_group
):
    """A second DELETE on a soft-deleted group returns 204 (idempotent)."""
    first = await client.delete(f"/scim/v2/Groups/{scim_group.id}")
    assert first.status_code == 204

    second = await client.delete(f"/scim/v2/Groups/{scim_group.id}")
    assert second.status_code == 204

    async with db_session() as session:
        result = await session.execute(
            select(UserGroups).where(UserGroups.id == scim_group.id)
        )
        assert result.scalar_one().state == "deleted"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_group_returns_404_for_unknown_id(client, bypass_scim_auth):
    """DELETE on a never-existed group ID returns 404 (not 204) — distinguishes from idempotent re-delete."""
    response = await client.delete(f"/scim/v2/Groups/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_group_reactivates_soft_deleted_group(
    db_session, client, bypass_scim_auth, scim_group
):
    """POST /Groups with displayName matching a soft-deleted group reactivates it (201)."""
    delete_response = await client.delete(f"/scim/v2/Groups/{scim_group.id}")
    assert delete_response.status_code == 204

    async with db_session() as session:
        result = await session.execute(
            select(UserGroups).where(UserGroups.id == scim_group.id)
        )
        assert result.scalar_one().state == "deleted"

    payload = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
        "displayName": scim_group.name,
        "externalId": "ext-reactivated-001",
        "members": [],
    }
    response = await client.post("/scim/v2/Groups", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["id"] == str(scim_group.id), (
        "Re-activation should reuse the existing row, not create a new one"
    )
    assert body["externalId"] == "ext-reactivated-001"

    async with db_session() as session:
        result = await session.execute(
            select(UserGroups).where(UserGroups.id == scim_group.id)
        )
        group = result.scalar_one()
        assert group.state is None, "state should be cleared (NULL) after reactivation"
