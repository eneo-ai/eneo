"""Release B safety contracts on disposable PostgreSQL 13 databases."""

from __future__ import annotations

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from hashlib import sha256
from time import monotonic, sleep
from uuid import uuid4

import psycopg2
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from tests.integration.migrations import test_file_icon_staged_backfill_expand as expand

override_settings_for_session = expand.override_settings_for_session
cleanup_database = expand.cleanup_database
seed_default_models = expand.seed_default_models
encryption_service = expand.encryption_service

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_BRIDGE = "202609071000"
_CONTRACT = "202609081400"
_LEGACY_COLUMNS = {
    ("files", name) for name in ("text", "blob", "checksum", "size", "transcription")
} | {("icons", name) for name in ("blob", "mimetype", "size")}


def _connect(url):
    return psycopg2.connect(url.replace("+psycopg2", ""), connect_timeout=5)


def _legacy_columns(url):
    with _connect(url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name IN ('files', 'icons')"
        )
        return set(cursor) & _LEGACY_COLUMNS


def _inline_reference_facts(url):
    with _connect(url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT refs.owner_kind, refs.owner_id::text, refs.variant, refs.ordinal, "
            "c.id::text, c.state, c.reference_count, c.size_bytes, c.sha256, sha256(p.payload) "
            "FROM (SELECT 'file' AS owner_kind, file_id AS owner_id, variant, ordinal, content_id "
            "FROM file_content_references UNION ALL "
            "SELECT 'icon', icon_id, variant, 0, content_id FROM icon_content_references) refs "
            "JOIN object_contents c ON c.id=refs.content_id "
            "JOIN inline_content_payloads p ON p.content_id=c.id "
            "ORDER BY owner_kind, owner_id, variant, ordinal"
        )
        return [(*row[:-2], bytes(row[-2]), bytes(row[-1])) for row in cursor]


def _adopt_fixture(url):
    """Construct available bridge state using the real database publication fences."""
    with _connect(url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT i.id, i.owner_kind, i.owner_id, i.variant, i.ordinal, i.tenant_id, "
            "CASE WHEN i.owner_kind='icon' THEN icon.blob "
            "WHEN i.variant='extracted_text' THEN convert_to(f.text, 'UTF8') "
            "WHEN i.variant='transcription' THEN convert_to(f.transcription, 'UTF8') "
            "ELSE f.blob END FROM file_icon_backfill_items i "
            "LEFT JOIN files f ON i.owner_kind='file' AND f.id=i.owner_id "
            "LEFT JOIN icons icon ON i.owner_kind='icon' AND icon.id=i.owner_id ORDER BY i.id"
        )
        for item_id, kind, owner_id, variant, ordinal, tenant, raw in cursor.fetchall():
            content_id = str(uuid4())
            payload = bytes(raw)
            digest = sha256(payload).digest()
            cursor.execute(
                "INSERT INTO object_contents (id, tenant_id, storage_kind, state, access_class, "
                "sha256, size_bytes, verified_media_type, idempotency_key, request_fingerprint, available_at) "
                "VALUES (%s, %s, 'postgres_inline', 'available', %s, %s, %s, "
                "'application/octet-stream', %s, %s, now())",
                (
                    content_id,
                    tenant,
                    "public_immutable" if kind == "icon" else "private_resource",
                    digest,
                    len(payload),
                    f"contract-fixture-{item_id}",
                    digest,
                ),
            )
            cursor.execute(
                "INSERT INTO inline_content_payloads (content_id, payload) VALUES (%s, %s)",
                (content_id, payload),
            )
            if kind == "file":
                cursor.execute(
                    "INSERT INTO file_content_references (file_id, variant, ordinal, content_id) "
                    "VALUES (%s, %s, %s, %s)",
                    (owner_id, variant, ordinal, content_id),
                )
            else:
                cursor.execute(
                    "INSERT INTO icon_content_references (icon_id, variant, content_id) "
                    "VALUES (%s, %s, %s)",
                    (owner_id, variant, content_id),
                )
            cursor.execute(
                "UPDATE file_icon_backfill_items SET state='done', content_id=%s, "
                "capacity_admitted=true WHERE id=%s",
                (content_id, item_id),
            )
        cursor.execute(
            "INSERT INTO file_icon_backfill_campaign "
            "(id, target_kind, state, capacity_admitted_bytes) "
            "SELECT %s, 'postgres_inline', 'complete', coalesce(sum(payload_size_estimate), 0) "
            "FROM file_icon_backfill_items",
            (str(uuid4()),),
        )


@pytest.fixture(scope="module")
def contract_postgres() -> Generator[PostgresContainer, None, None]:
    with PostgresContainer(
        image=expand._POSTGRES_13_IMAGE,
        username="contract_test",
        password="contract_test_password",
        dbname="contract_control",
    ) as postgres:
        yield postgres


@pytest.fixture(scope="module")
def adopted_template(contract_postgres):
    control_url = contract_postgres.get_connection_url()
    with closing(_connect(control_url)) as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute("CREATE DATABASE bridge_template")
    url = (
        make_url(control_url)
        .set(database="bridge_template")
        .render_as_string(hide_password=False)
    )
    config = expand._alembic_config(url)
    command.upgrade(config, expand._PREVIOUS_REVISION)
    ids = expand._seed_legacy_owners(url)
    with _connect(url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO files (id, name, text, blob, checksum, size, mimetype, file_type, user_id, tenant_id) "
            "VALUES (%s, 'empty.txt', '', %s, 'empty', 0, 'text/plain', 'text', %s, %s), "
            "(%s, 'absent.txt', NULL, NULL, 'absent', 0, 'text/plain', 'text', %s, %s)",
            (
                str(uuid4()),
                b"",
                ids["user"],
                ids["tenant"],
                str(uuid4()),
                ids["user"],
                ids["tenant"],
            ),
        )
    command.upgrade(config, _BRIDGE)
    _adopt_fixture(url)
    assert all(row[-2] == row[-1] for row in _inline_reference_facts(url))
    return ids


@pytest.fixture
def contract_database(request, contract_postgres, adopted_template):
    name = f"contract_{uuid4().hex}"
    control_url = contract_postgres.get_connection_url()
    with closing(_connect(control_url)) as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            template = (
                " TEMPLATE bridge_template" if getattr(request, "param", True) else ""
            )
            cursor.execute(f"CREATE DATABASE {name}{template}")
    url = make_url(control_url).set(database=name).render_as_string(hide_password=False)
    try:
        yield url, expand._alembic_config(url), adopted_template
    finally:
        with closing(_connect(control_url)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s",
                    (name,),
                )
                cursor.execute(f"DROP DATABASE {name}")


def test_adopted_bridge_removes_legacy_schema_and_preserves_content(contract_database):
    url, config, _ids = contract_database
    before = _inline_reference_facts(url)
    assert len(before) == 9
    command.upgrade(config, _CONTRACT)
    assert _legacy_columns(url) == set()
    assert _inline_reference_facts(url) == before
    with _connect(url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        assert cursor.fetchone() == (_CONTRACT,)
        cursor.execute(
            "SELECT to_regclass('file_icon_backfill_items'), to_regclass('file_icon_backfill_campaign'), "
            "to_regclass('file_icon_backfill_admission_state'), "
            "to_regprocedure('reject_file_icon_legacy_payload_write()'), "
            "to_regprocedure('cancel_deleted_file_icon_backfill_owner()')"
        )
        assert cursor.fetchone() == (None,) * 5


@pytest.mark.parametrize(
    "corruption",
    [
        "paused",
        "stale_complete",
        "unavailable",
        "missing_coverage",
        "wrong_reference",
        "corrupt_payload",
    ],
)
def test_contraction_refuses_unsafe_bridge_and_preserves_legacy(
    contract_database, corruption
):
    url, config, ids = contract_database
    with _connect(url) as connection, connection.cursor() as cursor:
        if corruption == "paused":
            cursor.execute("UPDATE file_icon_backfill_admission_state SET paused=true")
        elif corruption == "stale_complete":
            cursor.execute(
                "UPDATE file_icon_backfill_items SET state='ready', content_id=NULL WHERE owner_id=%s",
                (ids["image"],),
            )
        elif corruption == "unavailable":
            cursor.execute(
                "UPDATE object_contents SET state='failed', failure_code='backend_missing' "
                "WHERE id=(SELECT content_id FROM file_content_references WHERE file_id=%s)",
                (ids["image"],),
            )
        elif corruption in {"missing_coverage", "wrong_reference"}:
            cursor.execute(
                "DELETE FROM file_content_references WHERE file_id=%s", (ids["image"],)
            )
            if corruption == "missing_coverage":
                cursor.execute(
                    "DELETE FROM file_icon_backfill_items WHERE owner_id=%s",
                    (ids["image"],),
                )
            else:
                cursor.execute(
                    "INSERT INTO file_content_references (file_id, variant, ordinal, content_id) "
                    "SELECT %s, 'legacy_image', 0, content_id FROM file_content_references "
                    "WHERE file_id=%s AND variant='extracted_text'",
                    (ids["image"], ids["text"]),
                )
        else:
            # Simulate byte corruption that bypassed the normal immutable writer.
            cursor.execute(
                "ALTER TABLE inline_content_payloads DISABLE TRIGGER inline_content_payloads_identity_fence"
            )
            cursor.execute(
                "UPDATE inline_content_payloads SET payload=%s WHERE content_id="
                "(SELECT content_id FROM file_content_references WHERE file_id=%s)",
                (b"LEGACY IMAGE", ids["image"]),
            )
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute(
                "ALTER TABLE inline_content_payloads ENABLE TRIGGER inline_content_payloads_identity_fence"
            )
    with pytest.raises(RuntimeError, match="File/Icon contraction refused"):
        command.upgrade(config, _CONTRACT)
    assert _legacy_columns(url) == _LEGACY_COLUMNS
    with _connect(url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT blob FROM files WHERE id=%s", (ids["image"],))
        assert bytes(cursor.fetchone()[0]) == b"legacy image"
        cursor.execute("SELECT version_num FROM alembic_version")
        assert cursor.fetchone() == (_BRIDGE,)


@pytest.mark.parametrize("contract_database", [False], indirect=True)
def test_fresh_install_runs_the_complete_historical_chain(contract_database):
    url, config, _ids = contract_database
    command.upgrade(config, "head")
    assert _legacy_columns(url) == set()
    assert _inline_reference_facts(url) == []


@pytest.mark.parametrize("contract_database", [False], indirect=True)
def test_direct_skip_preserves_sources_and_can_continue_through_bridge(
    contract_database,
):
    url, config, _ids = contract_database
    command.upgrade(config, expand._PREVIOUS_REVISION)
    ids = expand._seed_legacy_owners(url)
    with pytest.raises(RuntimeError, match="File/Icon contraction refused"):
        command.upgrade(config, _CONTRACT)
    assert _legacy_columns(url) == _LEGACY_COLUMNS
    with _connect(url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT blob FROM files WHERE id=%s", (ids["image"],))
        assert bytes(cursor.fetchone()[0]) == b"legacy image"
    command.upgrade(config, _BRIDGE)
    _adopt_fixture(url)
    before = _inline_reference_facts(url)
    command.upgrade(config, _CONTRACT)
    assert _inline_reference_facts(url) == before
    assert _legacy_columns(url) == set()


def test_verified_existing_reference_and_deleted_owner_are_supported(contract_database):
    url, config, ids = contract_database
    with _connect(url) as connection, connection.cursor() as cursor:
        # The original inventory excludes keys that already have a reference.
        cursor.execute(
            "DELETE FROM file_icon_backfill_items WHERE owner_id=%s", (ids["image"],)
        )
        cursor.execute("DELETE FROM files WHERE id=%s", (ids["text"],))
    before = _inline_reference_facts(url)
    command.upgrade(config, _CONTRACT)
    assert _inline_reference_facts(url) == before
    assert _legacy_columns(url) == set()


def test_identical_bytes_cannot_replace_the_exact_adopted_reference(contract_database):
    url, config, ids = contract_database
    replacement = str(uuid4())
    with _connect(url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO object_contents (id, tenant_id, storage_kind, state, access_class, "
            "sha256, size_bytes, verified_media_type, idempotency_key, request_fingerprint, available_at) "
            "SELECT %s, tenant_id, storage_kind, state, access_class, sha256, size_bytes, "
            "verified_media_type, %s, request_fingerprint, available_at FROM object_contents "
            "WHERE id=(SELECT content_id FROM file_content_references WHERE file_id=%s)",
            (replacement, replacement, ids["image"]),
        )
        cursor.execute(
            "INSERT INTO inline_content_payloads (content_id, payload) SELECT %s, payload "
            "FROM inline_content_payloads WHERE content_id="
            "(SELECT content_id FROM file_content_references WHERE file_id=%s)",
            (replacement, ids["image"]),
        )
        cursor.execute(
            "DELETE FROM file_content_references WHERE file_id=%s", (ids["image"],)
        )
        cursor.execute(
            "INSERT INTO file_content_references (file_id, variant, ordinal, content_id) "
            "VALUES (%s, 'legacy_image', 0, %s)",
            (ids["image"], replacement),
        )
    with pytest.raises(RuntimeError, match="ledger key"):
        command.upgrade(config, _CONTRACT)
    assert _legacy_columns(url) == _LEGACY_COLUMNS


@pytest.mark.parametrize("complete_manifest", [True, False])
def test_recorded_object_store_authority_requires_complete_verification_metadata(
    contract_database, complete_manifest
):
    url, config, ids = contract_database
    with _connect(url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT content_id FROM file_content_references WHERE file_id=%s",
            (ids["image"],),
        )
        content_id = cursor.fetchone()[0]
        # The bridge supports ordinary verified moves after inline adoption.
        cursor.execute(
            "INSERT INTO object_content_moves (content_id, target_kind, state, object_key, "
            "verification_chunk_size_bytes, verification_chunk_sha256) "
            "VALUES (%s, 'object_store', 'target_verified', %s, 1024, %s)",
            (content_id, f"contract/{content_id}", sha256(b"legacy image").digest()),
        )
        cursor.execute(
            "DELETE FROM inline_content_payloads WHERE content_id=%s", (content_id,)
        )
        cursor.execute(
            "UPDATE object_contents SET storage_kind='object_store' WHERE id=%s",
            (content_id,),
        )
        cursor.execute(
            "INSERT INTO object_store_objects (content_id, object_key, verification_chunk_size_bytes, "
            "verification_chunk_sha256) VALUES (%s, %s, %s, %s)",
            (
                content_id,
                f"contract/{content_id}",
                1024 if complete_manifest else 1,
                sha256(b"legacy image").digest(),
            ),
        )
        cursor.execute(
            "DELETE FROM object_content_moves WHERE content_id=%s", (content_id,)
        )
    if complete_manifest:
        command.upgrade(config, _CONTRACT)
        assert _legacy_columns(url) == set()
        with _connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT content_id FROM file_content_references WHERE file_id=%s",
                (ids["image"],),
            )
            assert cursor.fetchone() == (content_id,)
    else:
        with pytest.raises(RuntimeError, match="lacks matching available bytes"):
            command.upgrade(config, _CONTRACT)
        assert _legacy_columns(url) == _LEGACY_COLUMNS


def test_unsupported_source_shape_refuses_before_other_removals(contract_database):
    url, config, _ids = contract_database
    with _connect(url) as connection, connection.cursor() as cursor:
        cursor.execute("ALTER TABLE files DROP COLUMN checksum CASCADE")
    before = _legacy_columns(url)
    with pytest.raises(RuntimeError, match="expected bridge legacy columns"):
        command.upgrade(config, _CONTRACT)
    assert _legacy_columns(url) == before


def test_failure_after_first_drop_rolls_back_the_entire_contraction(contract_database):
    url, config, _ids = contract_database
    before = _inline_reference_facts(url)
    with _connect(url) as connection, connection.cursor() as cursor:
        cursor.execute("""
            CREATE FUNCTION abort_contract_ddl() RETURNS event_trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'injected contraction interruption'; END $$;
            CREATE EVENT TRIGGER abort_contract_ddl ON ddl_command_end
            WHEN TAG IN ('ALTER TABLE') EXECUTE FUNCTION abort_contract_ddl();
        """)
    with pytest.raises(DBAPIError, match="injected contraction interruption"):
        command.upgrade(config, _CONTRACT)
    assert _legacy_columns(url) == _LEGACY_COLUMNS
    assert _inline_reference_facts(url) == before
    with _connect(url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_regprocedure('reject_file_icon_legacy_payload_write()') IS NOT NULL"
        )
        assert cursor.fetchone() == (True,)
        cursor.execute("SELECT version_num FROM alembic_version")
        assert cursor.fetchone() == (_BRIDGE,)


def _wait_for_blocked_backend(url, blocker_pid):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        with _connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT pid FROM pg_stat_activity WHERE datname=current_database() "
                "AND %s=ANY(pg_blocking_pids(pid))",
                (blocker_pid,),
            )
            row = cursor.fetchone()
            if row is not None:
                return row[0]
        sleep(0.02)
    raise AssertionError("Expected database writer did not reach the lock fence")


def test_failure_committed_before_fence_is_seen_by_final_verification(
    contract_database,
):
    url, config, ids = contract_database
    with (
        ThreadPoolExecutor(max_workers=1) as executor,
        closing(_connect(url)) as failure,
    ):
        with failure.cursor() as cursor:
            cursor.execute(
                "UPDATE object_contents SET state='failed', failure_code='backend_missing' "
                "WHERE id=(SELECT content_id FROM file_content_references WHERE file_id=%s)",
                (ids["image"],),
            )
            cursor.execute("SELECT pg_backend_pid()")
            blocker_pid = cursor.fetchone()[0]
            migration = executor.submit(command.upgrade, config, _CONTRACT)
            try:
                _wait_for_blocked_backend(url, blocker_pid)
            finally:
                failure.commit()
        with pytest.raises(RuntimeError, match="File/Icon contraction refused"):
            migration.result(timeout=10)
    assert _legacy_columns(url) == _LEGACY_COLUMNS


def _rollback_writer(url, owner_id, operation):
    with closing(_connect(url)) as connection, connection.cursor() as cursor:
        if operation == "delete_owner":
            cursor.execute("DELETE FROM files WHERE id=%s", (owner_id,))
        else:
            cursor.execute(
                "UPDATE object_contents SET state='failed', failure_code='backend_missing' "
                "WHERE id=(SELECT content_id FROM file_content_references WHERE file_id=%s)",
                (owner_id,),
            )
        connection.rollback()


@pytest.mark.parametrize("operation", ["delete_owner", "fail_content"])
def test_final_verification_and_drops_share_the_writer_fence(
    contract_database, operation
):
    url, config, ids = contract_database
    before = _inline_reference_facts(url)
    barrier_key = 793_202_613
    with _connect(url) as connection, connection.cursor() as cursor:
        cursor.execute(f"""
            CREATE FUNCTION block_contract_ddl() RETURNS event_trigger LANGUAGE plpgsql AS $$
            BEGIN PERFORM pg_advisory_xact_lock({barrier_key}); END $$;
            CREATE EVENT TRIGGER block_contract_ddl ON ddl_command_end
            WHEN TAG IN ('ALTER TABLE') EXECUTE FUNCTION block_contract_ddl();
        """)
    with (
        ThreadPoolExecutor(max_workers=2) as executor,
        closing(_connect(url)) as barrier,
    ):
        with barrier.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_lock(%s), pg_backend_pid()", (barrier_key,)
            )
            blocker_pid = cursor.fetchone()[1]
            migration = executor.submit(command.upgrade, config, _CONTRACT)
            writer = None
            try:
                migration_pid = _wait_for_blocked_backend(url, blocker_pid)
                writer = executor.submit(_rollback_writer, url, ids["image"], operation)
                _wait_for_blocked_backend(url, migration_pid)
                assert not writer.done()
            finally:
                cursor.execute("SELECT pg_advisory_unlock(%s)", (barrier_key,))
            migration.result(timeout=10)
            assert writer is not None
            writer.result(timeout=10)
    assert _legacy_columns(url) == set()
    assert _inline_reference_facts(url) == before


def test_downgrade_refuses_to_reconstruct_discarded_sources(contract_database):
    url, config, _ids = contract_database
    command.upgrade(config, _CONTRACT)
    with pytest.raises(RuntimeError, match="cannot recreate those bytes"):
        command.downgrade(config, _BRIDGE)
    assert _legacy_columns(url) == set()


def test_contraction_requires_fresh_snapshots_after_waiting_for_writers(
    contract_database,
):
    url, config, _ids = contract_database
    name = make_url(url).database
    with _connect(url) as connection, connection.cursor() as cursor:
        cursor.execute(
            f"ALTER DATABASE {name} SET default_transaction_isolation TO 'repeatable read'"
        )
    with pytest.raises(RuntimeError, match="READ COMMITTED"):
        command.upgrade(config, _CONTRACT)
    assert _legacy_columns(url) == _LEGACY_COLUMNS


def test_contraction_preserves_the_callers_lock_timeout(contract_database):
    url, config, _ids = contract_database
    migration = ScriptDirectory.from_config(config).get_revision(_CONTRACT).module
    engine = create_engine(url)
    try:
        with engine.connect() as connection, connection.begin() as transaction:
            connection.exec_driver_sql("SET LOCAL lock_timeout = '17s'")
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            assert connection.exec_driver_sql("SHOW lock_timeout").scalar_one() == "17s"
            transaction.rollback()
    finally:
        engine.dispose()
