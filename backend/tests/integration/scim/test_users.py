"""Integration tests for SCIM user repository and HTTP endpoints.

Repository tests verify the SQL filter/sort logic by inserting data with all
required fields (tenant_id, state) and querying via ScimUserRepository directly.
All ORM attribute access happens inside the session context to avoid
DetachedInstanceError (SQLAlchemy expires objects after session closes).

HTTP tests exercise the full stack through the mounted scim_app sub-application.
"""

import uuid

import pytest

from intric.database.tables.users_table import Users
from intric.scim.repositories.user_repository import ScimUserRepository
from intric.scim.schemas.common import ScimFilter, ScimSort

# ---------------------------------------------------------------------------
# Repository-level integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_returns_active_users(db_session, test_tenant):
    """list() includes active users for the given tenant."""
    async with db_session() as session:
        session.add(
            Users(
                email="active@example.com",
                username="active.user",
                state="active",
                tenant_id=test_tenant.id,
            )
        )

    async with db_session() as session:
        repo = ScimUserRepository(session)
        users = await repo.list(tenant_id=test_tenant.id)
        emails = {u.email for u in users}

    assert "active@example.com" in emails


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_excludes_inactive_users(db_session, test_tenant):
    """list() excludes users with state='inactive'."""
    async with db_session() as session:
        session.add(
            Users(
                email="inactive@example.com",
                username="inactive.user",
                state="inactive",
                tenant_id=test_tenant.id,
            )
        )

    async with db_session() as session:
        repo = ScimUserRepository(session)
        users = await repo.list(tenant_id=test_tenant.id)
        emails = {u.email for u in users}

    assert "inactive@example.com" not in emails


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_filter_eq_username(db_session, test_tenant):
    """list() with eq filter on userName returns only the matching user."""
    async with db_session() as session:
        session.add(
            Users(
                email="filter-a@example.com",
                username="filter.alpha",
                state="active",
                tenant_id=test_tenant.id,
            )
        )
        session.add(
            Users(
                email="filter-b@example.com",
                username="filter.beta",
                state="active",
                tenant_id=test_tenant.id,
            )
        )

    async with db_session() as session:
        repo = ScimUserRepository(session)
        users = await repo.list(
            tenant_id=test_tenant.id,
            scim_filter=ScimFilter(
                attribute="userName", operator="eq", value="filter.alpha"
            ),
        )
        count = len(users)
        username = users[0].username if users else None

    assert count == 1
    assert username == "filter.alpha"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_filter_co_email(db_session, test_tenant):
    """list() with co (contains) filter on email performs case-insensitive substring match."""
    async with db_session() as session:
        session.add(
            Users(
                email="scim-match@corp.example.com",
                username="match.user",
                state="active",
                tenant_id=test_tenant.id,
            )
        )
        session.add(
            Users(
                email="other@different.com",
                username="other.user",
                state="active",
                tenant_id=test_tenant.id,
            )
        )

    async with db_session() as session:
        repo = ScimUserRepository(session)
        users = await repo.list(
            tenant_id=test_tenant.id,
            scim_filter=ScimFilter(
                attribute="email", operator="co", value="corp.example"
            ),
        )
        emails = {u.email for u in users}

    assert "scim-match@corp.example.com" in emails
    assert "other@different.com" not in emails


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_filter_sw_username(db_session, test_tenant):
    """list() with sw (starts with) filter matches prefix correctly."""
    async with db_session() as session:
        session.add(
            Users(
                email="sw-match@example.com",
                username="john.doe",
                state="active",
                tenant_id=test_tenant.id,
            )
        )
        session.add(
            Users(
                email="sw-no-match@example.com",
                username="jane.doe",
                state="active",
                tenant_id=test_tenant.id,
            )
        )

    async with db_session() as session:
        repo = ScimUserRepository(session)
        users = await repo.list(
            tenant_id=test_tenant.id,
            scim_filter=ScimFilter(attribute="userName", operator="sw", value="john"),
        )
        usernames = {u.username for u in users}

    assert "john.doe" in usernames
    assert "jane.doe" not in usernames


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_filter_pr_external_id(db_session, test_tenant):
    """list() with pr (present) filter returns only users that have externalId set."""
    async with db_session() as session:
        session.add(
            Users(
                email="has-ext@example.com",
                username="has.ext",
                state="active",
                external_id="ext-999",
                tenant_id=test_tenant.id,
            )
        )
        session.add(
            Users(
                email="no-ext@example.com",
                username="no.ext",
                state="active",
                tenant_id=test_tenant.id,
            )
        )

    async with db_session() as session:
        repo = ScimUserRepository(session)
        users = await repo.list(
            tenant_id=test_tenant.id,
            scim_filter=ScimFilter(attribute="externalId", operator="pr", value=""),
        )
        emails = {u.email for u in users}

    assert "has-ext@example.com" in emails
    assert "no-ext@example.com" not in emails


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_filter_emails_value_maps_to_email(db_session, test_tenant):
    """Azure Entra ID sends `emails.value eq "x@y"` as its primary de-dup
    filter. The previous code path silently dropped this filter and returned
    every user in the tenant, which could cause IdPs to provision duplicates
    when they relied on the filter for existence checks. Now it must map to
    the email column."""
    async with db_session() as session:
        session.add(
            Users(
                email="azure-match@example.com",
                username="azure.match",
                state="active",
                tenant_id=test_tenant.id,
            )
        )
        session.add(
            Users(
                email="azure-other@example.com",
                username="azure.other",
                state="active",
                tenant_id=test_tenant.id,
            )
        )

    async with db_session() as session:
        repo = ScimUserRepository(session)
        users = await repo.list(
            tenant_id=test_tenant.id,
            scim_filter=ScimFilter(
                attribute="emails.value", operator="eq", value="azure-match@example.com"
            ),
        )
        emails = {u.email for u in users}

    assert emails == {"azure-match@example.com"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_filter_unsupported_attribute_raises_invalid_filter(
    db_session, test_tenant
):
    """RFC 7644 §3.4.2.2: unsupported filter attributes must surface as 400
    invalidFilter. Silently returning unfiltered results would mislead IdPs
    that depend on the filter for de-dup."""
    from intric.scim.domain.errors import ScimInvalidFilterError

    async with db_session() as session:
        repo = ScimUserRepository(session)
        with pytest.raises(ScimInvalidFilterError, match="phoneNumbers.value"):
            await repo.list(
                tenant_id=test_tenant.id,
                scim_filter=ScimFilter(
                    attribute="phoneNumbers.value", operator="eq", value="+46"
                ),
            )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_sort_ascending_by_username(db_session, test_tenant):
    """list() with sort ascending on userName returns results in ascending order."""
    async with db_session() as session:
        for name in ("charlie", "alice", "bob"):
            session.add(
                Users(
                    email=f"{name}@example.com",
                    username=name,
                    state="active",
                    tenant_id=test_tenant.id,
                )
            )

    async with db_session() as session:
        repo = ScimUserRepository(session)
        users = await repo.list(
            tenant_id=test_tenant.id,
            scim_sort=ScimSort(attribute="userName", order="ascending"),
        )
        usernames = [
            u.username for u in users if u.username in ("alice", "bob", "charlie")
        ]

    assert usernames == sorted(usernames)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_sort_descending_by_username(db_session, test_tenant):
    """list() with sort descending on userName returns results in descending order."""
    async with db_session() as session:
        for name in ("charlie", "alice", "bob"):
            session.add(
                Users(
                    email=f"{name}@example.com",
                    username=name,
                    state="active",
                    tenant_id=test_tenant.id,
                )
            )

    async with db_session() as session:
        repo = ScimUserRepository(session)
        users = await repo.list(
            tenant_id=test_tenant.id,
            scim_sort=ScimSort(attribute="userName", order="descending"),
        )
        usernames = [
            u.username for u in users if u.username in ("alice", "bob", "charlie")
        ]

    assert usernames == sorted(usernames, reverse=True)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_by_id_returns_correct_user(db_session, scim_user):
    """get_by_id() returns the user with the given UUID."""
    async with db_session() as session:
        repo = ScimUserRepository(session)
        result = await repo.get_by_id(scim_user.id, tenant_id=scim_user.tenant_id)
        found_id = result.id if result else None
        found_email = result.email if result else None

    assert found_id == scim_user.id
    assert found_email == scim_user.email


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_by_id_returns_none_for_unknown_id(db_session, test_tenant):
    """get_by_id() returns None for a UUID that doesn't exist."""
    async with db_session() as session:
        repo = ScimUserRepository(session)
        result = await repo.get_by_id(uuid.uuid4(), tenant_id=test_tenant.id)

    assert result is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_by_id_returns_none_for_wrong_tenant(db_session, scim_user):
    """get_by_id() returns None when tenant_id doesn't match the user's tenant."""
    async with db_session() as session:
        repo = ScimUserRepository(session)
        result = await repo.get_by_id(scim_user.id, tenant_id=uuid.uuid4())

    assert result is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_by_username_returns_correct_user(db_session, scim_user):
    """get_by_username() returns the user with the given username."""
    async with db_session() as session:
        repo = ScimUserRepository(session)
        result = await repo.get_by_username(
            scim_user.username, tenant_id=scim_user.tenant_id
        )
        found_username = result.username if result else None

    assert found_username == scim_user.username


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_by_username_returns_none_for_unknown(db_session, test_tenant):
    """get_by_username() returns None for a username that doesn't exist."""
    async with db_session() as session:
        repo = ScimUserRepository(session)
        result = await repo.get_by_username("nobody@nowhere", tenant_id=test_tenant.id)

    assert result is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_soft_delete_via_state_inactive(db_session, scim_user):
    """Setting state='inactive' hides the user from list() but keeps the row.

    Defensive coverage: SCIM service no longer writes state='inactive' (it uses
    state='deleted'), but the list filter still excludes any non-active state
    so legacy or manually-modified rows do not leak into SCIM responses.
    """
    from sqlalchemy import select

    async with db_session() as session:
        result = await session.execute(select(Users).where(Users.id == scim_user.id))
        user = result.scalar_one()
        user.state = "inactive"

    async with db_session() as session:
        repo = ScimUserRepository(session)
        users = await repo.list(tenant_id=scim_user.tenant_id)
        ids = {u.id for u in users}

    assert scim_user.id not in ids

    async with db_session() as session:
        from sqlalchemy import select as sel

        result = await session.execute(sel(Users).where(Users.id == scim_user.id))
        still_exists = result.scalar_one_or_none()
        row_exists = still_exists is not None

    assert row_exists, "Row must still exist after soft delete"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_filters_by_tenant(db_session, test_tenant):
    """list() returns only users for the given tenant_id — no cross-tenant leakage."""
    from dependency_injector import providers

    from intric.main.container.container import Container
    from intric.tenants.tenant import TenantBase

    async with db_session() as session:
        container = Container(session=providers.Object(session))
        tenant_service = container.tenant_service()
        tenant_b = await tenant_service.create_tenant(
            TenantBase(name="tenant_b_scim", slug="tenant-b-scim")
        )
        session.add(
            Users(
                email="tenant-b-user@example.com",
                username="tenant.b.user",
                state="active",
                tenant_id=tenant_b.id,
            )
        )
        tenant_b_id = tenant_b.id

    async with db_session() as session:
        repo = ScimUserRepository(session)
        users_a = await repo.list(tenant_id=test_tenant.id)
        users_b = await repo.list(tenant_id=tenant_b_id)
        emails_a = {u.email for u in users_a}
        emails_b = {u.email for u in users_b}

    assert "tenant-b-user@example.com" not in emails_a, (
        "Tenant A must not see Tenant B's users"
    )
    assert "tenant-b-user@example.com" in emails_b


# ---------------------------------------------------------------------------
# HTTP smoke tests (via main app with bypass_scim_auth)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_users_http(client, bypass_scim_auth):
    """GET /scim/v2/Users returns a ListResponse."""
    response = await client.get("/scim/v2/Users")
    assert response.status_code == 200
    body = response.json()
    assert "totalResults" in body
    assert "Resources" in body


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_users_http_unsupported_filter_returns_400_invalid_filter(
    client, bypass_scim_auth
):
    """RFC 7644 §3.4.2.2: unsupported filter attribute returns 400 with
    scimType=invalidFilter, not 200 with the whole tenant."""
    response = await client.get('/scim/v2/Users?filter=phoneNumbers.value eq "+46123"')
    assert response.status_code == 400
    body = response.json()
    assert body.get("scimType") == "invalidFilter"
    assert "phoneNumbers.value" in body.get("detail", "")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_users_http_emails_value_filter_returns_match(
    client, bypass_scim_auth, db_session, test_tenant
):
    """Azure Entra ID's primary de-dup filter (`emails.value eq "x"`) must
    return only the matching user, not the entire tenant."""
    async with db_session() as session:
        session.add(
            Users(
                email="http-azure@example.com",
                username="http.azure",
                state="active",
                tenant_id=test_tenant.id,
            )
        )

    response = await client.get(
        '/scim/v2/Users?filter=emails.value eq "http-azure@example.com"'
    )
    assert response.status_code == 200
    body = response.json()
    assert body["totalResults"] == 1
    assert body["Resources"][0]["userName"] == "http.azure"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_user_http(client, bypass_scim_auth):
    payload = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "userName": "new.scim.user",
        "emails": [{"value": "new-scim@example.com", "primary": True}],
    }
    response = await client.post("/scim/v2/Users", json=payload)
    assert response.status_code == 201


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_user_http(client, bypass_scim_auth, scim_user):
    """GET /scim/v2/Users/{id} returns a ScimUser."""
    response = await client.get(f"/scim/v2/Users/{scim_user.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(scim_user.id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_user_sets_deleted_state_and_timestamp(
    db_session, client, bypass_scim_auth, scim_user
):
    """DELETE /scim/v2/Users/{id} soft-deletes: state='deleted' and deleted_at set."""
    from sqlalchemy import select

    response = await client.delete(f"/scim/v2/Users/{scim_user.id}")
    assert response.status_code == 204

    async with db_session() as session:
        result = await session.execute(select(Users).where(Users.id == scim_user.id))
        user = result.scalar_one()
        assert user.state == "deleted"
        assert user.deleted_at is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_user_is_idempotent(
    db_session, client, bypass_scim_auth, scim_user
):
    """A second DELETE returns 204 and does not overwrite the original deleted_at."""
    from sqlalchemy import select

    first = await client.delete(f"/scim/v2/Users/{scim_user.id}")
    assert first.status_code == 204

    async with db_session() as session:
        result = await session.execute(select(Users).where(Users.id == scim_user.id))
        first_deleted_at = result.scalar_one().deleted_at

    second = await client.delete(f"/scim/v2/Users/{scim_user.id}")
    assert second.status_code == 204

    async with db_session() as session:
        result = await session.execute(select(Users).where(Users.id == scim_user.id))
        user = result.scalar_one()
        assert user.state == "deleted"
        assert user.deleted_at == first_deleted_at


@pytest.mark.asyncio
@pytest.mark.integration
async def test_patch_active_false_soft_deletes_user(
    db_session, client, bypass_scim_auth, scim_user
):
    """PATCH active=false maps to state='deleted' and stamps deleted_at."""
    from sqlalchemy import select

    payload = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "replace", "path": "active", "value": False}],
    }
    response = await client.patch(f"/scim/v2/Users/{scim_user.id}", json=payload)
    assert response.status_code == 200
    assert response.json()["active"] is False

    async with db_session() as session:
        result = await session.execute(select(Users).where(Users.id == scim_user.id))
        user = result.scalar_one()
        assert user.state == "deleted"
        assert user.deleted_at is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_patch_active_true_reactivates_deleted_user(
    db_session, client, bypass_scim_auth, scim_user
):
    """PATCH active=true on a soft-deleted user clears deleted_at and restores state='active'."""
    from sqlalchemy import select

    deactivate = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "replace", "path": "active", "value": False}],
    }
    assert (
        await client.patch(f"/scim/v2/Users/{scim_user.id}", json=deactivate)
    ).status_code == 200

    reactivate = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "replace", "path": "active", "value": True}],
    }
    response = await client.patch(f"/scim/v2/Users/{scim_user.id}", json=reactivate)
    assert response.status_code == 200
    assert response.json()["active"] is True

    async with db_session() as session:
        result = await session.execute(select(Users).where(Users.id == scim_user.id))
        user = result.scalar_one()
        assert user.state == "active"
        assert user.deleted_at is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_logs_warning_when_tenant_has_no_default_role(
    db_session, test_tenant, caplog
):
    """SCIM provisioning when the tenant has `default_role_id IS NULL` must
    emit a WARNING (mirrors the JIT-provisioning flow in
    `authentication/federation_router.py:210-222`). Without this signal,
    operators only see the failure when an affected user tries to do
    anything in Eneo — the SCIM 201 response and audit row are not enough.
    """
    import logging

    from sqlalchemy import update

    from intric.database.tables.tenant_table import Tenants
    from intric.scim.repositories.user_repository import logger as repo_logger

    async with db_session() as session:
        await session.execute(
            update(Tenants)
            .where(Tenants.id == test_tenant.id)
            .values(default_role_id=None)
        )

    # Eneo's `get_logger` returns a custom `SimpleLogger` with its own
    # handlers — caplog's root-logger hook never sees the record. Attach
    # caplog's handler directly to the repo logger (same pattern as
    # tests/integration/credentials/test_credential_resolver.py:71-93).
    with caplog.at_level(logging.WARNING):
        repo_logger.addHandler(caplog.handler)
        try:
            async with db_session() as session:
                repo = ScimUserRepository(session)
                user = Users(
                    email="no-default-role@example.com",
                    username="no.default.role.user",
                    state="active",
                    tenant_id=test_tenant.id,
                )
                created = await repo.create(user)
                created_id = created.id
        finally:
            repo_logger.removeHandler(caplog.handler)

    assert created_id is not None  # user creation still succeeds
    matching_warns = [
        r
        for r in caplog.records
        if r.levelname == "WARNING" and "No default role configured" in r.getMessage()
    ]
    assert matching_warns, (
        f"Expected WARNING with 'No default role configured' in log. "
        f"Got records: {[(r.levelname, r.getMessage()) for r in caplog.records]}"
    )
