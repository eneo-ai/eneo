"""A new organisation gets its predefined roles from the template: the Owner
manages retention, and no role uses Flows until an administrator grants it.

- POST /sysadmin/tenants/
"""

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from eneo.database.database import sessionmanager
from eneo.database.tables.roles_table import Roles

FLOW_PERMISSIONS = {"flows_view", "flows_run", "flows_manage", "flows_trace"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_new_organisation_has_no_flow_permission_and_an_owner_for_retention(
    client: AsyncClient, super_admin_token: str
):
    tenant = await client.post(
        "/api/v1/sysadmin/tenants/",
        json={"name": f"new-tenant-roles-{uuid4().hex[:8]}"},
        headers={"X-API-Key": super_admin_token},
    )
    assert tenant.status_code == 200, tenant.text

    async with sessionmanager.session() as session, session.begin():
        rows = (
            await session.execute(
                sa.select(Roles.predefined_source, Roles.permissions).where(
                    Roles.tenant_id == UUID(tenant.json()["id"])
                )
            )
        ).all()
    roles = {source: set(permissions) for source, permissions in rows}

    assert set(roles) == {"User", "AI Configurator", "Owner"}
    for source, permissions in roles.items():
        assert not permissions & FLOW_PERMISSIONS, source
    assert {"retention_manage", "retention_holds"} <= roles["Owner"]
