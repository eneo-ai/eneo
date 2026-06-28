"""Fixtures for SCIM integration tests."""

import hashlib
from uuid import UUID

import pytest
from sqlalchemy import update

from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import Users
from eneo.scim.app import scim_app
from eneo.scim.auth import require_scim_auth

TEST_SCIM_TOKEN = "integration-test-scim-bearer-token"
_TEST_SCIM_TOKEN_HASH = hashlib.sha256(TEST_SCIM_TOKEN.encode()).hexdigest()


@pytest.fixture
def bypass_scim_auth(test_tenant):
    """Bypass require_scim_auth on scim_app, returning the test tenant's id."""
    tenant_id: UUID = test_tenant.id

    scim_app.dependency_overrides[require_scim_auth] = lambda: tenant_id
    yield
    scim_app.dependency_overrides.pop(require_scim_auth, None)


@pytest.fixture
async def scim_auth_headers(db_session, test_tenant):
    """Store the SCIM token hash in the test tenant and return matching auth header.

    Uses a real DB write so require_scim_auth can validate via DB lookup.
    Cleans up (sets hash back to None) after the test.
    """
    async with db_session() as session:
        await session.execute(
            update(Tenants)
            .where(Tenants.id == test_tenant.id)
            .values(scim_token_hash=_TEST_SCIM_TOKEN_HASH)
        )

    yield {"Authorization": f"Bearer {TEST_SCIM_TOKEN}"}

    async with db_session() as session:
        await session.execute(
            update(Tenants)
            .where(Tenants.id == test_tenant.id)
            .values(scim_token_hash=None)
        )


@pytest.fixture
async def scim_user(db_session, test_tenant):
    """Active user with all required fields for SCIM repository tests."""
    async with db_session() as session:
        user = Users(
            email="scim-user@example.com",
            username="scim.user",
            external_id="ext-scim-001",
            state="active",
            tenant_id=test_tenant.id,
        )
        session.add(user)
        await session.flush()
        user_id = user.id
        user_email = user.email
        user_username = user.username
        user_external_id = user.external_id
        user_tenant_id = user.tenant_id

    class _User:
        id = user_id
        email = user_email
        username = user_username
        external_id = user_external_id
        tenant_id = user_tenant_id

    return _User()


@pytest.fixture
async def scim_group(db_session, test_tenant):
    """Group with all required fields for SCIM repository tests."""
    async with db_session() as session:
        group = UserGroups(
            name="SCIM Test Group",
            external_id="grp-scim-001",
            tenant_id=test_tenant.id,
        )
        session.add(group)
        await session.flush()
        group_id = group.id
        group_name = group.name
        group_external_id = group.external_id
        group_tenant_id = group.tenant_id

    class _Group:
        id = group_id
        name = group_name
        external_id = group_external_id
        tenant_id = group_tenant_id

    return _Group()
