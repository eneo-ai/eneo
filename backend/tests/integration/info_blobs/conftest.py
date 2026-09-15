from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate

KNOWLEDGE_PERMISSIONS = [
    Permission.COLLECTIONS,
    Permission.WEBSITES,
    Permission.INTEGRATIONS,
]


@pytest.fixture
def grant_knowledge_permissions():
    """Give a user the tenant permissions that reading knowledge sources needs.

    Reading a document through a space the reader belongs to also requires the
    source type's tenant permission there (``collections`` for collections).
    Chat and assistant permissions are deliberately not granted.
    """

    async def _grant(container, user_id, tenant_id):
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"knowledge-reader-{uuid4().hex[:8]}",
                permissions=KNOWLEDGE_PERMISSIONS,
                tenant_id=tenant_id,
            )
        )
        await container.session().execute(
            sa.text("INSERT INTO users_roles (user_id, role_id) VALUES (:u, :r)"),
            {"u": user_id, "r": role.id},
        )

    return _grant
