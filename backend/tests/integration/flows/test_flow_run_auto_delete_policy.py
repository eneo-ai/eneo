"""Flow run-history policy write guards and read fences.

The write limits (the activation gate and the deployment maximum), the reason a
change that stops or delays automatic deletion needs, the read fence on runs
whose deletion has started, all against real PostgreSQL through the admin API and the run repository. Each test
names the mutant it kills (.lane/mutants.py).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.data_retention.infrastructure import retention_tasks
from eneo.data_retention.infrastructure.retention_tasks import (
    RetentionTaskRegistration,
)
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.flow_tables import (
    FlowRuns,
    Flows,
    FlowVersions,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.flows.domain.flow_run_exceptions import FlowRunNotFoundError
from eneo.flows.domain.flow_run_retention_policy import FLOWS_HISTORY_TASK
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.principal import FlowPrincipal
from eneo.main.config import get_settings
from eneo.main.exceptions import ConflictException

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

ROOT = "/api/v1/settings/flow-run-retention-policy"


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.fixture
async def regular_token(db_container, patch_auth_service_jwt, user_factory, admin_user):
    async with db_container() as container:
        user = await user_factory(container.session(), tenant_id=admin_user.tenant_id)
        return container.auth_service().create_access_token_for_user(user)


@pytest.fixture
def headers(admin_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}


def _register_flows_history(monkeypatch) -> None:
    """The deleting task is in the code list (the gate's only input)."""
    monkeypatch.setattr(
        retention_tasks,
        "RETENTION_TASKS",
        (
            *retention_tasks.RETENTION_TASKS,
            RetentionTaskRegistration(
                name=FLOWS_HISTORY_TASK,
                enabled=lambda settings: True,
                build=lambda session: (_ for _ in ()).throw(AssertionError("unused")),
            ),
        ),
    )


@pytest.fixture
def flows_history_registered(monkeypatch) -> None:
    _register_flows_history(monkeypatch)


@pytest.fixture
async def scope(db_container, admin_user) -> dict[str, UUID]:
    """A Space with one Flow, both inheriting the Organization policy."""
    async with db_container() as container:
        session = container.session()
        parent_id = await session.scalar(
            sa.select(Spaces.id).where(
                Spaces.tenant_id == admin_user.tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
            )
        )
        space = Spaces(
            name=f"Auto delete Space {uuid4()}",
            tenant_id=admin_user.tenant_id,
            tenant_space_id=parent_id,
        )
        session.add(space)
        await session.flush()
        flow = await _flow(session, admin_user, space.id)
        return {"space_id": space.id, "flow_id": flow}


async def _flow(session, admin_user, space_id, mode=None, days=None) -> UUID:
    flow = Flows(
        name=f"Auto delete Flow {uuid4()}",
        tenant_id=admin_user.tenant_id,
        space_id=space_id,
        flow_run_history_retention_mode=mode,
        flow_run_history_retention_days=days,
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
    return flow.id


async def _set_policy(db_container, table, row_id: UUID, mode: str, days: int) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(table)
            .where(table.id == row_id)
            .values(
                flow_run_history_retention_mode=mode,
                flow_run_history_retention_days=days,
            )
        )


async def _run(session, admin_user, flow_id, *, age: timedelta, **values) -> UUID:
    at = datetime.now(timezone.utc) - age
    status = values.pop("status", "completed")
    run = FlowRuns(
        flow_id=flow_id,
        flow_version=1,
        tenant_id=admin_user.tenant_id,
        principal_type="user",
        principal_user_id=admin_user.id,
        trace_id=uuid4(),
        status=status,
        started_at=at,
        finished_at=at if status != "running" else None,
        created_at=at,
        updated_at=at,
        **values,
    )
    session.add(run)
    await session.flush()
    return run.id


async def _policy_audits(db_container, tenant_id) -> list[dict[str, object]]:
    async with db_container() as container:
        return list(
            await container.session().scalars(
                sa.select(AuditLog.log_metadata)
                .where(AuditLog.tenant_id == tenant_id)
                .where(AuditLog.action == "flow_run_retention_policy_changed")
                .order_by(AuditLog.timestamp)
            )
        )


# Write limits -----------------------------------------------------------------


async def test_auto_delete_is_refused_until_the_deleting_task_is_registered(
    client, headers, admin_user, db_container, scope, monkeypatch
) -> None:
    """Mutant gate_open."""
    refused = await client.put(
        ROOT, json={"policy": {"mode": "auto_delete", "days": 30}}, headers=headers
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["code"] == "flow_retention_auto_delete_unavailable"
    current = (await client.get(ROOT, headers=headers)).json()
    assert current["local_policy"] is None
    assert current["write_rules"]["auto_delete_available"] is False
    assert await _policy_audits(db_container, admin_user.tenant_id) == []
    # A stored auto_delete rule still reads and applies while the gate is closed.
    await _set_policy(db_container, Spaces, scope["space_id"], "auto_delete", 30)
    flow = (
        await client.get(f"{ROOT}/flows/{scope['flow_id']}", headers=headers)
    ).json()
    assert flow["inherited_policy"] == {"mode": "auto_delete", "days": 30}

    _register_flows_history(monkeypatch)

    accepted = await client.put(
        ROOT, json={"policy": {"mode": "auto_delete", "days": 30}}, headers=headers
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["local_policy"] == {"mode": "auto_delete", "days": 30}
    assert accepted.json()["write_rules"]["auto_delete_available"] is True


async def test_the_maximum_applies_on_write_and_a_stored_longer_rule_still_applies(
    client, headers, db_container, scope, monkeypatch
) -> None:
    """Mutant ceiling_ge."""
    monkeypatch.setattr(get_settings(), "flow_retention_max_days", 100)
    flow_path = f"{ROOT}/flows/{scope['flow_id']}"

    above = await client.put(
        flow_path, json={"policy": {"mode": "preserve", "days": 101}}, headers=headers
    )
    at = await client.put(
        flow_path, json={"policy": {"mode": "preserve", "days": 100}}, headers=headers
    )

    assert above.status_code == 400, above.text
    assert above.json()["code"] == "flow_retention_days_above_maximum"
    assert at.status_code == 200, at.text
    assert at.json()["write_rules"]["max_days"] == 100
    # A Space rule stored before the maximum was lowered keeps applying.
    await _set_policy(db_container, Spaces, scope["space_id"], "preserve", 40_000)
    cleared = await client.put(flow_path, json={"policy": None}, headers=headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["effective"]["effective_days"] == 40_000


async def test_stopping_or_delaying_auto_delete_needs_a_recorded_reason(
    client, headers, admin_user, db_container, scope, flows_history_registered
) -> None:
    """Mutants reason_skipped, reason_on_local_policy."""
    space_path = f"{ROOT}/spaces/{scope['space_id']}"

    async def put(path: str, policy: object, reason: str | None = None):
        body: dict[str, object] = {"policy": policy}
        if reason is not None:
            body["reason"] = reason
        return await client.put(path, json=body, headers=headers)

    # Starting or shortening automatic deletion needs no reason.
    assert (await put(ROOT, {"mode": "auto_delete", "days": 30})).status_code == 200
    assert (await put(ROOT, {"mode": "auto_delete", "days": 20})).status_code == 200
    # Every change that stops or delays it does, at the level where it applies.
    for path, policy in (
        (ROOT, {"mode": "auto_delete", "days": 21}),
        (ROOT, {"mode": "preserve", "days": 20}),
        (ROOT, None),
        (space_path, {"mode": "review_required", "days": 20}),
    ):
        refused = await put(path, policy)
        assert refused.status_code == 400, (path, policy, refused.text)
        assert refused.json()["code"] == "flow_retention_reason_required"
    before = await _policy_audits(db_container, admin_user.tenant_id)

    stopped = await put(
        space_path, {"mode": "preserve", "days": 20}, reason="Archive transfer first"
    )

    assert stopped.status_code == 200, stopped.text
    audits = await _policy_audits(db_container, admin_user.tenant_id)
    assert len(audits) == len(before) + 1
    assert audits[-1]["reason"] == "Archive transfer first"
    assert audits[-1]["previous_effective_policy"] == {
        "mode": "auto_delete",
        "days": 20,
    }
    assert audits[-1]["effective_policy"] == {"mode": "preserve", "days": 20}
    assert audits[-1]["previous_local_policy"] is None
    # A blank reason is not a reason.
    assert (await put(ROOT, None, reason="   ")).status_code == 422


# Read fence ------------------------------------------------------------------


async def test_a_run_whose_deletion_started_reads_as_deleted_everywhere(
    client, headers, admin_user, db_container, scope
) -> None:
    """Mutants fence_get, fence_review_queue, idempotency_returns_fenced,
    hold_accepts_fenced, purge_selector_unfenced."""
    flow_id = scope["flow_id"]
    await _set_policy(db_container, Flows, flow_id, "review_required", 1)
    async with db_container() as container:
        session = container.session()
        visible = await _run(session, admin_user, flow_id, age=timedelta(3))
        fenced = await _run(
            session,
            admin_user,
            flow_id,
            age=timedelta(4),
            idempotency_key="replay-me",
            gallring_receipt_id=uuid4(),
        )

    async with db_container() as container:
        runs = FlowRunRepository(container.session())
        tenant_id = admin_user.tenant_id
        for read in (runs.get, runs.get_status):
            with pytest.raises(FlowRunNotFoundError):
                await read(run_id=fenced, tenant_id=tenant_id)
            assert (await read(run_id=visible, tenant_id=tenant_id)).id == visible
        listed = await runs.list_statuses(tenant_id=tenant_id, flow_id=flow_id)
        assert [run.id for run in listed] == [visible]
        # Its idempotency key is never answered with it, nor reused (409).
        with pytest.raises(ConflictException) as replayed:
            await runs.get_idempotent_run(
                tenant_id=tenant_id,
                flow_id=flow_id,
                idempotency_key="replay-me",
                principal=FlowPrincipal.from_user(admin_user),
            )
        assert replayed.value.code == "flow_run_idempotency_run_deleted"

    queue = await client.get(f"{ROOT}/flows/{flow_id}/review-queue", headers=headers)
    assert [item["run_id"] for item in queue.json()["items"]] == [str(visible)]
    hold = await client.post(
        "/api/v1/settings/flow-retention-holds",
        json={
            "flow_id": str(flow_id),
            "run_ids": [str(fenced)],
            "reason": "Disclosure request",
            "review_by": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        },
        headers=headers,
    )
    assert hold.status_code == 400, hold.text
    assert hold.json()["code"] == "flow_retention_hold_run_not_in_flow"

    await _set_policy(db_container, Flows, flow_id, "preserve", 1)
    purged = await client.post(
        f"{ROOT}/flows/{flow_id}/purge",
        json={"dry_run": False, "limit": 10},
        headers=headers,
    )
    assert purged.status_code == 200, purged.text
    # The visible run only, in the selection and in the blocked counts.
    assert purged.json()["candidate_count"] == 1
    assert purged.json()["blocked"]["counted_runs"] == 1
    async with db_container() as container:
        assert await container.session().get(FlowRuns, fenced) is not None
