"""Migration proofs for requested capabilities on Flow provider-call evidence.

Run explicitly:
    pytest -m migration_isolation tests/integration/migrations/test_flow_provider_call_capabilities_migration.py -q
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic, sleep
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

PRIOR_REVISION = "202607261600_provider_calls"
MIGRATION_REVISION = "202607270830_call_capabilities"


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
    """Shadow global cleanup while this test controls the schema revision."""
    yield


@pytest.fixture(autouse=True)
def seed_default_models() -> Iterator[None]:
    """Shadow global model seeding while this test controls the schema revision."""
    yield


@pytest.fixture
def migration_db(test_settings) -> Iterator[MigrationDb]:
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
        yield MigrationDb(conn=conn, cfg=cfg)
    finally:
        _clear_seeded_rows(conn)
        command.upgrade(cfg, "head")
        conn.close()


def _insert_live_provider_call(
    conn: PsycopgConnection,
    *,
    attempt_id: UUID,
    ordinal: int,
    response_format: str,
    requested_capabilities: list[str] | list[list[str]] | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO flow_provider_calls (
                flow_step_attempt_id, ordinal, status, evidence_source,
                request_schema_version, provider_request_hash, response_format,
                requested_capabilities, call_reason, num_tokens_input,
                num_tokens_output, input_source, output_source, requested_at,
                finished_at
            )
            VALUES (
                %s, %s, 'completed', 'live_observer', 1, %s, %s, %s,
                'initial', 3, 2, 'provider', 'provider', now(), now()
            )
            """,
            (
                attempt_id,
                ordinal,
                "a" * 64,
                response_format,
                requested_capabilities,
            ),
        )


def test_upgrade_preserves_null_and_accepts_observed_capability_sets(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    _insert_live_provider_call(
        migration_db.conn,
        attempt_id=attempt_id,
        ordinal=1,
        response_format="none",
        requested_capabilities=None,
    )
    _insert_live_provider_call(
        migration_db.conn,
        attempt_id=attempt_id,
        ordinal=2,
        response_format="none",
        requested_capabilities=[],
    )
    _insert_live_provider_call(
        migration_db.conn,
        attempt_id=attempt_id,
        ordinal=3,
        response_format="json_schema",
        requested_capabilities=["reasoning", "structured_output"],
    )

    with migration_db.conn.cursor() as cur:
        cur.execute(
            """
            SELECT requested_capabilities
            FROM flow_provider_calls
            WHERE flow_step_attempt_id = %s
            ORDER BY ordinal
            """,
            (attempt_id,),
        )
        assert cur.fetchall() == [
            (None,),
            ([],),
            (["reasoning", "structured_output"],),
        ]


@pytest.mark.parametrize(
    ("response_format", "requested_capabilities", "constraint_name"),
    [
        ("none", ["unknown"], "ck_flow_provider_calls_capabilities_allowed"),
        (
            "none",
            ["reasoning", "reasoning", "reasoning", "reasoning", "reasoning"],
            "ck_flow_provider_calls_capabilities_allowed",
        ),
        (
            "none",
            ["structured_output"],
            "ck_flow_provider_calls_capabilities_response_format",
        ),
        (
            "json_object",
            [],
            "ck_flow_provider_calls_capabilities_response_format",
        ),
    ],
)
def test_database_rejects_invalid_capability_evidence(
    migration_db: MigrationDb,
    response_format: str,
    requested_capabilities: list[str],
    constraint_name: str,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    with pytest.raises(psycopg2.errors.CheckViolation) as exc_info:
        _insert_live_provider_call(
            migration_db.conn,
            attempt_id=attempt_id,
            ordinal=1,
            response_format=response_format,
            requested_capabilities=requested_capabilities,
        )

    assert constraint_name in str(exc_info.value)


def test_database_accepts_duplicates_because_domain_owns_canonical_order(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    _insert_live_provider_call(
        migration_db.conn,
        attempt_id=attempt_id,
        ordinal=1,
        response_format="none",
        requested_capabilities=["reasoning", "reasoning"],
    )


def test_database_rejects_multidimensional_capability_arrays(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    with pytest.raises(psycopg2.errors.CheckViolation) as exc_info:
        _insert_live_provider_call(
            migration_db.conn,
            attempt_id=attempt_id,
            ordinal=1,
            response_format="none",
            requested_capabilities=[["reasoning"], ["tool_calling"]],
        )

    assert "ck_flow_provider_calls_capabilities_allowed" in str(exc_info.value)


def test_nonnull_capabilities_require_observed_response_format(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    with pytest.raises(psycopg2.errors.CheckViolation) as exc_info:
        with migration_db.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO flow_provider_calls (
                    flow_step_attempt_id, ordinal, status, evidence_source,
                    request_schema_version, provider_request_hash,
                    response_format, requested_capabilities, call_reason,
                    num_tokens_input, num_tokens_output, input_source,
                    output_source, requested_at, finished_at
                )
                VALUES (
                    %s, 1, 'completed', 'legacy_provenance', NULL, NULL,
                    NULL, ARRAY['reasoning']::varchar(32)[], 'legacy_backfill',
                    3, 2, 'provider', 'provider', NULL, NULL
                )
                """,
                (attempt_id,),
            )

    assert "ck_flow_provider_calls_capabilities_response_format" in str(exc_info.value)


def test_downgrade_refuses_to_discard_observed_capabilities(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)
    _insert_live_provider_call(
        migration_db.conn,
        attempt_id=attempt_id,
        ordinal=1,
        response_format="none",
        requested_capabilities=[],
    )

    with pytest.raises(RuntimeError, match="requested capability evidence"):
        command.downgrade(migration_db.cfg, PRIOR_REVISION)

    assert current_revisions(migration_db.conn) == {MIGRATION_REVISION}


def test_downgrade_lock_prevents_a_queued_writer_from_sneaking_through(
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
        _insert_live_provider_call(
            blocker,
            attempt_id=attempt_id,
            ordinal=1,
            response_format="none",
            requested_capabilities=None,
        )
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
                            WHERE relation = 'flow_provider_calls'::regclass
                              AND mode = 'AccessExclusiveLock'
                              AND NOT granted
                        )
                        """
                    )
                    if cur.fetchone() == (True,):
                        break
                sleep(0.02)
            else:
                blocker.rollback()
                downgrade.result(timeout=5)
                pytest.fail("downgrade did not request its table lock")

            queued_writer = executor.submit(
                _insert_live_provider_call,
                writer,
                attempt_id=attempt_id,
                ordinal=2,
                response_format="none",
                requested_capabilities=[],
            )
            blocker.commit()
            downgrade.result(timeout=5)
            with pytest.raises(psycopg2.Error):
                queued_writer.result(timeout=5)
    finally:
        blocker.close()
        writer.close()

    assert current_revisions(migration_db.conn) == {PRIOR_REVISION}


def test_downgrade_succeeds_when_only_unobserved_rows_exist(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)
    _insert_live_provider_call(
        migration_db.conn,
        attempt_id=attempt_id,
        ordinal=1,
        response_format="none",
        requested_capabilities=None,
    )

    command.downgrade(migration_db.cfg, PRIOR_REVISION)

    assert current_revisions(migration_db.conn) == {PRIOR_REVISION}
