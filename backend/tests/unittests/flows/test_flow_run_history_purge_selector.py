from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.flows.infrastructure.flow_retention_repo import FlowRetentionRepository


def _compile(stmt: sa.Select[Any]) -> str:
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


def test_flow_run_history_purge_batch_orders_by_retention_anchor_then_run_id() -> None:
    service = FlowRetentionRepository(cast(AsyncSession, object()))

    compiled = _compile(
        service._build_flow_run_history_purge_batch_query(
            now=datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc),
            limit=5000,
        )
    )
    assert (
        "ORDER BY coalesce(flow_runs.finished_at, flow_runs.created_at), "
        "flow_runs.id" in compiled
    )
    assert "flow_run_webhook_deliveries.flow_run_id = flow_runs.id" in compiled
    assert "flow_run_webhook_deliveries.delivery_status = 'pending'" in compiled
    assert "flow_run_webhook_deliveries.claim_token" not in compiled
    assert "flow_run_webhook_deliveries.claimed_at" not in compiled
    assert "flow_run_webhook_deliveries.claim_expires_at" not in compiled


def test_the_automatic_selection_adds_the_mark_and_the_space_time_now() -> None:
    """Mutants: the automatic removal takes an unmarked run, a run of a space
    whose time was removed, or one of a personal space."""
    service = FlowRetentionRepository(cast(AsyncSession, object()))

    compiled = _compile(
        service._build_automatic_removal_candidates(
            now=datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
        )
    )

    assert "flow_runs.started_under_space_retention IS true" in compiled
    assert "spaces.data_retention_days IS NOT NULL" in compiled
    assert "spaces.user_id IS NULL" in compiled
    assert "ORDER BY" not in compiled
