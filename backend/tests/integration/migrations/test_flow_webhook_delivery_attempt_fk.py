"""Migration tests for Flow webhook delivery attempt ownership.

Run explicitly:
    pytest -m migration_isolation tests/integration/migrations/test_flow_webhook_delivery_attempt_fk.py -q
"""

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "20260605_review_ckpt_attempt_fk"
MIGRATION_REVISION = "20260605_webhook_attempt_fk"
CONSTRAINT_NAME = "fk_flow_run_webhook_deliveries_step_attempt"
PAYLOAD_REF = "flow_run:webhook-delivery-attempt-fk-migration-test"


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


@pytest.fixture
def migration_db(test_settings):
    cfg = _alembic_cfg(test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True

    command.upgrade(cfg, "head")
    command.downgrade(cfg, PRIOR_REVISION)
    _clear_seeded_rows(conn)

    try:
        yield {"conn": conn, "cfg": cfg}
    finally:
        _clear_seeded_rows(conn)
        command.upgrade(cfg, "head")
        conn.close()


def _clear_seeded_rows(conn) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = replica")
            cur.execute(
                "DELETE FROM flow_run_webhook_deliveries WHERE payload_ref = %s",
                (PAYLOAD_REF,),
            )
    finally:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = DEFAULT")


def _current_revision(conn) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        row = cur.fetchone()
    return row[0] if row else None


def _constraint_definition(conn, constraint_name: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg_get_constraintdef(constraint_row.oid)
            FROM pg_constraint constraint_row
            JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
            WHERE table_row.relname = 'flow_run_webhook_deliveries'
              AND constraint_row.conname = %s
            """,
            (constraint_name,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _insert_orphan_delivery(
    conn,
    *,
    delivery_id: str,
    flow_run_id: str,
    step_id: str,
    attempt_no: int,
) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = replica")
            cur.execute(
                """
                INSERT INTO flow_run_webhook_deliveries (
                    id,
                    tenant_id,
                    flow_id,
                    flow_run_id,
                    step_id,
                    step_order,
                    attempt_no,
                    idempotency_key,
                    payload_ref
                )
                VALUES (%s, %s, %s, %s, %s, 1, %s, %s, %s)
                """,
                (
                    delivery_id,
                    str(uuid4()),
                    str(uuid4()),
                    flow_run_id,
                    step_id,
                    attempt_no,
                    f"{flow_run_id}:{step_id}:{attempt_no}:webhook",
                    PAYLOAD_REF,
                ),
            )
    finally:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = DEFAULT")


def test_upgrade_aborts_when_delivery_has_no_attempt(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    delivery_id = str(uuid4())
    flow_run_id = str(uuid4())
    step_id = str(uuid4())
    _insert_orphan_delivery(
        conn,
        delivery_id=delivery_id,
        flow_run_id=flow_run_id,
        step_id=step_id,
        attempt_no=7,
    )

    with pytest.raises(RuntimeError) as exc:
        command.upgrade(cfg, MIGRATION_REVISION)

    message = str(exc.value)
    assert CONSTRAINT_NAME in message
    assert "1 flow_run_webhook_deliveries rows" in message
    assert f"id={delivery_id}" in message
    assert f"flow_run_id={flow_run_id}" in message
    assert f"step_id={step_id}" in message
    assert "tenant_id=" in message
    assert "flow_id=" in message
    assert "step_order=1" in message
    assert "attempt_no=7" in message
    assert "delivery_status=pending" in message
    assert "delivery_attempts=0" in message
    assert "created_at=" in message
    assert "Delete or repair orphan webhook deliveries" in message
    assert _current_revision(conn) == PRIOR_REVISION
    assert _constraint_definition(conn, CONSTRAINT_NAME) is None


def test_upgrade_adds_restrict_fk_and_downgrade_drops_it(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]

    command.upgrade(cfg, MIGRATION_REVISION)

    definition = _constraint_definition(conn, CONSTRAINT_NAME)
    assert definition is not None
    assert "FOREIGN KEY (flow_run_id, step_id, attempt_no)" in definition
    assert (
        "REFERENCES flow_step_attempts(flow_run_id, step_id, attempt_no)" in definition
    )
    assert "ON DELETE RESTRICT" in definition

    command.downgrade(cfg, PRIOR_REVISION)

    assert _constraint_definition(conn, CONSTRAINT_NAME) is None
