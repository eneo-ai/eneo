from __future__ import annotations

from datetime import datetime, timezone
from typing import cast
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.infrastructure.data_retention_service import (
    DataRetentionService,
)


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


def test_due_flow_run_history_purge_query_keeps_exact_policy_after_anchor_gate() -> (
    None
):
    service = DataRetentionService(cast(AsyncSession, object()))
    now = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)

    compiled = _compile(service._build_due_flow_run_history_purge_query(now=now))

    assert (
        compiled.count("coalesce(flow_runs.finished_at, flow_runs.created_at) <=") == 2
    )
    assert "flow_runs.status IN ('completed', 'failed', 'cancelled')" in compiled
    assert compiled.count("make_interval") >= 2
    assert "LEFT OUTER JOIN flow_classification_retention_policies" in compiled
    assert (
        "flow_classification_retention_policies.security_classification_id = "
        "spaces.security_classification_id" in compiled
    )
    assert "flow_classification_retention_policies.tenant_id = spaces.tenant_id" in (
        compiled
    )
    assert "JOIN tenants ON flow_runs.tenant_id = tenants.id" in compiled
    activation_sql = (
        "least(tenants.flow_run_history_retention_days, "
        "flow_classification_retention_policies.data_retention_days)"
    )
    effective_retention_sql = (
        f"CASE WHEN ({activation_sql} IS NOT NULL) THEN "
        f"least({activation_sql}, spaces.data_retention_days, "
        "flows.data_retention_days) ELSE NULL END"
    )
    assert f"{activation_sql} IS NOT NULL" in compiled
    assert f"make_interval(0, 0, 0, {effective_retention_sql})" in compiled
    assert "coalesce(flows.data_retention_days, spaces.data_retention_days)" not in (
        compiled
    )


@pytest.mark.asyncio
async def test_flow_run_history_purge_batch_orders_by_retention_anchor_then_run_id() -> (
    None
):
    session = _RecordingSession()
    service = DataRetentionService(cast(AsyncSession, session))

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
