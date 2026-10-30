"""A Flow settings change keeps the admin who made it after a rename and deletion."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.audit.application.audit_worker_task import log_audit_event_task
from eneo.database.tables.users_table import Users, users_roles_table
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.settings.settings import FlowDocumentRenderLimitsUpdate

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _create_admin(db_container, *, tenant_id: UUID, username: str) -> UUID:
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"settings-admin-{uuid4().hex[:8]}",
                permissions=[Permission.ADMIN],
                tenant_id=tenant_id,
            )
        )
        session = container.session()
        user_id = await session.scalar(
            sa.insert(Users)
            .values(
                username=username,
                email=f"{username}@example.org",
                state="active",
                used_tokens=0,
                tenant_id=tenant_id,
            )
            .returning(Users.id)
        )
        await session.execute(
            sa.insert(users_roles_table).values(user_id=user_id, role_id=role.id)
        )
    assert user_id is not None
    return user_id


async def _listed(client, redis_client, admin_user, admin_user_api_key, **params):
    headers = {"X-API-Key": admin_user_api_key.key}
    await redis_client.delete(
        f"rate_limit:audit_session:{admin_user.id}:{admin_user.tenant_id}"
    )
    access = await client.post(
        "/api/v1/audit/access-session",
        json={
            "category": "integration_test",
            "description": "Check flow settings audit attribution",
        },
        headers=headers,
    )
    assert access.status_code == 200, access.text
    response = await client.get(
        "/api/v1/audit/logs",
        params={"page_size": "1000", **params},
        headers=headers,
        cookies={"audit_session_id": access.cookies["audit_session_id"]},
    )
    assert response.status_code == 200, response.text
    return response.json()["logs"]


async def test_a_settings_change_keeps_the_admin_after_rename_and_deletion(
    db_container, admin_user, admin_user_api_key, client, redis_client
):
    actor_id = await _create_admin(
        db_container, tenant_id=admin_user.tenant_id, username="settings-admin"
    )
    with patch("eneo.audit.application.audit_service.job_manager") as job_manager:
        job_manager.enqueue = AsyncMock()
        async with db_container() as container:
            actor = await container.user_repo().get_user_by_id(actor_id)
            assert actor is not None
        async with db_container(user=actor) as container:
            await container.settings_service().update_flow_document_render_limits(
                FlowDocumentRenderLimitsUpdate(max_blocks=50)
            )
    params: dict[str, Any] = job_manager.enqueue.call_args.args[2]
    async with db_container() as container:
        await log_audit_event_task(
            job_id=uuid4(), params=params, session=container.session()
        )
        await container.session().execute(
            sa.update(Users).where(Users.id == actor_id).values(username="renamed")
        )

    renamed = await _listed(
        client, redis_client, admin_user, admin_user_api_key, actor_id=str(actor_id)
    )
    async with db_container() as container:
        await container.session().execute(sa.delete(Users).where(Users.id == actor_id))
    deleted = await _listed(
        client, redis_client, admin_user, admin_user_api_key, actor_id=str(actor_id)
    )

    expected = {
        "type": "user",
        "id": str(actor_id),
        "name": "settings-admin",
        "email": "settings-admin@example.org",
    }
    for logs in (renamed, deleted):
        settings_rows = [
            log
            for log in logs
            if log["metadata"].get("setting") == "flow_document_render_limits"
        ]
        assert [log["metadata"]["actor"] for log in settings_rows] == [expected]
