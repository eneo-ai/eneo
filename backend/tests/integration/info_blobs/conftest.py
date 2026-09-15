from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate


@pytest.fixture
def grant_collections_permission():
    """Give a user the ``collections`` tenant permission and nothing else.

    Reading a collection document through a space the reader belongs to also
    requires that permission. Website and integration reads need no tenant
    permission, so readers of those sources stay permissionless in the tests
    to keep that exemption covered. Chat and assistant permissions are never
    granted here.
    """

    async def _grant(container, user_id, tenant_id):
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"collections-reader-{uuid4().hex[:8]}",
                permissions=[Permission.COLLECTIONS],
                tenant_id=tenant_id,
            )
        )
        await container.session().execute(
            sa.text("INSERT INTO users_roles (user_id, role_id) VALUES (:u, :r)"),
            {"u": user_id, "r": role.id},
        )

    return _grant
