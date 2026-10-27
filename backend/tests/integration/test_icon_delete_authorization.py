"""An icon id never authorizes removing an icon another resource still shows.

Icon ids are public: ``GET /icons/{id}/`` is unauthenticated and the id sits in
every ``<img src>``. Assistants, apps, spaces and group chats reference icons
with ``ON DELETE SET NULL``, so a delete that only checks the tenant silently
clears whatever resource uses the icon. A resource releases its icon itself
when an update replaces or clears it, or when the resource is deleted.
"""

import asyncio
from uuid import UUID, uuid4

import psycopg2
import pytest
import sqlalchemy as sa

from eneo.database.tables.assistant_table import Assistants
from eneo.icons.icon import IconInUseError
from eneo.main.exceptions import ErrorCodes, NotFoundException
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserAdd, UserState
from init_db import add_tenant_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

_RESOURCE_PATHS = {
    "assistant": "/api/v1/assistants/{id}/",
    "app": "/api/v1/apps/{id}/",
    "space": "/api/v1/spaces/{id}/",
    "group_chat": "/api/v1/group-chats/{id}/",
}
_CREATE_PATHS = {
    "assistant": "assistants",
    "app": "apps",
    "group_chat": "group-chats",
}


async def _headers(db_container, user) -> dict[str, str]:
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def owner(db_container, admin_user, patch_auth_service_jwt) -> dict[str, str]:
    return await _headers(db_container, admin_user)


@pytest.fixture
async def member(db_container, admin_user, patch_auth_service_jwt) -> dict[str, str]:
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"member-{uuid4().hex[:8]}",
                permissions=[Permission.ASSISTANTS, Permission.SHARED_SPACES],
                tenant_id=admin_user.tenant_id,
            )
        )
        user = await container.user_repo().add(
            UserAdd(
                email=f"member-{uuid4().hex[:8]}@example.com",
                username=f"member_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )
    return await _headers(db_container, user)


@pytest.fixture
async def other_tenant(db_container, test_settings, patch_auth_service_jwt):
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    add_tenant_user(
        conn,
        tenant_name="icon_tenant_2",
        quota_limit=1000000,
        user_name="icon_user_2",
        user_email="icon2@example.com",
        user_password="TenantFixturePass123!",
    )
    conn.close()
    async with db_container() as container:
        user = await container.user_repo().get_user_by_email("icon2@example.com")
    return await _headers(db_container, user)


@pytest.fixture
async def apps_enabled(db_container, transcription_model_factory) -> None:
    """Apps need a transcription model; the tenant default serves new spaces."""
    async with db_container() as container:
        await transcription_model_factory(
            container.session(), "whisper-icons", is_default=True
        )


async def _upload(client, headers: dict[str, str]) -> str:
    uploaded = await client.post(
        "/api/v1/icons/",
        files={"file": ("icon.png", _PNG, "image/png")},
        headers=headers,
    )
    assert uploaded.status_code == 200, uploaded.text
    return uploaded.json()["id"]


async def _create(
    client, headers: dict[str, str], kind: str, space_id: str | None = None
) -> str:
    """Create a resource of ``kind``, by default in a new space of the caller."""
    if space_id is None:
        space = await client.post(
            "/api/v1/spaces/",
            json={"name": f"Icons {uuid4().hex[:8]}"},
            headers=headers,
        )
        assert space.status_code == 201, space.text
        space_id = space.json()["id"]
    if kind == "space":
        return space_id
    created = await client.post(
        f"/api/v1/spaces/{space_id}/applications/{_CREATE_PATHS[kind]}/",
        json={"name": f"Shows an icon {uuid4().hex[:8]}"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def _set_icon(
    client, headers: dict[str, str], kind: str, resource_id: str, icon_id: str | None
):
    send = client.post if kind == "assistant" else client.patch
    return await send(
        _RESOURCE_PATHS[kind].format(id=resource_id),
        json={"icon_id": icon_id},
        headers=headers,
    )


async def _with_icon(
    client,
    headers: dict[str, str],
    kind: str = "assistant",
    icon_id: str | None = None,
    space_id: str | None = None,
) -> tuple[str, str]:
    """Create a resource of the caller and show an icon on it."""
    if icon_id is None:
        icon_id = await _upload(client, headers)
    resource_id = await _create(client, headers, kind, space_id)
    attached = await _set_icon(client, headers, kind, resource_id, icon_id)
    assert attached.status_code == 200, attached.text
    assert attached.json()["icon_id"] == icon_id
    return resource_id, icon_id


async def _shown_icon(
    client, headers: dict[str, str], resource_id: str, kind: str = "assistant"
) -> str | None:
    response = await client.get(
        _RESOURCE_PATHS[kind].format(id=resource_id), headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["icon_id"]


async def _icon_status(client, icon_id: str) -> int:
    return (await client.get(f"/api/v1/icons/{icon_id}/")).status_code


@pytest.mark.parametrize("caller", ["member", "owner"])
async def test_an_icon_an_assistant_shows_cannot_be_deleted(
    client, owner, member, caller
):
    assistant_id, icon_id = await _with_icon(client, owner)

    response = await client.delete(
        f"/api/v1/icons/{icon_id}/",
        headers={"member": member, "owner": owner}[caller],
    )

    assert response.status_code == 409, response.text
    assert response.json()["eneo_error_code"] == ErrorCodes.ICON_IN_USE == 9075
    assert await _shown_icon(client, owner, assistant_id) == icon_id
    assert await _icon_status(client, icon_id) == 200


async def test_an_icon_of_another_tenant_cannot_be_deleted(client, owner, other_tenant):
    icon_id = await _upload(client, owner)

    response = await client.delete(f"/api/v1/icons/{icon_id}/", headers=other_tenant)

    assert response.status_code == 400, response.text
    assert await _icon_status(client, icon_id) == 200


@pytest.mark.parametrize("change", ["replace", "clear"])
@pytest.mark.parametrize("kind", ["assistant", "app", "space", "group_chat"])
async def test_changing_the_icon_deletes_the_one_it_replaced(
    client, owner, apps_enabled, kind, change
):
    resource_id, icon_id = await _with_icon(client, owner, kind)
    new_icon_id = await _upload(client, owner) if change == "replace" else None

    changed = await _set_icon(client, owner, kind, resource_id, new_icon_id)

    assert changed.status_code == 200, changed.text
    assert await _shown_icon(client, owner, resource_id, kind) == new_icon_id
    assert await _icon_status(client, icon_id) == 404
    if new_icon_id is not None:
        assert await _icon_status(client, new_icon_id) == 200


async def test_sending_the_current_icon_again_keeps_it(client, owner):
    assistant_id, icon_id = await _with_icon(client, owner)

    resent = await _set_icon(client, owner, "assistant", assistant_id, icon_id)

    assert resent.status_code == 200, resent.text
    assert await _icon_status(client, icon_id) == 200


async def test_clearing_an_icon_keeps_it_for_another_resource_that_shows_it(
    client, owner, member
):
    owned_assistant, icon_id = await _with_icon(client, owner)
    borrowing_assistant, _ = await _with_icon(client, member, icon_id=icon_id)

    cleared = await _set_icon(client, member, "assistant", borrowing_assistant, None)

    assert cleared.status_code == 200, cleared.text
    assert await _shown_icon(client, owner, owned_assistant) == icon_id
    assert await _icon_status(client, icon_id) == 200


async def test_deleting_a_resource_keeps_an_icon_another_resource_shows(
    client, owner, member
):
    owned_assistant, icon_id = await _with_icon(client, owner)
    borrowing_assistant, _ = await _with_icon(client, member, icon_id=icon_id)

    deleted = await client.delete(
        f"/api/v1/assistants/{borrowing_assistant}/", headers=member
    )

    assert deleted.status_code == 204, deleted.text
    assert await _shown_icon(client, owner, owned_assistant) == icon_id
    assert await _icon_status(client, icon_id) == 200


@pytest.mark.parametrize("kind", ["assistant", "app", "space", "group_chat"])
async def test_deleting_the_last_resource_that_shows_an_icon_deletes_it(
    client, owner, apps_enabled, kind
):
    resource_id, icon_id = await _with_icon(client, owner, kind)

    deleted = await client.delete(
        _RESOURCE_PATHS[kind].format(id=resource_id), headers=owner
    )

    assert deleted.status_code == 204, deleted.text
    assert await _icon_status(client, icon_id) == 404


async def test_deleting_a_space_deletes_the_icons_of_the_resources_in_it(
    client, owner, apps_enabled
):
    space_id, space_icon = await _with_icon(client, owner, "space")
    icons = [space_icon]
    for kind in ("assistant", "app", "group_chat"):
        _, icon_id = await _with_icon(client, owner, kind, space_id=space_id)
        icons.append(icon_id)

    deleted = await client.delete(f"/api/v1/spaces/{space_id}/", headers=owner)

    assert deleted.status_code == 204, deleted.text
    assert [await _icon_status(client, icon_id) for icon_id in icons] == [404] * 4


def _deleting(db_container, icon_id: str, tenant_id: UUID):
    """Start ``delete_icon`` in its own session; the future resolves to its backend pid."""
    pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    async def delete() -> None:
        async with db_container() as deleting:
            pid.set_result(
                await deleting.session().scalar(sa.text("SELECT pg_backend_pid()"))
            )
            await deleting.icon_service().delete_icon(UUID(icon_id), tenant_id)

    return asyncio.create_task(delete()), pid


async def _wait_until_blocked(session, racer: asyncio.Task, racer_pid) -> None:
    """Return once ``racer`` waits on a lock this session's backend holds."""
    holder_pid = await session.scalar(sa.text("SELECT pg_backend_pid()"))
    await asyncio.wait(
        {racer, racer_pid}, timeout=10, return_when=asyncio.FIRST_COMPLETED
    )
    assert racer_pid.done(), "the racer finished before it reported its backend"
    for _ in range(200):
        assert not racer.done(), "the racer did not wait for the lock"
        blocked = await session.scalar(
            sa.text("SELECT :holder = ANY(pg_blocking_pids(:racer))"),
            {"holder": holder_pid, "racer": racer_pid.result()},
        )
        if blocked:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the racer never waited on the lock")


async def test_an_attach_committing_during_the_delete_keeps_the_icon(
    client, owner, admin_user, db_container
):
    icon_id = await _upload(client, owner)
    assistant_id = await _create(client, owner, "assistant")

    async with db_container() as attaching:
        session = attaching.session()
        # The foreign key check takes FOR KEY SHARE on the icon until commit.
        await session.execute(
            sa.update(Assistants)
            .where(Assistants.id == UUID(assistant_id))
            .values(icon_id=UUID(icon_id))
        )
        deleting, deleter_pid = _deleting(db_container, icon_id, admin_user.tenant_id)
        await _wait_until_blocked(session, deleting, deleter_pid)

    with pytest.raises(IconInUseError):
        await deleting
    assert await _shown_icon(client, owner, assistant_id) == icon_id
    assert await _icon_status(client, icon_id) == 200


async def test_a_delete_that_waited_for_another_delete_finds_nothing(
    client, owner, admin_user, db_container
):
    icon_id = await _upload(client, owner)

    async with db_container() as first:
        await first.icon_service().delete_icon(UUID(icon_id), admin_user.tenant_id)
        second, second_pid = _deleting(db_container, icon_id, admin_user.tenant_id)
        await _wait_until_blocked(first.session(), second, second_pid)

    with pytest.raises(NotFoundException):
        await second
