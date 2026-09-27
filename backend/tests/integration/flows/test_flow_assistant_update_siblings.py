"""Updating one flow assistant writes only that assistant, so a concurrent
change to another assistant of the same space neither fails the update nor
is overwritten by it."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.assistants.assistant_service import AssistantService
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.database.tables.assistant_table import Assistants
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserUpdate


async def _admin_token_and_space(client, db_container, admin_user) -> tuple[str, UUID]:
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"flow-assistant-update-{uuid4().hex[:8]}",
                permissions=[
                    Permission.ASSISTANTS,
                    Permission.SHARED_SPACES,
                    Permission.FLOWS_MANAGE,
                ],
                tenant_id=admin_user.tenant_id,
            )
        )
    async with db_container() as container:
        admin = await container.user_repo().update(
            UserUpdate(id=admin_user.id, roles=[ModelId(id=role.id)])
        )
        assert admin is not None
        token = container.auth_service().create_access_token_for_user(admin)

    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"flow-assistant-update-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return token, UUID(response.json()["id"])


async def _flow_with_assistants(db_container, *, space_id: UUID, names: list[str]):
    async with db_container() as container:
        flow_service = container.flow_service()
        flow = await flow_service.create_flow(
            space_id=space_id,
            name="Syskon",
            description="Assistenter i samma utrymme.",
            steps=[],
        )
        ids = []
        for name in names:
            assistant, _ = await flow_service.create_flow_assistant(
                flow_id=flow.id, name=name
            )
            ids.append(assistant.id)
    return flow.id, ids


async def _names(db_container, assistant_ids: list[UUID]) -> dict[UUID, str]:
    async with db_container() as container:
        rows = await container.session().execute(
            sa.select(Assistants.id, Assistants.name).where(
                Assistants.id.in_(assistant_ids)
            )
        )
    return {row.id: row.name for row in rows}


def _change_rows_after_load(monkeypatch: pytest.MonkeyPatch, change) -> None:
    # The governance check runs after update_assistant loaded the space and
    # before it persists, so a change made here through the request's own
    # session is what a concurrent request committing in between looks like.
    check = AssistantService._ensure_governance_policy_allows_update

    async def change_then_check(self, **kwargs):
        await change(self.repo.session)
        return await check(self, **kwargs)

    monkeypatch.setattr(
        AssistantService, "_ensure_governance_policy_allows_update", change_then_check
    )


def _record_audit(monkeypatch: pytest.MonkeyPatch) -> list[tuple[ActionType, UUID]]:
    audited: list[tuple[ActionType, UUID]] = []
    log_async = AuditService.log_async

    async def record(self, **kwargs):
        audited.append((kwargs["action"], kwargs["entity_id"]))
        return await log_async(self, **kwargs)

    monkeypatch.setattr(AuditService, "log_async", record)
    return audited


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_succeeds_when_a_sibling_is_deleted_meanwhile(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    monkeypatch: pytest.MonkeyPatch,
):
    _ = patch_auth_service_jwt
    token, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow_id, (target_id, sibling_id) = await _flow_with_assistants(
        db_container, space_id=space_id, names=["target", "sibling"]
    )

    async def delete_sibling(session) -> None:
        await session.execute(sa.delete(Assistants).where(Assistants.id == sibling_id))

    _change_rows_after_load(monkeypatch, delete_sibling)
    audited = _record_audit(monkeypatch)

    response = await client.patch(
        f"/api/v1/flows/{flow_id}/assistants/{target_id}/",
        json={"name": "updated"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "updated"
    assert await _names(db_container, [target_id, sibling_id]) == {target_id: "updated"}
    assert audited == [(ActionType.ASSISTANT_UPDATED, target_id)]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_does_not_rewrite_a_sibling_changed_meanwhile(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    monkeypatch: pytest.MonkeyPatch,
):
    _ = patch_auth_service_jwt
    token, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow_id, (target_id, sibling_id) = await _flow_with_assistants(
        db_container, space_id=space_id, names=["target", "sibling"]
    )

    async def rename_sibling(session) -> None:
        await session.execute(
            sa.update(Assistants)
            .where(Assistants.id == sibling_id)
            .values(name="renamed elsewhere")
        )

    _change_rows_after_load(monkeypatch, rename_sibling)
    audited = _record_audit(monkeypatch)

    response = await client.patch(
        f"/api/v1/flows/{flow_id}/assistants/{target_id}/",
        json={"name": "updated"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text
    assert await _names(db_container, [target_id, sibling_id]) == {
        target_id: "updated",
        sibling_id: "renamed elsewhere",
    }
    assert audited == [(ActionType.ASSISTANT_UPDATED, target_id)]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_of_an_assistant_deleted_meanwhile_is_not_found(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    monkeypatch: pytest.MonkeyPatch,
):
    _ = patch_auth_service_jwt
    token, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow_id, (target_id,) = await _flow_with_assistants(
        db_container, space_id=space_id, names=["target"]
    )

    async def delete_target(session) -> None:
        await session.execute(sa.delete(Assistants).where(Assistants.id == target_id))

    _change_rows_after_load(monkeypatch, delete_target)
    audited = _record_audit(monkeypatch)

    response = await client.patch(
        f"/api/v1/flows/{flow_id}/assistants/{target_id}/",
        json={"name": "updated"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404, response.text
    assert audited == []
