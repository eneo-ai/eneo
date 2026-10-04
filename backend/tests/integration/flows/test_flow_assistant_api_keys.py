"""A flow-managed step assistant is internal configuration, never an API key
scope: a key for one cannot be created or rotated, an existing one cannot
authenticate, the daily key maintenance revokes it, and the space owners that
revoke keys by assistant find hidden assistants too."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from eneo.assistants.assistant_service import AssistantService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.schemas.audit_config_schemas import ActionUpdate
from eneo.authentication.api_key_scope_revoker import ApiKeyScopeRevoker
from eneo.authentication.auth_models import ApiKeyStateReasonCode
from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.database.tables.flow_tables import Flows
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.users.user import UserAdd, UserState, UserUpdate
from eneo.worker.routes import api_key_maintenance
from tests.fixtures import mint_v2_api_key

REFUSAL_CODE = "flow_managed_assistant"


async def _token_and_space(client, db_container, admin_user) -> tuple[str, UUID]:
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"flow-assistant-keys-{uuid4().hex[:8]}",
                permissions=[
                    Permission.ASSISTANTS,
                    Permission.SHARED_SPACES,
                    Permission.FLOWS_MANAGE,
                    Permission.API_KEYS,
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
        json={"name": f"flow-assistant-keys-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return token, UUID(response.json()["id"])


async def _flow_assistant(db_container, *, space_id: UUID) -> tuple[UUID, UUID]:
    """(flow id, the id of an assistant that flow manages)."""
    async with db_container() as container:
        flow_service = container.flow_service()
        flow = await flow_service.create_flow(
            space_id=space_id, name="Nycklar", description="", steps=[]
        )
        assistant, _ = await flow_service.create_flow_assistant(
            flow_id=flow.id, name="steg"
        )
    return flow.id, assistant.id


async def _visible_assistant(db_container, *, space_id: UUID) -> UUID:
    async with db_container() as container:
        assistant, _ = await container.assistant_service().create_assistant(
            name="Synlig", space_id=space_id
        )
    return assistant.id


async def _mint(db_container, *, tenant_id: UUID, user_id: UUID, scope_id: UUID):
    async with db_container() as container:
        return await mint_v2_api_key(
            container.api_key_v2_repo(),
            tenant_id=tenant_id,
            user_id=user_id,
            scope_type="assistant",
            scope_id=scope_id,
        )


async def _keys_scoped_to(db_container, scope_id: UUID) -> list[tuple[UUID, str]]:
    async with db_container() as container:
        rows = await container.session().execute(
            sa.select(ApiKeysV2.id, ApiKeysV2.state).where(
                ApiKeysV2.scope_id == scope_id
            )
        )
    return [(row.id, row.state) for row in rows]


async def _key_row(db_container, key_id: UUID):
    async with db_container() as container:
        return (
            await container.session().execute(
                sa.select(
                    ApiKeysV2.state,
                    ApiKeysV2.revoked_at,
                    ApiKeysV2.revoked_reason_code,
                ).where(ApiKeysV2.id == key_id)
            )
        ).one()


async def _revocation_audit(db_container, key_ids) -> list[tuple[UUID, str]]:
    async with db_container() as container:
        rows = await container.session().execute(
            sa.select(AuditLogTable.entity_id, AuditLogTable.actor_type)
            .where(AuditLogTable.action == ActionType.API_KEY_REVOKED.value)
            .where(AuditLogTable.entity_id.in_(key_ids))
        )
    return sorted((row.entity_id, str(row.actor_type)) for row in rows)


def _create_body(scope_id: UUID) -> dict[str, object]:
    return {
        "name": "Stegnyckel",
        "key_type": "sk_",
        "permission": "read",
        "scope_type": "assistant",
        "scope_id": str(scope_id),
    }


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("flow_state", ["live", "soft_deleted"])
async def test_creating_a_key_for_a_flow_managed_assistant_is_refused(
    flow_state: str, client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    token, space_id = await _token_and_space(client, db_container, admin_user)
    flow_id, assistant_id = await _flow_assistant(db_container, space_id=space_id)
    if flow_state == "soft_deleted":
        async with db_container() as container:
            await container.session().execute(
                sa.update(Flows)
                .where(Flows.id == flow_id)
                .values(deleted_at=datetime.now(timezone.utc))
            )

    response = await client.post(
        "/api/v1/api-keys",
        json=_create_body(assistant_id),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == REFUSAL_CODE
    assert await _keys_scoped_to(db_container, assistant_id) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_creating_a_key_for_a_visible_or_missing_assistant_is_unchanged(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    token, space_id = await _token_and_space(client, db_container, admin_user)
    visible_id = await _visible_assistant(db_container, space_id=space_id)
    missing_id = uuid4()

    created = await client.post(
        "/api/v1/api-keys",
        json=_create_body(visible_id),
        headers={"Authorization": f"Bearer {token}"},
    )
    missing = await client.post(
        "/api/v1/api-keys",
        json=_create_body(missing_id),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert created.status_code == 201, created.text
    assert missing.status_code == 404, missing.text
    assert await _keys_scoped_to(db_container, missing_id) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rotating_a_key_of_a_flow_managed_assistant_is_refused(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    token, space_id = await _token_and_space(client, db_container, admin_user)
    _, assistant_id = await _flow_assistant(db_container, space_id=space_id)
    key = await _mint(
        db_container,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        scope_id=assistant_id,
    )

    response = await client.post(
        f"/api/v1/api-keys/{key.id}/rotate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == REFUSAL_CODE
    assert [
        key_id for key_id, _ in await _keys_scoped_to(db_container, assistant_id)
    ] == [key.id]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "target", ["own_assistant", "other_assistant", "space", "space_assistants"]
)
async def test_a_key_of_a_flow_managed_assistant_cannot_authenticate(
    target: str, client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    _, space_id = await _token_and_space(client, db_container, admin_user)
    _, assistant_id = await _flow_assistant(db_container, space_id=space_id)
    visible_id = await _visible_assistant(db_container, space_id=space_id)
    key = await _mint(
        db_container,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        scope_id=assistant_id,
    )
    # By assistant id loads the space through that assistant; the space routes
    # load it through get_space.
    path = {
        "own_assistant": f"/api/v1/assistants/{assistant_id}/",
        "other_assistant": f"/api/v1/assistants/{visible_id}/",
        "space": f"/api/v1/spaces/{space_id}/",
        "space_assistants": f"/api/v1/spaces/{space_id}/applications/",
    }[target]

    response = await client.get(path, headers={"X-API-Key": key.key})

    assert response.status_code == 403, response.text
    assert response.json()["code"] == REFUSAL_CODE


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_key_of_a_visible_assistant_still_authenticates(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    _, space_id = await _token_and_space(client, db_container, admin_user)
    visible_id = await _visible_assistant(db_container, space_id=space_id)
    key = await _mint(
        db_container,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        scope_id=visible_id,
    )

    response = await client.get(
        f"/api/v1/assistants/{visible_id}/", headers={"X-API-Key": key.key}
    )

    assert response.status_code == 200, response.text


async def _sweep_fixture(client, db_container, admin_user):
    """Keys on: a flow-managed assistant (active, and already revoked), a
    visible assistant, a hidden user assistant, and an assistant id that no
    longer exists."""
    _, space_id = await _token_and_space(client, db_container, admin_user)
    _, flow_assistant_id = await _flow_assistant(db_container, space_id=space_id)
    visible_id = await _visible_assistant(db_container, space_id=space_id)
    hidden_user_id = await _visible_assistant(db_container, space_id=space_id)
    async with db_container() as container:
        await container.session().execute(
            sa.update(Assistants)
            .where(Assistants.id == hidden_user_id)
            .values(hidden=True)
        )
    mint = {"tenant_id": admin_user.tenant_id, "user_id": admin_user.id}
    first = await _mint(db_container, scope_id=flow_assistant_id, **mint)
    second = await _mint(db_container, scope_id=flow_assistant_id, **mint)
    revoked = await _mint(db_container, scope_id=flow_assistant_id, **mint)
    async with db_container() as container:
        await container.session().execute(
            sa.update(ApiKeysV2)
            .where(ApiKeysV2.id == revoked.id)
            .values(state="revoked", revoked_at=datetime.now(timezone.utc))
        )
    untouched = [
        await _mint(db_container, scope_id=scope_id, **mint)
        for scope_id in (visible_id, hidden_user_id, uuid4())
    ]
    return first, second, revoked, untouched, hidden_user_id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_key_maintenance_revokes_keys_of_flow_managed_assistants_once(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    first, second, revoked, untouched, hidden_user_id = await _sweep_fixture(
        client, db_container, admin_user
    )
    swept = [first.id, second.id]

    for _ in range(2):
        async with db_container() as container:
            results = await api_key_maintenance.__wrapped__(container=container)
        assert not [
            error for error in results["errors"] if error["key_id"] in map(str, swept)
        ]

    for key_id in swept:
        state, revoked_at, reason = await _key_row(db_container, key_id)
        assert (state, reason) == ("revoked", "policy_violation")
        assert revoked_at is not None
    assert await _revocation_audit(
        db_container, [*swept, revoked.id, *(key.id for key in untouched)]
    ) == sorted((key_id, "system") for key_id in swept)
    for key in untouched:
        assert (await _key_row(db_container, key.id))[0] == "active"
    # Only flow-managed assistants are prohibited: a key of an ordinary hidden
    # assistant keeps its access.
    response = await client.get(
        f"/api/v1/assistants/{hidden_user_id}/",
        headers={"X-API-Key": untouched[1].key},
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_key_maintenance_leaves_expiry_and_rotation_cleanup_off(
    client, db_container, admin_user, patch_auth_service_jwt
):
    """The job runs only the policy sweep: the expiry and rotation-cleanup
    phases stay disabled until they are hardened (eneo-946w)."""
    _ = patch_auth_service_jwt
    _, space_id = await _token_and_space(client, db_container, admin_user)
    visible_id = await _visible_assistant(db_container, space_id=space_id)
    mint = {"tenant_id": admin_user.tenant_id, "user_id": admin_user.id}
    past_expiry = await _mint(db_container, scope_id=visible_id, **mint)
    past_grace = await _mint(db_container, scope_id=visible_id, **mint)
    past = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(ApiKeysV2)
            .where(ApiKeysV2.id == past_expiry.id)
            .values(expires_at=past)
        )
        await session.execute(
            sa.update(ApiKeysV2)
            .where(ApiKeysV2.id == past_grace.id)
            .values(rotation_grace_until=past)
        )

    async with db_container() as container:
        results = await api_key_maintenance.__wrapped__(container=container)

    assert set(results) == {"flow_managed_assistant_revoked", "errors"}
    for key in (past_expiry, past_grace):
        state, revoked_at, _ = await _key_row(db_container, key.id)
        assert (state, revoked_at) == ("active", None)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_interrupted_key_sweep_completes_on_the_next_run(
    client, db_container, admin_user, patch_auth_service_jwt, monkeypatch
):
    _ = patch_auth_service_jwt
    first, second, *_ = await _sweep_fixture(client, db_container, admin_user)
    swept = sorted([first.id, second.id], key=str)

    from eneo.audit.application.audit_service import AuditService

    original_log = AuditService.log

    async def fail_for_the_second_key(self, *args, **kwargs):
        if kwargs.get("entity_id") == swept[1]:
            raise RuntimeError("audit write failed")
        return await original_log(self, *args, **kwargs)

    monkeypatch.setattr(AuditService, "log", fail_for_the_second_key)
    async with db_container() as container:
        results = await (
            container.api_key_maintenance_service().revoke_flow_managed_assistant_keys()
        )
    assert [
        error["key_id"]
        for error in results["errors"]
        if error["key_id"] in map(str, swept)
    ] == [str(swept[1])]
    assert (await _key_row(db_container, swept[1]))[0] == "active"
    assert await _revocation_audit(db_container, swept) == [(swept[0], "system")]

    monkeypatch.setattr(AuditService, "log", original_log)
    async with db_container() as container:
        await (
            container.api_key_maintenance_service().revoke_flow_managed_assistant_keys()
        )

    assert [(await _key_row(db_container, key_id))[0] for key_id in swept] == [
        "revoked",
        "revoked",
    ]
    assert await _revocation_audit(db_container, swept) == sorted(
        (key_id, "system") for key_id in swept
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reactivating_a_key_of_a_flow_managed_assistant_is_refused(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    token, space_id = await _token_and_space(client, db_container, admin_user)
    _, assistant_id = await _flow_assistant(db_container, space_id=space_id)
    key = await _mint(
        db_container,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        scope_id=assistant_id,
    )
    async with db_container() as container:
        await container.session().execute(
            sa.update(ApiKeysV2)
            .where(ApiKeysV2.id == key.id)
            .values(state="suspended", suspended_at=datetime.now(timezone.utc))
        )

    response = await client.post(
        f"/api/v1/api-keys/{key.id}/reactivate",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == REFUSAL_CODE
    assert (await _key_row(db_container, key.id))[0] == "suspended"


async def _flow_key_selection(client, db_container, admin_user):
    _, space_id = await _token_and_space(client, db_container, admin_user)
    _, assistant_id = await _flow_assistant(db_container, space_id=space_id)
    key = await _mint(
        db_container,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        scope_id=assistant_id,
    )
    async with db_container() as container:
        selected = await container.api_key_v2_repo().get(
            key_id=key.id, tenant_id=admin_user.tenant_id
        )
    assert selected is not None
    return selected


async def _revoke_as_system(db_container, keys, reason_text: str) -> int:
    async with db_container() as container:
        revoker = ApiKeyScopeRevoker(
            container.api_key_v2_repo(), container.audit_service(), user=None
        )
        return await revoker.revoke_as_system(
            keys,
            reason_code=ApiKeyStateReasonCode.POLICY_VIOLATION,
            reason_text=reason_text,
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_stale_selection_revokes_and_audits_a_key_once(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    stale = await _flow_key_selection(client, db_container, admin_user)

    first = await _revoke_as_system(db_container, [stale], "first")
    second = await _revoke_as_system(db_container, [stale], "second")

    assert (first, second) == (1, 0)
    async with db_container() as container:
        reason_text = await container.session().scalar(
            sa.select(ApiKeysV2.revoked_reason_text).where(ApiKeysV2.id == stale.id)
        )
    assert reason_text == "first"
    assert await _revocation_audit(db_container, [stale.id]) == [(stale.id, "system")]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_revocation_between_selection_and_update_is_kept(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    stale = await _flow_key_selection(client, db_container, admin_user)
    admin_revoked_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    async with db_container() as container:
        await container.session().execute(
            sa.update(ApiKeysV2)
            .where(ApiKeysV2.id == stale.id)
            .values(
                state="revoked",
                revoked_at=admin_revoked_at,
                revoked_reason_code="admin_action",
            )
        )

    assert await _revoke_as_system(db_container, [stale], "sweep") == 0
    state, revoked_at, reason = await _key_row(db_container, stale.id)
    assert (state, revoked_at, reason) == ("revoked", admin_revoked_at, "admin_action")
    assert await _revocation_audit(db_container, [stale.id]) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_system_revocation_is_audited_when_the_action_is_turned_off(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    stale = await _flow_key_selection(client, db_container, admin_user)
    action_off = [ActionUpdate(action=ActionType.API_KEY_REVOKED.value, enabled=False)]
    action_on = [ActionUpdate(action=ActionType.API_KEY_REVOKED.value, enabled=True)]
    async with db_container() as container:
        await container.audit_config_service().update_action_config(
            admin_user.tenant_id, action_off
        )
    try:
        async with db_container() as container:
            assert not await container.audit_service()._should_log_action(  # pyright: ignore[reportPrivateUsage]
                admin_user.tenant_id, ActionType.API_KEY_REVOKED
            )
        assert await _revoke_as_system(db_container, [stale], "sweep") == 1
    finally:
        async with db_container() as container:
            await container.audit_config_service().update_action_config(
                admin_user.tenant_id, action_on
            )

    assert await _revocation_audit(db_container, [stale.id]) == [(stale.id, "system")]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_deleting_a_space_revokes_keys_of_its_hidden_assistants(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    token, space_id = await _token_and_space(client, db_container, admin_user)
    hidden_id = await _visible_assistant(db_container, space_id=space_id)
    async with db_container() as container:
        await container.session().execute(
            sa.update(Assistants).where(Assistants.id == hidden_id).values(hidden=True)
        )
    key = await _mint(
        db_container,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        scope_id=hidden_id,
    )

    response = await client.delete(
        f"/api/v1/spaces/{space_id}/", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 204, response.text
    assert (await _key_row(db_container, key.id))[0] == "revoked"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_removing_a_member_revokes_their_keys_of_flow_managed_assistants(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    token, space_id = await _token_and_space(client, db_container, admin_user)
    _, assistant_id = await _flow_assistant(db_container, space_id=space_id)
    async with db_container() as container:
        member = await container.user_repo().add(
            UserAdd(
                email=f"flow-key-member-{uuid4().hex[:8]}@example.com",
                username=f"flow_key_member_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
            )
        )
        await container.session().execute(
            sa.text(
                "INSERT INTO spaces_users (space_id, user_id, role) "
                "VALUES (:space_id, :user_id, :role)"
            ),
            {
                "space_id": str(space_id),
                "user_id": str(member.id),
                "role": SpaceRoleValue.EDITOR.value,
            },
        )
    key = await _mint(
        db_container,
        tenant_id=admin_user.tenant_id,
        user_id=member.id,
        scope_id=assistant_id,
    )

    response = await client.delete(
        f"/api/v1/spaces/{space_id}/members/{member.id}/",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 204, response.text
    assert (await _key_row(db_container, key.id))[0] == "revoked"


def test_flow_managed_assistant_cleanup_always_has_a_key_revoker():
    parameter = inspect.signature(AssistantService).parameters["api_key_scope_revoker"]

    assert parameter.default is inspect.Parameter.empty
    assert "None" not in str(parameter.annotation)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_flow_managed_origin_always_names_its_flow(
    client, db_container, admin_user, patch_auth_service_jwt
):
    """origin decides "flow-managed": the schema ties it to managing_flow_id,
    so neither can be set without the other."""
    _ = patch_auth_service_jwt
    _, space_id = await _token_and_space(client, db_container, admin_user)
    _, flow_assistant_id = await _flow_assistant(db_container, space_id=space_id)
    visible_id = await _visible_assistant(db_container, space_id=space_id)
    flow_id = await _row_flow(db_container, flow_assistant_id)

    for assistant_id, values in (
        (flow_assistant_id, {"managing_flow_id": None}),
        (visible_id, {"managing_flow_id": flow_id, "hidden": True}),
    ):
        with pytest.raises(IntegrityError):
            async with db_container() as container:
                await container.session().execute(
                    sa.update(Assistants)
                    .where(Assistants.id == assistant_id)
                    .values(**values)
                )


async def _row_flow(db_container, assistant_id: UUID) -> UUID:
    async with db_container() as container:
        flow_id = await container.session().scalar(
            sa.select(Assistants.managing_flow_id).where(Assistants.id == assistant_id)
        )
    assert flow_id is not None
    return flow_id
