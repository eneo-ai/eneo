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
            """
            INSERT INTO spaces (id, name, tenant_id, user_id)
            VALUES (%s, %s, %s, NULL)
            """,
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
        cur.execute(
            "UPDATE flows SET published_version = 1 WHERE id = %s",
            (flow_id,),
        )
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
            (
                attempt_id,
                run_id,
                flow_id,
                tenant_id,
                step_id,
                Json(provenance_json),
            ),
        )
    return attempt_id


def _table_exists(conn: PsycopgConnection, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (table_name,))
        row = cur.fetchone()
    return row is not None and row[0] is not None


def _provider_call_rows(
    conn: PsycopgConnection,
    *,
    attempt_id: UUID,
) -> list[tuple[object, ...]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                ordinal, status, evidence_source, request_schema_version,
                provider_request_hash, requested_model, provider,
                response_format, call_reason, mapped_execution_mode,
                mapped_item_index, mapped_source_index, mapped_source_id,
                response_model,
                provider_response_id, num_tokens_input, num_tokens_output,
                input_source, output_source, requested_at, finished_at
            FROM flow_provider_calls
            WHERE flow_step_attempt_id = %s
            ORDER BY ordinal
            """,
            (attempt_id,),
        )
        return list(cur.fetchall())


def test_upgrade_aborts_before_casting_inconsistent_legacy_token_usage(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(
        migration_db.conn,
        provenance_json={
            "token_usage": {
                "completed_provider_calls": [
                    {
                        "call_index": 1,
                        "num_tokens_input": None,
                        "num_tokens_output": 8,
                        "input_source": "provider",
                        "output_source": "provider",
                    }
                ]
            }
        },
    )

    with pytest.raises(RuntimeError) as exc:
        command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    message = str(exc.value)
    assert "invalid legacy provider receipts" in message
    assert "invalid_token_usage=1" in message
    assert str(attempt_id) in message


def test_relational_table_rejects_token_counts_that_disagree_with_their_source(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(
        migration_db.conn,
        provenance_json={},
    )
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    with pytest.raises(psycopg2.errors.CheckViolation) as exc:
        with migration_db.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO flow_provider_calls (
                    flow_step_attempt_id, ordinal, status, evidence_source,
                    request_schema_version, provider_request_hash,
                    response_format, call_reason, num_tokens_input,
                    num_tokens_output, input_source, output_source,
                    requested_at, finished_at
                )
                VALUES (
                    %s, 1, 'completed', 'live_observer', 1, %s,
                    'none', 'initial', NULL, NULL, 'provider', 'not_reported',
                    now(), now()
                )
                """,
                (attempt_id, "a" * 64),
            )

    assert "ck_flow_provider_calls_input_usage_shape" in str(exc.value)


def test_relational_table_rejects_completed_rows_without_usage_sources(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(
        migration_db.conn,
        provenance_json={},
    )
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    with pytest.raises(psycopg2.errors.CheckViolation) as exc:
        with migration_db.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO flow_provider_calls (
                    flow_step_attempt_id, ordinal, status, evidence_source,
                    call_reason
                )
                VALUES (
                    %s, 1, 'completed', 'legacy_provenance',
                    'legacy_backfill'
                )
                """,
                (attempt_id,),
            )

    assert "ck_flow_provider_calls_lifecycle_shape" in str(exc.value)


def test_relational_table_requires_response_format_for_live_evidence(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(
        migration_db.conn,
        provenance_json={},
    )
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    with pytest.raises(psycopg2.errors.CheckViolation) as exc:
        with migration_db.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO flow_provider_calls (
                    flow_step_attempt_id, ordinal, status, evidence_source,
                    request_schema_version, provider_request_hash, call_reason,
                    num_tokens_input, num_tokens_output, input_source,
                    output_source, requested_at, finished_at
                )
                VALUES (
                    %s, 1, 'completed', 'live_observer', 1, %s, 'initial',
                    5, 3, 'provider', 'provider', now(), now()
                )
                """,
                (attempt_id, "a" * 64),
            )

    assert "ck_flow_provider_calls_evidence_shape" in str(exc.value)


def test_upgrade_aborts_when_legacy_call_ordinals_are_not_sequential(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(
        migration_db.conn,
        provenance_json={
            "token_usage": {
                "completed_provider_calls": [
                    {
                        "call_index": 2,
                        "num_tokens_input": 5,
                        "num_tokens_output": 8,
                        "input_source": "provider",
                        "output_source": "provider",
                    }
                ]
            }
        },
    )

    with pytest.raises(RuntimeError) as exc:
        command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    message = str(exc.value)
    assert "invalid_ordinals=1" in message
    assert str(attempt_id) in message


def test_upgrade_reports_unrepresentable_legacy_mapping_before_backfill_casts(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(
        migration_db.conn,
        provenance_json={
            "token_usage": {
                "completed_provider_calls": [
                    {
                        "call_index": 1,
                        "num_tokens_input": 5,
                        "num_tokens_output": 8,
                        "input_source": "provider",
                        "output_source": "provider",
                        "mapped_call": {
                            "execution_mode": "per_item",
                            "item_index": "one",
                            "source_index": None,
                        },
                    }
                ]
            }
        },
    )

    with pytest.raises(RuntimeError) as exc:
        command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    message = str(exc.value)
    assert "invalid_fields=1" in message
    assert str(attempt_id) in message


def test_upgrade_backfills_legacy_receipts_without_inventing_unknown_usage(
    migration_db: MigrationDb,
) -> None:
    legacy_receipts = [
        {
            "call_index": 1,
            "num_tokens_input": None,
            "num_tokens_output": 0,
            "input_source": "not_reported",
            "output_source": "provider",
            "requested_model": "gpt-5-mini",
            "response_model": "gpt-5-mini-2025-08-07",
            "provider": "openai",
            "provider_response_id": "resp_legacy_1",
            "mapped_call": {
                "execution_mode": "per_item",
                "item_index": 1,
                "source_index": None,
                "source_id": "source-file-1",
            },
        },
        {
            "call_index": 2,
            "num_tokens_input": 7,
            "num_tokens_output": 3,
            "input_source": "estimated",
            "output_source": "provider",
            "mapped_call": {
                "execution_mode": "per_source_reader",
                "item_index": None,
                "source_index": 2,
                "source_id": "source-file-2",
            },
        },
    ]
    provenance_json = {"token_usage": {"completed_provider_calls": legacy_receipts}}
    attempt_id = _insert_completed_attempt(
        migration_db.conn,
        provenance_json=provenance_json,
    )

    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    assert _provider_call_rows(
        migration_db.conn,
        attempt_id=attempt_id,
    ) == [
        (
            1,
            "completed",
            "legacy_provenance",
            None,
            None,
            "gpt-5-mini",
            "openai",
            None,
            "legacy_backfill",
            "per_item",
            1,
            None,
            "source-file-1",
            "gpt-5-mini-2025-08-07",
            "resp_legacy_1",
            None,
            0,
            "not_reported",
            "provider",
            None,
            None,
        ),
        (
            2,
            "completed",
            "legacy_provenance",
            None,
            None,
            None,
            None,
            None,
            "legacy_backfill",
            "per_source",
            None,
            2,
            "source-file-2",
            None,
            None,
            7,
            3,
            "estimated",
            "provider",
            None,
            None,
        ),
    ]

    command.downgrade(migration_db.cfg, PRIOR_REVISION)
    assert not _table_exists(migration_db.conn, "flow_provider_calls")
    with migration_db.conn.cursor() as cur:
        cur.execute(
            """
            SELECT provenance_json #> '{token_usage,completed_provider_calls}'
            FROM flow_step_attempts
            WHERE id = %s
            """,
            (attempt_id,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == legacy_receipts


def test_upgrade_requires_flow_workers_to_be_drained(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(
        migration_db.conn,
        provenance_json={},
    )
    with migration_db.conn.cursor() as cur:
        cur.execute(
            """
            UPDATE flow_step_attempts
            SET status = 'started', finished_at = NULL
            WHERE id = %s
            """,
            (attempt_id,),
        )

    with pytest.raises(RuntimeError) as exc:
        command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    assert "requires drained Flow workers" in str(exc.value)
    assert "found 1 started flow_step_attempts" in str(exc.value)
    assert not _table_exists(migration_db.conn, "flow_provider_calls")
    assert PRIOR_REVISION in current_revisions(migration_db.conn)


def test_downgrade_refuses_to_discard_live_provider_call_evidence(
    migration_db: MigrationDb,
) -> None:
    attempt_id = _insert_completed_attempt(
        migration_db.conn,
        provenance_json={},
    )
    command.upgrade(migration_db.cfg, MIGRATION_REVISION)
    with migration_db.conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO flow_provider_calls (
                flow_step_attempt_id, ordinal, status, evidence_source,
                request_schema_version, provider_request_hash,
                response_format, call_reason, num_tokens_input,
                num_tokens_output, input_source, output_source,
                requested_at, finished_at
            )
            VALUES (
                %s, 1, 'completed', 'live_observer', 1, %s,
                'none', 'initial', 5, 3, 'provider', 'provider', now(), now()
            )
            """,
            (attempt_id, "b" * 64),
        )

    with pytest.raises(RuntimeError) as exc:
        command.downgrade(migration_db.cfg, PRIOR_REVISION)

    assert "would discard live provider lifecycle evidence (1 rows)" in str(exc.value)
    assert _table_exists(migration_db.conn, "flow_provider_calls")
    assert MIGRATION_REVISION in current_revisions(migration_db.conn)
