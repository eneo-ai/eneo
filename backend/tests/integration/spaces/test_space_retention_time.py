"""A space's time is also the cap on its Flows' run history.

In a shared space, changing it needs a space admin whose role has
`retention_manage`, signed in as a person. A change takes the retention lock
before the space row, is audited in the same transaction, and an unchanged
value is never written."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from eneo.audit.application.audit_service import AuditService
from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from eneo.data_retention.domain.rules import RetentionTimeChangedError
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.roles_table import Roles
from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.database.tables.users_table import users_roles_table
from eneo.icons.icon_repo import IconRepository
from eneo.main.exceptions import ConflictException, NotFoundException
from tests.fixtures import mint_v2_api_key

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _space_admin(db_container, admin_user, user_factory, permissions, days=30):
    """A user whose role has `permissions`, admin of a new shared space that
    keeps `days` days."""
    async with db_container() as container:
        session = container.session()
        user = await user_factory(session, tenant_id=admin_user.tenant_id)
        role = Roles(
            name=f"Space retention role {uuid4()}",
            permissions=permissions,
            tenant_id=admin_user.tenant_id,
        )
        session.add(role)
        await session.flush()
        await session.execute(
            sa.insert(users_roles_table).values(user_id=user.id, role_id=role.id)
        )
        hub_id = await session.scalar(
            sa.select(Spaces.id).where(
                Spaces.tenant_id == admin_user.tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
            )
        )
        space = Spaces(
            name=f"Retention time space {uuid4()}",
            tenant_id=admin_user.tenant_id,
            user_id=None,
            tenant_space_id=hub_id,
            data_retention_days=days,
        )
        session.add(space)
        await session.flush()
        session.add(SpacesUsers(space_id=space.id, user_id=user.id, role="admin"))
        await session.flush()
        user_id, space_id = user.id, space.id
    async with db_container() as container:
        loaded = await container.user_repo().get_user_by_id(user_id)
        token = container.auth_service().create_access_token_for_user(loaded)
    return loaded, token, space_id


async def _stored(db_container, space_id: UUID) -> tuple[str, int | None] | None:
    async with db_container() as container:
        row = (
            await container.session().execute(
                sa.select(Spaces.name, Spaces.data_retention_days).where(
                    Spaces.id == space_id
                )
            )
        ).one_or_none()
    return None if row is None else (row.name, row.data_retention_days)


async def _retention_audits(db_container, space_id: UUID) -> list[dict]:
    async with db_container() as container:
        return [
            row.log_metadata
            for row in await container.session().scalars(
                sa.select(AuditLog)
                .where(AuditLog.action == "flow_run_retention_policy_changed")
                .where(AuditLog.entity_id == space_id)
            )
        ]


async def test_a_space_admin_needs_retention_manage_to_change_the_time(
    client, db_container, admin_user, user_factory, patch_auth_service_jwt
):
    """Mutants: a space admin without the permission changes the time; an
    explicit null slips through as no change; an unchanged resend beside a
    rename is refused."""
    _, token, space_id = await _space_admin(
        db_container, admin_user, user_factory, ["assistants"]
    )
    headers = {"Authorization": f"Bearer {token}"}
    path = f"/api/v1/spaces/{space_id}/"

    for days in (7, None):
        refused = await client.patch(
            path, json={"data_retention_days": days}, headers=headers
        )
        assert refused.status_code == 403, refused.text
        assert refused.json()["code"] == "retention_permission_required"

    renamed = await client.patch(
        path, json={"name": "Renamed space", "data_retention_days": 30}, headers=headers
    )
    assert renamed.status_code == 200, renamed.text
    assert await _stored(db_container, space_id) == ("Renamed space", 30)
    assert await _retention_audits(db_container, space_id) == []


async def test_a_change_with_the_permission_is_saved_and_audited(
    client, db_container, admin_user, user_factory, patch_auth_service_jwt
):
    """Mutants: the change writes no retention audit row; the row carries the
    request's values instead of the stored ones."""
    _, token, space_id = await _space_admin(
        db_container, admin_user, user_factory, ["assistants", "retention_manage"]
    )
    response = await client.patch(
        f"/api/v1/spaces/{space_id}/",
        json={"data_retention_days": 7},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert (await _stored(db_container, space_id))[1] == 7
    [metadata] = await _retention_audits(db_container, space_id)
    assert {key: metadata[key] for key in metadata if key != "actor"} == {
        "scope": "space",
        "scope_id": str(space_id),
        "setting": "data_retention_days",
        "previous_value": 30,
        "new_value": 7,
    }


async def test_the_audit_row_is_written_when_the_action_is_switched_off(
    client, db_container, admin_user, user_factory, patch_auth_service_jwt, monkeypatch
):
    """An organisation can switch audit actions off; the cap's row is required.
    Mutant: the row is written only when the action is switched on."""
    _, token, space_id = await _space_admin(
        db_container, admin_user, user_factory, ["assistants", "retention_manage"]
    )
    monkeypatch.setattr(
        AuditService, "_should_log_action", AsyncMock(return_value=False)
    )
    response = await client.patch(
        f"/api/v1/spaces/{space_id}/",
        json={"data_retention_days": 7},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    [metadata] = await _retention_audits(db_container, space_id)
    assert (metadata["previous_value"], metadata["new_value"]) == (30, 7)


async def test_an_api_key_cannot_change_the_time(
    client, db_container, admin_user, user_factory, patch_auth_service_jwt
):
    """Before this, an API key of a space admin could change the time. Mutant:
    the key's owner holds `retention_manage`, so the key passes."""
    user, _, space_id = await _space_admin(
        db_container, admin_user, user_factory, ["assistants", "retention_manage"]
    )
    async with db_container() as container:
        key = await mint_v2_api_key(
            container.api_key_v2_repo(),
            tenant_id=user.tenant_id,
            user_id=user.id,
            scope_type="space",
            scope_id=space_id,
        )
    response = await client.patch(
        f"/api/v1/spaces/{space_id}/",
        json={"data_retention_days": 7},
        headers={"X-API-Key": key.key},
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "retention_person_required"
    assert (await _stored(db_container, space_id))[1] == 30


async def test_a_failed_audit_leaves_the_time_unchanged(
    client, db_container, admin_user, user_factory, patch_auth_service_jwt, monkeypatch
):
    _, token, space_id = await _space_admin(
        db_container, admin_user, user_factory, ["assistants", "retention_manage"]
    )

    async def fail_audit_insert(_repository, _audit_log):
        raise RuntimeError("forced space retention audit failure")

    monkeypatch.setattr(AuditLogRepositoryImpl, "create", fail_audit_insert)
    with pytest.raises(RuntimeError, match="forced space retention audit failure"):
        await client.patch(
            f"/api/v1/spaces/{space_id}/",
            json={"data_retention_days": 7},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert (await _stored(db_container, space_id))[1] == 30


async def _wait_for_a_lock_waiter(db_container, timeout: float = 4.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        async with db_container() as probe:
            if await probe.session().scalar(
                sa.text("SELECT count(*) FROM pg_locks WHERE NOT granted")
            ):
                return
        if loop.time() > deadline:
            raise AssertionError("no transaction waited for a lock")
        await asyncio.sleep(0.05)


async def test_a_stale_resend_beside_a_rename_keeps_a_concurrent_change(
    db_container, admin_user, user_factory
):
    """Session B read 30 before A changed it to 3, then renames and resends 30.
    Mutant: the resend is written after A commits, so 30 replaces 3."""
    user, _, space_id = await _space_admin(
        db_container, admin_user, user_factory, ["assistants", "retention_manage"]
    )

    async def rename():
        async with db_container(user=user) as renaming:
            await renaming.space_service().update_space(
                space_id, name="Renamed by B", data_retention_days=30
            )

    async with db_container(user=user) as changing:
        await changing.space_service().update_space(space_id, data_retention_days=3)
        # B reads 30, as A has not committed, then waits for the space row.
        renaming = asyncio.create_task(rename())
        try:
            await _wait_for_a_lock_waiter(db_container)
        except BaseException:
            renaming.cancel()
            raise
    await renaming
    assert await _stored(db_container, space_id) == ("Renamed by B", 3)


async def test_a_cap_change_and_a_space_delete_never_deadlock(
    db_container, admin_user, user_factory, monkeypatch
):
    """The delete holds the space row when the change starts. Mutant: the
    delete takes the retention lock after the space row, the change takes them
    the other way round, and Postgres reports a deadlock."""
    user, _, space_id = await _space_admin(
        db_container, admin_user, user_factory, ["assistants", "retention_manage"]
    )
    row_locked, go_on = asyncio.Event(), asyncio.Event()
    lock_shown = IconRepository.lock_shown_in_space

    async def paused_lock_shown(self, space_id):
        icon_ids = await lock_shown(self, space_id)
        row_locked.set()
        await go_on.wait()
        return icon_ids

    monkeypatch.setattr(IconRepository, "lock_shown_in_space", paused_lock_shown)

    async def delete():
        async with db_container(user=user) as deleting:
            await deleting.space_service().delete_space(space_id)

    async def change():
        async with db_container(user=user) as changing:
            await changing.space_service().update_space(space_id, data_retention_days=3)

    deleting = asyncio.create_task(delete())
    await asyncio.wait_for(row_locked.wait(), timeout=5)
    changing = asyncio.create_task(change())
    try:
        await _wait_for_a_lock_waiter(db_container)
    finally:
        go_on.set()
    outcomes = await asyncio.gather(deleting, changing, return_exceptions=True)
    for outcome in outcomes:
        if isinstance(outcome, DBAPIError):
            raise outcome
        assert outcome is None or isinstance(
            outcome, (NotFoundException, ConflictException)
        ), repr(outcome)
    assert await _stored(db_container, space_id) is None


@pytest.mark.parametrize("sent", [5, 3], ids=["another-time", "the-new-time"])
async def test_a_change_waiting_on_another_compares_with_the_committed_time(
    db_container, admin_user, user_factory, sent
):
    """B reads 30 and waits while A changes it to 3. Mutant: B keeps the time
    it read before the lock, so its audit row says 30, or it writes 3 again."""
    user, _, space_id = await _space_admin(
        db_container, admin_user, user_factory, ["assistants", "retention_manage"]
    )

    async def change_again():
        async with db_container(user=user) as second:
            await second.space_service().update_space(
                space_id, data_retention_days=sent
            )

    async with db_container(user=user) as first:
        await first.space_service().update_space(space_id, data_retention_days=3)
        waiting = asyncio.create_task(change_again())
        try:
            await _wait_for_a_lock_waiter(db_container)
        except BaseException:
            waiting.cancel()
            raise
    await waiting
    assert (await _stored(db_container, space_id))[1] == sent
    audits = await _retention_audits(db_container, space_id)
    assert sorted((a["previous_value"], a["new_value"]) for a in audits) == sorted(
        [(30, 3)] + ([(3, sent)] if sent != 3 else [])
    )


def _record_space_updates(monkeypatch) -> list[dict]:
    """The metadata of every `space_updated` the router queues, with the action
    switched on."""
    monkeypatch.setattr(
        AuditService, "_should_log_action", AsyncMock(return_value=True)
    )
    recorded: list[dict] = []
    log_async = AuditService.log_async

    async def record(self, **kwargs):
        if kwargs["action"].value == "space_updated":
            recorded.append(kwargs["metadata"])
        return await log_async(self, **kwargs)

    monkeypatch.setattr(AuditService, "log_async", record)
    return recorded


@pytest.mark.parametrize("sent", [3, 5], ids=["the-new-time", "another-time"])
async def test_the_space_update_event_carries_the_change_made_under_the_lock(
    client,
    db_container,
    admin_user,
    user_factory,
    patch_auth_service_jwt,
    monkeypatch,
    sent,
):
    """B's PATCH reads 30 and waits while A changes it to 3. Mutant: the router
    takes the change from its read before the lock, so `space_updated` says
    30 -> 3 for a write B never made, or 30 -> 5 where the change is 3 -> 5."""
    user, token, space_id = await _space_admin(
        db_container, admin_user, user_factory, ["assistants", "retention_manage"]
    )
    recorded = _record_space_updates(monkeypatch)

    async with db_container(user=user) as first:
        await first.space_service().update_space(space_id, data_retention_days=3)
        waiting = asyncio.create_task(
            client.patch(
                f"/api/v1/spaces/{space_id}/",
                json={"data_retention_days": sent},
                headers={"Authorization": f"Bearer {token}"},
            )
        )
        try:
            await _wait_for_a_lock_waiter(db_container)
        except BaseException:
            waiting.cancel()
            raise
    response = await waiting
    assert response.status_code == 200, response.text
    [metadata] = recorded
    changes = metadata.get("changes", {})
    if sent == 3:
        assert "data_retention_days" not in changes
    else:
        assert changes["data_retention_days"] == {"old": 3, "new": 5}


async def test_the_space_update_event_still_carries_a_change_of_the_time(
    client, db_container, admin_user, user_factory, patch_auth_service_jwt, monkeypatch
):
    """Mutant: the router leaves the time out of `space_updated` altogether."""
    _, token, space_id = await _space_admin(
        db_container, admin_user, user_factory, ["assistants", "retention_manage"]
    )
    recorded = _record_space_updates(monkeypatch)
    response = await client.patch(
        f"/api/v1/spaces/{space_id}/",
        json={"data_retention_days": 7},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    [metadata] = recorded
    assert metadata["changes"]["data_retention_days"] == {"old": 30, "new": 7}


async def test_a_personal_space_owner_still_cannot_change_its_time(
    client, db_container, admin_user, patch_auth_service_jwt
):
    """A personal space has no admin to edit it, so its owner gains no right to
    cap their flows, even with `retention_manage`."""
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
    headers = {"Authorization": f"Bearer {token}"}
    personal = await client.get("/api/v1/spaces/type/personal/", headers=headers)
    assert personal.status_code == 200, personal.text
    space_id = personal.json()["id"]
    refused = await client.patch(
        f"/api/v1/spaces/{space_id}/", json={"data_retention_days": 7}, headers=headers
    )
    assert refused.status_code == 403, refused.text
    assert (await _stored(db_container, UUID(space_id)))[1] is None


_MANAGE = ["assistants", "retention_manage"]


@pytest.mark.parametrize(
    "stored,seen", [(30, 30), (None, None)], ids=["a-time", "no-time"]
)
async def test_a_change_that_names_the_time_it_replaces_is_saved(
    client, db_container, admin_user, user_factory, patch_auth_service_jwt, stored, seen
):
    """`null` means "I saw no time set". Mutant: a seen null is read as absent,
    or as a mismatch against a space without a time."""
    _, token, space_id = await _space_admin(
        db_container, admin_user, user_factory, _MANAGE, days=stored
    )
    response = await client.patch(
        f"/api/v1/spaces/{space_id}/",
        json={"data_retention_days": 7, "expected_data_retention_days": seen},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert (await _stored(db_container, space_id))[1] == 7


@pytest.mark.parametrize("seen", [60, None], ids=["another-time", "no-time"])
async def test_a_change_against_a_time_no_longer_stored_saves_nothing(
    client, db_container, admin_user, user_factory, patch_auth_service_jwt, seen
):
    """The rename beside the time is refused with it. Mutants: the check is
    skipped; the rename is saved; the refusal names the time that was sent."""
    _, token, space_id = await _space_admin(
        db_container, admin_user, user_factory, _MANAGE
    )
    before = await _stored(db_container, space_id)
    response = await client.patch(
        f"/api/v1/spaces/{space_id}/",
        json={
            "name": "Renamed space",
            "data_retention_days": 7,
            "expected_data_retention_days": seen,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 409, response.text
    body = response.json()
    assert (body["code"], body["eneo_error_code"], body["context"]) == (
        "retention_time_changed",
        9087,
        {"current_days": 30},
    )
    assert await _stored(db_container, space_id) == before
    assert await _retention_audits(db_container, space_id) == []


@pytest.mark.parametrize(
    "sent",
    [
        {"name": "Renamed space", "expected_data_retention_days": 60},
        {
            "name": "Renamed space",
            "data_retention_days": 30,
            "expected_data_retention_days": 60,
        },
    ],
    ids=["no-new-time", "the-stored-time"],
)
async def test_a_seen_time_is_checked_only_when_the_time_changes(
    client, db_container, admin_user, user_factory, patch_auth_service_jwt, sent
):
    """Mutant: a seen time beside no new time, or beside the stored one,
    refuses the rest of the request."""
    _, token, space_id = await _space_admin(
        db_container, admin_user, user_factory, _MANAGE
    )
    response = await client.patch(
        f"/api/v1/spaces/{space_id}/",
        json=sent,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert await _stored(db_container, space_id) == ("Renamed space", 30)
    assert await _retention_audits(db_container, space_id) == []


@pytest.mark.parametrize("sent", [5, 3], ids=["another-time", "the-new-time"])
async def test_a_change_waiting_on_another_is_refused_when_its_time_was_replaced(
    db_container, admin_user, user_factory, sent
):
    """B saw 30 and waits while A changes it to 3. Mutants: B compares with its
    read before the lock, so 30 passes and 5 replaces 3; B's resend of 3 is
    refused although it changes nothing."""
    user, _, space_id = await _space_admin(
        db_container, admin_user, user_factory, _MANAGE
    )

    async def change_again():
        async with db_container(user=user) as second:
            await second.space_service().update_space(
                space_id, data_retention_days=sent, expected_data_retention_days=30
            )

    async with db_container(user=user) as first:
        await first.space_service().update_space(space_id, data_retention_days=3)
        waiting = asyncio.create_task(change_again())
        try:
            await _wait_for_a_lock_waiter(db_container)
        except BaseException:
            waiting.cancel()
            raise
    if sent == 3:
        await waiting
    else:
        with pytest.raises(RetentionTimeChangedError) as refused:
            await waiting
        assert refused.value.context == {"current_days": 3}
    assert (await _stored(db_container, space_id))[1] == 3
    audits = await _retention_audits(db_container, space_id)
    assert [(a["previous_value"], a["new_value"]) for a in audits] == [(30, 3)]
