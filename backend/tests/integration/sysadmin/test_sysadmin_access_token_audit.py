"""A token the operator takes for a user with the super API key leaves a
stored audit row, whatever the tenant's audit settings.

- POST /sysadmin/users/{user_id}/access-token/
"""

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from eneo.database.database import sessionmanager
from eneo.database.tables.audit_log_table import AuditLog


@pytest.mark.integration
@pytest.mark.asyncio
async def test_an_issued_access_token_is_audited(
    client: AsyncClient, super_admin_token: str
):
    headers = {"X-API-Key": super_admin_token}
    suffix = uuid4().hex[:8]
    tenant = await client.post(
        "/api/v1/sysadmin/tenants/",
        json={"name": f"access-token-audit-{suffix}"},
        headers=headers,
    )
    assert tenant.status_code == 200, tenant.text
    tenant_id = tenant.json()["id"]
    user = await client.post(
        "/api/v1/sysadmin/users/",
        json={
            "email": f"access-token-audit-{suffix}@example.com",
            "username": f"access-token-audit-{suffix}",
            "tenant_id": tenant_id,
            "password": "IntegrationPass123!",
        },
        headers=headers,
    )
    assert user.status_code == 200, user.text
    user_id = user.json()["id"]

    response = await client.post(
        f"/api/v1/sysadmin/users/{user_id}/access-token/", headers=headers
    )

    assert response.status_code == 200, response.text
    assert isinstance(response.json(), str) and response.json()  # the token
    async with sessionmanager.session() as session, session.begin():
        rows = (
            await session.execute(
                sa.select(
                    AuditLog.entity_id,
                    AuditLog.actor_id,
                    AuditLog.actor_type,
                    AuditLog.log_metadata,
                )
                .where(AuditLog.tenant_id == UUID(tenant_id))
                .where(AuditLog.action == "user_access_token_issued")
            )
        ).all()
    assert [(row.entity_id, row.actor_id, row.actor_type) for row in rows] == [
        (UUID(user_id), None, "system")
    ]
    assert rows[0].log_metadata["actor"] == {
        "type": "sysadmin",
        "via": "eneo_super_api_key",
    }
    assert rows[0].log_metadata["target"]["id"] == user_id
