from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from freezegun import freeze_time

from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import FlowRunError, FlowRunErrorDetails


@pytest.mark.parametrize("wait", ["approved_review", "exhausted_dispatch"])
def test_abandonment_serializes_its_own_facts_and_never_promises_safe_retry(wait):
    from eneo.flows.domain.flow_run_recovery_policy import flow_run_abandonment_deadline
    from eneo.flows.flow_run_error import FlowRunAbandonmentFacts

    anchor = datetime(2026, 8, 22, tzinfo=timezone.utc)
    checkpoint_id = uuid4() if wait == "approved_review" else None
    facts = FlowRunAbandonmentFacts(
        wait=wait,
        anchor_at=anchor,
        deadline=flow_run_abandonment_deadline(anchor),
        checkpoint_id=checkpoint_id,
    )
    error = FlowRunError.from_source(
        FlowRunLifecycleSource.ABANDONMENT_RECONCILER,
        code=FlowApiErrorCode.RUN_ABANDONED,
        message="Flow run exceeded its abandonment deadline.",
        details=FlowRunErrorDetails(abandonment=facts),
    )

    payload = error.model_dump(mode="json", exclude_none=True)
    assert payload["code"] == "flow_run_abandoned"
    assert payload["retryable"] is False
    assert payload["details"] == {
        "abandonment": {
            "wait": wait,
            "anchor_at": "2026-08-22T00:00:00Z",
            "deadline": "2026-09-21T00:00:00Z",
            **({"checkpoint_id": str(checkpoint_id)} if checkpoint_id else {}),
        }
    }
    assert FlowRunError.model_validate(payload) == error


def _facts(wait):
    from eneo.flows.flow_run_error import FlowRunAbandonmentFacts

    return FlowRunAbandonmentFacts(
        wait=wait,
        anchor_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
        deadline=datetime(2026, 9, 21, tzinfo=timezone.utc),
        checkpoint_id=uuid4() if wait == "approved_review" else None,
    )


@pytest.mark.parametrize("wait", ["approved_review", "exhausted_dispatch"])
async def test_abandonment_update_rechecks_anchor_state_and_revision_under_parent_lock(
    wait,
):
    from sqlalchemy.dialects import postgresql

    from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository

    session = AsyncMock()
    session.scalar.return_value = None
    repo = FlowRunRepository(session=session)
    facts = _facts(wait)
    run_id, tenant_id = uuid4(), uuid4()
    error = FlowRunError.from_source(
        FlowRunLifecycleSource.ABANDONMENT_RECONCILER,
        code=FlowApiErrorCode.RUN_ABANDONED,
        message="Flow run exceeded its abandonment deadline.",
        details=FlowRunErrorDetails(abandonment=facts),
    )

    assert (
        await repo.terminalize_abandoned_run_status(
            run_id=run_id,
            tenant_id=tenant_id,
            expected_revision=7,
            facts=facts,
            error=error,
        )
        is None
    )

    lock, update = [call.args[0] for call in session.scalar.await_args_list]
    assert "FOR UPDATE" in str(lock.compile(dialect=postgresql.dialect()))
    compiled = update.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "flow_runs.revision =" in sql
    assert "statement_timestamp()" in sql
    assert run_id in compiled.params.values()
    assert tenant_id in compiled.params.values()
    assert facts.anchor_at in compiled.params.values()
    assert 7 in compiled.params.values()
    assert "input_payload_json=" not in sql
    assert "output_payload_json=" not in sql
    if wait == "approved_review":
        assert "awaiting_review" in compiled.params.values()
        assert "approved" in compiled.params.values()
        assert "flow_run_review_checkpoints.approved_at =" in sql
        assert "flow_run_review_checkpoints.tenant_id = flow_runs.tenant_id" in sql
        assert facts.checkpoint_id in compiled.params.values()
    else:
        assert "queued" in compiled.params.values()
        assert "flow_runs.dispatch_pending_since =" in sql
        assert "flow_runs.dispatch_exhausted_at IS NOT NULL" in sql


@pytest.mark.parametrize("wait", ["approved_review", "exhausted_dispatch"])
@pytest.mark.parametrize("lost_race", [False, True])
async def test_abandonment_terminalizes_once_as_system_and_keeps_approval_actor(
    wait, lost_race
):
    from eneo.audit.domain.actor_types import ActorType
    from eneo.flows.application.flow_run_terminalization import FlowRunTerminalizer
    from eneo.flows.domain.flow import FlowRun, FlowRunStatus

    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        tenant_id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        principal_type="user",
        principal_user_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.AWAITING_REVIEW
        if wait == "approved_review"
        else FlowRunStatus.QUEUED,
        created_at=now,
        updated_at=now,
    )
    run_repo, audit_repo, checkpoint_repo = AsyncMock(), AsyncMock(), AsyncMock()
    run_repo.get.return_value = run
    run_repo.terminalize_abandoned_run_status.return_value = (
        None if lost_race else run.model_copy(update={"status": FlowRunStatus.FAILED})
    )
    terminalizer = FlowRunTerminalizer(run_repo, audit_repo, checkpoint_repo)
    result = await terminalizer.terminalize_abandoned_run(
        run_id=run.id,
        tenant_id=run.tenant_id,
        expected_revision=run.revision,
        facts=_facts(wait),
    )

    assert result.did_transition is not lost_race
    run_repo.terminalize_run_status.assert_not_awaited()
    if lost_race:
        checkpoint_repo.cancel_active_review_checkpoint_for_terminal_run.assert_not_awaited()
        audit_repo.insert_terminal_audit_outbox.assert_not_awaited()
    else:
        assert result.run.status == FlowRunStatus.FAILED
        error = run_repo.terminalize_abandoned_run_status.await_args.kwargs["error"]
        assert error.code == "flow_run_abandoned"
        assert error.details.abandonment.wait == wait
        assert error.retryable is False
        checkpoint_repo.cancel_active_review_checkpoint_for_terminal_run.assert_awaited_once()
        assert (
            checkpoint_repo.cancel_active_review_checkpoint_for_terminal_run.await_args.kwargs[
                "principal"
            ]
            is None
        )
        audit_repo.insert_terminal_audit_outbox.assert_awaited_once()
        assert (
            audit_repo.insert_terminal_audit_outbox.await_args.kwargs["actor_type"]
            == ActorType.SYSTEM
        )
        assert (
            audit_repo.insert_terminal_audit_outbox.await_args.kwargs["actor_id"]
            is None
        )


@freeze_time("2026-09-21T00:00:00Z")
async def test_approved_resume_past_deadline_is_refused_without_terminal_writes():
    from eneo.flows.domain.flow_run_recovery_policy import (
        FlowRunAbandonmentDeadlineExceeded,
    )
    from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
        FlowRunReviewCheckpointRepository,
    )

    facts = _facts("approved_review")
    session = AsyncMock()
    repo = FlowRunReviewCheckpointRepository(
        session=session, audit_outbox_repo=AsyncMock()
    )
    repo._load_review_checkpoint_and_run_rows_for_update = AsyncMock(
        return_value=(
            SimpleNamespace(
                id=facts.checkpoint_id,
                state="approved",
                revision=2,
                approved_at=facts.anchor_at,
                expires_at=None,
                resume_idempotency_key=None,
            ),
            SimpleNamespace(status="awaiting_review"),
        )
    )
    with pytest.raises(FlowRunAbandonmentDeadlineExceeded) as caught:
        await repo.resume_review_checkpoint(
            checkpoint_id=facts.checkpoint_id,
            tenant_id=uuid4(),
            flow_id=uuid4(),
            flow_run_id=uuid4(),
            expected_revision=2,
            resume_idempotency_key="resume",
            principal=AsyncMock(),
        )
    assert caught.value.anchor_at == facts.anchor_at
    assert caught.value.checkpoint_id == facts.checkpoint_id
    session.scalar.assert_not_awaited()
    session.execute.assert_not_awaited()


async def test_shared_recovery_bounds_checkpoint_inspection_and_advances_healthy_parents(
    monkeypatch,
):
    from contextlib import asynccontextmanager
    from datetime import timedelta
    from uuid import UUID

    import sqlalchemy as sa

    from eneo.database.tables.flow_tables import FlowRuns, FlowRunWebhookDeliveries
    from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
    from eneo.flows.runtime import tasks

    inspected = set()

    def inspect_checkpoint(run_id, state):
        inspected.add(run_id)
        return state

    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    parents = sa.Table(
        "flow_runs",
        metadata,
        *[
            sa.Column(name, FlowRuns.__table__.c[name].type.as_generic())
            for name in (
                "id",
                "tenant_id",
                "revision",
                "status",
                "created_at",
                "execution_heartbeat_at",
                "dispatch_pending_since",
                "dispatch_exhausted_at",
            )
        ],
    )
    sa.Table(
        "flow_run_webhook_deliveries",
        metadata,
        *[
            sa.Column(
                name, FlowRunWebhookDeliveries.__table__.c[name].type.as_generic()
            )
            for name in ("id", "tenant_id", "flow_run_id", "delivery_status")
        ],
    )
    checkpoints = sa.Table(
        "checkpoint_rows",
        metadata,
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("flow_run_id", sa.Uuid, index=True),
        sa.Column("tenant_id", sa.Uuid),
        sa.Column("state", sa.String),
        sa.Column("approved_at", sa.DateTime),
    )
    metadata.create_all(engine)
    tenant_id = uuid4()
    anchor = datetime(2026, 8, 1)
    backlog, page_size = 1000, 7
    with engine.connect() as connection:
        connection.connection.driver_connection.create_function(
            "statement_timestamp", 0, lambda: "2026-09-21 00:00:00"
        )
        connection.connection.driver_connection.create_function(
            "inspect_checkpoint", 2, inspect_checkpoint
        )
        connection.exec_driver_sql(
            "CREATE VIEW flow_run_review_checkpoints AS "
            "SELECT id, flow_run_id, tenant_id, approved_at, "
            "inspect_checkpoint(flow_run_id, state) AS state FROM checkpoint_rows"
        )
        connection.execute(
            parents.insert(),
            [
                dict(
                    id=UUID(int=i),
                    tenant_id=tenant_id,
                    revision=1,
                    status="awaiting_review",
                    created_at=anchor + timedelta(seconds=i),
                )
                for i in range(1, backlog + 1)
            ],
        )
        connection.execute(
            checkpoints.insert(),
            [
                dict(
                    id=uuid4(),
                    flow_run_id=UUID(int=i),
                    tenant_id=tenant_id,
                    state="awaiting_review",
                )
                for i in range(1, backlog + 1)
            ],
        )
        session = MagicMock()
        session.execute = AsyncMock(side_effect=connection.execute)
        repo = FlowRunRepository(session=session)
        boundary = await repo.recovery_sweep_boundary()
        assert inspected == set(), "Boundary discovery must not inspect checkpoints"
        assert boundary == (anchor + timedelta(seconds=backlog), UUID(int=backlog))
        terminalizer = AsyncMock()
        container = SimpleNamespace(
            flow_run_repo=lambda: repo,
            flow_run_terminalizer=lambda: terminalizer,
            flow_provider_call_repo=lambda: AsyncMock(),
        )

        @asynccontextmanager
        async def session_context():
            yield session

        monkeypatch.setattr(tasks.sessionmanager, "session", session_context)
        monkeypatch.setattr(
            tasks, "enable_autobegin_for_flow_task_session", lambda _: None
        )
        monkeypatch.setattr(tasks, "Container", lambda **_: container)
        monkeypatch.setattr(tasks, "_stale_running_cursor", None)
        monkeypatch.setattr(tasks, "_stale_running_window_end", boundary)
        for page in range(2):
            inspected.clear()
            result = await tasks._reconcile_stale_running_runs_all_tenants(
                limit=page_size
            )
            assert inspected == {
                UUID(int=i).hex
                for i in range(page * page_size + 1, (page + 1) * page_size + 1)
            }
            last = (page + 1) * page_size
            assert tasks._stale_running_cursor == (
                anchor + timedelta(seconds=last),
                UUID(int=last),
            )
            assert result["review_checkpoint_invariant_violations"] == 0
            assert result["abandoned"] == result["reconciled"] == 0
        terminalizer.terminalize_abandoned_run.assert_not_awaited()
        terminalizer.terminalize_stale_running_run.assert_not_awaited()
    engine.dispose()


async def test_review_page_keeps_cursor_separate_from_approval_deadline():
    from eneo.flows.domain.flow_run_recovery_policy import FlowRunRecoveryKind
    from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository

    facts = _facts("approved_review")
    created_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
    tenant_id = uuid4()
    parents = [
        SimpleNamespace(
            id=uuid4(),
            tenant_id=tenant_id,
            revision=2,
            anchor_at=created_at,
            kind="review_checkpoint_inspection",
            checkpoint_id=None,
        )
        for _ in range(4)
    ]
    approved = SimpleNamespace(
        id=facts.checkpoint_id,
        flow_run_id=parents[0].id,
        tenant_id=tenant_id,
        state="approved",
        approved_at=facts.anchor_at,
        abandonment_due=True,
    )
    healthy = SimpleNamespace(
        id=uuid4(),
        flow_run_id=parents[1].id,
        tenant_id=tenant_id,
        state="approved",
        approved_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
        abandonment_due=False,
    )
    missing = SimpleNamespace(
        id=None,
        flow_run_id=parents[2].id,
        tenant_id=tenant_id,
        state=None,
        approved_at=None,
        abandonment_due=False,
    )
    session = AsyncMock()
    session.execute.side_effect = [
        MagicMock(all=lambda: parents),
        MagicMock(all=lambda: [approved, healthy, missing]),
    ]
    candidates = await FlowRunRepository(session=session).list_recovery_candidates(
        limit=4
    )
    assert candidates[0].abandonment == facts
    assert candidates[0].cursor == (created_at, parents[0].id)
    assert candidates[1].kind == FlowRunRecoveryKind.REVIEW_CHECKPOINT_INSPECTION
    assert candidates[1].abandonment is None
    assert candidates[2].kind == FlowRunRecoveryKind.MISSING_REVIEW_CHECKPOINT
    assert candidates[2].abandonment is None
    assert candidates[2].cursor == (created_at, parents[2].id)
    # The last parent stopped awaiting review between page discovery and inspection.
    assert candidates[3].kind == FlowRunRecoveryKind.REVIEW_CHECKPOINT_INSPECTION
    assert candidates[3].abandonment is None


async def test_shared_sweep_reports_missing_checkpoint_without_inventing_deadline(
    monkeypatch,
):
    from contextlib import asynccontextmanager

    from eneo.flows.domain.flow_run_recovery_policy import FlowRunRecoveryKind
    from eneo.flows.infrastructure.flow_run_repo import FlowRunRecoveryCandidate
    from eneo.flows.runtime import tasks

    candidate = FlowRunRecoveryCandidate(
        id=uuid4(),
        tenant_id=uuid4(),
        revision=2,
        kind=FlowRunRecoveryKind.MISSING_REVIEW_CHECKPOINT,
        anchor_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    assert candidate.abandonment is None
    repo, terminalizer = AsyncMock(), AsyncMock()
    repo.recovery_sweep_boundary.return_value = (candidate.anchor_at, candidate.id)
    repo.list_recovery_candidates.return_value = [candidate]
    container = SimpleNamespace(
        flow_run_repo=lambda: repo,
        flow_run_terminalizer=lambda: terminalizer,
        flow_provider_call_repo=lambda: AsyncMock(),
    )

    @asynccontextmanager
    async def session_context():
        yield MagicMock()

    monkeypatch.setattr(tasks.sessionmanager, "session", session_context)
    monkeypatch.setattr(tasks, "enable_autobegin_for_flow_task_session", lambda _: None)
    monkeypatch.setattr(tasks, "Container", lambda **_: container)
    monkeypatch.setattr(tasks, "_stale_running_cursor", None)
    monkeypatch.setattr(tasks, "_stale_running_window_end", None)
    result = await tasks._reconcile_stale_running_runs_all_tenants(limit=1)
    assert result["review_checkpoint_invariant_violations"] == 1
    assert result["abandoned"] == 0
    terminalizer.terminalize_abandoned_run.assert_not_awaited()
    terminalizer.terminalize_stale_running_run.assert_not_awaited()
    assert tasks._stale_running_cursor == (candidate.anchor_at, candidate.id)


async def test_exhausted_dispatch_past_deadline_cannot_reset_its_epoch():
    from eneo.flows.domain.flow_run_recovery_policy import (
        FlowRunAbandonmentDeadlineExceeded,
    )
    from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository

    facts = _facts("exhausted_dispatch")
    session = AsyncMock()
    exhausted_at = datetime(2026, 8, 23, tzinfo=timezone.utc)
    session.scalar.return_value = SimpleNamespace(
        status="queued",
        dispatch_pending_since=facts.anchor_at,
        dispatch_exhausted_at=exhausted_at,
        dispatched_at=facts.anchor_at,
        dispatch_last_error=None,
    )
    repo = FlowRunRepository(session=session)
    with pytest.raises(FlowRunAbandonmentDeadlineExceeded):
        await repo.rearm_exhausted_accepted_dispatch_for_redrive(
            run_id=uuid4(),
            tenant_id=uuid4(),
            expected_revision=2,
            expected_dispatch_exhausted_at=exhausted_at,
            now=facts.deadline,
        )
    assert session.scalar.await_count == 1
    session.execute.assert_not_awaited()


async def test_redrive_rechecks_deadline_after_waiting_for_parent_lock():
    from eneo.flows.domain.flow_run_recovery_policy import (
        FlowRunAbandonmentDeadlineExceeded,
    )
    from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository

    facts = _facts("exhausted_dispatch")
    exhausted_at = datetime(2026, 8, 23, tzinfo=timezone.utc)
    row = SimpleNamespace(
        status="queued",
        dispatch_pending_since=facts.anchor_at,
        dispatch_exhausted_at=exhausted_at,
        dispatched_at=facts.anchor_at,
        dispatch_last_error=None,
    )
    with freeze_time("2026-09-20T23:59:59Z") as clock:
        requested_at = datetime.now(timezone.utc)

        async def lock_then_cross_deadline(statement):
            if not statement.is_select:
                pytest.fail(
                    "An epoch past its deadline was rearmed after the lock wait"
                )
            clock.tick(2)
            return row

        session = AsyncMock()
        session.scalar.side_effect = lock_then_cross_deadline
        with pytest.raises(FlowRunAbandonmentDeadlineExceeded):
            await FlowRunRepository(
                session=session
            ).rearm_exhausted_accepted_dispatch_for_redrive(
                run_id=uuid4(),
                tenant_id=uuid4(),
                expected_revision=2,
                expected_dispatch_exhausted_at=exhausted_at,
                now=requested_at,
            )
