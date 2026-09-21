from __future__ import annotations

import json

import pytest
import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.flows.domain.flow_run_recovery_policy import FlowRunRecoveryKind
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from tests.integration.flows import test_flow_run_abandonment
from tests.integration.flows.test_flow_run_listing_and_evidence_measurement import (
    _capture_queries,
    _decode_explain,
)
from tests.integration.flows.test_flow_run_repository import (
    _plan_nodes,
    _scan_rows_examined,
)

pytestmark = pytest.mark.integration
approved_wait = test_flow_run_abandonment.approved_wait

_MIGRATION_INDEXES = {
    "ix_flow_runs_awaiting_review_created",
    "ix_flow_runs_exhausted_dispatch_wait",
    "ix_flow_review_approved_wait",
}


async def test_recovery_discovery_plans_bound_parent_reads(approved_wait, tmp_path):
    run, checkpoint, _ = approved_wait
    backlog = 20_000
    page_size = 25
    async with sessionmanager.session() as session, session.begin():
        parameters = {
            "tenant_id": run.tenant_id,
            "flow_id": run.flow_id,
            "user_id": run.principal_user_id,
            "step_id": checkpoint.step_id,
            "source_run_id": run.id,
            "backlog": backlog,
        }
        await session.execute(
            sa.text("""
                INSERT INTO flow_runs (
                    tenant_id, flow_id, flow_version, principal_user_id, status,
                    created_at, dispatch_pending_since, dispatch_exhausted_at,
                    execution_heartbeat_at
                )
                SELECT :tenant_id, :flow_id, 1, :user_id,
                    CASE kind WHEN 'review' THEN 'awaiting_review'
                        WHEN 'running' THEN 'running' ELSE 'queued' END,
                    now() - interval '60 days' + n * interval '1 second',
                    CASE WHEN kind = 'exhausted' THEN now() - interval '35 days'
                        WHEN kind = 'queued' THEN now() END,
                    CASE WHEN kind = 'exhausted' THEN now() - interval '34 days' END,
                    CASE WHEN kind = 'running' THEN now() - interval '10 minutes' END
                FROM (VALUES ('review'), ('queued'), ('exhausted'), ('running')) kinds(kind)
                CROSS JOIN LATERAL generate_series(
                    1, CASE WHEN kind IN ('review', 'queued') THEN :backlog ELSE 200 END
                ) series(n)
            """),
            parameters,
        )
        await session.execute(
            sa.text("""
                INSERT INTO flow_step_attempts (
                    flow_run_id, flow_id, tenant_id, step_id, step_order,
                    attempt_no, status, started_at, finished_at
                )
                SELECT id, flow_id, tenant_id, :step_id, 1, 1, 'completed', now(), now()
                FROM flow_runs WHERE status = 'awaiting_review' AND id <> :source_run_id
            """),
            parameters,
        )
        await session.execute(
            sa.text("""
                INSERT INTO flow_run_review_checkpoints (
                    flow_run_id, flow_id, tenant_id, step_id, step_order, attempt_no,
                    review_mode, output_type, requester_principal_type,
                    requester_user_id, expires_at
                )
                SELECT id, flow_id, tenant_id, :step_id, 1, 1,
                    'view', 'json', 'user', principal_user_id, now() + interval '14 days'
                FROM flow_runs WHERE status = 'awaiting_review' AND id <> :source_run_id
            """),
            parameters,
        )
        assert (
            await session.scalar(sa.text("SELECT count(*) FROM flow_runs"))
            == 2 * backlog + 401
        )
        indexes = set(
            (
                await session.scalars(
                    sa.text(
                        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
                    )
                )
            ).all()
        )
        assert _MIGRATION_INDEXES <= indexes

        # ANALYZE changes shared planner statistics even when row cleanup truncates tables.
        savepoint = await session.begin_nested()
        try:
            connection = await session.connection()
            for table in (
                "flow_runs",
                "flow_run_review_checkpoints",
                "flow_run_webhook_deliveries",
            ):
                await connection.exec_driver_sql(f"ANALYZE {table}")
            assert await session.scalar(sa.text("SHOW enable_seqscan")) == "on"
            repo = FlowRunRepository(session=session)
            bind = session.sync_session.bind
            assert bind is not None
            with _capture_queries(bind) as boundary_queries:
                boundary = await repo.recovery_sweep_boundary()
            assert boundary is not None
            with _capture_queries(bind) as first_queries:
                first = await repo.list_recovery_candidates(
                    limit=page_size, through=boundary
                )
            with _capture_queries(bind) as resumed_queries:
                resumed = await repo.list_recovery_candidates(
                    limit=page_size, after=first[-1].cursor, through=boundary
                )
            assert len(boundary_queries) == 1
            assert len(first_queries) == len(resumed_queries) == 2
            assert len(first) == len(resumed) == page_size
            assert first[-1].cursor < resumed[0].cursor
            assert all(
                candidate.kind == FlowRunRecoveryKind.REVIEW_CHECKPOINT_INSPECTION
                for candidate in [*first, *resumed]
            )
            plans = {}
            for name, query in (
                ("boundary", boundary_queries[0]),
                ("first_page", first_queries[0]),
                ("first_checkpoints", first_queries[1]),
                ("resumed_page", resumed_queries[0]),
                ("resumed_checkpoints", resumed_queries[1]),
            ):
                explained = await connection.exec_driver_sql(
                    f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query.sql}",
                    query.parameters,
                )
                plans[name] = _decode_explain(explained.scalar_one())
            report = tmp_path / "recovery-discovery-plans.json"
            report.write_text(json.dumps(plans, indent=2))
            print(f"Discovery plans: {report}")

            for name, document in plans.items():
                nodes = list(_plan_nodes(document["Plan"]))
                parent_scans = [
                    node for node in nodes if node.get("Relation Name") == "flow_runs"
                ]
                assert parent_scans, (name, document)
                assert all(node["Node Type"] != "Seq Scan" for node in parent_scans), (
                    name,
                    document,
                )
                index_names = {
                    node["Index Name"]
                    for node in nodes
                    if node["Node Type"]
                    in ("Index Scan", "Index Only Scan", "Bitmap Index Scan")
                }
                assert index_names & _MIGRATION_INDEXES, (name, document)
                if "checkpoints" not in name:
                    assert {
                        "ix_flow_runs_awaiting_review_created",
                        "ix_flow_runs_exhausted_dispatch_wait",
                    } <= index_names, (name, document)
                else:
                    assert "ix_flow_runs_awaiting_review_created" in index_names, (
                        name,
                        document,
                    )
                examined = sum(_scan_rows_examined(node) for node in parent_scans)
                bound = (
                    3
                    if name == "boundary"
                    else page_size
                    if "checkpoints" in name
                    else page_size + 2
                )
                assert examined <= bound, (name, examined, bound, document)
                for node in nodes:
                    if "Index Name" in node:
                        assert _scan_rows_examined(node) <= bound, (name, node)
                print(
                    f"{name}: parent rows examined={examined}, bound={bound}, indexes={sorted(index_names)}"
                )
        finally:
            await savepoint.rollback()
