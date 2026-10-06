"""Flow run-history policies, read fences, status and overdue health.

The write limits (the activation gate and the deployment maximum), the reason a
change that stops or delays automatic deletion needs, the read fence on runs
whose deletion has started, the status route and the overdue health flag, all
against real PostgreSQL through the admin API and the run repository. Each test
names the mutant it kills (.lane/mutants.py).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from eneo.data_retention.domain.retention import RetentionJobOutcome
from eneo.data_retention.infrastructure import retention_tasks
from eneo.data_retention.infrastructure.retention_tasks import RetentionTaskRegistration
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.flow_tables import (
    FlowRetentionHolds,
    FlowRunAuditOutbox,
    FlowRuns,
    Flows,
    FlowVersions,
)
from eneo.database.tables.retention_tables import RetentionJobRuns, RetentionReceipts
from eneo.database.tables.spaces_table import Spaces
from eneo.flows.domain.flow_run_exceptions import FlowRunNotFoundError
from eneo.flows.domain.flow_run_retention_policy import FLOWS_HISTORY_TASK
from eneo.flows.infrastructure.flow_run_history_due_repo import (
    FlowRunHistoryDueRepository,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.principal import FlowPrincipal
from eneo.flows.runtime.flow_runtime_health import (
    FlowRuntimeHealthFlag,
    FlowRuntimeHealthStatus,
    FlowRuntimeProbe,
    build_flow_runtime_health_policy,
    classify_flow_runtime_health,
    load_flow_runtime_health_snapshot,
)
from eneo.main.config import get_settings
from eneo.main.exceptions import ConflictException
from eneo.server.main import logger as server_logger

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


@pytest.fixture
def flows_history_registered(monkeypatch) -> None:
    _register_flows_history(monkeypatch)


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


async def _seed_runs(session, admin_user, flow_id, *, n: int, age_days: int) -> None:
    await session.execute(
        sa.text(
            "INSERT INTO flow_runs (flow_id, flow_version, tenant_id, principal_type, "
            "principal_user_id, status, started_at, finished_at, created_at, updated_at) "
            "SELECT :flow_id, 1, :tenant_id, 'user', :user_id, 'completed', at, at, at, at "
            "FROM (SELECT now() - make_interval(days => :age) - make_interval(mins => g) "
            "AS at FROM generate_series(1, :n) AS g) AS s"
        ),
        {
            "flow_id": flow_id,
            "tenant_id": admin_user.tenant_id,
            "user_id": admin_user.id,
            "n": n,
            "age": age_days,
        },
    )


def _hold(admin_user, flow_id: UUID, run_id: UUID) -> FlowRetentionHolds:
    return FlowRetentionHolds(
        tenant_id=admin_user.tenant_id,
        flow_id=flow_id,
        flow_run_id=run_id,
        reason="Disclosure request",
        review_by=datetime.now(timezone.utc) + timedelta(days=30),
        created_by_actor={"type": "user", "id": str(admin_user.id)},
        created_by_user_id=admin_user.id,
    )


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


# Status and overdue -------------------------------------------------------------


@pytest.fixture
async def overdue_history(db_container, admin_user, scope) -> dict[str, UUID]:
    """An auto_delete Flow (1 day) with runs in every overdue state, and one
    unfinished deletion receipt."""
    flow_id = scope["flow_id"]
    await _set_policy(db_container, Flows, flow_id, "auto_delete", 1)
    async with db_container() as container:
        session = container.session()
        plain = await _run(session, admin_user, flow_id, age=timedelta(days=5))
        audit = await _run(session, admin_user, flow_id, age=timedelta(days=4))
        session.add(
            FlowRunAuditOutbox(
                tenant_id=admin_user.tenant_id,
                flow_id=flow_id,
                flow_run_id=audit,
                run_revision=1,
                description="flow_run_completed:executor_completed",
                action="flow_run_completed",
                entity_type="flow_run",
                entity_id=audit,
                actor_id=admin_user.id,
                actor_type="user",
                source="executor_completed",
                target_status="completed",
                delivery_status="pending",
            )
        )
        held = await _run(session, admin_user, flow_id, age=timedelta(days=6))
        session.add(_hold(admin_user, flow_id, held))
        # Due, but within the overdue window: not overdue yet.
        await _run(session, admin_user, flow_id, age=timedelta(hours=36))
        # Deletion started, still running, or under another mode: never counted.
        await _run(
            session, admin_user, flow_id, age=timedelta(9), gallring_receipt_id=uuid4()
        )
        await _run(
            session,
            admin_user,
            flow_id,
            age=timedelta(9),
            status="running",
            execution_heartbeat_at=datetime.now(timezone.utc),
        )
        other = await _flow(
            session, admin_user, scope["space_id"], mode="preserve", days=1
        )
        await _run(session, admin_user, other, age=timedelta(days=9))
        now = datetime.now(timezone.utc)
        session.add(
            RetentionReceipts(
                task=FLOWS_HISTORY_TASK,
                entity_kind="flow_run",
                entity_id=uuid4(),
                category="run_record",
                trigger="scheduled",
                tenant_id=admin_user.tenant_id,
                policy_source="flow",
                policy_mode="auto_delete",
                policy_days=30,
                phase="deleting",
                started_at=now - timedelta(hours=5),
                updated_at=now,
                manifest_completed_at=now,
            )
        )
        return {"plain": plain, "audit": audit, "held": held}


async def test_status_reports_tasks_overdue_runs_by_blocker_and_receipts(
    client, headers, regular_token, db_container, overdue_history
) -> None:
    """Mutants overdue_counts_held, overdue_skips_fence, overdue_always_complete."""
    response = await client.get(f"{ROOT}/status", headers=headers)

    assert response.status_code == 200, response.text
    status = response.json()
    assert status["auto_delete_available"] is False
    assert status["overdue_window_days"] == 1
    assert [task["name"] for task in status["tasks"]] == [
        registration.name for registration in retention_tasks.RETENTION_TASKS
    ]
    assert status["tasks"][0]["enabled"] is True
    assert status["tasks"][0]["last_execution"] is None
    overdue = status["overdue"]
    assert {key: overdue[key] for key in overdue if key != "oldest_due_at"} == {
        "count": 2,
        "complete": True,
        "undelivered_audit": 1,
        "unresolved_webhook": 0,
        "not_yet_deleted": 1,
        "held": 1,
    }
    expected = datetime.now(timezone.utc) - timedelta(days=4)
    oldest = datetime.fromisoformat(overdue["oldest_due_at"])
    assert abs((oldest - expected).total_seconds()) < 120
    assert status["receipts"]["unfinished"] == 1
    assert status["receipts"]["oldest_unfinished_started_at"] is not None
    forbidden = await client.get(
        f"{ROOT}/status", headers={"Authorization": f"Bearer {regular_token}"}
    )
    assert forbidden.status_code == 403, forbidden.text
    # Capped: the count says it did not cover everything.
    async with db_container() as container:
        capped = await FlowRunHistoryDueRepository(container.session()).overdue(
            now=datetime.now(timezone.utc), window=timedelta(days=1), cap=1
        )
    assert (capped.count, capped.complete, capped.held) == (1, False, 1)


async def test_a_task_the_switch_turned_off_is_never_reported_stale(
    client, headers, db_container, monkeypatch
) -> None:
    """Mutant stale_when_disabled."""
    monkeypatch.setattr(get_settings(), "gallring_flows_housekeeping_enabled", False)
    at = datetime.now(timezone.utc) - timedelta(days=5)
    async with db_container() as container:
        container.session().add(
            RetentionJobRuns(
                task="flows.housekeeping",
                outcome=RetentionJobOutcome.SKIPPED.value,
                started_at=at,
                heartbeat_at=at,
                finished_at=at,
                error_code="disabled_by_deployment_setting",
            )
        )

    status = (await client.get(f"{ROOT}/status", headers=headers)).json()

    [housekeeping] = [t for t in status["tasks"] if t["name"] == "flows.housekeeping"]
    assert (housekeeping["enabled"], housekeeping["stale"]) == (False, False)
    assert housekeeping["last_execution"]["outcome"] == "skipped"


# Health ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("snapshots", "registered", "flagged", "count", "unknown", "window_days"),
    [
        # (age in hours, overdue count, complete) per execution, oldest first.
        pytest.param([], True, False, None, False, 1, id="never-ran"),
        pytest.param([(3, 0, True)], True, False, 0, False, 1, id="zero"),
        pytest.param(
            [(3, 0, True), (1, 4, True)], True, True, 4, False, 1, id="newest"
        ),
        pytest.param([(49, 0, True)], True, True, None, True, 1, id="stale"),
        pytest.param(
            [(49, 0, True)], True, True, None, True, 7, id="stale-large-window"
        ),
        pytest.param([(2, None, None)], True, True, None, True, 1, id="missing"),
        pytest.param([(1, 0, False)], True, True, None, True, 1, id="zero-partial"),
        pytest.param([(1, 4, True)], False, False, None, False, 1, id="not-registered"),
    ],
)
async def test_health_flags_overdue_from_the_newest_fresh_complete_snapshot(
    db_container,
    snapshots,
    registered,
    flagged,
    count,
    unknown,
    window_days,
    monkeypatch,
) -> None:
    """Mutants health_reads_oldest, health_ignores_unknown, zero_incomplete_is_known,
    freshness_uses_window, unregistered_snapshot_is_read."""
    now = datetime.now(timezone.utc)
    async with db_container() as container:
        for hours, overdue, complete in snapshots:
            at = now - timedelta(hours=hours)
            container.session().add(
                RetentionJobRuns(
                    task=FLOWS_HISTORY_TASK,
                    outcome=RetentionJobOutcome.SUCCEEDED.value,
                    started_at=at,
                    heartbeat_at=at,
                    finished_at=at,
                    overdue_observed_at=at if overdue is not None else None,
                    overdue_count=overdue,
                    overdue_complete=complete,
                    overdue_oldest_due_at=at - timedelta(days=3) if overdue else None,
                )
            )
    monkeypatch.setattr(get_settings(), "gallring_overdue_window_days", window_days)
    policy = build_flow_runtime_health_policy(
        task_timeout_seconds=600,
        gallring_tasks=(FLOWS_HISTORY_TASK,) if registered else (),
        gallring_overdue_task=FLOWS_HISTORY_TASK,
    )
    async with db_container() as container:
        snapshot = await load_flow_runtime_health_snapshot(
            session=container.session(), now=now, policy=policy
        )
    health = classify_flow_runtime_health(
        snapshot=snapshot,
        now=now,
        policy=policy,
        probe=FlowRuntimeProbe(
            db_query_ok=True, execution_worker_ready=True, maintenance_worker_ready=True
        ),
    )

    assert (FlowRuntimeHealthFlag.GALLRING_OVERDUE in health.status_flags) is flagged
    assert (health.gallring.overdue_count, health.gallring.overdue_unknown) == (
        count,
        unknown,
    )
    if flagged:
        assert health.status is FlowRuntimeHealthStatus.UNHEALTHY


@pytest.mark.parametrize(
    ("statement", "status", "code"),
    [
        pytest.param(
            sa.select(sa.func.pg_sleep(1)),
            503,
            "retention_status_unavailable",
            id="timeout",
        ),
        pytest.param(None, 200, None, id="within-limit"),
        pytest.param(
            sa.select(sa.literal_column("retention_status_missing_column")),
            500,
            "internal_error",
            id="permanent-error",
        ),
    ],
)
async def test_status_database_errors_keep_their_failure_contract(
    app, headers, monkeypatch, caplog, statement, status, code
) -> None:
    """Mutants status_timeout_removed, permanent_error_mapped_to_unavailable."""
    monkeypatch.setattr(get_settings(), "gallring_chunk_statement_timeout_ms", 500)
    original = FlowRunHistoryDueRepository.overdue

    async def observed(self, **kwargs):
        if statement is not None:
            await self.session.execute(statement)
        return await original(self, **kwargs)

    monkeypatch.setattr(FlowRunHistoryDueRepository, "overdue", observed)
    server_logger.addHandler(caplog.handler)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test.local",
        ) as client:
            with caplog.at_level(logging.ERROR):
                response = await client.get(f"{ROOT}/status", headers=headers)
    finally:
        server_logger.removeHandler(caplog.handler)
    assert response.status_code == status, response.text
    if code is not None:
        assert response.json()["code"] == code
    if status == 500:
        error_id = response.json()["error_id"]
        records = [
            r for r in caplog.records if getattr(r, "error_id", None) == error_id
        ]
        assert len(records) == 1
        assert getattr(records[0], "exception_type", None) == "ProgrammingError"
        assert "UndefinedColumn" in getattr(records[0], "traceback", "")
