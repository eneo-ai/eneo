"""Legal holds on Flow run history: admission into every deletion, locking, API.

A held run is excluded from the explicit purge's selection and from the purge
repository's locked-run recheck, so a hold that commits between selection and
deletion is still honoured. Hold and policy changes take the retention lock
EXCLUSIVE, deletions take it SHARED.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from eneo.data_retention.infrastructure import retention_lock
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.flow_tables import (
    FlowRetentionHolds,
    FlowRuns,
    Flows,
    FlowVersions,
)
from eneo.database.tables.roles_table import Roles
from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import users_roles_table
from eneo.flows.application import flow_run_history_purge
from eneo.flows.domain.flow_retention_hold import FlowRetentionHoldCreateRequest
from eneo.flows.domain.flow_run_retention_policy import (
    FlowRunRetentionMode,
    FlowRunRetentionPolicy,
)
from eneo.flows.runtime.flow_runtime_health import (
    FlowRuntimeHealthFlag,
    FlowRuntimeProbe,
    build_flow_runtime_health_policy,
    classify_flow_runtime_health,
    load_flow_runtime_health_snapshot,
)
from eneo.main.config import get_settings
from eneo.main.exceptions import ConflictException
from eneo.settings.settings import FlowRetentionPolicyUpdate
from tests.fixtures import mint_v2_api_key
from tests.integration.flows.flow_run_deletion_support import delete_run, due_run_ids

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

HOLDS = "/api/v1/settings/flow-retention-holds"
OLD = timedelta(days=3)


def _review_by(days: int = 30) -> datetime:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0)


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.fixture
async def regular_token(db_container, patch_auth_service_jwt, user_factory, admin_user):
    async with db_container() as container:
        regular_user = await user_factory(
            container.session(), tenant_id=admin_user.tenant_id
        )
        return container.auth_service().create_access_token_for_user(regular_user)


@pytest.fixture
async def history(db_container, admin_user):
    """Two Flows in one Space whose completed runs are due under a 1-day preserve rule."""
    async with db_container() as container:
        session = container.session()
        parent_space_id = await session.scalar(
            sa.select(Spaces.id).where(
                Spaces.tenant_id == admin_user.tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
            )
        )
        space = Spaces(
            name=f"Hold Space {uuid4()}",
            tenant_id=admin_user.tenant_id,
            tenant_space_id=parent_space_id,
        )
        session.add(space)
        await session.flush()
        flow_ids = []
        for label in ("held", "sibling"):
            flow = Flows(
                name=f"Hold {label} {uuid4()}",
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                flow_run_history_retention_mode="preserve",
                flow_run_history_retention_days=1,
            )
            session.add(flow)
            await session.flush()
            session.add(
                FlowVersions(
                    flow_id=flow.id,
                    version=1,
                    tenant_id=admin_user.tenant_id,
                    definition_checksum=str(uuid4()),
                    definition_json={"schema_version": 1, "steps": []},
                )
            )
            await session.flush()
            flow_ids.append(flow.id)
        space_id = space.id
    return {"space_id": space_id, "flow_id": flow_ids[0], "sibling_id": flow_ids[1]}


async def _add_run(db_container, admin_user, flow_id) -> UUID:
    old = datetime.now(timezone.utc) - OLD
    async with db_container() as container:
        run = FlowRuns(
            flow_id=flow_id,
            flow_version=1,
            tenant_id=admin_user.tenant_id,
            principal_type="user",
            principal_user_id=admin_user.id,
            trace_id=uuid4(),
            status="completed",
            started_at=old,
            finished_at=old,
            created_at=old,
            updated_at=old,
        )
        container.session().add(run)
        await container.session().flush()
        run_id = run.id
    return run_id


async def _existing_runs(db_container, run_ids) -> set[UUID]:
    async with db_container() as container:
        return set(
            await container.session().scalars(
                sa.select(FlowRuns.id).where(FlowRuns.id.in_(list(run_ids)))
            )
        )


async def _purge(client, token, flow_id, *, dry_run: bool = False) -> dict:
    response = await client.post(
        f"/api/v1/settings/flow-run-retention-policy/flows/{flow_id}/purge",
        json={"dry_run": dry_run, "limit": 100},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _place(client, token, **body) -> list[dict]:
    payload = {
        "reason": "Pending disclosure request",
        "review_by": _review_by().isoformat(),
        **body,
    }
    if payload.get("run_ids") is not None:
        payload["run_ids"] = [str(run_id) for run_id in payload["run_ids"]]
    payload["flow_id"] = str(payload["flow_id"])
    response = await client.post(
        HOLDS, json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201, response.text
    return response.json()["holds"]


async def _release(client, token, hold_id, reason="Request answered") -> dict:
    response = await client.post(
        f"{HOLDS}/{hold_id}/release",
        json={"reason": reason},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _wait_for_retention_lock_waiter(db_container, timeout: float = 4.0) -> None:
    """Return once another transaction waits for the retention advisory lock."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        async with db_container() as probe:
            waiting = await probe.session().scalar(
                sa.text(
                    "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                    "AND NOT granted AND objsubid = 1 "
                    "AND ((classid::bigint << 32) | objid::bigint) = :key"
                ),
                {"key": retention_lock.RetentionSubject.FLOW_HISTORY.key},
            )
        if waiting:
            return
        if loop.time() > deadline:
            raise AssertionError("no transaction waited for the retention lock")
        await asyncio.sleep(0.05)


def _hold_request(flow_id, run_ids=None) -> FlowRetentionHoldCreateRequest:
    return FlowRetentionHoldCreateRequest(
        flow_id=flow_id,
        run_ids=run_ids,
        reason="Pending disclosure request",
        review_by=_review_by(),
    )


async def test_flow_hold_keeps_every_run_including_later_runs_until_released(
    client, admin_token, admin_user, db_container, history
):
    flow_id = history["flow_id"]
    before = await _add_run(db_container, admin_user, flow_id)
    sibling = await _add_run(db_container, admin_user, history["sibling_id"])
    [hold] = await _place(client, admin_token, flow_id=flow_id)
    assert hold["scope"] == "flow" and hold["flow_run_id"] is None
    assert hold["active"] is True
    later = await _add_run(db_container, admin_user, flow_id)

    preview = await _purge(client, admin_token, flow_id, dry_run=True)
    assert preview["candidate_count"] == 0
    assert (await _purge(client, admin_token, flow_id))["purged_count"] == 0
    assert (await _purge(client, admin_token, history["sibling_id"]))[
        "purged_run_ids"
    ] == [str(sibling)]
    assert await _existing_runs(db_container, {before, later}) == {before, later}

    await _release(client, admin_token, hold["id"])
    purged = await _purge(client, admin_token, flow_id)
    assert set(purged["purged_run_ids"]) == {str(before), str(later)}


async def test_run_hold_keeps_only_the_named_run(
    client, admin_token, admin_user, db_container, history
):
    flow_id = history["flow_id"]
    held = await _add_run(db_container, admin_user, flow_id)
    free = await _add_run(db_container, admin_user, flow_id)
    [hold] = await _place(client, admin_token, flow_id=flow_id, run_ids=[str(held)])
    assert hold["scope"] == "run" and hold["flow_run_id"] == str(held)

    assert (await _purge(client, admin_token, flow_id, dry_run=True))[
        "candidate_count"
    ] == 1
    assert (await _purge(client, admin_token, flow_id))["purged_run_ids"] == [str(free)]
    assert await _existing_runs(db_container, {held, free}) == {held}


async def test_a_hold_whose_end_date_passed_no_longer_holds(
    client, admin_token, admin_user, db_container, history
):
    flow_id = history["flow_id"]
    run_id = await _add_run(db_container, admin_user, flow_id)
    now = datetime.now(timezone.utc)
    async with db_container() as container:
        container.session().add(
            FlowRetentionHolds(
                tenant_id=admin_user.tenant_id,
                flow_id=flow_id,
                flow_run_id=None,
                reason="Expired request",
                created_at=now - timedelta(days=2),
                review_by=now + timedelta(days=30),
                ends_at=now - timedelta(hours=1),
                created_by_actor={"type": "user", "id": str(admin_user.id)},
            )
        )

    listed = await client.get(
        f"{HOLDS}?status=all&flow_id={flow_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert [item["active"] for item in listed.json()["items"]] == [False]
    assert listed.json()["review_limit_days"] == 365
    active = await client.get(HOLDS, headers={"Authorization": f"Bearer {admin_token}"})
    assert flow_id not in {UUID(item["flow_id"]) for item in active.json()["items"]}
    assert (await _purge(client, admin_token, flow_id))["purged_run_ids"] == [
        str(run_id)
    ]


async def test_releasing_one_of_overlapping_holds_releases_only_its_own_coverage(
    client, admin_token, admin_user, db_container, history
):
    flow_id = history["flow_id"]
    named = await _add_run(db_container, admin_user, flow_id)
    other = await _add_run(db_container, admin_user, flow_id)
    [first_flow_hold] = await _place(client, admin_token, flow_id=flow_id)
    [run_hold] = await _place(client, admin_token, flow_id=flow_id, run_ids=[named])
    [second_flow_hold] = await _place(client, admin_token, flow_id=flow_id)

    released = await _release(client, admin_token, first_flow_hold["id"])
    assert released["active"] is False
    assert released["release_reason"] == "Request answered"
    assert (await _purge(client, admin_token, flow_id))["purged_count"] == 0
    active = await client.get(
        f"{HOLDS}?flow_id={flow_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert {item["id"] for item in active.json()["items"]} == {
        run_hold["id"],
        second_flow_hold["id"],
    }

    await _release(client, admin_token, second_flow_hold["id"])
    assert (await _purge(client, admin_token, flow_id))["purged_run_ids"] == [
        str(other)
    ]
    await _release(client, admin_token, run_hold["id"])
    assert (await _purge(client, admin_token, flow_id))["purged_run_ids"] == [
        str(named)
    ]


async def test_purge_recheck_honours_a_hold_committed_after_selection(
    admin_user, db_container, history
):
    flow_id = history["flow_id"]
    run_id = await _add_run(db_container, admin_user, flow_id)
    async with db_container() as purging:
        session = purging.session()
        # Selected without the retention lock, as an older caller could.
        _, selected = await due_run_ids(
            session, admin_user.tenant_id, now=datetime.now(timezone.utc)
        )
        assert run_id in selected
        async with db_container() as holding:
            await holding.flow_retention_hold_service().place(_hold_request(flow_id))
        out, receipt = await delete_run(session, run_id)
        assert receipt is None
        assert out.blocked["held"] == 1
    assert await _existing_runs(db_container, {run_id}) == {run_id}


async def test_hold_placement_waits_for_an_open_purge(
    admin_user, db_container, history
):
    flow_id = history["flow_id"]
    run_id = await _add_run(db_container, admin_user, flow_id)

    async def place_hold():
        async with db_container() as holding:
            return await holding.flow_retention_hold_service().place(
                _hold_request(flow_id)
            )

    async with db_container() as purging:
        purge = await purging.flow_run_retention_policy_service().purge_due_history(
            dry_run=False, limit=10, flow_id=flow_id
        )
        assert purge.purged_run_ids == [run_id]
        placing = asyncio.create_task(place_hold())
        try:
            await _wait_for_retention_lock_waiter(db_container)
            assert not placing.done()
        except BaseException:
            placing.cancel()
            raise
    placement = await placing
    assert [hold.flow_id for hold in placement.holds] == [flow_id]
    assert await _existing_runs(db_container, {run_id}) == set()


async def test_purge_waits_for_an_uncommitted_hold_then_keeps_the_held_run(
    admin_user, db_container, history
):
    flow_id = history["flow_id"]
    run_id = await _add_run(db_container, admin_user, flow_id)

    async def purge():
        async with db_container() as purging:
            return await purging.flow_run_retention_policy_service().purge_due_history(
                dry_run=False, limit=10, flow_id=flow_id
            )

    async with db_container() as holding:
        await holding.flow_retention_hold_service().place(_hold_request(flow_id))
        purging_task = asyncio.create_task(purge())
        try:
            await _wait_for_retention_lock_waiter(db_container)
        except BaseException:
            purging_task.cancel()
            raise
    result = await purging_task
    assert result.purged_count == 0
    assert result.candidate_count == 0
    assert await _existing_runs(db_container, {run_id}) == {run_id}


async def test_policy_replacement_waits_for_an_open_purge(
    admin_user, db_container, history
):
    flow_id = history["flow_id"]
    await _add_run(db_container, admin_user, flow_id)

    async def replace_policy():
        async with db_container() as changing:
            return await changing.flow_run_retention_policy_service().replace_flow(
                flow_id=flow_id,
                delete_transcription_audio_after_use=None,
                policy=FlowRunRetentionPolicy(
                    mode=FlowRunRetentionMode.REVIEW_REQUIRED, days=30
                ),
            )

    async with db_container() as purging:
        await purging.flow_run_retention_policy_service().purge_due_history(
            dry_run=False, limit=10, flow_id=flow_id
        )
        replacing = asyncio.create_task(replace_policy())
        try:
            await _wait_for_retention_lock_waiter(db_container)
            assert not replacing.done()
        except BaseException:
            replacing.cancel()
            raise
    changed = await replacing
    assert changed.local_policy == FlowRunRetentionPolicy(
        mode=FlowRunRetentionMode.REVIEW_REQUIRED, days=30
    )


async def test_a_busy_retention_lock_is_refused_typed_and_writes_nothing(
    client, admin_token, admin_user, db_container, history, monkeypatch
):
    flow_id = history["flow_id"]
    await _add_run(db_container, admin_user, flow_id)
    monkeypatch.setattr(get_settings(), "gallring_chunk_lock_timeout_ms", 100)
    async with db_container() as purging:
        await purging.flow_run_retention_policy_service().purge_due_history(
            dry_run=False, limit=10, flow_id=flow_id
        )
        response = await client.post(
            HOLDS,
            json={
                "flow_id": str(flow_id),
                "reason": "Pending request",
                "review_by": _review_by().isoformat(),
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "flow_retention_lock_busy"
    async with db_container() as container:
        session = container.session()
        assert (
            await session.scalar(sa.select(sa.func.count(FlowRetentionHolds.id))) == 0
        )
        assert (
            await session.scalar(
                sa.select(sa.func.count(AuditLog.id)).where(
                    AuditLog.action == "flow_retention_hold_placed"
                )
            )
            == 0
        )


async def test_place_and_release_write_required_audit_with_the_actor_snapshot(
    client, admin_token, admin_user, db_container, history
):
    flow_id = history["flow_id"]
    run_id = await _add_run(db_container, admin_user, flow_id)
    ends_at = _review_by(60)
    review_by = _review_by(20)
    [hold] = await _place(
        client,
        admin_token,
        flow_id=flow_id,
        run_ids=[str(run_id), str(run_id)],
        reason="  Disclosure request 2026-114  ",
        review_by=review_by.isoformat(),
        ends_at=ends_at.isoformat(),
    )
    actor = {
        "type": "user",
        "id": str(admin_user.id),
        "name": admin_user.username,
    }
    assert hold["reason"] == "Disclosure request 2026-114"
    assert hold["created_by"] == actor
    assert datetime.fromisoformat(hold["ends_at"]) == ends_at
    assert datetime.fromisoformat(hold["review_by"]) == review_by
    assert hold["review_overdue"] is False
    released = await _release(client, admin_token, hold["id"], reason="Answered")
    assert released["released_by"] == actor

    snapshot = {**actor, "email": admin_user.email}
    async with db_container() as container:
        session = container.session()
        placed = (
            await session.scalars(
                sa.select(AuditLog).where(
                    AuditLog.action == "flow_retention_hold_placed"
                )
            )
        ).one()
        released_row = (
            await session.scalars(
                sa.select(AuditLog).where(
                    AuditLog.action == "flow_retention_hold_released"
                )
            )
        ).one()
        row = await session.get(FlowRetentionHolds, UUID(hold["id"]))
        assert placed.entity_id == released_row.entity_id == flow_id
        assert placed.actor_id == released_row.actor_id == admin_user.id
        assert placed.log_metadata == {
            "actor": snapshot,
            "hold_ids": [hold["id"]],
            "flow_id": str(flow_id),
            "scope": "run",
            "run_ids": [str(run_id)],
            "reason": "Disclosure request 2026-114",
            "review_by": review_by.isoformat(),
            "ends_at": ends_at.isoformat(),
        }
        assert released_row.log_metadata == {
            "actor": snapshot,
            "hold_id": hold["id"],
            "flow_id": str(flow_id),
            "scope": "run",
            "flow_run_id": str(run_id),
            "release_reason": "Answered",
        }
        assert row is not None
        assert row.created_by_actor == snapshot == row.released_by_actor
        assert row.created_by_user_id == row.released_by_user_id == admin_user.id


async def test_hold_changes_roll_back_when_the_required_audit_fails(
    client, admin_token, admin_user, db_container, history, monkeypatch
):
    flow_id = history["flow_id"]
    [hold] = await _place(client, admin_token, flow_id=flow_id)

    async def fail_audit_insert(_repository, _audit_log):
        raise RuntimeError("forced hold audit failure")

    monkeypatch.setattr(AuditLogRepositoryImpl, "create", fail_audit_insert)
    headers = {"Authorization": f"Bearer {admin_token}"}
    with pytest.raises(RuntimeError, match="forced hold audit failure"):
        await client.post(
            HOLDS,
            json={
                "flow_id": str(flow_id),
                "reason": "Second",
                "review_by": _review_by().isoformat(),
            },
            headers=headers,
        )
    with pytest.raises(RuntimeError, match="forced hold audit failure"):
        await client.post(
            f"{HOLDS}/{hold['id']}/release", json={"reason": "Done"}, headers=headers
        )
    async with db_container() as container:
        rows = (await container.session().scalars(sa.select(FlowRetentionHolds))).all()
        assert [(row.id, row.released_at) for row in rows] == [(UUID(hold["id"]), None)]


async def test_hold_routes_refuse_a_user_without_a_retention_permission(
    client, admin_token, regular_token, admin_user, db_container, history
):
    flow_id = history["flow_id"]
    [hold] = await _place(client, admin_token, flow_id=flow_id)
    headers = {"Authorization": f"Bearer {regular_token}"}
    responses = [
        await client.get(HOLDS, headers=headers),
        await client.post(
            HOLDS,
            json={
                "flow_id": str(flow_id),
                "reason": "x",
                "review_by": _review_by().isoformat(),
            },
            headers=headers,
        ),
        await client.post(
            f"{HOLDS}/{hold['id']}/release", json={"reason": "x"}, headers=headers
        ),
    ]
    assert [response.status_code for response in responses] == [403, 403, 403]
    async with db_container() as container:
        session = container.session()
        rows = (await session.scalars(sa.select(FlowRetentionHolds))).all()
        audit_actions = list(
            await session.scalars(
                sa.select(AuditLog.action).where(
                    AuditLog.action.in_(
                        ["flow_retention_hold_placed", "flow_retention_hold_released"]
                    )
                )
            )
        )
        assert [(row.id, row.released_at) for row in rows] == [(UUID(hold["id"]), None)]
    assert audit_actions == ["flow_retention_hold_placed"]


async def test_invalid_hold_requests_are_refused_typed_and_write_nothing(
    client, admin_token, admin_user, db_container, history, user_factory
):
    flow_id = history["flow_id"]
    sibling_run = await _add_run(db_container, admin_user, history["sibling_id"])
    async with db_container() as container:
        session = container.session()
        foreign_tenant = Tenants(
            name=f"Hold isolation {uuid4()}", state="active", quota_limit=1_000_000
        )
        session.add(foreign_tenant)
        await session.flush()
        foreign_space = Spaces(name="Foreign hold space", tenant_id=foreign_tenant.id)
        session.add(foreign_space)
        await session.flush()
        foreign_flow = Flows(
            name="Foreign hold flow",
            tenant_id=foreign_tenant.id,
            space_id=foreign_space.id,
        )
        session.add(foreign_flow)
        await session.flush()
        foreign_flow_id = foreign_flow.id
    headers = {"Authorization": f"Bearer {admin_token}"}
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    cases = [
        ({"review_by": past}, 400, "flow_retention_hold_review_out_of_range"),
        (
            {"review_by": _review_by(366).isoformat()},
            400,
            "flow_retention_hold_review_out_of_range",
        ),
        ({"review_by": None}, 422, None),
        ({"run_ids": [str(sibling_run)]}, 400, "flow_retention_hold_run_not_in_flow"),
        ({"run_ids": [str(uuid4())]}, 400, "flow_retention_hold_run_not_in_flow"),
        ({"ends_at": past}, 400, "flow_retention_hold_end_not_in_future"),
        ({"flow_id": str(foreign_flow_id)}, 404, None),
        ({"flow_id": str(uuid4())}, 404, None),
        ({"reason": "   "}, 422, None),
        ({"reason": "x" * 513}, 422, None),
        ({"run_ids": []}, 422, None),
        ({"ends_at": "2999-01-01T00:00:00"}, 422, None),
        ({"scope": "flow"}, 422, None),
    ]
    for override, status, code in cases:
        response = await client.post(
            HOLDS,
            json={
                "flow_id": str(flow_id),
                "reason": "Request",
                "review_by": _review_by().isoformat(),
                **override,
            },
            headers=headers,
        )
        assert response.status_code == status, (override, response.text)
        if code is not None:
            assert response.json()["code"] == code, override

    [hold] = await _place(client, admin_token, flow_id=flow_id)
    await _release(client, admin_token, hold["id"])
    again = await client.post(
        f"{HOLDS}/{hold['id']}/release", json={"reason": "Twice"}, headers=headers
    )
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "flow_retention_hold_already_released"
    unknown = await client.post(
        f"{HOLDS}/{uuid4()}/release", json={"reason": "Nothing"}, headers=headers
    )
    assert unknown.status_code == 404, unknown.text
    async with db_container() as container:
        session = container.session()
        rows = (await session.scalars(sa.select(FlowRetentionHolds))).all()
        assert [row.id for row in rows] == [UUID(hold["id"])]
        assert rows[0].release_reason == "Request answered"
        assert (
            await session.scalar(
                sa.select(sa.func.count(AuditLog.id)).where(
                    AuditLog.action.in_(
                        ["flow_retention_hold_placed", "flow_retention_hold_released"]
                    )
                )
            )
            == 2
        )


async def test_a_deleted_flow_can_be_held_and_the_flow_selector_marks_held_flows(
    client, admin_token, admin_user, db_container, history
):
    flow_id = history["flow_id"]
    run_id = await _add_run(db_container, admin_user, flow_id)
    async with db_container() as container:
        await container.session().execute(
            sa.update(Flows)
            .where(Flows.id == flow_id)
            .values(deleted_at=datetime.now(timezone.utc))
        )
    [hold] = await _place(client, admin_token, flow_id=flow_id, run_ids=[run_id])
    assert hold["flow_retired"] is True

    targets = await client.get(
        "/api/v1/settings/flow-run-retention-policy/targets/spaces/"
        f"{history['space_id']}/flows",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert targets.status_code == 200, targets.text
    assert {item["id"]: item["held"] for item in targets.json()["items"]} == {
        str(flow_id): True,
        str(history["sibling_id"]): False,
    }
    assert (await _purge(client, admin_token, flow_id))["purged_count"] == 0


async def test_a_reason_is_required_to_place_and_to_release_a_hold(
    client, admin_token, admin_user, db_container, history
):
    """Stopping gallring always records why: no reason, no hold and no release."""
    flow_id = history["flow_id"]
    headers = {"Authorization": f"Bearer {admin_token}"}
    for body in ({"flow_id": str(flow_id)}, {"flow_id": str(flow_id), "reason": None}):
        refused = await client.post(HOLDS, json=body, headers=headers)
        assert refused.status_code == 422, refused.text
        assert refused.json()["code"] == "request_validation_error"
        assert "reason" in str(refused.json()["details"]["errors"])
    [hold] = await _place(client, admin_token, flow_id=flow_id)
    for body in ({}, {"reason": ""}, {"reason": "  \n "}):
        refused = await client.post(
            f"{HOLDS}/{hold['id']}/release", json=body, headers=headers
        )
        assert refused.status_code == 422, (body, refused.text)
    async with db_container() as container:
        session = container.session()
        rows = (await session.scalars(sa.select(FlowRetentionHolds))).all()
        assert [(row.id, row.released_at) for row in rows] == [(UUID(hold["id"]), None)]
        assert list(
            await session.scalars(
                sa.select(AuditLog.action).where(
                    AuditLog.action.in_(
                        ["flow_retention_hold_placed", "flow_retention_hold_released"]
                    )
                )
            )
        ) == ["flow_retention_hold_placed"]


async def _insert_hold(db_container, admin_user, flow_id, **values) -> UUID:
    now = datetime.now(timezone.utc)
    row = FlowRetentionHolds(
        tenant_id=admin_user.tenant_id,
        flow_id=flow_id,
        flow_run_id=None,
        reason="Recorded request",
        created_by_actor={"type": "user", "id": str(admin_user.id), "name": "anna"},
        **{"created_at": now - timedelta(days=40), **values},
    )
    async with db_container() as container:
        container.session().add(row)
        await container.session().flush()
        hold_id = row.id
    return hold_id


async def test_an_overdue_review_keeps_the_hold_and_raises_the_health_flag(
    client, admin_token, admin_user, db_container, history
):
    flow_id = history["flow_id"]
    run_id = await _add_run(db_container, admin_user, flow_id)
    hold_id = await _insert_hold(
        db_container,
        admin_user,
        flow_id,
        review_by=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    assert (await _purge(client, admin_token, flow_id))["purged_count"] == 0
    assert await _existing_runs(db_container, {run_id}) == {run_id}
    listed = await client.get(HOLDS, headers={"Authorization": f"Bearer {admin_token}"})
    [item] = [i for i in listed.json()["items"] if i["id"] == str(hold_id)]
    assert (item["active"], item["review_overdue"]) == (True, True)

    async with db_container() as container:
        policy = build_flow_runtime_health_policy(task_timeout_seconds=600)
        now = datetime.now(timezone.utc)
        snapshot = await load_flow_runtime_health_snapshot(
            session=container.session(), now=now, policy=policy
        )
    health = classify_flow_runtime_health(
        snapshot=snapshot,
        now=now,
        policy=policy,
        probe=FlowRuntimeProbe(
            db_query_ok=True,
            execution_worker_ready=True,
            maintenance_worker_ready=True,
        ),
    )
    assert FlowRuntimeHealthFlag.GALLRING_HOLD_REVIEW_OVERDUE in health.status_flags
    assert health.retention_holds.review_overdue_count == 1
    assert health.retention_holds.oldest_review_overdue_age_seconds >= 3600

    extended = await client.post(
        f"{HOLDS}/{hold_id}/extend-review",
        json={"review_by": _review_by(10).isoformat(), "reason": "Still open"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert extended.status_code == 200, extended.text
    assert extended.json()["review_overdue"] is False
    async with db_container() as container:
        snapshot = await load_flow_runtime_health_snapshot(
            session=container.session(), now=now, policy=policy
        )
    assert snapshot.retention_hold_review_overdue_count == 0


async def test_extending_a_review_needs_a_later_date_and_a_reason_and_is_audited(
    client, admin_token, admin_user, db_container, history
):
    flow_id = history["flow_id"]
    headers = {"Authorization": f"Bearer {admin_token}"}
    first_review = _review_by(10)
    [hold] = await _place(
        client, admin_token, flow_id=flow_id, review_by=first_review.isoformat()
    )
    path = f"{HOLDS}/{hold['id']}/extend-review"
    refusals = [
        ({"review_by": _review_by(20).isoformat()}, 422, None),
        ({"review_by": _review_by(20).isoformat(), "reason": " "}, 422, None),
        ({"reason": "Still open"}, 422, None),
        (
            {"review_by": _review_by(5).isoformat(), "reason": "Earlier"},
            400,
            "flow_retention_hold_review_not_later",
        ),
        (
            {"review_by": _review_by(400).isoformat(), "reason": "Too far"},
            400,
            "flow_retention_hold_review_out_of_range",
        ),
        (
            {"review_by": _review_by(20).isoformat(), "reason": "x", "ends_at": None},
            422,
            None,
        ),
    ]
    for body, status, code in refusals:
        refused = await client.post(path, json=body, headers=headers)
        assert refused.status_code == status, (body, refused.text)
        if code is not None:
            assert refused.json()["code"] == code, body

    new_review = _review_by(90)
    extended = await client.post(
        path,
        json={"review_by": new_review.isoformat(), "reason": "  Still open  "},
        headers=headers,
    )
    assert extended.status_code == 200, extended.text
    assert datetime.fromisoformat(extended.json()["review_by"]) == new_review
    assert extended.json()["active"] is True

    await _release(client, admin_token, hold["id"])
    after_release = await client.post(
        path,
        json={"review_by": _review_by(120).isoformat(), "reason": "Late"},
        headers=headers,
    )
    assert after_release.status_code == 409, after_release.text
    assert after_release.json()["code"] == "flow_retention_hold_not_active"
    ended_id = await _insert_hold(
        db_container,
        admin_user,
        flow_id,
        review_by=datetime.now(timezone.utc) + timedelta(days=5),
        ends_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    ended = await client.post(
        f"{HOLDS}/{ended_id}/extend-review",
        json={"review_by": _review_by(30).isoformat(), "reason": "Ended"},
        headers=headers,
    )
    assert ended.status_code == 409, ended.text

    async with db_container() as container:
        audits = (
            await container.session().scalars(
                sa.select(AuditLog).where(
                    AuditLog.action == "flow_retention_hold_review_extended"
                )
            )
        ).all()
        assert [audit.log_metadata for audit in audits] == [
            {
                "actor": {
                    "type": "user",
                    "id": str(admin_user.id),
                    "name": admin_user.username,
                    "email": admin_user.email,
                },
                "hold_id": hold["id"],
                "flow_id": str(flow_id),
                "scope": "flow",
                "flow_run_id": None,
                "previous_review_by": first_review.isoformat(),
                "review_by": new_review.isoformat(),
                "reason": "Still open",
            }
        ]


async def _token_with_permissions(
    db_container, admin_user, user_factory, permissions: list[str]
) -> str:
    async with db_container() as container:
        session = container.session()
        user = await user_factory(session, tenant_id=admin_user.tenant_id)
        role = Roles(
            name=f"Retention role {uuid4()}",
            permissions=permissions,
            tenant_id=admin_user.tenant_id,
        )
        session.add(role)
        await session.flush()
        await session.execute(
            sa.insert(users_roles_table).values(user_id=user.id, role_id=role.id)
        )
        user_id = user.id
    async with db_container() as container:
        loaded = await container.user_repo().get_user_by_id(user_id)
        return container.auth_service().create_access_token_for_user(loaded)


async def test_rules_and_holds_need_their_own_retention_permission(
    client, admin_user, db_container, history, user_factory, patch_auth_service_jwt
):
    flow_id = history["flow_id"]
    holds_only, rules_only, plain_admin = [
        await _token_with_permissions(db_container, admin_user, user_factory, perms)
        for perms in (["retention_holds"], ["retention_manage"], ["admin"])
    ]
    rule_path = f"/api/v1/settings/flow-run-retention-policy/flows/{flow_id}"
    rule = {
        "delete_transcription_audio_after_use": None,
        "policy": {"mode": "preserve", "days": 30},
    }
    limit_path = "/api/v1/settings/flow-run-retention-policy/hold-review-limit"
    queue_path = "/api/v1/settings/flow-run-retention-policy/review-queue"
    hold_body = {
        "flow_id": str(flow_id),
        "reason": "Request",
        "review_by": _review_by().isoformat(),
    }

    def bearer(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    placed = await client.post(HOLDS, json=hold_body, headers=bearer(holds_only))
    assert placed.status_code == 201, placed.text
    assert (await client.get(HOLDS, headers=bearer(holds_only))).status_code == 200
    assert (await client.get(rule_path, headers=bearer(holds_only))).status_code == 200
    for refused in (
        await client.put(rule_path, json=rule, headers=bearer(holds_only)),
        await client.post(
            f"{rule_path}/purge", json={"dry_run": False}, headers=bearer(holds_only)
        ),
        await client.post(HOLDS, json=hold_body, headers=bearer(rules_only)),
        await client.post(
            f"{HOLDS}/{placed.json()['holds'][0]['id']}/release",
            json={"reason": "x"},
            headers=bearer(rules_only),
        ),
        await client.get(HOLDS, headers=bearer(plain_admin)),
        await client.put(rule_path, json=rule, headers=bearer(plain_admin)),
        await client.post(HOLDS, json=hold_body, headers=bearer(plain_admin)),
        await client.get(queue_path, headers=bearer(holds_only)),
        await client.put(limit_path, json={"days": 30}, headers=bearer(holds_only)),
        await client.put(limit_path, json={"days": 30}, headers=bearer(plain_admin)),
    ):
        assert refused.status_code == 403, refused.text
        assert refused.json()["code"] == "retention_permission_required"
    changed = await client.put(rule_path, json=rule, headers=bearer(rules_only))
    assert changed.status_code == 200, changed.text
    assert (await client.get(HOLDS, headers=bearer(rules_only))).status_code == 200
    assert (await client.get(queue_path, headers=bearer(rules_only))).status_code == 200

    limited = await client.put(
        limit_path, json={"days": 30}, headers=bearer(rules_only)
    )
    assert limited.status_code == 200, limited.text
    assert limited.json() == {"days": 30, "is_default": False}
    read = await client.get(limit_path, headers=bearer(holds_only))
    assert read.json() == {"days": 30, "is_default": False}
    listed = await client.get(HOLDS, headers=bearer(holds_only))
    assert listed.json()["review_limit_days"] == 30
    too_far = await client.post(
        HOLDS,
        json={**hold_body, "review_by": _review_by(40).isoformat()},
        headers=bearer(holds_only),
    )
    assert too_far.status_code == 400, too_far.text
    assert too_far.json()["code"] == "flow_retention_hold_review_out_of_range"
    reset = await client.put(
        limit_path, json={"days": None}, headers=bearer(rules_only)
    )
    assert reset.json() == {"days": 365, "is_default": True}
    async with db_container() as container:
        changes = (
            await container.session().scalars(
                sa.select(AuditLog).where(
                    AuditLog.action == "flow_run_retention_policy_changed",
                    AuditLog.log_metadata["setting"].astext == "hold_review_limit_days",
                )
            )
        ).all()
        assert [
            (change.log_metadata["previous_value"], change.log_metadata["new_value"])
            for change in sorted(changes, key=lambda change: change.timestamp)
        ] == [(365, 30), (30, 365)]


async def test_the_upload_window_is_a_retention_decision(
    client, admin_user, db_container, user_factory, patch_auth_service_jwt
):
    path = "/api/v1/settings/flow-retention-policy"
    plain_admin, manager = [
        await _token_with_permissions(db_container, admin_user, user_factory, perms)
        for perms in (["admin"], ["admin", "retention_manage"])
    ]

    def bearer(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    async def window(body: dict, token: str):
        return await client.patch(path, json=body, headers=bearer(token))

    refused = await window({"flow_runtime_upload_abandonment_days": 10}, plain_admin)
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "retention_permission_required"
    # A reason without a window change is refused, not recorded.
    reason_only = await window({"reason": "Recordings audit"}, manager)
    assert reason_only.status_code == 400, reason_only.text
    assert reason_only.json()["code"] == "flow_settings_invalid_payload"
    # The debug evidence window stays an admin setting.
    debug = await window({"run_debug_evidence_days": 14}, plain_admin)
    assert debug.status_code == 200, debug.text
    # Shorter than the 30-day default: deletion comes earlier, no reason needed.
    shorter = await window({"flow_runtime_upload_abandonment_days": 10}, manager)
    assert shorter.status_code == 200, shorter.text
    longer = await window({"flow_runtime_upload_abandonment_days": 60}, manager)
    assert longer.status_code == 400, longer.text
    assert longer.json()["code"] == "flow_retention_reason_required"
    unset = await window({"flow_runtime_upload_abandonment_days": None}, manager)
    assert unset.json()["code"] == "flow_retention_reason_required"  # 10 -> 30
    reasoned = await window(
        {"flow_runtime_upload_abandonment_days": 60, "reason": "Recordings audit"},
        manager,
    )
    assert reasoned.status_code == 200, reasoned.text
    async with db_container() as container:
        key = await mint_v2_api_key(
            container.api_key_v2_repo(),
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
        )
    by_key = await client.patch(
        path,
        json={"flow_runtime_upload_abandonment_days": 5},
        headers={"X-API-Key": key.key},
    )
    assert by_key.status_code == 403, by_key.text
    assert by_key.json()["code"] == "retention_person_required"

    async with db_container() as container:
        session = container.session()
        days = await session.scalar(
            sa.select(Tenants.flow_runtime_upload_abandonment_days).where(
                Tenants.id == admin_user.tenant_id
            )
        )
        changes = (
            await session.scalars(
                sa.select(AuditLog.log_metadata)
                .where(
                    AuditLog.action == "flow_run_retention_policy_changed",
                    AuditLog.log_metadata["setting"].astext
                    == "runtime_upload_window_days",
                )
                .order_by(AuditLog.timestamp)
            )
        ).all()
    assert days == 60
    assert [
        (change["previous_value"], change["new_value"], change["reason"])
        for change in changes
    ] == [(None, 10, None), (10, 60, "Recordings audit")]


async def test_an_api_key_never_changes_or_stops_retention(
    client, admin_user, db_container, history
):
    flow_id = history["flow_id"]
    async with db_container() as container:
        key = await mint_v2_api_key(
            container.api_key_v2_repo(),
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
        )
    headers = {"X-API-Key": key.key}
    for refused in (
        await client.post(
            HOLDS,
            json={
                "flow_id": str(flow_id),
                "reason": "Request",
                "review_by": _review_by().isoformat(),
            },
            headers=headers,
        ),
        await client.put(
            f"/api/v1/settings/flow-run-retention-policy/flows/{flow_id}",
            json={
                "delete_transcription_audio_after_use": None,
                "policy": {"mode": "preserve", "days": 30},
            },
            headers=headers,
        ),
        await client.get(HOLDS, headers=headers),
        await client.put(
            "/api/v1/settings/flow-run-retention-policy/hold-review-limit",
            json={"days": 2000},
            headers=headers,
        ),
    ):
        assert refused.status_code == 403, refused.text
        assert refused.json()["code"] == "retention_person_required"
    async with db_container() as container:
        assert (
            await container.session().scalar(
                sa.select(sa.func.count(FlowRetentionHolds.id))
            )
            == 0
        )


async def test_an_active_hold_blocks_deleting_its_space_and_stays(
    client, admin_token, admin_user, db_container, history
):
    """A held Flow with no runs, then deleted: its Space still cannot be deleted."""
    space_id = history["space_id"]
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.delete(Flows).where(
                Flows.id.in_([history["flow_id"], history["sibling_id"]])
            )
        )
        flow = Flows(
            name=f"Empty held {uuid4()}",
            tenant_id=admin_user.tenant_id,
            space_id=space_id,
        )
        session.add(flow)
        session.add(SpacesUsers(space_id=space_id, user_id=admin_user.id, role="admin"))
        await session.flush()
        flow_id = flow.id
    [hold] = await _place(client, admin_token, flow_id=flow_id)
    async with db_container() as container:
        await container.session().execute(
            sa.update(Flows)
            .where(Flows.id == flow_id)
            .values(deleted_at=datetime.now(timezone.utc))
        )

    with pytest.raises(ConflictException) as refused:
        async with db_container() as container:
            await container.space_service().delete_space(space_id)
    assert refused.value.code == "space_contains_legal_hold"
    async with db_container() as container:
        session = container.session()
        assert await session.get(Spaces, space_id) is not None
        row = await session.get(FlowRetentionHolds, UUID(hold["id"]))
        assert row is not None and row.released_at is None

    await _release(client, admin_token, hold["id"])
    async with db_container() as container:
        await container.space_service().delete_space(space_id)
    async with db_container() as container:
        assert await container.session().get(Spaces, space_id) is None


async def test_purge_preview_counts_held_runs_apart_from_real_blockers(
    client, admin_token, admin_user, db_container, history, monkeypatch
):
    flow_id, sibling_id = history["flow_id"], history["sibling_id"]
    for _ in range(2):
        await _add_run(db_container, admin_user, flow_id)
    await _add_run(db_container, admin_user, sibling_id)
    async with db_container() as container:
        await container.session().execute(
            sa.update(Flows)
            .where(Flows.id == sibling_id)
            .values(flow_run_history_retention_mode="review_required")
        )
    await _place(client, admin_token, flow_id=flow_id)
    monkeypatch.setattr(flow_run_history_purge, "FLOW_RUN_HISTORY_DIAGNOSTIC_WINDOW", 1)

    response = await client.post(
        f"/api/v1/settings/flow-run-retention-policy/spaces/{history['space_id']}/purge",
        json={"dry_run": True, "limit": 100},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["candidate_count"] == 0
    assert response.json()["blocked"] == {
        "undelivered_audit": 0,
        "unresolved_webhook": 0,
        "review_required": 1,
        "legal_hold": 1,
        "counted_runs": 1,
        "complete": False,
    }


async def test_a_released_hold_without_a_release_reason_is_rejected(
    admin_user, db_container, history
):
    now = datetime.now(timezone.utc)
    with pytest.raises(
        IntegrityError, match="ck_flow_retention_holds_release_complete"
    ):
        async with db_container() as container:
            container.session().add(
                FlowRetentionHolds(
                    tenant_id=admin_user.tenant_id,
                    flow_id=history["flow_id"],
                    reason="Recorded request",
                    review_by=now + timedelta(days=30),
                    created_by_actor={"type": "user", "id": str(admin_user.id)},
                    released_at=now,
                    released_by_actor={"type": "user", "id": str(admin_user.id)},
                    release_reason=None,
                )
            )
            await container.session().flush()


async def _wait_for_row_lock_waiter(db_container, timeout: float = 4.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        async with db_container() as probe:
            waiting = await probe.session().scalar(
                sa.text(
                    "SELECT count(*) FROM pg_locks WHERE NOT granted "
                    "AND locktype IN ('transactionid', 'tuple')"
                )
            )
        if waiting:
            return
        if loop.time() > deadline:
            raise AssertionError("no transaction waited for the tenant row")
        await asyncio.sleep(0.05)


async def test_concurrent_changes_to_flow_settings_keep_each_other(
    admin_user, db_container, history
):
    """The hold review limit and the debug-evidence window share one JSON column."""

    async def change_debug_window():
        async with db_container() as other:
            await other.settings_service().update_flow_retention_policy(
                FlowRetentionPolicyUpdate(run_debug_evidence_days=14)
            )

    async with db_container() as limiting:
        await limiting.flow_run_retention_policy_service().replace_hold_review_limit(
            days=30
        )
        changing = asyncio.create_task(change_debug_window())
        try:
            await _wait_for_row_lock_waiter(db_container)
            assert not changing.done()
        except BaseException:
            changing.cancel()
            raise
    await changing

    async with db_container() as container:
        flow_settings = await container.session().scalar(
            sa.select(Tenants.flow_settings).where(Tenants.id == admin_user.tenant_id)
        )
    assert flow_settings["retention_policy"]["hold_max_review_days"] == 30
    assert flow_settings["retention_policy"]["run_debug_evidence_days"] == 14


async def test_a_flow_settings_change_reports_the_locked_read_as_before(
    admin_user, db_container
):
    """Every writer audits `before`; a transform editing its argument must not alter it."""
    tenant_id = admin_user.tenant_id
    async with db_container() as container:
        repo = container.tenant_repo()
        await repo.update_flow_settings(
            tenant_id,
            lambda _current: {
                "retention_policy": {"version": 1, "run_debug_evidence_days": 9}
            },
            extra_values={"flow_runtime_upload_abandonment_days": 7},
        )

        def edit_in_place(current: dict | None) -> dict:
            assert current is not None
            current["retention_policy"]["run_debug_evidence_days"] = 21
            return current

        change = await repo.update_flow_settings(
            tenant_id,
            edit_in_place,
            read_columns=("flow_runtime_upload_abandonment_days",),
        )
    assert change.before == {
        "retention_policy": {"version": 1, "run_debug_evidence_days": 9}
    }
    assert change.after == {
        "retention_policy": {"version": 1, "run_debug_evidence_days": 21}
    }
    assert change.columns_before == {"flow_runtime_upload_abandonment_days": 7}


async def test_an_older_debug_window_save_keeps_a_newer_upload_window_save(
    admin_user, db_container
):
    """A save writes only the fields it supplies and audits the locked values.

    The debug-only save starts while the upload save still holds the tenant
    row, so the upload window it would have read before the lock is the old 7.
    """
    async with db_container() as container:
        await container.settings_service().update_flow_retention_policy(
            FlowRetentionPolicyUpdate(flow_runtime_upload_abandonment_days=7)
        )

    async def save_debug_window_only():
        async with db_container() as other:
            await other.settings_service().update_flow_retention_policy(
                FlowRetentionPolicyUpdate(run_debug_evidence_days=14)
            )

    async with db_container() as uploading:
        await uploading.settings_service().update_flow_retention_policy(
            FlowRetentionPolicyUpdate(
                flow_runtime_upload_abandonment_days=30, reason="Recordings audit"
            )
        )
        saving = asyncio.create_task(save_debug_window_only())
        try:
            await _wait_for_row_lock_waiter(db_container)
            assert not saving.done()
        except BaseException:
            saving.cancel()
            raise
    await saving

    async with db_container() as container:
        session = container.session()
        tenant = (
            await session.execute(
                sa.select(
                    Tenants.flow_settings, Tenants.flow_runtime_upload_abandonment_days
                ).where(Tenants.id == admin_user.tenant_id)
            )
        ).one()
        audits = (
            await session.scalars(
                sa.select(AuditLog.log_metadata)
                .where(
                    AuditLog.tenant_id == admin_user.tenant_id,
                    AuditLog.description == "Updated flow retention policy",
                )
                .order_by(AuditLog.timestamp)
            )
        ).all()
    assert tenant.flow_runtime_upload_abandonment_days == 30
    assert tenant.flow_settings["retention_policy"]["run_debug_evidence_days"] == 14
    assert [
        {key: audit[key] for key in ("old_policy", "new_policy")}
        for audit in audits[-2:]
    ] == [
        {
            "old_policy": {
                "run_debug_evidence_days": None,
                "flow_runtime_upload_abandonment_days": 7,
            },
            "new_policy": {
                "run_debug_evidence_days": None,
                "flow_runtime_upload_abandonment_days": 30,
            },
        },
        {
            "old_policy": {
                "run_debug_evidence_days": None,
                "flow_runtime_upload_abandonment_days": 30,
            },
            "new_policy": {
                "run_debug_evidence_days": 14,
                "flow_runtime_upload_abandonment_days": 30,
            },
        },
    ]
