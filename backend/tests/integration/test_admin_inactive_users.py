"""``GET /admin/users/inactive`` lists the tenant's inactive users in one read.

It returned each user's name, email, state and last change, but read every
user of the tenant with their roles, tenant, modules and groups to find the
few inactive ones.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.users_table import Users
from eneo.tenants.tenant import TenantBase
from tests.integration.flows.statement_capture_support import capture_queries

pytestmark = pytest.mark.integration

CHANGED = datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=timezone.utc)


@pytest.fixture
async def token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.fixture
async def users(db_container, admin_user) -> None:
    async with db_container() as container:
        other = await container.tenant_repo().add(
            TenantBase(name=f"inactive-other-{uuid4().hex[:8]}")
        )
        rows = [
            ("Bo.Inactive@Kommun.SE", "bo", "inactive", admin_user.tenant_id, None),
            ("ada.inactive@kommun.se", None, "inactive", admin_user.tenant_id, None),
            ("cy.active@kommun.se", "cy", "active", admin_user.tenant_id, None),
            ("di.invited@kommun.se", "di", "invited", admin_user.tenant_id, None),
            ("ed.deleted@kommun.se", "ed", "inactive", admin_user.tenant_id, CHANGED),
            ("fi.other@kommun.se", "fi", "inactive", other.id, None),
        ]
        await container.session().execute(
            sa.insert(Users),
            [
                {
                    "email": email,
                    "username": username,
                    "state": state,
                    "tenant_id": tenant_id,
                    "deleted_at": deleted_at,
                    "updated_at": CHANGED,
                }
                for email, username, state, tenant_id, deleted_at in rows
            ],
        )


async def test_the_tenants_inactive_users_by_email(client, users, token) -> None:
    response = await client.get(
        "/api/v1/admin/users/inactive", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200, response.text
    changed = response.json()[0]["state_changed_at"]
    assert datetime.fromisoformat(changed) == CHANGED
    assert response.json() == [
        {
            "username": "ada.inactive@kommun.se",
            "email": "ada.inactive@kommun.se",
            "state": "inactive",
            "state_changed_at": changed,
        },
        {
            "username": "bo",
            "email": "Bo.Inactive@kommun.se",
            "state": "inactive",
            "state_changed_at": changed,
        },
    ]


async def test_one_read_whatever_the_tenant_size(
    db_container, admin_user, users
) -> None:
    async with db_container() as container:
        container.user.override(admin_user)
        service = container.admin_service()
        with capture_queries(container.session().sync_session.bind) as queries:
            inactive = await service.get_inactive_tenant_users()

    assert len(inactive) == 2
    assert len(queries) == 1, [q.sql for q in queries]


async def test_rows_it_does_not_return_cannot_fail_it(
    client, db_container, admin_user, token
) -> None:
    """Only the inactive rows are validated, and an empty username shows the email."""
    async with db_container() as container:
        await container.session().execute(
            sa.insert(Users),
            [
                {
                    "email": "not-an-email",
                    "username": "broken",
                    "state": "active",
                    "tenant_id": admin_user.tenant_id,
                    "updated_at": CHANGED,
                },
                {
                    "email": "gu.inactive@kommun.se",
                    "username": "",
                    "state": "inactive",
                    "tenant_id": admin_user.tenant_id,
                    "updated_at": CHANGED,
                },
            ],
        )

    response = await client.get(
        "/api/v1/admin/users/inactive", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200, response.text
    assert [(u["username"], u["email"]) for u in response.json()] == [
        ("gu.inactive@kommun.se", "gu.inactive@kommun.se")
    ]
