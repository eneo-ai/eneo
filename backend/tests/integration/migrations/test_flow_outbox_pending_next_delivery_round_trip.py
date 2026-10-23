"""Round trip for 202610231100: a pending outbox row has a next delivery time.

    pytest -m migration_isolation \
        tests/integration/migrations/test_flow_outbox_pending_next_delivery_round_trip.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.errors
import pytest

from alembic import command
from alembic.config import Config
from eneo.database.tables.flow_tables import (
    FlowRunAuditOutbox,
    FlowRunWebhookDeliveries,
)
from tests.integration.migrations.alembic_test_utils import at_revision

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202610231000"
REVISION = "202610231100"
_AUDIT_ROW = (
    "INSERT INTO flow_run_audit_outbox (tenant_id, flow_id, flow_run_id, "
    "description, action, entity_type, entity_id, actor_type, source, "
    "target_status, delivery_status, next_delivery_at, delivered_at, created_at) "
    "VALUES (gen_random_uuid(), gen_random_uuid(), gen_random_uuid(), "
    "'flow_run_completed:executor_completed', 'flow_run_completed', 'flow_run', "
    "gen_random_uuid(), 'system', 'executor_completed', 'completed', "
    "%s, NULL, %s, now() - interval '1 day') RETURNING id"
)
_WEBHOOK_ROW = (
    "INSERT INTO flow_run_webhook_deliveries (tenant_id, flow_id, flow_run_id, "
    "step_id, step_order, attempt_no, idempotency_key, payload_ref, "
    "delivery_status, next_delivery_at, delivered_at, created_at) "
    "VALUES (gen_random_uuid(), gen_random_uuid(), gen_random_uuid(), "
    "gen_random_uuid(), 1, 1, 'key', 'payload', %s, NULL, %s, "
    "now() - interval '1 day') RETURNING id"
)
# Per table: its ORM class, the new CHECK and a row insert (status, delivered_at).
TABLES = {
    "flow_run_audit_outbox": (
        FlowRunAuditOutbox,
        "ck_flow_run_audit_outbox_pending_next_delivery",
        _AUDIT_ROW,
    ),
    "flow_run_webhook_deliveries": (
        FlowRunWebhookDeliveries,
        "ck_flow_run_webhook_deliveries_pending_next_delivery",
        _WEBHOOK_ROW,
    ),
}
CHECK_NAMES = [check for _orm, check, _sql in TABLES.values()]


@pytest.fixture(autouse=True)
def cleanup_database():
    """Keep the schema revision across the cycle within this module."""
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


def _checks(conn) -> dict[str, bool]:
    """The new CHECKs present, by name, and whether PostgreSQL validated each."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT conname, convalidated FROM pg_constraint WHERE conname = ANY(%s)",
            (CHECK_NAMES,),
        )
        return dict(cur.fetchall())


def _store(conn, table: str, status: str, *, delivered: bool) -> str:
    # The rows' runs, flows and tenants are not what is tested: without the
    # foreign-key triggers a row needs none. A CHECK is no trigger.
    with conn.cursor() as cur:
        cur.execute("SET session_replication_role = replica")
        try:
            delivered_at = datetime.now(timezone.utc) if delivered else None
            cur.execute(TABLES[table][2], (status, delivered_at))
            return cur.fetchone()[0]
        finally:
            cur.execute("SET session_replication_role = DEFAULT")


def _store_rows(conn) -> dict[str, tuple[str, str]]:
    """Per table, a pending and a delivered row, both with a NULL next time."""
    return {
        table: (
            _store(conn, table, "pending", delivered=False),
            _store(conn, table, "delivered", delivered=True),
        )
        for table in TABLES
    }


def _next_delivery(conn, table: str, row_id: str) -> tuple[bool, bool]:
    """Whether the row's next delivery time is NULL, and whether it is its created_at."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT next_delivery_at IS NULL, next_delivery_at = created_at "
            f"FROM {table} WHERE id = %s",
            (row_id,),
        )
        is_null, is_created_at = cur.fetchone()
        return is_null, bool(is_created_at)


def test_orm_declares_the_checks():
    for orm, check, _sql in TABLES.values():
        assert check in {constraint.name for constraint in orm.__table__.constraints}


def test_upgrade_repairs_null_pending_rows_and_downgrade_drops_the_checks(
    test_settings,
):
    # Kills the mutants where the upgrade leaves a CHECK absent or not
    # validated, fails on a legacy pending row with no next time, repairs it to
    # anything but its created_at, touches a delivered row, or where the
    # downgrade leaves a CHECK behind.
    cfg = Config(str(Path(__file__).parents[3] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True
    validated = dict.fromkeys(CHECK_NAMES, True)
    try:
        with at_revision(cfg, REVISION):
            try:
                assert _checks(conn) == validated

                command.downgrade(cfg, PRE_REVISION)
                assert _checks(conn) == {}
                rows = _store_rows(conn)

                command.upgrade(cfg, REVISION)
                assert _checks(conn) == validated
                for table, (pending_id, delivered_id) in rows.items():
                    assert _next_delivery(conn, table, pending_id) == (False, True)
                    assert _next_delivery(conn, table, delivered_id) == (True, False)
                    with pytest.raises(
                        psycopg2.errors.CheckViolation, match=TABLES[table][1]
                    ):
                        _store(conn, table, "pending", delivered=False)

                command.downgrade(cfg, PRE_REVISION)
                assert _checks(conn) == {}
                _store_rows(conn)

                command.upgrade(cfg, REVISION)
                assert _checks(conn) == validated
            finally:
                with conn.cursor() as cur:
                    for table in TABLES:
                        cur.execute(f"DELETE FROM {table}")
    finally:
        conn.close()
