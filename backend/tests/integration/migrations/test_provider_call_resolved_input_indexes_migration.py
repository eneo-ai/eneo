"""Migration proofs for provider-call resolved-input links."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple
from uuid import UUID

import psycopg2
import pytest
from psycopg2.extensions import connection as PsycopgConnection

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import current_revisions
from tests.integration.migrations.test_flow_provider_calls_migration import (
    _clear_seeded_rows,
    _insert_completed_attempt,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "202607271530_provider_call_v2"
MIGRATION_REVISION = "202607271700_call_input_indexes"


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


def _insert_provider_call(
    conn: PsycopgConnection,
    *,
    attempt_id: UUID,
    resolved_input_edge_indexes: list[int | None] | None = None,
) -> None:
    columns = ""
    value = ""
    parameters: tuple[object, ...] = (attempt_id, "a" * 64)
    if resolved_input_edge_indexes is not None:
        columns = ", resolved_input_edge_indexes"
        value = ", %s"
        parameters += (resolved_input_edge_indexes,)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO flow_provider_calls (
                flow_step_attempt_id, ordinal, status, request_schema_version,
                provider_request_hash, requested_model, response_format,
                requested_capabilities, call_reason, requested_at{columns}
            )
            VALUES (
                %s, 1, 'started', 2, %s, 'openai/gpt-5-mini', 'none',
                '{{}}', 'initial', now(){value}
            )
            """,
            parameters,
        )


def _insert_resolved_inputs(
    conn: PsycopgConnection,
    *,
    attempt_id: UUID,
    edge_count: int,
) -> None:
    edges = [
        {
            "binding_ref": f"input-{index}",
            "source": {
                "kind": "flow_input",
                "selector": {"kind": "json_path", "path": ["question"]},
            },
            "selection": {
                "encoding": "utf8",
                "sha256": "a" * 64,
                "byte_size": 1,
            },
        }
        for index in range(edge_count)
    ]
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO flow_step_attempt_resolved_inputs (
                flow_step_attempt_id, resolved_input_edges_jsonb
            ) VALUES (%s, %s::jsonb)
            """,
            (attempt_id, json.dumps({"schema_version": 1, "edges": edges})),
        )


def test_upgrade_removes_unlinkable_rows_and_requires_bounded_indexes(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    _insert_provider_call(migration_db.conn, attempt_id=attempt_id)

    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    assert current_revisions(migration_db.conn) == {MIGRATION_REVISION}
    with migration_db.conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM flow_provider_calls")
        assert cur.fetchone() == (0,)
        cur.execute(
            """
            SELECT is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'flow_provider_calls'
              AND column_name = 'resolved_input_edge_indexes'
            """
        )
        assert cur.fetchone() == ("NO", None)

    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        _insert_provider_call(
            migration_db.conn,
            attempt_id=attempt_id,
            resolved_input_edge_indexes=[0, 2],
        )
    _insert_resolved_inputs(migration_db.conn, attempt_id=attempt_id, edge_count=3)
    _insert_provider_call(
        migration_db.conn,
        attempt_id=attempt_id,
        resolved_input_edge_indexes=[0, 2],
    )
    with migration_db.conn.cursor() as cur:
        cur.execute(
            "SELECT resolved_input_edge_indexes FROM flow_provider_calls "
            "WHERE flow_step_attempt_id = %s",
            (attempt_id,),
        )
        assert cur.fetchone() == ([0, 2],)
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute(
                "DELETE FROM flow_step_attempt_resolved_inputs "
                "WHERE flow_step_attempt_id = %s",
                (attempt_id,),
            )

    for invalid_indexes in ([-1], [2048], [None], [[0, 1]]):
        with pytest.raises(psycopg2.errors.CheckViolation) as exc_info:
            with migration_db.conn.cursor() as cur:
                cur.execute(
                    "UPDATE flow_provider_calls "
                    "SET resolved_input_edge_indexes = %s "
                    "WHERE flow_step_attempt_id = %s",
                    (invalid_indexes, attempt_id),
                )
        assert "ck_flow_provider_calls_resolved_input_indexes" in str(exc_info.value)

    with migration_db.conn.cursor() as cur:
        cur.execute(
            "DELETE FROM flow_step_attempts WHERE id = %s",
            (attempt_id,),
        )
        cur.execute(
            "SELECT count(*) FROM flow_provider_calls WHERE flow_step_attempt_id = %s",
            (attempt_id,),
        )
        assert cur.fetchone() == (0,)
        cur.execute(
            "SELECT count(*) FROM flow_step_attempt_resolved_inputs "
            "WHERE flow_step_attempt_id = %s",
            (attempt_id,),
        )
        assert cur.fetchone() == (0,)


def test_downgrade_refuses_to_discard_links_and_removes_empty_schema(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)
    _insert_resolved_inputs(migration_db.conn, attempt_id=attempt_id, edge_count=0)
    _insert_provider_call(
        migration_db.conn,
        attempt_id=attempt_id,
        resolved_input_edge_indexes=[],
    )

    with pytest.raises(RuntimeError, match="resolved-input links"):
        command.downgrade(migration_db.cfg, PRIOR_REVISION)
    assert current_revisions(migration_db.conn) == {MIGRATION_REVISION}

    with migration_db.conn.cursor() as cur:
        cur.execute("DELETE FROM flow_provider_calls")
    command.downgrade(migration_db.cfg, PRIOR_REVISION)

    assert current_revisions(migration_db.conn) == {PRIOR_REVISION}
    with migration_db.conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)
            FROM information_schema.columns
            WHERE table_name = 'flow_provider_calls'
              AND column_name = 'resolved_input_edge_indexes'
            """
        )
        assert cur.fetchone() == (0,)
