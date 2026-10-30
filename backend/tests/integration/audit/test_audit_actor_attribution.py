"""The actor recorded with an audit event is what readers show, filter and export.

A recorded actor block (a mapping with a string "type" and "id") is authoritative:
renames and deletions after the event do not change it. Rows without one keep the
live lookup for display only, and the lookup never writes back.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.audit.application.audit_worker_task import log_audit_event_task
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.audit_log import AuditLog
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.domain.outcome import Outcome
from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.database.tables.users_table import Users
from tests.fixtures import mint_v2_api_key

pytestmark = pytest.mark.integration


async def _create_user(db_container, *, tenant_id: UUID, username: str) -> UUID:
    async with db_container() as container:
        user_id = await container.session().scalar(
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
    assert user_id is not None
    return user_id


async def _log_as(db_container, user_id: UUID, *, entity_id: UUID) -> None:
    async with db_container() as container:
        user = await container.user_repo().get_user_by_id(user_id)
        assert user is not None
        await container.audit_service().log(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.FLOW_DELETED,
            entity_type=EntityType.FLOW,
            entity_id=entity_id,
            description="Deleted flow 'Attribution'",
            metadata={"target": {"id": str(entity_id), "name": "Attribution"}},
            required=True,
        )


async def _set_username(db_container, user_id: UUID, username: str) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(Users).where(Users.id == user_id).values(username=username)
        )


async def _hard_delete_user(db_container, user_id: UUID) -> None:
    async with db_container() as container:
        await container.session().execute(sa.delete(Users).where(Users.id == user_id))


async def _insert_row(
    db_container,
    *,
    tenant_id: UUID,
    metadata: dict[str, Any],
    actor_id: UUID | None = None,
    actor_type: ActorType = ActorType.USER,
    actor_api_key_id: UUID | None = None,
) -> UUID:
    row_id = uuid4()
    async with db_container() as container:
        await AuditLogRepositoryImpl(container.session()).create(
            AuditLog(
                id=row_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
                actor_type=actor_type,
                actor_api_key_id=actor_api_key_id,
                action=ActionType.FLOW_UPDATED,
                entity_type=EntityType.FLOW,
                entity_id=uuid4(),
                timestamp=datetime.now(timezone.utc),
                description="Updated flow",
                metadata=metadata,
                outcome=Outcome.SUCCESS,
            )
        )
    return row_id


async def _stored_metadata(db_container, row_id: UUID) -> dict[str, Any]:
    async with db_container() as container:
        return await container.session().scalar(
            sa.select(AuditLogTable.log_metadata).where(AuditLogTable.id == row_id)
        )


async def _listed(client, auth, **params: str) -> dict[str, Any]:
    headers, cookies = auth
    response = await client.get(
        "/api/v1/audit/logs",
        params={"page_size": "1000", **params},
        headers=headers,
        cookies=cookies,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _by_entity(listing: dict[str, Any], entity_id: UUID) -> dict[str, Any]:
    matches = [log for log in listing["logs"] if log["entity_id"] == str(entity_id)]
    assert len(matches) == 1, listing
    return matches[0]


def _by_id(listing: dict[str, Any], row_id: UUID) -> dict[str, Any]:
    matches = [log for log in listing["logs"] if log["id"] == str(row_id)]
    assert len(matches) == 1, listing
    return matches[0]


async def test_renamed_user_is_shown_with_the_name_at_the_time(
    client, auth_headers_with_session, db_container, admin_user
):
    user_id = await _create_user(
        db_container, tenant_id=admin_user.tenant_id, username="maria-before"
    )
    entity_id = uuid4()
    await _log_as(db_container, user_id, entity_id=entity_id)
    legacy_id = await _insert_row(
        db_container, tenant_id=admin_user.tenant_id, actor_id=user_id, metadata={}
    )
    await _set_username(db_container, user_id, "maria-after")

    listing = await _listed(client, auth_headers_with_session)

    assert _by_entity(listing, entity_id)["metadata"]["actor"] == {
        "type": "user",
        "id": str(user_id),
        "name": "maria-before",
        "email": "maria-before@example.org",
    }
    assert _by_id(listing, legacy_id)["metadata"]["actor"]["name"] == "maria-after"


async def test_a_deleted_users_events_are_found_and_named_by_every_reader(
    client, auth_headers, auth_headers_with_session, db_container, admin_user
):
    user_id = await _create_user(
        db_container, tenant_id=admin_user.tenant_id, username="leaver"
    )
    entity_id = uuid4()
    await _log_as(db_container, user_id, entity_id=entity_id)
    await _hard_delete_user(db_container, user_id)

    listed = _by_entity(
        await _listed(client, auth_headers_with_session, actor_id=str(user_id)),
        entity_id,
    )
    assert listed["actor_id"] is None
    assert listed["metadata"]["actor"]["name"] == "leaver"

    headers, cookies = auth_headers_with_session
    subject = await client.get(
        f"/api/v1/audit/logs/user/{user_id}", headers=headers, cookies=cookies
    )
    assert subject.status_code == 200, subject.text
    assert _by_entity(subject.json(), entity_id)["metadata"]["actor"]["name"] == (
        "leaver"
    )

    for filter_name in ("actor_id", "user_id"):
        exported_csv = await client.get(
            "/api/v1/audit/logs/export",
            params={filter_name: str(user_id), "format": "csv"},
            headers=auth_headers,
        )
        assert exported_csv.status_code == 200, exported_csv.text
        rows = [
            row
            for row in csv.DictReader(io.StringIO(exported_csv.text))
            if row["Entity ID"] == str(entity_id)
        ]
        assert [(row["Actor ID"], row["Actor Name"]) for row in rows] == [
            (str(user_id), "leaver")
        ], filter_name

    exported_jsonl = await client.get(
        "/api/v1/audit/logs/export",
        params={"actor_id": str(user_id), "format": "json"},
        headers=auth_headers,
    )
    assert exported_jsonl.status_code == 200, exported_jsonl.text
    lines = [
        json.loads(line)
        for line in exported_jsonl.text.splitlines()
        if line.strip() and json.loads(line)["entity_id"] == str(entity_id)
    ]
    assert [line["metadata"]["actor"]["name"] for line in lines] == ["leaver"]


async def test_an_api_key_actor_is_found_by_its_key_id_without_an_actor_id(
    client, auth_headers_with_session, db_container, admin_user
):
    async with db_container() as container:
        key = await mint_v2_api_key(
            container.api_key_v2_repo(),
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            prefix="attr",
        )
    snapshot = {
        "type": "service_key",
        "id": str(key.id),
        "name": "Ingest key at the time",
        "key_prefix": "attr_",
    }
    row_id = await _insert_row(
        db_container,
        tenant_id=admin_user.tenant_id,
        actor_type=ActorType.API_KEY,
        actor_api_key_id=key.id,
        metadata={"actor": snapshot},
    )

    listed = _by_id(
        await _listed(client, auth_headers_with_session, actor_id=str(key.id)),
        row_id,
    )

    assert listed["actor_id"] is None
    assert listed["metadata"]["actor"] == snapshot


@pytest.mark.parametrize(
    "legacy_actor",
    [
        "absent",
        None,
        "a string",
        ["list"],
        {},
        {"type": "user"},
        {"name": "stale"},
        {"type": "user", "id": 7},
        {"type": "user", "id": ""},
    ],
)
async def test_a_row_without_a_recorded_actor_shows_the_live_user_and_is_not_rewritten(
    client, auth_headers_with_session, db_container, admin_user, legacy_actor
):
    user_id = await _create_user(
        db_container,
        tenant_id=admin_user.tenant_id,
        username=f"live-{uuid4().hex[:6]}",
    )
    metadata: dict[str, Any] = (
        {"extra": "kept"}
        if legacy_actor == "absent"
        else {"extra": "kept", "actor": legacy_actor}
    )
    row_id = await _insert_row(
        db_container,
        tenant_id=admin_user.tenant_id,
        actor_id=user_id,
        metadata=metadata,
    )
    async with db_container() as container:
        username = await container.session().scalar(
            sa.select(Users.username).where(Users.id == user_id)
        )

    listed = _by_id(await _listed(client, auth_headers_with_session), row_id)

    assert listed["metadata"]["actor"]["name"] == username
    assert listed["metadata"]["extra"] == "kept"
    assert await _stored_metadata(db_container, row_id) == metadata


async def test_a_user_deleted_between_enqueue_and_worker_insert_keeps_the_row(
    db_container, db_session, admin_user
):
    user_id = await _create_user(
        db_container, tenant_id=admin_user.tenant_id, username="gone-before-insert"
    )
    entity_id = uuid4()
    with patch("eneo.audit.application.audit_service.job_manager") as job_manager:
        job_manager.enqueue = AsyncMock()
        async with db_container() as container:
            user = await container.user_repo().get_user_by_id(user_id)
            assert user is not None
            await container.audit_service().log_async(
                tenant_id=user.tenant_id,
                user=user,
                action=ActionType.FLOW_DELETED,
                entity_type=EntityType.FLOW,
                entity_id=entity_id,
                description="Deleted flow",
                metadata={},
            )
    params = job_manager.enqueue.call_args.args[2]
    await _hard_delete_user(db_container, user_id)

    async with db_session() as session:
        result = await log_audit_event_task(
            job_id=uuid4(), params=params, session=session
        )

    async with db_container() as container:
        stored = (
            await container.session().execute(
                sa.select(
                    AuditLogTable.id, AuditLogTable.actor_id, AuditLogTable.log_metadata
                ).where(AuditLogTable.entity_id == entity_id)
            )
        ).one()
    assert result == {"audit_log_id": str(stored.id)}
    assert stored.actor_id is None
    assert stored.log_metadata["actor"] == {
        "type": "user",
        "id": str(user_id),
        "name": "gone-before-insert",
        "email": "gone-before-insert@example.org",
    }


async def test_an_untyped_recorded_actor_keeps_its_name_in_every_reader(
    client, auth_headers, auth_headers_with_session, db_container, admin_user
):
    user_id = await _create_user(
        db_container, tenant_id=admin_user.tenant_id, username="untyped-before"
    )
    recorded = {"id": str(user_id), "name": "untyped-before", "email": "u@example.org"}
    row_id = await _insert_row(
        db_container,
        tenant_id=admin_user.tenant_id,
        actor_id=user_id,
        metadata={"actor": recorded},
    )
    await _set_username(db_container, user_id, "untyped-after")

    renamed = _by_id(await _listed(client, auth_headers_with_session), row_id)
    assert renamed["metadata"]["actor"] == recorded

    await _hard_delete_user(db_container, user_id)
    exported = await client.get(
        "/api/v1/audit/logs/export",
        params={"actor_id": str(user_id), "format": "csv"},
        headers=auth_headers,
    )
    assert exported.status_code == 200, exported.text
    assert [
        (row["Actor ID"], row["Actor Name"])
        for row in csv.DictReader(io.StringIO(exported.text))
        if row["Description"] == "Updated flow"
    ] == [(str(user_id), "untyped-before")]


async def test_csv_actor_cells_are_sanitized(
    client, auth_headers, db_container, admin_user
):
    user_id = await _create_user(
        db_container, tenant_id=admin_user.tenant_id, username="=Maria"
    )
    entity_id = uuid4()
    await _log_as(db_container, user_id, entity_id=entity_id)
    await _insert_row(
        db_container,
        tenant_id=admin_user.tenant_id,
        actor_type=ActorType.SYSTEM,
        metadata={
            "actor": {"type": "system", "id": "=cmd|' /C calc'!A0", "name": "+x"}
        },
    )

    exported = await client.get(
        "/api/v1/audit/logs/export", params={"format": "csv"}, headers=auth_headers
    )

    assert exported.status_code == 200, exported.text
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    by_entity = [row for row in rows if row["Entity ID"] == str(entity_id)]
    assert [(row["Actor ID"], row["Actor Name"]) for row in by_entity] == [
        (str(user_id), "'=Maria")
    ]
    injected = [row for row in rows if row["Actor Name"] == "'+x"]
    assert [row["Actor ID"] for row in injected] == ["'=cmd|' /C calc'!A0"]


async def test_counts_and_the_async_export_find_a_deleted_users_events(
    client, auth_headers, db_container, admin_user, tmp_path
):
    user_id = await _create_user(
        db_container, tenant_id=admin_user.tenant_id, username="counted-leaver"
    )
    entity_id = uuid4()
    await _log_as(db_container, user_id, entity_id=entity_id)
    await _hard_delete_user(db_container, user_id)

    async with db_container() as container:
        repository = AuditLogRepositoryImpl(container.session())
        assert (
            await repository.count_logs(
                tenant_id=admin_user.tenant_id, actor_id=user_id
            )
            == 1
        )
        assert (
            await repository.count_user_logs(
                tenant_id=admin_user.tenant_id, user_id=user_id
            )
            == 1
        )

    exported = await client.get(
        "/api/v1/audit/logs/export",
        params={"actor_id": str(user_id), "format": "csv"},
        headers=auth_headers,
    )
    assert exported.status_code == 200, exported.text
    assert exported.headers["X-Total-Records"] == "1"
    async with db_container() as container:
        compliance = await container.session().scalar(
            sa.select(AuditLogTable.log_metadata).where(
                AuditLogTable.action == ActionType.AUDIT_LOG_EXPORTED.value
            )
        )
    assert compliance is not None
    assert compliance["total_records_matching"] == 1
    assert compliance["was_truncated"] is False

    for filters in ({"actor_id": user_id}, {"user_id": user_id}):
        target = tmp_path / f"export-{next(iter(filters))}.jsonl"
        progress: list[tuple[int, int]] = []

        async def record(processed: int, total: int) -> None:
            progress.append((processed, total))

        async def not_cancelled() -> bool:
            return False

        async with db_container() as container:
            written = await container.audit_export_service().stream_export_to_file(
                file_path=str(target),
                tenant_id=admin_user.tenant_id,
                format="jsonl",
                progress_callback=record,
                cancellation_check=not_cancelled,
                **filters,
            )
        lines = [json.loads(line) for line in target.read_text().splitlines()]
        assert written == 1, filters
        assert [line["metadata"]["actor"]["name"] for line in lines] == [
            "counted-leaver"
        ]
