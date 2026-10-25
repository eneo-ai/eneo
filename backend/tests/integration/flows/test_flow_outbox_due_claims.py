"""Due outbox rows are claimed in the pending-delivery index's own order.

A pending row always carries next_delivery_at (a CHECK says so), so each claim
query is a range scan of its partial index read in key order: the LIMIT stops
the scan after the claimed rows, with no sort of the due backlog.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from eneo.database.tables.flow_tables import (
    FlowRunAuditOutbox,
    FlowRunWebhookDeliveries,
)
from eneo.flows.application.flow_webhook_delivery_policy import (
    FLOW_WEBHOOK_MAX_ATTEMPTS,
)
from eneo.flows.infrastructure.flow_run_audit_outbox_repo import (
    FlowRunAuditOutboxRepository,
)
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRepository,
)
from tests.integration.flows.test_flow_audit_outbox_delivery import (
    _create_flow_and_run,
    _insert_completed_outbox,
)
from tests.integration.flows.test_flow_webhook_outbox_delivery import (
    _create_running_webhook_run,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

_BACKLOG = 3000


def _spy_statements(monkeypatch, session) -> list[sa.Executable]:
    statements: list[sa.Executable] = []
    execute = session.execute

    async def spy(statement, *args, **kwargs):
        statements.append(statement)
        return await execute(statement, *args, **kwargs)

    monkeypatch.setattr(session, "execute", spy)
    return statements


async def _plan(session, statement: sa.Executable) -> str:
    sql = statement.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    return "\n".join((await session.execute(sa.text(f"EXPLAIN {sql}"))).scalars())


def _assert_index_order_plan(plan: str, index: str) -> None:
    assert plan.startswith("Limit"), plan
    assert f"Index Scan using {index}" in plan, plan
    assert "Index Cond: (next_delivery_at <=" in plan, plan
    assert "Sort" not in plan, plan


async def _shape_backlog(session, table: str, ids: list[UUID], now: datetime):
    """Two rows due first (same time, created apart), one due next, one not due."""
    shapes = [
        (now - timedelta(hours=2), now - timedelta(minutes=10)),
        (now - timedelta(hours=2), now - timedelta(minutes=5)),
        (now - timedelta(minutes=90), now - timedelta(minutes=1)),
        (now + timedelta(hours=1), now - timedelta(days=1)),
    ]
    for row_id, (next_at, created_at) in zip(ids, shapes, strict=True):
        await session.execute(
            sa.text(
                f"UPDATE {table} SET next_delivery_at = :next_at, "
                "created_at = :created_at WHERE id = :id"
            ),
            {"next_at": next_at, "created_at": created_at, "id": row_id},
        )
    await session.execute(sa.text(f"ANALYZE {table}"))


async def test_audit_outbox_claims_due_rows_in_index_order(
    monkeypatch,
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        _flow, run = await _create_flow_and_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        repo = FlowRunAuditOutboxRepository(session=session)
        template_id = await _insert_completed_outbox(
            outbox_repo=repo, run=run, actor_id=admin_user.id
        )
        now = datetime.now(timezone.utc)
        ids = (
            (
                await session.execute(
                    sa.text(
                        "INSERT INTO flow_run_audit_outbox (tenant_id, flow_id, "
                        "flow_run_id, run_revision, description, action, entity_type, "
                        "entity_id, actor_type, source, target_status, next_delivery_at) "
                        "SELECT tenant_id, flow_id, flow_run_id, run_revision + g, "
                        "description, action, entity_type, entity_id, actor_type, "
                        "source, target_status, "
                        "CAST(:start AS timestamptz) + g * interval '1 millisecond' "
                        f"FROM flow_run_audit_outbox, generate_series(1, {_BACKLOG}) g "
                        "WHERE id = :template RETURNING id"
                    ),
                    {"start": now - timedelta(hours=1), "template": template_id},
                )
            )
            .scalars()
            .all()
        )
        first, second, third, not_due = ids[:4]
        await _shape_backlog(session, "flow_run_audit_outbox", ids[:4], now)

        statements = _spy_statements(monkeypatch, session)
        claimed = await repo.list_due_delivery_rows(now=now, limit=3)
        [claim_query] = statements
        plan = await _plan(session, claim_query)
        everything_due = await repo.list_due_delivery_rows(now=now, limit=_BACKLOG * 2)

        with pytest.raises(
            IntegrityError, match="ck_flow_run_audit_outbox_pending_next_delivery"
        ):
            async with session.begin_nested():
                await session.execute(
                    sa.update(FlowRunAuditOutbox)
                    .where(FlowRunAuditOutbox.id == first)
                    .values(next_delivery_at=None)
                )

    assert [row.id for row in claimed] == [first, second, third]
    claimed_ids = {row.id for row in everything_due}
    assert not_due not in claimed_ids
    assert set(ids) - {not_due} <= claimed_ids
    _assert_index_order_plan(plan, "ix_flow_run_audit_outbox_pending_delivery")


async def test_webhook_deliveries_claim_due_rows_in_index_order(
    monkeypatch,
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        _flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        keys = {"run": run.id, "step": step.id}
        # A delivery references its step attempt, so each needs one.
        await session.execute(
            sa.text(
                "INSERT INTO flow_step_attempts (flow_run_id, flow_id, tenant_id, "
                "step_id, step_order, attempt_no, status, started_at) "
                "SELECT flow_run_id, flow_id, tenant_id, step_id, step_order, "
                "attempt_no + g, status, started_at "
                f"FROM flow_step_attempts, generate_series(1, {_BACKLOG}) g "
                "WHERE flow_run_id = :run AND step_id = :step AND attempt_no = 1"
            ),
            keys,
        )
        now = datetime.now(timezone.utc)
        ids = (
            (
                await session.execute(
                    sa.text(
                        "INSERT INTO flow_run_webhook_deliveries (tenant_id, flow_id, "
                        "flow_run_id, step_id, step_order, attempt_no, idempotency_key, "
                        "payload_ref, next_delivery_at) "
                        "SELECT tenant_id, flow_id, flow_run_id, step_id, step_order, "
                        "attempt_no, 'key-' || attempt_no, 'payload', "
                        "CAST(:start AS timestamptz) + attempt_no * interval '1 millisecond' "
                        "FROM flow_step_attempts "
                        "WHERE flow_run_id = :run AND step_id = :step AND attempt_no > 1 "
                        "ORDER BY attempt_no RETURNING id"
                    ),
                    {**keys, "start": now - timedelta(hours=1)},
                )
            )
            .scalars()
            .all()
        )
        first, second, third, not_due = ids[:4]
        await _shape_backlog(session, "flow_run_webhook_deliveries", ids[:4], now)

        repo = FlowRunWebhookDeliveryRepository(session=session)
        statements = _spy_statements(monkeypatch, session)

        async def claim(limit: int):
            return await repo.claim_due_delivery_rows(
                now=now,
                limit=limit,
                claim_ttl_seconds=120,
                max_attempts=FLOW_WEBHOOK_MAX_ATTEMPTS,
            )

        claimed = await claim(3)
        claim_query = statements[0]
        plan = await _plan(session, claim_query)
        # The first claim still holds its rows: they are not due again.
        everything_due = await claim(_BACKLOG * 2)

        with pytest.raises(
            IntegrityError, match="ck_flow_run_webhook_deliveries_pending_next_delivery"
        ):
            async with session.begin_nested():
                await session.execute(
                    sa.update(FlowRunWebhookDeliveries)
                    .where(FlowRunWebhookDeliveries.id == first)
                    .values(next_delivery_at=None)
                )

    assert [row.id for row in claimed] == [first, second, third]
    claimed_ids = {row.id for row in everything_due}
    assert not_due not in claimed_ids
    assert set(ids) - {first, second, third, not_due} <= claimed_ids
    assert not claimed_ids & {first, second, third}
    _assert_index_order_plan(plan, "ix_flow_run_webhook_deliveries_pending_delivery")
