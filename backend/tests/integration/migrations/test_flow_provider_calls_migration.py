"""Migration proofs for relational Flow provider-call lifecycle evidence.

Run explicitly:
    pytest -m migration_isolation tests/integration/migrations/test_flow_provider_calls_migration.py -q
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple
from uuid import UUID, uuid4

import psycopg2
import pytest
from psycopg2.extensions import connection as PsycopgConnection
from psycopg2.extras import Json

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import current_revisions

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "202607250930_rerun_input_chain"
MIGRATION_REVISION = "202607261600_provider_calls"
_TENANT_NAME_PREFIX = "flow-provider-calls-migration-"


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


def _clear_seeded_rows(conn: PsycopgConnection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM tenants WHERE name LIKE %s",
            (_TENANT_NAME_PREFIX + "%",),
        )


def _insert_completed_attempt(
    conn: PsycopgConnection,
    *,
    provenance_json: dict[str, object],
) -> UUID:
    tenant_id = uuid4()
    user_id = uuid4()
    space_id = uuid4()
    flow_id = uuid4()
    run_id = uuid4()
    step_id = uuid4()
    attempt_id = uuid4()
    tenant_name = f"{_TENANT_NAME_PREFIX}{tenant_id}"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (
                id, name, display_name, slug, quota_limit, privacy_policy,
                domain, zitadel_org_id, provisioning, security_enabled, state
            )
            VALUES (%s, %s, %s, %s, 100000, NULL, NULL, NULL, false, false, 'active')
            """,
            (tenant_id, tenant_name, tenant_name, tenant_name[:63]),
        )
        cur.execute(
            """
            INSERT INTO users (
                id, username, email, email_verified, salt, password, is_active,
                state, used_tokens, tenant_id, quota_limit
            )
            VALUES (%s, %s, %s, true, NULL, NULL, true, 'active', 0, %s, NULL)
            """,
            (user_id, f"user-{user_id}", f"{user_id}@example.test", tenant_id),
        )
        cur.execute(
            "INSERT INTO spaces (id, name, tenant_id, user_id) VALUES (%s, %s, %s, NULL)",
            (space_id, "Provider-call migration space", tenant_id),
        )
        cur.execute(
            """
            INSERT INTO flows (
                id, name, tenant_id, space_id, created_by_user_id,
                owner_user_id, published_version
            )
            VALUES (%s, %s, %s, %s, %s, %s, NULL)
            """,
            (
                flow_id,
                "Provider-call migration flow",
                tenant_id,
                space_id,
                user_id,
                user_id,
            ),
        )
        cur.execute(
            """
            INSERT INTO flow_versions (
                flow_id, version, tenant_id, definition_checksum, definition_json
            )
            VALUES (%s, 1, %s, %s, %s)
            """,
            (
                flow_id,
                tenant_id,
                "provider-call-migration-checksum",
                Json(
                    {
                        "schema_version": 1,
                        "flow_id": str(flow_id),
                        "name": "Provider-call migration flow",
                        "steps": [
                            {
                                "step_id": str(step_id),
                                "assistant_id": str(uuid4()),
                                "step_order": 1,
                            }
                        ],
                    }
                ),
            ),
        )
        cur.execute("UPDATE flows SET published_version = 1 WHERE id = %s", (flow_id,))
        cur.execute(
            """
            INSERT INTO flow_runs (
                id, flow_id, flow_version, principal_type, principal_user_id,
                principal_service_id, tenant_id, trace_id, status, input_payload_json
            )
            VALUES (%s, %s, 1, 'user', %s, NULL, %s, %s, 'completed', '{}')
            """,
            (run_id, flow_id, user_id, tenant_id, uuid4()),
        )
        cur.execute(
            """
            INSERT INTO flow_step_attempts (
                id, flow_run_id, flow_id, tenant_id, step_id, step_order,
                attempt_no, status, provenance_json, started_at, finished_at
            )
            VALUES (%s, %s, %s, %s, %s, 1, 1, 'completed', %s, now(), now())
            """,
            (attempt_id, run_id, flow_id, tenant_id, step_id, Json(provenance_json)),
        )
    return attempt_id


def _table_exists(conn: PsycopgConnection, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (table_name,))
        row = cur.fetchone()
    return row is not None and row[0] is not None


def _insert_started_provider_call(
    conn: PsycopgConnection,
    *,
    attempt_id: UUID,
    schema_version: int = 2,
    call_reason: str = "initial",
    requested_model: str = "openai/gpt-5-mini",
    provider: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO flow_provider_calls (
                flow_step_attempt_id, ordinal, status, request_schema_version,
                provider_request_hash, requested_model, provider, response_format,
                call_reason, requested_at
            )
            VALUES (%s, 1, 'started', %s, %s, %s, %s, 'none', %s, now())
            """,
            (
                attempt_id,
                schema_version,
                "a" * 64,
                requested_model,
                provider,
                call_reason,
            ),
        )


def test_clean_install_ignores_attempt_json_and_requires_version_two_identity(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(
        migration_db.conn,
        provenance_json={
            "token_usage": {"completed_provider_calls": [{"call_index": 1}]}
        },
    )

    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    with migration_db.conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM flow_provider_calls")
        assert cur.fetchone() == (0,)
        cur.execute(
            """
            SELECT column_name, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'flow_provider_calls'
              AND column_name IN (
                  'evidence_source', 'request_schema_version',
                  'provider_request_hash', 'requested_model',
                  'response_format', 'requested_at'
              )
            ORDER BY column_name
            """
        )
        assert cur.fetchall() == [
            ("provider_request_hash", "NO"),
            ("request_schema_version", "NO"),
            ("requested_at", "NO"),
            ("requested_model", "NO"),
            ("response_format", "NO"),
        ]

    _insert_started_provider_call(migration_db.conn, attempt_id=attempt_id)


@pytest.mark.parametrize(
    ("schema_version", "call_reason", "constraint_name"),
    [
        (1, "initial", "ck_flow_provider_calls_request_identity"),
        (2, "legacy_backfill", "ck_flow_provider_calls_reason"),
    ],
)
def test_clean_install_rejects_superseded_provider_call_contracts(
    migration_db: MigrationDb,
    schema_version: int,
    call_reason: str,
    constraint_name: str,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    with pytest.raises(psycopg2.errors.CheckViolation) as exc_info:
        _insert_started_provider_call(
            migration_db.conn,
            attempt_id=attempt_id,
            schema_version=schema_version,
            call_reason=call_reason,
        )

    assert constraint_name in str(exc_info.value)


@pytest.mark.parametrize(
    ("requested_model", "provider", "constraint_name"),
    [
        ("", None, "ck_flow_provider_calls_requested_model_nonempty"),
        (
            "openai/gpt-5-mini",
            "",
            "ck_flow_provider_calls_provider_nonempty",
        ),
    ],
)
def test_clean_install_rejects_empty_model_identifiers(
    migration_db: MigrationDb,
    requested_model: str,
    provider: str | None,
    constraint_name: str,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    with pytest.raises(psycopg2.errors.CheckViolation) as exc_info:
        _insert_started_provider_call(
            migration_db.conn,
            attempt_id=attempt_id,
            requested_model=requested_model,
            provider=provider,
        )

    assert constraint_name in str(exc_info.value)


def test_migration_does_not_require_flow_workers_to_be_drained(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    with migration_db.conn.cursor() as cur:
        cur.execute(
            "UPDATE flow_step_attempts SET status = 'started', finished_at = NULL WHERE id = %s",
            (attempt_id,),
        )

    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    assert _table_exists(migration_db.conn, "flow_provider_calls")


def test_downgrade_refuses_rows_and_drops_an_empty_table(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(migration_db.conn, provenance_json={})
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)
    _insert_started_provider_call(migration_db.conn, attempt_id=attempt_id)

    with pytest.raises(RuntimeError, match="would discard provider lifecycle evidence"):
        command.downgrade(migration_db.cfg, PRIOR_REVISION)
    assert current_revisions(migration_db.conn) == {MIGRATION_REVISION}

    with migration_db.conn.cursor() as cur:
        cur.execute("DELETE FROM flow_provider_calls")
    command.downgrade(migration_db.cfg, PRIOR_REVISION)

    assert not _table_exists(migration_db.conn, "flow_provider_calls")
