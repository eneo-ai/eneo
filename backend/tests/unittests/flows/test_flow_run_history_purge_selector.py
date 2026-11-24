from __future__ import annotations

from datetime import datetime, timezone
from typing import cast
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.flows.infrastructure.flow_retention_repo import FlowRetentionRepository


class _EmptyScalarResult:
    def all(self) -> list[UUID]:
        return []


class _RecordingSession:
    statement: sa.Select[tuple[UUID]] | None = None

    async def scalars(self, stmt: sa.Select[tuple[UUID]]) -> _EmptyScalarResult:
        self.statement = stmt
        return _EmptyScalarResult()


def _compile(stmt: sa.Select[tuple[UUID]]) -> str:
    return str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_due_flow_run_history_purge_query_reads_the_space_time_as_the_cap() -> None:
    service = FlowRetentionRepository(cast(AsyncSession, object()))
    now = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)

    compiled = _compile(service._build_due_flow_run_history_purge_query(now=now))

    anchor = "coalesce(flow_runs.finished_at, flow_runs.created_at)"
    assert f"{anchor} <= '2026-06-10 12:00:00+00:00' - make_interval" in compiled
    assert f"{anchor} + make_interval(0, 0, 0, least(" in compiled
    assert "flow_runs.status IN ('completed', 'failed', 'cancelled')" in compiled
    assert "spaces.data_retention_days" in compiled
    assert "flows.flow_run_history_retention_days" in compiled
    assert "tenants" not in compiled
    assert "retention_mode" not in compiled


@pytest.mark.asyncio
async def test_flow_run_history_purge_batch_orders_by_retention_anchor_then_run_id() -> (
    None
):
    session = _RecordingSession()
    service = FlowRetentionRepository(cast(AsyncSession, session))

    await service._select_flow_run_history_purge_batch(
        now=datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc),
        limit=5000,
    )

    assert session.statement is not None
    compiled = _compile(session.statement)
    assert (
        "ORDER BY coalesce(flow_runs.finished_at, flow_runs.created_at), "
        "flow_runs.id" in compiled
    )
    assert "flow_run_webhook_deliveries.flow_run_id = flow_runs.id" in compiled
    assert "flow_run_webhook_deliveries.delivery_status = 'pending'" in compiled
    assert "flow_run_webhook_deliveries.claim_token" not in compiled
    assert "flow_run_webhook_deliveries.claimed_at" not in compiled
    assert "flow_run_webhook_deliveries.claim_expires_at" not in compiled
