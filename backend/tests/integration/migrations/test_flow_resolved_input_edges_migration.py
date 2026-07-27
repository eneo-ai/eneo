"""Migration proofs for immutable Flow attempt resolved-input evidence.

Run explicitly:
    pytest -m migration_isolation tests/integration/migrations/test_flow_resolved_input_edges_migration.py -q
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic, sleep
from typing import NamedTuple

import psycopg2
import pytest
from psycopg2.extensions import connection as PsycopgConnection
from psycopg2.extras import Json

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from eneo.database.tables.flow_tables import FlowStepAttemptResolvedInputs
from tests.integration.migrations.alembic_test_utils import current_revisions
from tests.integration.migrations.test_flow_provider_calls_migration import (
    _clear_seeded_rows,
    _insert_completed_attempt,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "202607270830_call_capabilities"
MIGRATION_REVISION = "202607271130_resolved_edges"
REPOSITORY_HEAD = "202607271530_provider_call_v2"
EVIDENCE_TABLE = "flow_step_attempt_resolved_inputs"


class MigrationDb(NamedTuple):
    conn: PsycopgConnection
    cfg: Config


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(autouse=True)
def cleanup_database() -> Iterator[None]:
    yield


@pytest.fixture(autouse=True)
def seed_default_models() -> Iterator[None]:
    yield


@pytest.fixture
def migration_db(test_settings) -> Iterator[MigrationDb]:
    cfg = _alembic_cfg(test_settings.sync_database_url)
    conn = psycopg2.connect(test_settings.sync_database_url)
    conn.autocommit = True

    command.upgrade(cfg, "head")
    command.downgrade(cfg, PRIOR_REVISION)
    _clear_seeded_rows(conn)

    try:
        yield MigrationDb(conn=conn, cfg=cfg)
    finally:
        _clear_seeded_rows(conn)
        command.upgrade(cfg, "head")
        conn.close()


def _set_edges(conn: PsycopgConnection, attempt_id, payload: object) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {EVIDENCE_TABLE} (
                flow_step_attempt_id,
                resolved_input_edges_jsonb
            )
            VALUES (%s, %s)
            ON CONFLICT (flow_step_attempt_id) DO UPDATE
            SET resolved_input_edges_jsonb = EXCLUDED.resolved_input_edges_jsonb
            """,
            (attempt_id, Json(payload)),
        )


def _table_exists(conn: PsycopgConnection, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
        return cur.fetchone()[0] is not None


def _attempts_relfilenode(conn: PsycopgConnection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_relation_filenode('flow_step_attempts'::regclass)")
        return cur.fetchone()[0]


def test_upgrade_preserves_hot_attempt_table_and_legacy_has_no_evidence_row(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    relfilenode_before = _attempts_relfilenode(migration_db.conn)

    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    assert _attempts_relfilenode(migration_db.conn) == relfilenode_before
    assert _table_exists(migration_db.conn, EVIDENCE_TABLE)
    with migration_db.conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM {EVIDENCE_TABLE} WHERE flow_step_attempt_id = %s",
            (attempt_id,),
        )
        assert cur.fetchone() == (0,)


def test_generated_count_distinguishes_absent_empty_and_nonempty(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    with migration_db.conn.cursor() as cur:
        cur.execute(
            f"SELECT resolved_input_edge_count FROM {EVIDENCE_TABLE} "
            "WHERE flow_step_attempt_id = %s",
            (attempt_id,),
        )
        assert cur.fetchone() is None

    _set_edges(migration_db.conn, attempt_id, {"schema_version": 1, "edges": []})
    with migration_db.conn.cursor() as cur:
        cur.execute(
            f"SELECT resolved_input_edge_count FROM {EVIDENCE_TABLE} "
            "WHERE flow_step_attempt_id = %s",
            (attempt_id,),
        )
        assert cur.fetchone() == (0,)

    _set_edges(
        migration_db.conn,
        attempt_id,
        {"schema_version": 1, "edges": [{}, {}, {}]},
    )
    with migration_db.conn.cursor() as cur:
        cur.execute(
            f"SELECT resolved_input_edge_count FROM {EVIDENCE_TABLE} "
            "WHERE flow_step_attempt_id = %s",
            (attempt_id,),
        )
        assert cur.fetchone() == (3,)


def test_parent_attempt_delete_cascades_to_resolved_input_evidence(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)
    _set_edges(migration_db.conn, attempt_id, {"schema_version": 1, "edges": []})

    with migration_db.conn.cursor() as cur:
        cur.execute("DELETE FROM flow_step_attempts WHERE id = %s", (attempt_id,))
        cur.execute(
            f"SELECT count(*) FROM {EVIDENCE_TABLE} WHERE flow_step_attempt_id = %s",
            (attempt_id,),
        )
        assert cur.fetchone() == (0,)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"schema_version": 1},
        {"schema_version": 1, "edges": "not-an-array"},
        {"schema_version": 1, "edges": [None] * 2049},
    ],
)
def test_database_rejects_invalid_top_level_shape_or_count(
    migration_db: MigrationDb,
    payload: object,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    with pytest.raises(psycopg2.errors.CheckViolation) as exc_info:
        _set_edges(migration_db.conn, attempt_id, payload)

    assert "ck_flow_step_attempt_resolved_input_count" in str(exc_info.value)


def test_database_count_does_not_own_schema_version(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    for payload in ({"edges": []}, {"schema_version": 999, "edges": []}):
        _set_edges(migration_db.conn, attempt_id, payload)
        with migration_db.conn.cursor() as cur:
            cur.execute(
                f"SELECT resolved_input_edge_count FROM {EVIDENCE_TABLE} "
                "WHERE flow_step_attempt_id = %s",
                (attempt_id,),
            )
            assert cur.fetchone() == (0,)


def test_database_and_orm_generated_count_contract_match(
    migration_db: MigrationDb,
) -> None:
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)
    orm_column = FlowStepAttemptResolvedInputs.__table__.columns[
        "resolved_input_edge_count"
    ]
    assert orm_column.computed is not None
    orm_expression = " ".join(str(orm_column.computed.sqltext).split()).lower()

    with migration_db.conn.cursor() as cur:
        cur.execute(
            """
            SELECT generation_expression
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name = 'resolved_input_edge_count'
            """,
            (EVIDENCE_TABLE,),
        )
        database_expression = " ".join(cur.fetchone()[0].split()).lower()
        cur.execute(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = %s::regclass
              AND conname = 'ck_flow_step_attempt_resolved_input_count'
            """,
            (EVIDENCE_TABLE,),
        )
        constraint_definition = cur.fetchone()[0]

    for fragment in ("jsonb_typeof", "jsonb_array_length"):
        assert fragment in orm_expression
        assert fragment in database_expression
    assert "schema_version" not in orm_expression
    assert "schema_version" not in database_expression
    assert "else -1" in orm_expression
    assert "else '-1'::integer" in database_expression
    assert "2048" in constraint_definition


def test_downgrade_refuses_to_discard_tracked_empty_aggregate(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)
    _set_edges(migration_db.conn, attempt_id, {"schema_version": 1, "edges": []})

    with pytest.raises(RuntimeError, match="resolved-input evidence"):
        command.downgrade(migration_db.cfg, PRIOR_REVISION)

    assert current_revisions(migration_db.conn) == {MIGRATION_REVISION}


def test_downgrade_serializes_against_a_queued_writer(
    migration_db: MigrationDb,
    test_settings,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)
    blocker = psycopg2.connect(test_settings.sync_database_url)
    writer = psycopg2.connect(test_settings.sync_database_url)
    blocker.autocommit = False
    writer.autocommit = True

    try:
        with blocker.cursor() as cur:
            cur.execute(f"LOCK TABLE {EVIDENCE_TABLE} IN ROW EXCLUSIVE MODE")
        with ThreadPoolExecutor(max_workers=2) as executor:
            downgrade = executor.submit(
                command.downgrade,
                migration_db.cfg,
                PRIOR_REVISION,
            )
            deadline = monotonic() + 5
            while monotonic() < deadline:
                with migration_db.conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM pg_locks
                            WHERE relation = %s::regclass
                              AND mode = 'AccessExclusiveLock'
                              AND NOT granted
                        )
                        """,
                        (EVIDENCE_TABLE,),
                    )
                    if cur.fetchone() == (True,):
                        break
                sleep(0.02)
            else:
                blocker.rollback()
                downgrade.result(timeout=5)
                pytest.fail("downgrade did not request its evidence-table lock")

            queued_writer = executor.submit(
                _set_edges,
                writer,
                attempt_id,
                {"schema_version": 1, "edges": []},
            )
            blocker.commit()
            downgrade.result(timeout=5)
            with pytest.raises(psycopg2.Error):
                queued_writer.result(timeout=5)
    finally:
        blocker.close()
        writer.close()

    assert current_revisions(migration_db.conn) == {PRIOR_REVISION}


def test_empty_downgrade_and_reupgrade_keep_one_head(
    migration_db: MigrationDb,
) -> None:
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)
    assert current_revisions(migration_db.conn) == {MIGRATION_REVISION}
    assert set(ScriptDirectory.from_config(migration_db.cfg).get_heads()) == {
        REPOSITORY_HEAD
    }

    command.downgrade(migration_db.cfg, PRIOR_REVISION)
    assert current_revisions(migration_db.conn) == {PRIOR_REVISION}
    assert not _table_exists(migration_db.conn, EVIDENCE_TABLE)

    command.upgrade(migration_db.cfg, MIGRATION_REVISION)
    assert current_revisions(migration_db.conn) == {MIGRATION_REVISION}
    assert _table_exists(migration_db.conn, EVIDENCE_TABLE)
