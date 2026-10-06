"""Round-trip the auto_delete vocabulary (202610051000) and the run fence (202610051010).

After both revisions the policy tables accept auto_delete and long rules, the
receipt and job-run columns match the ORM, and the K4 due index exists, valid,
with its declared shape. Each downgrade refuses while a stored value needs what
it would remove, and runs once that value is gone.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
import sqlalchemy as sa

import eneo.database.tables  # noqa: F401
from alembic import command
from alembic.config import Config
from eneo.database.tables.flow_tables import FlowRuns
from eneo.database.tables.retention_tables import RetentionJobRuns, RetentionReceipts

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

BEFORE = "202610060100"
VOCABULARY = "202610051000"
FENCE = "202610051010"


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


@pytest.fixture
def round_trip_db(test_settings):
    backend_dir = Path(__file__).parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True
    command.upgrade(cfg, FENCE)
    command.downgrade(cfg, FENCE)
    engine = sa.create_engine(test_settings.sync_database_url)
    try:
        yield conn, cfg, engine
    finally:
        command.upgrade(cfg, "head")
        engine.dispose()
        conn.close()


def _scalar(conn, sql: str, *params: object) -> object:
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()[0]


def _execute(conn, sql: str, *params: object) -> None:
    with conn.cursor() as cursor:
        cursor.execute(sql, params)


def _tenant(conn) -> str:
    tenant_id = str(uuid4())
    _execute(
        conn,
        "INSERT INTO tenants (id, name, quota_limit, state) "
        "VALUES (%s, %s, 1000, 'active')",
        tenant_id,
        f"round trip {tenant_id}",
    )
    return tenant_id


def _fenced_run(conn, tenant_id: str) -> str:
    user_id, space_id, flow_id, run_id = (str(uuid4()) for _ in range(4))
    _execute(
        conn,
        "INSERT INTO users (id, tenant_id, email, used_tokens, state) "
        "VALUES (%s, %s, %s, 0, 'active')",
        user_id,
        tenant_id,
        f"{user_id}@example.test",
    )
    _execute(
        conn,
        "INSERT INTO spaces (id, name, tenant_id) VALUES (%s, 'fence', %s)",
        space_id,
        tenant_id,
    )
    _execute(
        conn,
        "INSERT INTO flows (id, name, tenant_id, space_id) "
        "VALUES (%s, 'fence', %s, %s)",
        flow_id,
        tenant_id,
        space_id,
    )
    _execute(
        conn,
        "INSERT INTO flow_versions (flow_id, version, tenant_id, definition_checksum, "
        "definition_json) VALUES (%s, 1, %s, %s, '{}'::jsonb)",
        flow_id,
        tenant_id,
        run_id,
    )
    _execute(
        conn,
        "INSERT INTO flow_runs (id, flow_id, flow_version, tenant_id, principal_type, "
        "principal_user_id, status, finished_at, gallring_receipt_id) "
        "VALUES (%s, %s, 1, %s, 'user', %s, 'completed', now(), gen_random_uuid())",
        run_id,
        flow_id,
        tenant_id,
        user_id,
    )
    return run_id


def test_upgrade_matches_the_orm_and_builds_the_due_index(round_trip_db):
    conn, _, engine = round_trip_db
    inspector = sa.inspect(engine)
    for table in (RetentionJobRuns, RetentionReceipts, FlowRuns):
        reflected = {
            column["name"]: column["nullable"]
            for column in inspector.get_columns(table.__tablename__)
        }
        declared = {column.name: column.nullable for column in table.__table__.columns}
        assert reflected == declared, table.__tablename__

    definition = _scalar(
        conn,
        "SELECT pg_get_indexdef(indexrelid) FROM pg_index "
        "WHERE indexrelid = to_regclass('ix_flow_runs_flow_gallring_due') AND indisvalid",
    )
    assert definition == (
        "CREATE INDEX ix_flow_runs_flow_gallring_due ON public.flow_runs USING btree "
        "(flow_id, COALESCE(finished_at, created_at), id) WHERE (((status)::text = ANY "
        "((ARRAY['completed'::character varying, 'failed'::character varying, "
        "'cancelled'::character varying])::text[])) AND (gallring_receipt_id IS NULL))"
    )


_POLICY = (
    "UPDATE tenants SET flow_run_history_retention_mode = '{}', "
    "flow_run_history_retention_days = {} WHERE id = %s"
)
_SNAPSHOT = (
    "INSERT INTO gallring_job_runs (task, outcome, started_at, heartbeat_at, "
    "finished_at, overdue_observed_at, overdue_count, overdue_complete, "
    "overdue_oldest_due_at) VALUES ('flows.history', 'succeeded', now(), now(), "
    "now(), now(), {}, true, {})"
)


_CHECKS = (
    (_POLICY.format("auto_delete", 40_000), True),
    (_POLICY.format("preserve", 0), False),
    (_POLICY.format("automatic", 30), False),
    (_SNAPSHOT.format(3, "now()"), True),
    (_SNAPSHOT.format(3, "NULL"), False),
    (_SNAPSHOT.format(0, "now()"), False),
)


def test_the_new_checks_hold_after_upgrade(round_trip_db):
    """Mutants days_upper_bound_kept, overdue_check_unpaired: auto_delete and long
    rules are stored, zero days or an unknown mode are not; an overdue snapshot
    has an oldest deadline exactly when it counts."""
    conn, cfg, _ = round_trip_db
    command.downgrade(cfg, BEFORE)
    command.upgrade(cfg, FENCE)
    tenant_id = _tenant(conn)
    for statement, accepted in _CHECKS:
        params = (tenant_id,) if "%s" in statement else ()
        if accepted:
            _execute(conn, statement, *params)
        else:
            with pytest.raises(psycopg2.errors.CheckViolation):
                _execute(conn, statement, *params)
    _execute(conn, "DELETE FROM gallring_job_runs WHERE task = 'flows.history'")
    _execute(conn, "DELETE FROM tenants WHERE id = %s", tenant_id)


def test_downgrades_refuse_while_stored_values_need_them(round_trip_db):
    """Mutant downgrade_unguarded."""
    conn, cfg, _ = round_trip_db
    tenant_id = _tenant(conn)
    run_id = _fenced_run(conn, tenant_id)
    _execute(
        conn,
        "UPDATE tenants SET flow_run_history_retention_mode = 'preserve', "
        "flow_run_history_retention_days = 3000 WHERE id = %s",
        tenant_id,
    )

    with pytest.raises(RuntimeError, match="being deleted"):
        command.downgrade(cfg, VOCABULARY)
    assert _scalar(conn, "SELECT version_num FROM alembic_version") == FENCE

    _execute(conn, "DELETE FROM flow_runs WHERE id = %s", run_id)
    command.downgrade(cfg, VOCABULARY)
    assert _scalar(conn, "SELECT to_regclass('ix_flow_runs_flow_gallring_due')") is None

    with pytest.raises(RuntimeError, match="longer than 2555 days"):
        command.downgrade(cfg, BEFORE)
    assert _scalar(conn, "SELECT version_num FROM alembic_version") == VOCABULARY

    _execute(
        conn,
        "UPDATE tenants SET flow_run_history_retention_days = 2555 WHERE id = %s",
        tenant_id,
    )
    command.downgrade(cfg, BEFORE)
    with pytest.raises(psycopg2.errors.CheckViolation):
        _execute(
            conn,
            "UPDATE tenants SET flow_run_history_retention_mode = 'auto_delete' "
            "WHERE id = %s",
            tenant_id,
        )
    _execute(conn, "DELETE FROM tenants WHERE id = %s", tenant_id)
    command.upgrade(cfg, FENCE)


def test_receipt_reference_survives_until_the_fenced_run_is_gone(round_trip_db):
    """Mutant receipt_fk_missing: pruning cannot erase a fenced run's proof."""
    conn, cfg, _ = round_trip_db
    tenant_id = _tenant(conn)
    run_id = _fenced_run(conn, tenant_id)
    receipt_id = _scalar(
        conn, "SELECT gallring_receipt_id FROM flow_runs WHERE id = %s", run_id
    )
    _execute(
        conn,
        "INSERT INTO gallring_receipts "
        "(id, task, entity_kind, entity_id, category, trigger, tenant_id, "
        "phase, started_at, updated_at, manifest_completed_at) "
        "VALUES (%s, 'flows.history', 'flow_run', %s, 'run_record', 'scheduled', "
        "%s, 'deleting', now(), now(), now())",
        str(receipt_id),
        run_id,
        tenant_id,
    )
    try:
        command.upgrade(cfg, "202610051020")
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            _execute(
                conn, "DELETE FROM gallring_receipts WHERE id = %s", str(receipt_id)
            )
        assert (
            _scalar(
                conn,
                "SELECT convalidated FROM pg_constraint "
                "WHERE conname = 'fk_flow_runs_retention_receipt' "
                "AND conrelid = 'flow_runs'::regclass",
            )
            is True
        )
        assert _scalar(conn, "SHOW lock_timeout") == "0"
        _execute(conn, "DELETE FROM flow_runs WHERE id = %s", run_id)
        _execute(conn, "DELETE FROM gallring_receipts WHERE id = %s", str(receipt_id))
        assert (
            _scalar(
                conn,
                "SELECT count(*) FROM gallring_receipts WHERE id = %s",
                str(receipt_id),
            )
            == 0
        )
    finally:
        _execute(conn, "DELETE FROM tenants WHERE id = %s", tenant_id)
        _execute(conn, "DELETE FROM gallring_receipts WHERE id = %s", str(receipt_id))
