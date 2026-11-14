"""Resetting a predefined role to its template replaces its permissions.

No template carries the flow or retention permissions, so a reset takes away
those an administrator granted the role.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

from eneo.roles.permissions import Permission
from eneo.roles.role import RoleInDB
from eneo.roles.roles_service import RolesService
from eneo.server.dependencies.predefined_roles import (
    load_predefined_roles_from_config,
)
from tests.fixtures import TEST_USER


async def test_reset_to_the_owner_template_removes_granted_retention_and_flow_permissions():
    owner = RoleInDB(
        id=uuid4(),
        name="Owner",
        permissions=[
            Permission.ADMIN,
            Permission.RETENTION_MANAGE,
            Permission.RETENTION_HOLDS,
            Permission.FLOWS_MANAGE,
        ],
        predefined_source="Owner",
        tenant_id=TEST_USER.tenant_id,
    )
    service = RolesService(user=TEST_USER, repo=AsyncMock(), user_repo=None)
    service.repo.get_role.return_value = owner
    service.repo.update_role.return_value = owner

    await service.reset_role_to_default(owner.id)

    update = service.repo.update_role.await_args.args[0]
    template = next(
        t for t in load_predefined_roles_from_config() if t["name"] == "Owner"
    )
    assert list(update.permissions) == template["permissions"]
    granted = {
        Permission.RETENTION_MANAGE,
        Permission.RETENTION_HOLDS,
        Permission.FLOWS_MANAGE,
    }
    assert not {Permission(p) for p in update.permissions} & granted
