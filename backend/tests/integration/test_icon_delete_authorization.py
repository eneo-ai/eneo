"""An icon id never authorizes removing an icon another resource still shows.

Icon ids are public: ``GET /icons/{id}/`` is unauthenticated and the id sits in
every ``<img src>``. Assistants, apps, spaces and group chats reference icons
with ``ON DELETE SET NULL``, so a delete that only checks the tenant silently
clears whatever resource uses the icon. A resource releases its icon itself
when an update replaces or clears it, or when the resource is deleted, and
only an icon the caller uploaded in their tenant can be attached. Changes lock
the resource row before its icons, in id order, so concurrent changes neither
deadlock nor release the wrong icon.
"""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg2
import pytest
import sqlalchemy as sa

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from eneo.database.tables.app_table import Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.group_chats_table import GroupChatsTable
from eneo.database.tables.spaces_table import Spaces
from eneo.icons.icon import IconInUseError, IconNotAttachableError
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
async def member_user(db_container, admin_user):
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"member-{uuid4().hex[:8]}",
                permissions=[Permission.ASSISTANTS, Permission.SHARED_SPACES],
                tenant_id=admin_user.tenant_id,
            )
        )
        return await container.user_repo().add(
            UserAdd(
                email=f"member-{uuid4().hex[:8]}@example.com",
                username=f"member_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )


@pytest.fixture
async def member(db_container, member_user, patch_auth_service_jwt) -> dict[str, str]:
    return await _headers(db_container, member_user)


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


@pytest.mark.parametrize("release", ["clear", "delete"])
async def test_an_icon_another_resource_shows_survives_a_release(
    client, owner, release
):
    shown_by, icon_id = await _with_icon(client, owner)
    released_by, _ = await _with_icon(client, owner, icon_id=icon_id)

    if release == "clear":
        response = await _set_icon(client, owner, "assistant", released_by, None)
        assert response.status_code == 200, response.text
    else:
        response = await client.delete(
            f"/api/v1/assistants/{released_by}/", headers=owner
        )
        assert response.status_code == 204, response.text

    assert await _shown_icon(client, owner, shown_by) == icon_id
    assert await _icon_status(client, icon_id) == 200


@pytest.mark.parametrize("uploader", ["member", "other_tenant"])
@pytest.mark.parametrize("kind", ["assistant", "app", "space", "group_chat"])
async def test_a_resource_refuses_an_icon_the_caller_did_not_upload(
    client, owner, member, other_tenant, apps_enabled, kind, uploader
):
    foreign_icon = await _upload(
        client, {"member": member, "other_tenant": other_tenant}[uploader]
    )
    resource_id = await _create(client, owner, kind)

    response = await _set_icon(client, owner, kind, resource_id, foreign_icon)

    assert response.status_code == 400, response.text
    assert response.json()["eneo_error_code"] == ErrorCodes.ICON_NOT_ATTACHABLE == 9076
    assert await _shown_icon(client, owner, resource_id, kind) is None
    assert await _icon_status(client, foreign_icon) == 200


async def test_a_resource_refuses_an_unknown_icon(client, owner):
    assistant_id = await _create(client, owner, "assistant")

    response = await _set_icon(client, owner, "assistant", assistant_id, str(uuid4()))

    assert response.status_code == 400, response.text
    assert response.json()["eneo_error_code"] == 9076


async def test_another_editor_may_send_the_current_icon_again(
    client, owner, member, member_user
):
    assistant_id, icon_id = await _with_icon(client, owner)
    space_id = (
        await client.get(f"/api/v1/assistants/{assistant_id}/", headers=owner)
    ).json()["space_id"]
    added = await client.post(
        f"/api/v1/spaces/{space_id}/members/",
        json={"id": str(member_user.id), "role": "editor"},
        headers=owner,
    )
    assert added.status_code == 200, added.text
    unattached_icon = await _upload(client, owner)

    resent = await _set_icon(client, member, "assistant", assistant_id, icon_id)
    swapped = await _set_icon(
        client, member, "assistant", assistant_id, unattached_icon
    )

    assert resent.status_code == 200, resent.text
    assert swapped.status_code == 400, swapped.text
    assert await _shown_icon(client, owner, assistant_id) == icon_id
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


def _racing(db_container, work: Callable[[Any], Awaitable[object]]):
    """Start ``work`` in its own session; the future resolves to its backend pid."""
    pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    async def race() -> None:
        async with db_container() as racer:
            pid.set_result(
                await racer.session().scalar(sa.text("SELECT pg_backend_pid()"))
            )
            await work(racer)

    return asyncio.create_task(race()), pid


def _deleting(db_container, icon_id: str, tenant_id: UUID):
    return _racing(
        db_container,
        lambda deleting: deleting.icon_service().delete_icon(UUID(icon_id), tenant_id),
    )


async def _change_icon(container, kind: str, resource_id: str, icon_id: str) -> None:
    resource, icon = UUID(resource_id), UUID(icon_id)
    match kind:
        case "assistant":
            await container.assistant_service().update_assistant(resource, icon_id=icon)
        case "app":
            await container.app_service().update_app(resource, icon_id=icon)
        case "space":
            await container.space_service().update_space(resource, icon_id=icon)
        case _:
            await container.group_chat_service().update_group_chat(
                resource, icon_id=icon
            )


async def _delete(container, kind: str, resource_id: str) -> None:
    resource = UUID(resource_id)
    match kind:
        case "assistant":
            await container.assistant_service().delete_assistant(resource)
        case "app":
            await container.app_service().delete_app(resource)
        case "space":
            await container.space_service().delete_space(resource)
        case _:
            await container.group_chat_service().delete_group_chat(resource)


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


@pytest.mark.parametrize("kind", ["assistant", "app", "space", "group_chat"])
async def test_two_updates_swapping_icons_do_not_deadlock(
    client, owner, apps_enabled, db_container, kind
):
    first, first_icon = await _with_icon(client, owner, kind)
    second, second_icon = await _with_icon(client, owner, kind)
    keepers = [await _create(client, owner, "assistant") for _ in range(2)]

    async with db_container() as attaching:
        session = attaching.session()
        # Attaching both icons elsewhere holds FOR KEY SHARE on them until
        # commit, so each swap is halfway through when it starts waiting.
        for keeper, icon_id in zip(keepers, (first_icon, second_icon)):
            await session.execute(
                sa.update(Assistants)
                .where(Assistants.id == UUID(keeper))
                .values(icon_id=UUID(icon_id))
            )
        swaps = [
            _racing(db_container, lambda c: _change_icon(c, kind, first, second_icon)),
            _racing(db_container, lambda c: _change_icon(c, kind, second, first_icon)),
        ]
        for swap, pid in swaps:
            await _wait_until_blocked(session, swap, pid)

    results = await asyncio.gather(*(swap for swap, _ in swaps), return_exceptions=True)
    assert [r for r in results if isinstance(r, BaseException)] == []
    assert await _shown_icon(client, owner, first, kind) == second_icon
    assert await _shown_icon(client, owner, second, kind) == first_icon


@pytest.mark.parametrize("kind", ["assistant", "app", "space", "group_chat"])
async def test_concurrent_icon_changes_release_every_replaced_icon(
    client, owner, apps_enabled, db_container, kind
):
    resource_id, first_icon = await _with_icon(client, owner, kind)
    second_icon = await _upload(client, owner)
    third_icon = await _upload(client, owner)

    async with db_container() as changing:
        await _change_icon(changing, kind, resource_id, second_icon)
        racer, pid = _racing(
            db_container, lambda c: _change_icon(c, kind, resource_id, third_icon)
        )
        await _wait_until_blocked(changing.session(), racer, pid)

    await racer
    assert await _shown_icon(client, owner, resource_id, kind) == third_icon
    assert [
        await _icon_status(client, icon_id)
        for icon_id in (first_icon, second_icon, third_icon)
    ] == [404, 404, 200]


async def test_an_icon_deleted_while_an_update_attaches_it_is_refused(
    client, owner, admin_user, apps_enabled, db_container
):
    app_id = await _create(client, owner, "app")
    icon_id = await _upload(client, owner)

    async with db_container() as deleting:
        await deleting.icon_service().delete_icon(UUID(icon_id), admin_user.tenant_id)
        attaching, pid = _racing(
            db_container, lambda c: _change_icon(c, "app", app_id, icon_id)
        )
        await _wait_until_blocked(deleting.session(), attaching, pid)

    with pytest.raises(IconNotAttachableError):
        await attaching
    assert await _shown_icon(client, owner, app_id, "app") is None


@pytest.mark.parametrize(
    ("kind", "deleted"),
    [
        ("assistant", "assistant"),
        ("app", "app"),
        ("space", "space"),
        ("group_chat", "group_chat"),
        pytest.param("app", "space", id="app-in-space"),
    ],
)
async def test_a_delete_waiting_on_an_icon_change_releases_the_new_icon(
    client, owner, apps_enabled, db_container, kind, deleted
):
    space_id = await _create(client, owner, "space")
    resource_id, old_icon = await _with_icon(client, owner, kind, space_id=space_id)
    new_icon = await _upload(client, owner)
    deleted_id = space_id if deleted == "space" else resource_id

    async with db_container() as changing:
        await _change_icon(changing, kind, resource_id, new_icon)
        racer, pid = _racing(db_container, lambda c: _delete(c, deleted, deleted_id))
        await _wait_until_blocked(changing.session(), racer, pid)

    await racer
    assert [
        await _icon_status(client, icon_id) for icon_id in (old_icon, new_icon)
    ] == [
        404,
        404,
    ]


def _upgrade(connection, revision: str) -> None:
    backend = Path(__file__).resolve().parents[2]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    script = ScriptDirectory.from_config(config).get_revision(revision)
    assert script is not None
    with Operations.context(MigrationContext.configure(connection)):
        script.module.upgrade()


async def test_the_upgrade_clears_icons_borrowed_from_another_tenant(
    client, owner, other_tenant, apps_enabled, db_container
):
    tables = {
        "assistant": Assistants,
        "app": Apps,
        "space": Spaces,
        "group_chat": GroupChatsTable,
    }
    borrowing = {kind: await _create(client, owner, kind) for kind in tables}
    foreign_icon = await _upload(client, other_tenant)
    keeping, own_icon = await _with_icon(client, owner)

    async with db_container() as container:
        session = container.session()
        # Before #1228 an update accepted any icon id, so write those rows directly.
        for kind, resource_id in borrowing.items():
            table = tables[kind]
            await session.execute(
                sa.update(table)
                .where(table.id == UUID(resource_id))
                .values(icon_id=UUID(foreign_icon))
            )
        connection = await session.connection()
        await connection.run_sync(_upgrade, "202610261300")

    assert {
        kind: await _shown_icon(client, owner, resource_id, kind)
        for kind, resource_id in borrowing.items()
    } == dict.fromkeys(tables)
    assert await _shown_icon(client, owner, keeping) == own_icon
