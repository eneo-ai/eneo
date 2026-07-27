"""Migration proofs for the canonical Flow provider-call request contract.

Run explicitly:
    pytest -m migration_isolation tests/integration/migrations/test_flow_provider_call_v2_migration.py -q
"""

from __future__ import annotations

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

PRIOR_REVISION = "202607271130_resolved_edges"
MIGRATION_REVISION = "202607271530_provider_call_v2"


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


def _insert_started_call(
    conn: PsycopgConnection,
    *,
    attempt_id: UUID,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO flow_provider_calls (
                flow_step_attempt_id, ordinal, status, request_schema_version,
                provider_request_hash, requested_model, response_format,
                requested_capabilities, call_reason, requested_at
            )
            VALUES (
                %s, 1, 'started', 2, %s, 'openai/gpt-5-mini', 'none',
                '{}', 'initial', now()
            )
            """,
            (attempt_id, "a" * 64),
        )


def test_upgrade_converges_an_already_applied_version_one_development_schema(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    with migration_db.conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO flow_provider_calls (
                flow_step_attempt_id, ordinal, status, evidence_source,
                request_schema_version, provider_request_hash, requested_model,
                response_format, requested_capabilities, call_reason, requested_at
            )
            VALUES (
                %s, 1, 'started', 'live_observer',
                1, %s, 'openai/gpt-5-mini', 'none', '{}', 'initial', now()
            )
            """,
            (attempt_id, "a" * 64),
        )

    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    with migration_db.conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM flow_provider_calls")
        assert cur.fetchone() == (0,)
        cur.execute(
            """
            SELECT count(*)
            FROM information_schema.columns
            WHERE table_name = 'flow_provider_calls'
              AND column_name = 'evidence_source'
            """
        )
        assert cur.fetchone() == (0,)


def test_target_schema_requires_complete_version_two_request_identity(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    _insert_started_call(migration_db.conn, attempt_id=attempt_id)
    with migration_db.conn.cursor() as cur:
        cur.execute(
            """
            SELECT request_schema_version, requested_capabilities
            FROM flow_provider_calls
            WHERE flow_step_attempt_id = %s
            """,
            (attempt_id,),
        )
        assert cur.fetchone() == (2, [])
        cur.execute(
            """
            SELECT column_name, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'flow_provider_calls'
              AND column_name IN (
                  'request_schema_version', 'provider_request_hash',
                  'requested_model', 'response_format',
                  'requested_capabilities', 'requested_at'
              )
            ORDER BY column_name
            """
        )
        assert all(is_nullable == "NO" for _, is_nullable in cur.fetchall())

    with pytest.raises(psycopg2.errors.CheckViolation) as exc_info:
        with migration_db.conn.cursor() as cur:
            cur.execute(
                "UPDATE flow_provider_calls SET request_schema_version = 1 "
                "WHERE flow_step_attempt_id = %s",
                (attempt_id,),
            )
    assert "ck_flow_provider_calls_request_identity" in str(exc_info.value)


@pytest.mark.parametrize(
    ("column_name", "constraint_name"),
    [
        ("requested_model", "ck_flow_provider_calls_requested_model_nonempty"),
        ("provider", "ck_flow_provider_calls_provider_nonempty"),
    ],
)
def test_target_schema_rejects_empty_model_identifiers(
    migration_db: MigrationDb,
    column_name: str,
    constraint_name: str,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)
    _insert_started_call(migration_db.conn, attempt_id=attempt_id)

    with pytest.raises(psycopg2.errors.CheckViolation) as exc_info:
        with migration_db.conn.cursor() as cur:
            cur.execute(
                f"UPDATE flow_provider_calls SET {column_name} = '' "
                "WHERE flow_step_attempt_id = %s",
                (attempt_id,),
            )

    assert constraint_name in str(exc_info.value)


def test_downgrade_refuses_version_two_rows_and_is_honest_when_empty(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)
    _insert_started_call(migration_db.conn, attempt_id=attempt_id)

    with pytest.raises(RuntimeError, match="cannot reconstruct superseded"):
        command.downgrade(migration_db.cfg, PRIOR_REVISION)
    assert current_revisions(migration_db.conn) == {MIGRATION_REVISION}

    with migration_db.conn.cursor() as cur:
        cur.execute("DELETE FROM flow_provider_calls")
    command.downgrade(migration_db.cfg, PRIOR_REVISION)

    assert current_revisions(migration_db.conn) == {PRIOR_REVISION}
    with migration_db.conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'flow_provider_calls'
              AND column_name IN (
                  'evidence_source', 'request_schema_version',
                  'provider_request_hash', 'requested_model',
                  'response_format', 'requested_capabilities', 'requested_at'
              )
            """
        )
        columns = {
            column_name: (is_nullable, column_default)
            for column_name, is_nullable, column_default in cur.fetchall()
        }
        assert columns == {
            "evidence_source": ("NO", None),
            "provider_request_hash": ("YES", None),
            "request_schema_version": ("YES", None),
            "requested_at": ("YES", None),
            "requested_capabilities": ("YES", None),
            "requested_model": ("YES", None),
            "response_format": ("YES", None),
        }
        cur.execute(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'flow_provider_calls'::regclass
              AND conname IN (
                  'ck_flow_provider_calls_capabilities_allowed',
                  'ck_flow_provider_calls_capabilities_response_format',
                  'ck_flow_provider_calls_evidence_shape',
                  'ck_flow_provider_calls_evidence_source',
                  'ck_flow_provider_calls_lifecycle_shape',
                  'ck_flow_provider_calls_reason',
                  'ck_flow_provider_calls_request_identity',
                  'ck_flow_provider_calls_response_format'
              )
            """
        )
        assert {name for (name,) in cur.fetchall()} == {
            "ck_flow_provider_calls_capabilities_allowed",
            "ck_flow_provider_calls_capabilities_response_format",
            "ck_flow_provider_calls_evidence_shape",
            "ck_flow_provider_calls_evidence_source",
            "ck_flow_provider_calls_lifecycle_shape",
            "ck_flow_provider_calls_reason",
            "ck_flow_provider_calls_request_identity",
            "ck_flow_provider_calls_response_format",
        }
        cur.execute(
            """
            INSERT INTO flow_provider_calls (
                flow_step_attempt_id, ordinal, status, evidence_source,
                request_schema_version, provider_request_hash, requested_model,
                provider, response_format, requested_capabilities, call_reason,
                input_source, output_source, requested_at, finished_at
            )
            VALUES (
                %s, 1, 'completed', 'legacy_provenance',
                NULL, NULL, NULL, NULL, NULL, NULL, 'legacy_backfill',
                'not_reported', 'not_reported', NULL, NULL
            )
            """,
            (attempt_id,),
        )
