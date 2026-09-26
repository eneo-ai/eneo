"""Deleting a flow-managed assistant, through a removed step, the assistant
endpoint or the flow, has every effect of assistant deletion and touches only
what the flow owns."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from eneo.assistants.assistant_repo import AssistantRepository
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.authentication.api_key_scope_revoker import ApiKeyScopeRevoker
from eneo.authentication.api_key_v2_repo import ApiKeysV2Repository
from eneo.authentication.auth_models import ApiKeyState
from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.database.tables.flow_tables import Flows, FlowSteps
from eneo.database.tables.icons_table import Icons
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.icons.icon import IconMetadataCreate
from eneo.main.exceptions import BadRequestException
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.users.user import UserAdd, UserState, UserUpdate
from tests.fixtures import mint_v2_api_key


def _step(*, assistant_id: UUID, step_order: int) -> FlowStep:
    return FlowStep(
        id=None,
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=assistant_id,
        step_order=step_order,
        user_description=f"Steg {step_order}",
        input_source="flow_input" if step_order == 1 else "previous_step",
        input_type="text",
        output_mode="pass_through",
        output_type="text",
    )


async def _role(db_container, *, tenant_id: UUID, permissions: list[Permission]):
    async with db_container() as container:
        return await container.role_repo().create_role(
            RoleCreate(
                name=f"flow-step-removal-{uuid4().hex[:8]}",
                permissions=permissions,
                tenant_id=tenant_id,
            )
        )


async def _mint_key(db_container, admin_user, **kwargs: object):
    async with db_container() as container:
        return await mint_v2_api_key(
            container.api_key_v2_repo(),
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            **kwargs,
        )


async def _admin_token_and_space(client, db_container, admin_user) -> tuple[str, UUID]:
    role = await _role(
        db_container,
        tenant_id=admin_user.tenant_id,
        permissions=[
            Permission.ASSISTANTS,
            Permission.SHARED_SPACES,
            Permission.FLOWS_MANAGE,
        ],
    )
    async with db_container() as container:
        admin = await container.user_repo().update(
            UserUpdate(id=admin_user.id, roles=[ModelId(id=role.id)])
        )
        assert admin is not None
        token = container.auth_service().create_access_token_for_user(admin)

    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"flow-step-removal-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return token, UUID(response.json()["id"])


async def _two_step_flow(db_container, *, space_id: UUID, name: str = "Två steg"):
    async with db_container() as container:
        flow_service = container.flow_service()
        flow = await flow_service.create_flow(
            space_id=space_id,
            name=name,
            description="Sammanfattar och granskar.",
            steps=[],
        )
        kept, _ = await flow_service.create_flow_assistant(flow_id=flow.id, name="kept")
        removed, _ = await flow_service.create_flow_assistant(
            flow_id=flow.id, name="removed"
        )
        flow = await flow_service.update_flow(
            flow_id=flow.id,
            steps=[
                _step(assistant_id=assistant.id, step_order=order)
                for order, assistant in enumerate((kept, removed), start=1)
            ],
        )
    return flow, kept.id, removed.id


async def _icon(db_container, *, tenant_id: UUID) -> UUID:
    async with db_container() as container:
        icon = await container.icon_repo().add_metadata(
            IconMetadataCreate(tenant_id=tenant_id)
        )
    return icon.id


async def _set_icon(db_container, *, assistant_id: UUID, icon_id: UUID) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(Assistants)
            .where(Assistants.id == assistant_id)
            .values(icon_id=icon_id)
        )


async def _save_steps(client, flow: Flow, steps: list[FlowStep], headers):
    return await client.patch(
        f"/api/v1/flows/{flow.id}/",
        json={
            "name": flow.name,
            "expected_revision": flow.draft_revision,
            "steps": [
                {
                    "id": str(step.id),
                    "assistant_id": str(step.assistant_id),
                    "step_order": step.step_order,
                    "user_description": step.user_description,
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "text",
                }
                for step in steps
            ],
        },
        headers=headers,
    )


async def _state(db_container, *, assistant_ids, key_id: UUID, icon_id: UUID):
    """(remaining assistant ids, the key's state, whether the icon row remains)."""
    async with db_container() as container:
        session = container.session()
        remaining = set(
            await session.scalars(
                sa.select(Assistants.id).where(Assistants.id.in_(assistant_ids))
            )
        )
        key_state = await session.scalar(
            sa.select(ApiKeysV2.state).where(ApiKeysV2.id == key_id)
        )
        icon_row = await session.scalar(sa.select(Icons.id).where(Icons.id == icon_id))
    return remaining, key_state, icon_row is not None


async def _revocation_audit_count(db_container, *, key_ids) -> int:
    async with db_container() as container:
        count = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(AuditLogTable)
            .where(AuditLogTable.action == ActionType.API_KEY_REVOKED.value)
            .where(AuditLogTable.entity_id.in_(key_ids))
        )
    return int(count or 0)


async def _flows_manage_only_owner_headers(
    db_container, *, tenant_id: UUID, space_id: UUID, flow_id: UUID
) -> dict[str, str]:
    # The draft's owner, editing without the tenant ASSISTANTS permission: the
    # caller may not delete assistants itself, yet removing a step must work.
    role = await _role(
        db_container,
        tenant_id=tenant_id,
        permissions=[Permission.SHARED_SPACES, Permission.FLOWS_MANAGE],
    )
    async with db_container() as container:
        user = await container.user_repo().add(
            UserAdd(
                email=f"flow-editor-{uuid4().hex[:8]}@example.com",
                username=f"flow_editor_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )
        await container.session().execute(
            sa.text(
                "INSERT INTO spaces_users (space_id, user_id, role) "
                "VALUES (:space_id, :user_id, :role)"
            ),
            {
                "space_id": str(space_id),
                "user_id": str(user.id),
                "role": SpaceRoleValue.EDITOR.value,
            },
        )
        await container.session().execute(
            sa.update(Flows).where(Flows.id == flow_id).values(owner_user_id=user.id)
        )
        token = container.auth_service().create_access_token_for_user(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "caller",
    ["space_admin_session", "write_api_key", "flows_manage_only_owner"],
)
async def test_flow_update_removing_a_step_deletes_its_assistant_completely(
    caller: str,
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
):
    _ = patch_auth_service_jwt
    admin_token, space_id = await _admin_token_and_space(
        client, db_container, admin_user
    )
    flow, kept_id, removed_id = await _two_step_flow(db_container, space_id=space_id)
    icon_id = await _icon(db_container, tenant_id=admin_user.tenant_id)
    await _set_icon(db_container, assistant_id=removed_id, icon_id=icon_id)
    key = await _mint_key(
        db_container,
        admin_user,
        permission="read",
        scope_type="assistant",
        scope_id=removed_id,
    )

    if caller == "space_admin_session":
        headers = {"Authorization": f"Bearer {admin_token}"}
    elif caller == "write_api_key":
        # A write key may edit flows but not delete assistants.
        write_key = await _mint_key(
            db_container,
            admin_user,
            permission="write",
            scope_type="space",
            scope_id=space_id,
        )
        headers = {"X-API-Key": write_key.key}
    else:
        headers = await _flows_manage_only_owner_headers(
            db_container,
            tenant_id=admin_user.tenant_id,
            space_id=space_id,
            flow_id=flow.id,
        )

    # Saving a step reads its assistant, which needs the tenant ASSISTANTS
    # permission, so a caller without it can only remove every step.
    kept_steps = [] if caller == "flows_manage_only_owner" else flow.steps[:1]
    response = await _save_steps(client, flow, kept_steps, headers)

    assert response.status_code == 200, response.text
    assert await _state(
        db_container,
        assistant_ids=[kept_id, removed_id],
        key_id=key.id,
        icon_id=icon_id,
    ) == (
        {step.assistant_id for step in kept_steps},
        ApiKeyState.REVOKED.value,
        False,
    )
    async with db_container() as container:
        updated_flow = await container.flow_service().get_flow(flow.id)
    assert [(step.step_order, step.assistant_id) for step in updated_flow.steps] == [
        (step.step_order, step.assistant_id) for step in kept_steps
    ]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("icon_owner", "icon_survives"),
    [("own_unused", False), ("other_tenant", True), ("the_space", True)],
)
async def test_removing_a_step_deletes_only_an_own_unused_icon(
    icon_owner: str,
    icon_survives: bool,
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
):
    _ = patch_auth_service_jwt
    admin_token, space_id = await _admin_token_and_space(
        client, db_container, admin_user
    )
    headers = {"Authorization": f"Bearer {admin_token}"}
    flow, _, removed_id = await _two_step_flow(db_container, space_id=space_id)
    if icon_owner == "other_tenant":
        async with db_container() as container:
            other_tenant = Tenants(
                name=f"flow-step-removal-{uuid4()}",
                display_name=None,
                slug=f"flow-step-removal-{uuid4()}",
                quota_limit=1024**3,
            )
            container.session().add(other_tenant)
            await container.session().flush()
            other_tenant_id = other_tenant.id
        icon_id = await _icon(db_container, tenant_id=other_tenant_id)
    else:
        icon_id = await _icon(db_container, tenant_id=admin_user.tenant_id)
    if icon_owner == "the_space":
        async with db_container() as container:
            await container.session().execute(
                sa.update(Spaces).where(Spaces.id == space_id).values(icon_id=icon_id)
            )
    # Icon ids are public, and a flow assistant may name any of them.
    icon_response = await client.patch(
        f"/api/v1/flows/{flow.id}/assistants/{removed_id}/",
        json={"icon_id": str(icon_id)},
        headers=headers,
    )
    assert icon_response.status_code == 200, icon_response.text

    response = await _save_steps(client, flow, flow.steps[:1], headers)

    assert response.status_code == 200, response.text
    async with db_container() as container:
        session = container.session()
        icon_row = await session.scalar(sa.select(Icons.id).where(Icons.id == icon_id))
        space_icon_id = await session.scalar(
            sa.select(Spaces.icon_id).where(Spaces.id == space_id)
        )
    assert (icon_row is not None) is icon_survives
    if icon_owner == "the_space":
        assert space_icon_id == icon_id


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "refused",
    ["user_assistant", "other_flows_assistant", "assistant_a_step_uses", "mixed"],
)
async def test_flow_managed_deletion_refuses_what_the_flow_may_not_delete(
    refused: str,
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
):
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow, kept_id, _ = await _two_step_flow(db_container, space_id=space_id)
    _, other_flows_id, _ = await _two_step_flow(
        db_container, space_id=space_id, name="Ett annat flöde"
    )
    async with db_container() as container:
        user_assistant, _ = await container.assistant_service().create_assistant(
            name="plain", space_id=space_id
        )
        unattached, _ = await container.flow_service().create_flow_assistant(
            flow_id=flow.id, name="unattached"
        )
    icon_id = await _icon(db_container, tenant_id=admin_user.tenant_id)
    await _set_icon(db_container, assistant_id=unattached.id, icon_id=icon_id)
    key = await _mint_key(
        db_container,
        admin_user,
        permission="read",
        scope_type="assistant",
        scope_id=unattached.id,
    )
    requested = {
        "user_assistant": {user_assistant.id},
        "other_flows_assistant": {other_flows_id},
        "assistant_a_step_uses": {kept_id},
        # The flow may delete `unattached`, but not the whole set.
        "mixed": {unattached.id, other_flows_id},
    }[refused]

    async with db_container() as container:
        with pytest.raises(BadRequestException) as caught:
            await container.assistant_service().delete_flow_managed_assistants(
                flow_id=flow.id, assistant_ids=requested
            )
    assert caught.value.code == "flow_managed_assistant"

    candidates = [user_assistant.id, other_flows_id, kept_id, unattached.id]
    assert await _state(
        db_container, assistant_ids=candidates, key_id=key.id, icon_id=icon_id
    ) == (set(candidates), ApiKeyState.ACTIVE.value, True)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_deleting_a_flow_assistant_deletes_it_completely(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
):
    _ = patch_auth_service_jwt
    admin_token, space_id = await _admin_token_and_space(
        client, db_container, admin_user
    )
    flow, _, _ = await _two_step_flow(db_container, space_id=space_id)
    async with db_container() as container:
        spare, _ = await container.flow_service().create_flow_assistant(
            flow_id=flow.id, name="spare"
        )
    icon_id = await _icon(db_container, tenant_id=admin_user.tenant_id)
    await _set_icon(db_container, assistant_id=spare.id, icon_id=icon_id)
    key = await _mint_key(
        db_container,
        admin_user,
        permission="read",
        scope_type="assistant",
        scope_id=spare.id,
    )

    response = await client.delete(
        f"/api/v1/flows/{flow.id}/assistants/{spare.id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 204, response.text
    assert await _state(
        db_container, assistant_ids=[spare.id], key_id=key.id, icon_id=icon_id
    ) == (set(), ApiKeyState.REVOKED.value, False)
    # The revocation audit commits with the deletion.
    assert await _revocation_audit_count(db_container, key_ids=[key.id]) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_deleting_a_flow_assistant_a_step_uses_is_refused(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
):
    _ = patch_auth_service_jwt
    admin_token, space_id = await _admin_token_and_space(
        client, db_container, admin_user
    )
    flow, used_id, _ = await _two_step_flow(db_container, space_id=space_id)
    icon_id = await _icon(db_container, tenant_id=admin_user.tenant_id)
    await _set_icon(db_container, assistant_id=used_id, icon_id=icon_id)
    key = await _mint_key(
        db_container,
        admin_user,
        permission="read",
        scope_type="assistant",
        scope_id=used_id,
    )

    response = await client.delete(
        f"/api/v1/flows/{flow.id}/assistants/{used_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # The documented 400 of delete_flow_assistant, with nothing deleted.
    assert response.status_code == 400, response.text
    body = response.json()
    assert body.pop("request_id")
    assert body == {
        "message": (
            "Only assistants the flow manages and no step uses can be deleted with it."
        ),
        "eneo_error_code": 9007,
        "code": "flow_managed_assistant",
        "context": {"flow_id": str(flow.id), "assistant_ids": [str(used_id)]},
    }
    assert await _state(
        db_container, assistant_ids=[used_id], key_id=key.id, icon_id=icon_id
    ) == ({used_id}, ApiKeyState.ACTIVE.value, True)


async def _spare_assistant_with_icon_and_key(db_container, admin_user, *, flow):
    async with db_container() as container:
        spare, _ = await container.flow_service().create_flow_assistant(
            flow_id=flow.id, name="spare"
        )
    icon_id = await _icon(db_container, tenant_id=admin_user.tenant_id)
    await _set_icon(db_container, assistant_id=spare.id, icon_id=icon_id)
    key = await _mint_key(
        db_container,
        admin_user,
        permission="read",
        scope_type="assistant",
        scope_id=spare.id,
    )
    return spare.id, icon_id, key.id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_delete_statement_refuses_an_assistant_a_step_uses_when_it_runs(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    monkeypatch: pytest.MonkeyPatch,
):
    _ = patch_auth_service_jwt
    admin_token, space_id = await _admin_token_and_space(
        client, db_container, admin_user
    )
    flow, _, _ = await _two_step_flow(db_container, space_id=space_id)
    spare_id, icon_id, key_id = await _spare_assistant_with_icon_and_key(
        db_container, admin_user, flow=flow
    )
    delete_removable = AssistantRepository.delete_removable_flow_managed

    async def delete_after_a_step_attaches(self, **kwargs):
        # A step using the assistant becomes visible after every check that
        # precedes the delete statement (inserted here through the request's
        # own session): the conditional DELETE skips the row, and comparing
        # its RETURNING ids with the request turns that into the 400.
        await self.session.execute(
            sa.insert(FlowSteps).values(
                flow_id=flow.id,
                tenant_id=admin_user.tenant_id,
                assistant_id=spare_id,
                step_order=3,
                input_source="previous_step",
            )
        )
        return await delete_removable(self, **kwargs)

    audited: list[ActionType] = []
    log_async = AuditService.log_async

    async def record_audit(self, **kwargs):
        audited.append(kwargs["action"])
        return await log_async(self, **kwargs)

    monkeypatch.setattr(
        AssistantRepository,
        "delete_removable_flow_managed",
        delete_after_a_step_attaches,
    )
    monkeypatch.setattr(AuditService, "log_async", record_audit)

    response = await client.delete(
        f"/api/v1/flows/{flow.id}/assistants/{spare_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "flow_managed_assistant"
    assert audited == []
    assert await _state(
        db_container, assistant_ids=[spare_id], key_id=key_id, icon_id=icon_id
    ) == ({spare_id}, ApiKeyState.ACTIVE.value, True)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_failing_key_revocation_deletes_nothing(
    app,
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    monkeypatch: pytest.MonkeyPatch,
):
    _ = patch_auth_service_jwt
    admin_token, space_id = await _admin_token_and_space(
        client, db_container, admin_user
    )
    flow, _, _ = await _two_step_flow(db_container, space_id=space_id)
    spare_id, icon_id, key_id = await _spare_assistant_with_icon_and_key(
        db_container, admin_user, flow=flow
    )

    async def fail_revocation(self, **kwargs):
        raise RuntimeError("API key revocation failed")

    monkeypatch.setattr(ApiKeyScopeRevoker, "revoke_scope", fail_revocation)

    # The error must reach the caller as a response, not only as a raise.
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test.local",
    ) as raw_client:
        response = await raw_client.delete(
            f"/api/v1/flows/{flow.id}/assistants/{spare_id}/",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 500, response.text
    assert await _state(
        db_container, assistant_ids=[spare_id], key_id=key_id, icon_id=icon_id
    ) == ({spare_id}, ApiKeyState.ACTIVE.value, True)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_failure_after_one_revocation_leaves_no_revocation_audit(
    app,
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    monkeypatch: pytest.MonkeyPatch,
):
    _ = patch_auth_service_jwt
    admin_token, space_id = await _admin_token_and_space(
        client, db_container, admin_user
    )
    flow, _, _ = await _two_step_flow(db_container, space_id=space_id)
    spare_id, icon_id, first_key_id = await _spare_assistant_with_icon_and_key(
        db_container, admin_user, flow=flow
    )
    second_key = await _mint_key(
        db_container,
        admin_user,
        permission="read",
        scope_type="assistant",
        scope_id=spare_id,
    )
    update_key = ApiKeysV2Repository.update
    revocations = 0

    async def fail_the_second_revocation(self, **kwargs):
        nonlocal revocations
        if kwargs.get("state") == ApiKeyState.REVOKED.value:
            revocations += 1
            if revocations == 2:
                raise RuntimeError("API key revocation failed")
        return await update_key(self, **kwargs)

    queued: list[ActionType] = []
    log_async = AuditService.log_async

    async def record_queued_audit(self, **kwargs):
        queued.append(kwargs["action"])
        return await log_async(self, **kwargs)

    monkeypatch.setattr(ApiKeysV2Repository, "update", fail_the_second_revocation)
    monkeypatch.setattr(AuditService, "log_async", record_queued_audit)

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test.local",
    ) as raw_client:
        response = await raw_client.delete(
            f"/api/v1/flows/{flow.id}/assistants/{spare_id}/",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    # The first revocation's audit rolls back with it; none left the request.
    assert response.status_code == 500, response.text
    assert revocations == 2
    assert queued == []
    key_ids = [first_key_id, second_key.id]
    assert await _revocation_audit_count(db_container, key_ids=key_ids) == 0
    async with db_container() as container:
        key_states = set(
            await container.session().scalars(
                sa.select(ApiKeysV2.state).where(ApiKeysV2.id.in_(key_ids))
            )
        )
    assert key_states == {ApiKeyState.ACTIVE.value}
    assert await _state(
        db_container, assistant_ids=[spare_id], key_id=first_key_id, icon_id=icon_id
    ) == ({spare_id}, ApiKeyState.ACTIVE.value, True)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_deleting_a_flow_without_runs_deletes_its_assistants_completely(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
):
    _ = patch_auth_service_jwt
    admin_token, space_id = await _admin_token_and_space(
        client, db_container, admin_user
    )
    flow, kept_id, removed_id = await _two_step_flow(db_container, space_id=space_id)
    icon_id = await _icon(db_container, tenant_id=admin_user.tenant_id)
    await _set_icon(db_container, assistant_id=removed_id, icon_id=icon_id)
    key = await _mint_key(
        db_container,
        admin_user,
        permission="read",
        scope_type="assistant",
        scope_id=removed_id,
    )

    response = await client.delete(
        f"/api/v1/flows/{flow.id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 204, response.text
    assert await _state(
        db_container,
        assistant_ids=[kept_id, removed_id],
        key_id=key.id,
        icon_id=icon_id,
    ) == (set(), ApiKeyState.REVOKED.value, False)
