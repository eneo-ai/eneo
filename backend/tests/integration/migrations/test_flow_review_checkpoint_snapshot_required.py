"""Migration tests for requiring Flow review checkpoint step snapshots.

Run explicitly:
    pytest -m migration_isolation tests/integration/migrations/test_flow_review_checkpoint_snapshot_required.py -q
"""

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extras import Json

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import current_revisions

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]


PRIOR_REVISION = "20260526_flow_user_mirror_drop"
MIGRATION_REVISION = "20260527_review_ckpt_snapshot"
_CHECKPOINT_STEP_LABEL = "Review checkpoint snapshot migration test"


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
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM flow_run_review_checkpoints WHERE step_label = %s",
            (_CHECKPOINT_STEP_LABEL,),
        )


def _column_nullable(conn, table_name: str, column_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_name = %s
              AND column_name = %s
            """,
            (table_name, column_name),
        )
        row = cur.fetchone()
    assert row is not None
    return row[0] == "YES"


def _check_constraint_definition(
    conn,
    *,
    table_name: str,
    constraint_name: str,
) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg_get_constraintdef(constraint_row.oid)
            FROM pg_constraint constraint_row
            JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
            WHERE table_row.relname = %s
              AND constraint_row.conname = %s
            """,
            (table_name, constraint_name),
        )
        row = cur.fetchone()
    assert row is not None
    return row[0]


def _insert_checkpoint_row_with_missing_snapshot(
    conn,
    *,
    review_mode: str | None,
    output_type: str | None,
) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = replica")
            cur.execute(
                """
                INSERT INTO flow_run_review_checkpoints (
                    id,
                    tenant_id,
                    flow_id,
                    flow_run_id,
                    step_id,
                    step_order,
                    attempt_no,
                    state,
                    revision,
                    schema_version,
                    original_payload_json,
                    current_payload_json,
                    step_label,
                    review_mode,
                    output_type,
                    output_contract_json,
                    requester_principal_type
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    1,
                    1,
                    'awaiting_review',
                    1,
                    1,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    NULL,
                    'user'
                )
                """,
                (
                    uuid4(),
                    uuid4(),
                    uuid4(),
                    uuid4(),
                    uuid4(),
                    Json({"answer": "draft"}),
                    Json({"answer": "draft"}),
                    _CHECKPOINT_STEP_LABEL,
                    review_mode,
                    output_type,
                ),
            )
    finally:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = DEFAULT")


def test_upgrade_requires_snapshot_columns_and_replaces_nullable_checks(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]

    command.upgrade(cfg, MIGRATION_REVISION)

    assert _column_nullable(conn, "flow_run_review_checkpoints", "review_mode") is False
    assert _column_nullable(conn, "flow_run_review_checkpoints", "output_type") is False
    review_mode_check = _check_constraint_definition(
        conn,
        table_name="flow_run_review_checkpoints",
        constraint_name="ck_flow_run_review_checkpoints_review_mode",
    ).lower()
    output_type_check = _check_constraint_definition(
        conn,
        table_name="flow_run_review_checkpoints",
        constraint_name="ck_flow_run_review_checkpoints_output_type",
    ).lower()
    assert "is null" not in review_mode_check
    assert "is null" not in output_type_check


def test_downgrade_restores_nullable_snapshot_columns_and_checks(migration_db):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]

    command.upgrade(cfg, MIGRATION_REVISION)
    command.downgrade(cfg, PRIOR_REVISION)

    assert _column_nullable(conn, "flow_run_review_checkpoints", "review_mode") is True
    assert _column_nullable(conn, "flow_run_review_checkpoints", "output_type") is True
    review_mode_check = _check_constraint_definition(
        conn,
        table_name="flow_run_review_checkpoints",
        constraint_name="ck_flow_run_review_checkpoints_review_mode",
    ).lower()
    output_type_check = _check_constraint_definition(
        conn,
        table_name="flow_run_review_checkpoints",
        constraint_name="ck_flow_run_review_checkpoints_output_type",
    ).lower()
    assert "is null" in review_mode_check
    assert "is null" in output_type_check


@pytest.mark.parametrize(
    ("review_mode", "output_type"),
    [
        (None, "json"),
        ("edit", None),
    ],
)
def test_upgrade_aborts_when_checkpoint_missing_snapshot_fields(
    migration_db,
    review_mode: str | None,
    output_type: str | None,
):
    conn = migration_db["conn"]
    cfg = migration_db["cfg"]
    _insert_checkpoint_row_with_missing_snapshot(
        conn,
        review_mode=review_mode,
        output_type=output_type,
    )

    with pytest.raises(Exception, match="review checkpoint snapshots"):
        command.upgrade(cfg, MIGRATION_REVISION)

    assert PRIOR_REVISION in current_revisions(conn)
    assert _column_nullable(conn, "flow_run_review_checkpoints", "review_mode") is True
    assert _column_nullable(conn, "flow_run_review_checkpoints", "output_type") is True
