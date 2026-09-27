"""Creating, deleting or publishing one assistant writes only that assistant, so
a change another transaction commits meanwhile is neither undone nor deleted by
it. A whole-space write that still exists (group chat create) no longer deletes
an assistant created after it loaded the space."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.assistants.assistant_service import AssistantService
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.spaces_table import SpacesCompletionModels
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.spaces.space_repo import SpaceRepository
from eneo.users.user import UserUpdate


async def _admin_token(db_container, admin_user) -> str:
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"space-member-writes-{uuid4().hex[:8]}",
                permissions=[
                    Permission.ASSISTANTS,
                    Permission.GROUP_CHATS,
                    Permission.SHARED_SPACES,
                ],
                tenant_id=admin_user.tenant_id,
            )
        )
    async with db_container() as container:
        admin = await container.user_repo().update(
            UserUpdate(id=admin_user.id, roles=[ModelId(id=role.id)])
        )
        assert admin is not None
        return container.auth_service().create_access_token_for_user(admin)


async def _create_space(client, token: str) -> UUID:
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"space-member-writes-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def _admin_token_and_space(client, db_container, admin_user) -> tuple[str, UUID]:
    token = await _admin_token(db_container, admin_user)
    return token, await _create_space(client, token)


async def _create_assistant(client, token: str, space_id: UUID, name: str) -> UUID:
    response = await client.post(
        f"/api/v1/spaces/{space_id}/applications/assistants/",
        json={"name": name},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def _names(db_container, space_id: UUID) -> dict[UUID, str]:
    async with db_container() as container:
        rows = await container.session().execute(
            sa.select(Assistants.id, Assistants.name)
            .where(Assistants.space_id == space_id)
            .where(Assistants.is_default.is_(False))
        )
    return {row.id: row.name for row in rows}


def _rename(assistant_id: UUID, name: str):
    async def change(session) -> None:
        await session.execute(
            sa.update(Assistants).where(Assistants.id == assistant_id).values(name=name)
        )

    return change


def _move(assistant_id: UUID, space_id: UUID):
    async def change(session) -> None:
        await session.execute(
            sa.update(Assistants)
            .where(Assistants.id == assistant_id)
            .values(space_id=space_id)
        )

    return change


def _insert_assistant(space_id: UUID, user_id: UUID, created: list[UUID]):
    async def change(session) -> None:
        created.append(
            await session.scalar(
                sa.insert(Assistants)
                .values(
                    name="created meanwhile",
                    user_id=user_id,
                    space_id=space_id,
                    completion_model_kwargs={},
                    logging_enabled=False,
                    is_default=False,
                    published=False,
                )
                .returning(Assistants.id)
            )
        )

    return change


def _commit_elsewhere(db_container, *changes):
    # A second session and transaction, committed before the request goes on:
    # what another request finishing in between looks like to this one.
    async def run() -> None:
        async with db_container() as other:
            for change in changes:
                await change(other.session())

    return run


def _before(
    monkeypatch: pytest.MonkeyPatch, owner: type, method: str, run, *, call: int = 1
) -> None:
    # Runs ``run`` once, just before the ``call``-th call of ``method``.
    original = getattr(owner, method)
    calls = 0

    async def run_then_call(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == call:
            await run()
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(owner, method, run_then_call)


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
async def test_create_keeps_concurrent_sibling_update_and_creation(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    monkeypatch: pytest.MonkeyPatch,
):
    _ = patch_auth_service_jwt
    token, space_id = await _admin_token_and_space(client, db_container, admin_user)
    sibling_id = await _create_assistant(client, token, space_id, "sibling")

    created: list[UUID] = []
    # get_completion_model runs after create loaded the space, before it writes.
    _before(
        monkeypatch,
        AssistantService,
        "get_completion_model",
        _commit_elsewhere(
            db_container,
            _rename(sibling_id, "renamed elsewhere"),
            _insert_assistant(space_id, admin_user.id, created),
        ),
    )
    audited = _record_audit(monkeypatch)

    response = await client.post(
        f"/api/v1/spaces/{space_id}/applications/assistants/",
        json={"name": "new"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201, response.text
    new_id = UUID(response.json()["id"])
    assert response.json()["name"] == "new"
    assert await _names(db_container, space_id) == {
        sibling_id: "renamed elsewhere",
        created[0]: "created meanwhile",
        new_id: "new",
    }
    assert audited == [(ActionType.ASSISTANT_CREATED, new_id)]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_links_its_model_to_the_space(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
):
    _ = patch_auth_service_jwt
    token, space_id = await _admin_token_and_space(client, db_container, admin_user)
    async with db_container() as container:
        await container.session().execute(
            sa.delete(SpacesCompletionModels).where(
                SpacesCompletionModels.space_id == space_id
            )
        )

    new_id = await _create_assistant(client, token, space_id, "new")

    async with db_container() as container:
        session = container.session()
        model_id = await session.scalar(
            sa.select(Assistants.completion_model_id).where(Assistants.id == new_id)
        )
        linked = set(
            await session.scalars(
                sa.select(SpacesCompletionModels.completion_model_id).where(
                    SpacesCompletionModels.space_id == space_id
                )
            )
        )
    # The space had no model, so the assistant got the organisation default,
    # and creating it enabled that model in the space.
    assert model_id is not None
    assert linked == {model_id}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_does_not_touch_siblings(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    monkeypatch: pytest.MonkeyPatch,
):
    _ = patch_auth_service_jwt
    token, space_id = await _admin_token_and_space(client, db_container, admin_user)
    target_id = await _create_assistant(client, token, space_id, "target")
    sibling_id = await _create_assistant(client, token, space_id, "sibling")

    created: list[UUID] = []
    # _revoke_assistant_api_keys runs after delete loaded the space.
    _before(
        monkeypatch,
        AssistantService,
        "_revoke_assistant_api_keys",
        _commit_elsewhere(
            db_container,
            _rename(sibling_id, "renamed elsewhere"),
            _insert_assistant(space_id, admin_user.id, created),
        ),
    )
    audited = _record_audit(monkeypatch)

    response = await client.delete(
        f"/api/v1/assistants/{target_id}/",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 204, response.text
    assert await _names(db_container, space_id) == {
        sibling_id: "renamed elsewhere",
        created[0]: "created meanwhile",
    }
    assert audited == [(ActionType.ASSISTANT_DELETED, target_id)]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_of_an_assistant_moved_meanwhile_is_not_found(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    monkeypatch: pytest.MonkeyPatch,
):
    _ = patch_auth_service_jwt
    token, space_id = await _admin_token_and_space(client, db_container, admin_user)
    other_space_id = await _create_space(client, token)
    target_id = await _create_assistant(client, token, space_id, "target")

    _before(
        monkeypatch,
        AssistantService,
        "_revoke_assistant_api_keys",
        _commit_elsewhere(db_container, _move(target_id, other_space_id)),
    )
    audited = _record_audit(monkeypatch)

    response = await client.delete(
        f"/api/v1/assistants/{target_id}/",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Nothing was deleted, so nothing is reported or audited as deleted.
    assert response.status_code == 404, response.text
    assert audited == []
    assert await _names(db_container, other_space_id) == {target_id: "target"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_publish_keeps_a_rename_committed_meanwhile(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    monkeypatch: pytest.MonkeyPatch,
):
    _ = patch_auth_service_jwt
    token, space_id = await _admin_token_and_space(client, db_container, admin_user)
    target_id = await _create_assistant(client, token, space_id, "target")
    sibling_id = await _create_assistant(client, token, space_id, "sibling")

    created: list[UUID] = []
    # Between the load publish checks permissions on and the one it validates.
    _before(
        monkeypatch,
        SpaceRepository,
        "get_space_by_assistant",
        _commit_elsewhere(
            db_container,
            _rename(target_id, "target renamed elsewhere"),
            _rename(sibling_id, "renamed elsewhere"),
            _insert_assistant(space_id, admin_user.id, created),
        ),
        call=2,
    )
    audited = _record_audit(monkeypatch)

    response = await client.post(
        f"/api/v1/assistants/{target_id}/publish/?published=true",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["published"] is True
    assert response.json()["name"] == "target renamed elsewhere"
    assert await _names(db_container, space_id) == {
        target_id: "target renamed elsewhere",
        sibling_id: "renamed elsewhere",
        created[0]: "created meanwhile",
    }
    async with db_container() as container:
        assert await container.session().scalar(
            sa.select(Assistants.published).where(Assistants.id == target_id)
        )
    assert audited == [(ActionType.ASSISTANT_PUBLISHED, target_id)]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_whole_space_write_keeps_an_assistant_created_after_its_load(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    monkeypatch: pytest.MonkeyPatch,
):
    _ = patch_auth_service_jwt
    token, space_id = await _admin_token_and_space(client, db_container, admin_user)
    sibling_id = await _create_assistant(client, token, space_id, "sibling")

    created: list[UUID] = []
    _before(
        monkeypatch,
        SpaceRepository,
        "update",
        _commit_elsewhere(
            db_container, _insert_assistant(space_id, admin_user.id, created)
        ),
    )

    response = await client.post(
        f"/api/v1/spaces/{space_id}/applications/group-chats/",
        json={"name": "group"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201, response.text
    assert await _names(db_container, space_id) == {
        sibling_id: "sibling",
        created[0]: "created meanwhile",
    }
