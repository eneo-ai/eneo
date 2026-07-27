from __future__ import annotations

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from threading import Event
from uuid import uuid4

import psycopg2
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config
from eneo.database.tables.object_content_policy_table import (
    ObjectContentDeploymentPolicy,
)
from eneo.database.tables.object_content_table import ObjectContentMoves

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_POSTGRES_13_IMAGE = (
    "pgvector/pgvector:pg13@"
    "sha256:751a89c96f7c32cb8133472f711c274853378fb5f8b55dd9fa0e9d3f1471bfc3"
)
_PREVIOUS_REVISION = "202607261700"
_MOVE_REVISION = "202607262200"


@pytest.fixture(scope="session", autouse=True)
def override_settings_for_session() -> Generator[None, None, None]:
    yield


@pytest.fixture(autouse=True)
def cleanup_database() -> Generator[None, None, None]:
    yield


@pytest.fixture(autouse=True)
def seed_default_models() -> Generator[None, None, None]:
    yield


def _alembic_config(database_url: str) -> Config:
    backend_dir = Path(__file__).resolve().parents[3]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migration_database() -> Generator[tuple[str, Config], None, None]:
    postgres = PostgresContainer(
        image=_POSTGRES_13_IMAGE,
        username="verified_content_moves",
        password="verified_content_moves_password",
        dbname="verified_content_moves",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)
        command.upgrade(config, _PREVIOUS_REVISION)
        yield database_url.replace("+psycopg2", ""), config


def _seed_inline_content(connection) -> tuple[str, str, bytes]:
    tenant_id = str(uuid4())
    user_id = str(uuid4())
    file_id = str(uuid4())
    content_id = str(uuid4())
    payload = b"fenced content move"
    digest = sha256(payload).digest()
    with connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (%s, %s, 1000000, 'active')
            """,
            (tenant_id, f"verified-content-moves-{uuid4().hex[:8]}"),
        )
        cursor.execute(
            """
            INSERT INTO users (
                id, tenant_id, username, email, used_tokens, state
            )
            VALUES (%s, %s, %s, %s, 0, 'active')
            """,
            (
                user_id,
                tenant_id,
                f"verified-move-{uuid4().hex[:8]}",
                f"verified-move-{uuid4().hex[:12]}@example.test",
            ),
        )
        cursor.execute(
            """
            INSERT INTO files (
                id, name, mimetype, file_type, user_id, tenant_id
            )
            VALUES (%s, 'move.txt', 'text/plain', 'text', %s, %s)
            """,
            (file_id, user_id, tenant_id),
        )
        cursor.execute(
            """
            INSERT INTO object_contents (
                id, tenant_id, storage_kind, state, access_class, sha256,
                size_bytes, declared_media_type, verified_media_type,
                idempotency_key, request_fingerprint, available_at
            )
            VALUES (
                %s, %s, 'postgres_inline', 'available', 'private_resource', %s,
                %s, 'text/plain', 'text/plain', %s, %s, now()
            )
            """,
            (
                content_id,
                tenant_id,
                digest,
                len(payload),
                f"move-{content_id}",
                digest,
            ),
        )
        cursor.execute(
            """
            INSERT INTO inline_content_payloads (content_id, payload)
            VALUES (%s, %s)
            """,
            (content_id, payload),
        )
        cursor.execute(
            """
            INSERT INTO file_content_references (
                file_id, content_id, variant, ordinal
            )
            VALUES (%s, %s, 'original', 0)
            """,
            (file_id, content_id),
        )
    return tenant_id, content_id, payload


def _assert_orm_parity(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        for model in (ObjectContentDeploymentPolicy, ObjectContentMoves):
            database_columns = {
                str(column["name"])
                for column in inspector.get_columns(model.__tablename__)
            }
            orm_columns = {column.name for column in model.__table__.columns}
            assert database_columns == orm_columns, model.__tablename__
    finally:
        engine.dispose()


def test_move_schema_round_trip_preserves_the_existing_authority_fences(
    migration_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, config = migration_database
    connection = psycopg2.connect(database_url)
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE INDEX ix_object_contents_move_candidates
                ON object_contents (storage_kind, created_at, id)
                WHERE state = 'available'
                  AND reference_count > 0
                  AND delete_requested_at IS NULL
                """
            )
            cursor.execute(
                """
                UPDATE pg_index
                SET indisvalid = false
                WHERE indexrelid =
                    'ix_object_contents_move_candidates'::regclass
                """
            )

        _tenant_id, content_id, payload = _seed_inline_content(connection)
        validation_ready = Event()
        allow_validation = Event()
        downgrade_ready = Event()
        allow_downgrade = Event()
        original_execute = Connection.execute

        def pause_at_migration_boundaries(
            self: Connection,
            statement,
            *args,
            **kwargs,
        ):
            if (
                "VALIDATE CONSTRAINT "
                "fk_object_content_audit_events_actor_user_id" in str(statement)
            ):
                validation_ready.set()
                if not allow_validation.wait(timeout=10):
                    raise TimeoutError("audit validation was not released by the test")
            if "LOCK TABLE object_content_moves IN ACCESS EXCLUSIVE MODE" in str(
                statement
            ):
                downgrade_ready.set()
                if not allow_downgrade.wait(timeout=10):
                    raise TimeoutError("downgrade lock was not released by the test")
            return original_execute(self, statement, *args, **kwargs)

        monkeypatch.setattr(Connection, "execute", pause_at_migration_boundaries)
        blocker = psycopg2.connect(database_url)
        probe = psycopg2.connect(database_url)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                upgrade = executor.submit(command.upgrade, config, _MOVE_REVISION)
                try:
                    assert validation_ready.wait(timeout=10)
                    with blocker.cursor() as cursor:
                        cursor.execute("SET lock_timeout = '1s'")
                        cursor.execute(
                            "LOCK TABLE object_content_audit_events "
                            "IN SHARE UPDATE EXCLUSIVE MODE"
                        )
                    allow_validation.set()
                    with probe, probe.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '1s'")
                        cursor.execute(
                            "SELECT count(*) FROM object_content_audit_events"
                        )
                        cursor.execute(
                            """
                            INSERT INTO object_content_audit_events (
                                content_id, event_type
                            )
                            VALUES (%s, 'available')
                            """,
                            (content_id,),
                        )
                finally:
                    allow_validation.set()
                    blocker.rollback()
                upgrade.result(timeout=30)
        finally:
            blocker.close()
            probe.close()

        with connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT indisvalid
                FROM pg_index
                WHERE indexrelid =
                    'ix_object_contents_move_candidates'::regclass
                """
            )
            assert cursor.fetchone() == (True,)

        concurrent_writer = psycopg2.connect(database_url)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                downgrade = executor.submit(
                    command.downgrade,
                    config,
                    _PREVIOUS_REVISION,
                )
                try:
                    assert downgrade_ready.wait(timeout=10)
                    with concurrent_writer, concurrent_writer.cursor() as cursor:
                        cursor.execute(
                            """
                            INSERT INTO object_content_moves (
                                content_id, target_kind, state
                            )
                            VALUES (%s, 'object_store', 'pending')
                            """,
                            (content_id,),
                        )
                finally:
                    allow_downgrade.set()
                with pytest.raises(
                    DBAPIError,
                    match=(
                        "cannot downgrade object-content moves after durable "
                        "evidence exists"
                    ),
                ):
                    downgrade.result(timeout=30)
        finally:
            concurrent_writer.close()

        with connection, connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            assert cursor.fetchone() == (_MOVE_REVISION,)
            cursor.execute("SELECT count(*) FROM object_content_moves")
            assert cursor.fetchone() == (1,)
        command.upgrade(config, _MOVE_REVISION)

        with connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO object_content_audit_events (content_id, event_type)
                VALUES (%s, 'storage_moved')
                """,
                (content_id,),
            )
            cursor.execute(
                """
                DELETE FROM object_content_audit_events
                WHERE content_id = %s AND event_type = 'storage_moved'
                """,
                (content_id,),
            )
            cursor.execute(
                "DELETE FROM object_content_moves WHERE content_id = %s",
                (content_id,),
            )

        command.downgrade(config, _PREVIOUS_REVISION)
        command.upgrade(config, _MOVE_REVISION)
        _assert_orm_parity(database_url)

        object_key = f"v1/{uuid4().hex}"
        digest = sha256(payload).digest()

        with connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO object_content_moves (
                    content_id, target_kind, state
                )
                VALUES (%s, 'object_store', 'pending')
                """,
                (content_id,),
            )

        with pytest.raises(
            DBAPIError,
            match="cannot downgrade object-content moves after durable evidence exists",
        ):
            command.downgrade(config, _PREVIOUS_REVISION)

        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            assert cursor.fetchone() == (_MOVE_REVISION,)
            cursor.execute("SELECT count(*) FROM object_content_moves")
            assert cursor.fetchone() == (1,)
            cursor.execute(
                """
                SELECT count(*)
                FROM object_content_audit_events
                WHERE event_type = 'storage_moved'
                """
            )
            assert cursor.fetchone() == (0,)

        with pytest.raises(psycopg2.errors.RaiseException):
            with connection, connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM inline_content_payloads WHERE content_id = %s",
                    (content_id,),
                )
                cursor.execute(
                    """
                    UPDATE object_contents
                    SET storage_kind = 'object_store'
                    WHERE id = %s
                    """,
                    (content_id,),
                )

        with connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE object_content_moves
                SET state = 'target_verified', object_key = %s,
                    verification_chunk_size_bytes = %s,
                    verification_chunk_sha256 = %s
                WHERE content_id = %s
                """,
                (object_key, len(payload), digest, content_id),
            )

        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            with connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE object_contents
                    SET storage_kind = 'object_store'
                    WHERE id = %s
                    """,
                    (content_id,),
                )

        with connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM inline_content_payloads WHERE content_id = %s",
                (content_id,),
            )
            cursor.execute(
                """
                UPDATE object_contents
                SET storage_kind = 'object_store'
                WHERE id = %s
                """,
                (content_id,),
            )
            cursor.execute(
                """
                INSERT INTO object_store_objects (
                    content_id, object_key, verification_chunk_size_bytes,
                    verification_chunk_sha256
                )
                VALUES (%s, %s, %s, %s)
                """,
                (content_id, object_key, len(payload), digest),
            )
            cursor.execute(
                """
                INSERT INTO object_content_audit_events (
                    content_id, event_type, actor_user_id
                )
                VALUES (%s, 'storage_moved', NULL)
                """,
                (content_id,),
            )
            cursor.execute(
                """
                UPDATE object_content_moves
                SET state = 'failed', object_key = NULL,
                    verification_chunk_size_bytes = NULL,
                    verification_chunk_sha256 = NULL,
                    failure_code = 'content_ineligible'
                WHERE content_id = %s
                """,
                (content_id,),
            )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT conname, condeferrable
                FROM pg_constraint
                WHERE conname IN (
                    'fk_inline_content_payloads_content_kind',
                    'fk_object_store_objects_content_kind'
                )
                ORDER BY conname
                """
            )
            assert cursor.fetchall() == [
                ("fk_inline_content_payloads_content_kind", False),
                ("fk_object_store_objects_content_kind", False),
            ]

        with pytest.raises(psycopg2.errors.RaiseException):
            with connection, connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM object_store_objects WHERE content_id = %s",
                    (content_id,),
                )
                cursor.execute(
                    """
                    UPDATE object_contents
                    SET storage_kind = 'postgres_inline'
                    WHERE id = %s
                    """,
                    (content_id,),
                )

        with connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM object_content_moves WHERE content_id = %s",
                (content_id,),
            )

        with pytest.raises(
            DBAPIError,
            match="cannot downgrade object-content moves after durable evidence exists",
        ):
            command.downgrade(config, _PREVIOUS_REVISION)

        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            assert cursor.fetchone() == (_MOVE_REVISION,)
            cursor.execute(
                "SELECT moves_paused FROM object_content_deployment_policy WHERE id = 1"
            )
            assert cursor.fetchone() == (False,)
            cursor.execute("SELECT count(*) FROM object_content_moves")
            assert cursor.fetchone() == (0,)
            cursor.execute(
                """
                SELECT count(*)
                FROM object_content_audit_events
                WHERE event_type = 'storage_moved'
                """
            )
            assert cursor.fetchone() == (1,)
    finally:
        connection.close()
