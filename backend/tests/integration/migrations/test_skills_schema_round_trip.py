"""PostgreSQL contract tests for the first-class Skills migrations.

Run in the migration-isolation lane:

    pytest -m migration_isolation \
        tests/integration/migrations/test_skills_schema_round_trip.py -v
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
from time import monotonic, sleep
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extensions import connection as PgConnection
from sqlalchemy.exc import DBAPIError

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_SKILLS_REVISION = "202607221000"
SKILLS_SCHEMA_REVISION = "202607221200"
SKILLS_PERMISSION_REVISION = "202607221300"
SKILLS_PROVENANCE_INDEX_REVISION = "202607221400"
PRE_RESOURCE_BINDING_SCOPE_REVISION = "202607221500"
PRE_PERMISSION_CONVERGENCE_REVISION = "202607221600"
SKILLS_HEAD_REVISION = "202607221700"


@dataclass(frozen=True)
class MigrationDatabase:
    connection: PgConnection
    alembic_config: Config


def _alembic_config(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(autouse=True)
def cleanup_database():
    """Leave schema ownership to this migration-isolation module."""
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    """This module inserts only the rows its schema assertions require."""
    yield


@pytest.fixture
def pre_skills_database(test_settings) -> Iterator[MigrationDatabase]:
    config = _alembic_config(test_settings.sync_database_url)

    try:
        command.downgrade(config, PRE_SKILLS_REVISION)
    except Exception:
        command.upgrade(config, PRE_SKILLS_REVISION)

    connection = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    connection.autocommit = True

    try:
        yield MigrationDatabase(connection=connection, alembic_config=config)
    finally:
        connection.close()


def _insert_tenant(connection: PgConnection, label: str) -> str:
    tenant_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants (
                id, name, quota_limit, state, created_at, updated_at
            )
            VALUES (%s, %s, 1000000, 'active', now(), now())
            """,
            (tenant_id, f"skills-{label}-{uuid4().hex[:8]}"),
        )
    return tenant_id


def _insert_user(connection: PgConnection, tenant_id: str, label: str) -> str:
    user_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO users (
                id, tenant_id, username, email, used_tokens, state,
                created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, 0, 'active', now(), now())
            """,
            (
                user_id,
                tenant_id,
                f"skills-{label}-{uuid4().hex[:6]}",
                f"skills-{label}-{uuid4().hex[:10]}@example.test",
            ),
        )
    return user_id


def _insert_space(
    connection: PgConnection,
    tenant_id: str,
    label: str,
    *,
    tenant_space_id: str | None = None,
) -> str:
    space_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO spaces (
                id, tenant_id, tenant_space_id, name, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, now(), now())
            """,
            (space_id, tenant_id, tenant_space_id, f"Skills {label}"),
        )
    return space_id


def _insert_role(
    connection: PgConnection,
    *,
    tenant_id: str,
    label: str,
    permissions: list[str],
    predefined_source: str | None = None,
) -> str:
    role_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO roles (
                id, name, permissions, tenant_id, predefined_source,
                created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, now(), now())
            """,
            (
                role_id,
                f"Skills {label} {uuid4().hex[:6]}",
                permissions,
                tenant_id,
                predefined_source,
            ),
        )
    return role_id


def _permissions(connection: PgConnection, role_id: str) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT permissions FROM roles WHERE id = %s", (role_id,))
        row = cursor.fetchone()
    assert row is not None
    return list(row[0])


def _current_revision(connection: PgConnection) -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        row = cursor.fetchone()
    assert row is not None
    return str(row[0])


def test_permission_convergence_changes_only_predefined_roles(
    pre_skills_database: MigrationDatabase,
):
    connection = pre_skills_database.connection
    config = pre_skills_database.alembic_config
    command.upgrade(config, PRE_PERMISSION_CONVERGENCE_REVISION)

    tenant_id = _insert_tenant(connection, "permission-convergence")
    role_ids = {
        "owner": _insert_role(
            connection,
            tenant_id=tenant_id,
            label="owner-before-convergence",
            permissions=["admin", "skills"],
            predefined_source="Owner",
        ),
        "user": _insert_role(
            connection,
            tenant_id=tenant_id,
            label="user-before-convergence",
            permissions=["assistants", "skills"],
            predefined_source="User",
        ),
        "ai_configurator": _insert_role(
            connection,
            tenant_id=tenant_id,
            label="ai-configurator-before-convergence",
            permissions=["AI", "skills", "skills_management"],
            predefined_source="AI Configurator",
        ),
        "custom_manager": _insert_role(
            connection,
            tenant_id=tenant_id,
            label="custom-manager-before-convergence",
            permissions=["assistants", "skills", "skills_management"],
        ),
        "custom_plain": _insert_role(
            connection,
            tenant_id=tenant_id,
            label="custom-plain-before-convergence",
            permissions=["assistants"],
        ),
    }

    command.upgrade(config, SKILLS_HEAD_REVISION)
    command.upgrade(config, SKILLS_HEAD_REVISION)

    assert _current_revision(connection) == SKILLS_HEAD_REVISION
    assert _permissions(connection, role_ids["owner"]) == [
        "admin",
        "skills",
        "skills_management",
    ]
    assert _permissions(connection, role_ids["user"]) == ["assistants"]
    assert _permissions(connection, role_ids["ai_configurator"]) == ["AI"]
    assert _permissions(connection, role_ids["custom_manager"]) == [
        "assistants",
        "skills",
        "skills_management",
    ]
    assert _permissions(connection, role_ids["custom_plain"]) == ["assistants"]

    command.downgrade(config, PRE_PERMISSION_CONVERGENCE_REVISION)

    assert _permissions(connection, role_ids["owner"]) == [
        "admin",
        "skills",
        "skills_management",
    ]
    assert _permissions(connection, role_ids["user"]) == ["assistants", "skills"]
    assert _permissions(connection, role_ids["ai_configurator"]) == [
        "AI",
        "skills",
        "skills_management",
    ]
    assert _permissions(connection, role_ids["custom_manager"]) == [
        "assistants",
        "skills",
        "skills_management",
    ]
    assert _permissions(connection, role_ids["custom_plain"]) == ["assistants"]


def _insert_assistant(connection: PgConnection, *, user_id: str, space_id: str) -> str:
    assistant_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO assistants (
                id, user_id, space_id, name, logging_enabled, is_default,
                published, type, insight_enabled, created_at, updated_at
            )
            VALUES (
                %s, %s, %s, 'Migration Skill Assistant', false, false,
                false, 'assistant', false, now(), now()
            )
            """,
            (assistant_id, user_id, space_id),
        )
    return assistant_id


def _insert_app(
    connection: PgConnection,
    *,
    tenant_id: str,
    user_id: str,
    space_id: str,
) -> str:
    app_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO apps (
                id, tenant_id, user_id, space_id, name, published,
                created_at, updated_at
            )
            VALUES (
                %s, %s, %s, %s, 'Migration Skill App', false, now(), now()
            )
            """,
            (app_id, tenant_id, user_id, space_id),
        )
    return app_id


def _insert_completion_model(connection: PgConnection) -> str:
    completion_model_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO completion_models (
                id, name, nickname, max_input_tokens, max_output_tokens,
                family, stability, hosting, reasoning, created_at, updated_at
            )
            VALUES (
                %s, %s, 'Skills index test', 4096, 1024,
                'test', 'stable', 'local', false, now(), now()
            )
            """,
            (
                completion_model_id,
                f"skills-index-{completion_model_id[:8]}",
            ),
        )
    return completion_model_id


def _insert_app_run(
    connection: PgConnection,
    *,
    tenant_id: str,
    user_id: str,
    app_id: str,
    completion_model_id: str,
    skill_id: str,
) -> str:
    app_run_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO app_runs (
                id, input_text, tenant_id, user_id, app_id,
                completion_model_id, skill_provenance, created_at, updated_at
            )
            VALUES (
                %s, 'seed', %s, %s, %s, %s, %s::jsonb, now(), now()
            )
            """,
            (
                app_run_id,
                tenant_id,
                user_id,
                app_id,
                completion_model_id,
                json.dumps([{"skill_id": skill_id}]),
            ),
        )
    return app_run_id


def _wait_for_concurrent_index_validation(
    connection: PgConnection,
    migration_thread: Thread,
    migration_errors: Queue[BaseException],
) -> tuple[int, str, bool, bool]:
    deadline = time.monotonic() + 10
    last_progress: tuple[int, str, bool, bool] | None = None

    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT progress.pid, progress.phase,
                       index_state.indisready, index_state.indisvalid
                FROM pg_stat_progress_create_index AS progress
                JOIN pg_class AS index_class
                  ON index_class.oid = progress.index_relid
                JOIN pg_index AS index_state
                  ON index_state.indexrelid = index_class.oid
                WHERE index_class.relname =
                      'ix_app_runs_skill_provenance_gin'
                """
            )
            row = cursor.fetchone()

        if row is not None:
            last_progress = (int(row[0]), str(row[1]), bool(row[2]), bool(row[3]))
            if last_progress[1:] == ("waiting for old snapshots", True, False):
                return last_progress

        if not migration_thread.is_alive():
            try:
                error = migration_errors.get_nowait()
            except Empty:
                error = None
            raise AssertionError(
                "Concurrent index migration completed before its write-safe "
                f"validation phase; last progress: {last_progress}"
            ) from error

        time.sleep(0.05)

    raise AssertionError(
        "Timed out waiting for the concurrent index validation phase; "
        f"last progress: {last_progress}"
    )


def _insert_policy(connection: PgConnection, tenant_id: str) -> str:
    policy_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO governance_policies (
                id, tenant_id, scope, created_at, updated_at
            )
            VALUES (
                %s, %s, 'personal_default_assistant', now(), now()
            )
            """,
            (policy_id, tenant_id),
        )
    return policy_id


def _insert_skill(
    connection: PgConnection,
    *,
    space_id: str,
    created_by_user_id: str,
    label: str,
) -> tuple[str, str]:
    skill_id = str(uuid4())
    revision_id = str(uuid4())
    digest = revision_id.replace("-", "") * 2

    with connection.cursor() as cursor:
        cursor.execute("BEGIN")
        try:
            cursor.execute(
                """
                INSERT INTO skills (
                    id, space_id, slug, is_active, current_revision_number,
                    created_by_user_id, created_at, updated_at
                )
                VALUES (%s, %s, %s, true, 1, %s, now(), now())
                """,
                (
                    skill_id,
                    space_id,
                    f"{label}-{skill_id[:8]}",
                    created_by_user_id,
                ),
            )
            cursor.execute(
                """
                INSERT INTO skill_revisions (
                    id, skill_id, revision_number, display_name, description,
                    instructions, content_digest, created_by_user_id,
                    created_at, updated_at
                )
                VALUES (
                    %s, %s, 1, %s, 'Migration contract Skill',
                    'Follow the migration contract.', %s, %s, now(), now()
                )
                """,
                (
                    revision_id,
                    skill_id,
                    f"Skill {label}",
                    digest,
                    created_by_user_id,
                ),
            )
            cursor.execute("COMMIT")
        except Exception:
            cursor.execute("ROLLBACK")
            raise

    return skill_id, revision_id


def _assert_constraint(
    connection: PgConnection,
    *,
    expected: str | set[str],
    statement: str,
    parameters: tuple[object, ...],
) -> None:
    with connection.cursor() as cursor:
        with pytest.raises(psycopg2.IntegrityError) as error:
            cursor.execute(statement, parameters)

    expected_names = {expected} if isinstance(expected, str) else expected
    assert error.value.diag.constraint_name in expected_names


def _insert_populated_resource_bindings(
    connection: PgConnection,
    *,
    tenant_id: str,
    user_id: str,
    space_id: str,
    skill_id: str,
    skill_revision_id: str,
    row_count: int,
) -> tuple[str, str]:
    seed = uuid4().hex
    resource_name = f"Migration lock probe {seed}"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO assistants (
                id, user_id, space_id, name, logging_enabled, is_default,
                published, type, insight_enabled, created_at, updated_at
            )
            SELECT
                md5(%s || '-assistant-' || ordinal::text)::uuid,
                %s, %s, %s, false, false, false, 'assistant', false,
                now(), now()
            FROM generate_series(1, %s) AS ordinal
            """,
            (seed, user_id, space_id, resource_name, row_count),
        )
        cursor.execute(
            """
            INSERT INTO assistant_skill_bindings (
                assistant_id, skill_id, skill_revision_id, space_id, position
            )
            SELECT
                md5(%s || '-assistant-' || ordinal::text)::uuid,
                %s, %s, %s, 0
            FROM generate_series(1, %s) AS ordinal
            """,
            (seed, skill_id, skill_revision_id, space_id, row_count),
        )
        cursor.execute(
            """
            INSERT INTO apps (
                id, tenant_id, user_id, space_id, name, published,
                created_at, updated_at
            )
            SELECT
                md5(%s || '-app-' || ordinal::text)::uuid,
                %s, %s, %s, %s, false, now(), now()
            FROM generate_series(1, %s) AS ordinal
            """,
            (seed, tenant_id, user_id, space_id, resource_name, row_count),
        )
        cursor.execute(
            """
            INSERT INTO app_skill_bindings (
                app_id, skill_id, skill_revision_id, space_id, position
            )
            SELECT
                md5(%s || '-app-' || ordinal::text)::uuid,
                %s, %s, %s, 0
            FROM generate_series(1, %s) AS ordinal
            """,
            (seed, skill_id, skill_revision_id, space_id, row_count),
        )
        cursor.execute(
            "SELECT id FROM assistants WHERE name = %s ORDER BY id LIMIT 1",
            (resource_name,),
        )
        assistant_id = cursor.fetchone()
        cursor.execute(
            "SELECT id FROM apps WHERE name = %s ORDER BY id LIMIT 1",
            (resource_name,),
        )
        app_id = cursor.fetchone()

    assert assistant_id is not None
    assert app_id is not None
    return str(assistant_id[0]), str(app_id[0])


def test_resource_binding_validation_does_not_retain_exclusive_table_locks(
    pre_skills_database: MigrationDatabase,
    test_settings,
):
    connection = pre_skills_database.connection
    config = pre_skills_database.alembic_config
    command.upgrade(config, PRE_RESOURCE_BINDING_SCOPE_REVISION)

    tenant_id = _insert_tenant(connection, "online-binding-contract")
    user_id = _insert_user(connection, tenant_id, "online-binding-contract")
    space_id = _insert_space(connection, tenant_id, "online-binding-contract")
    skill_id, revision_id = _insert_skill(
        connection,
        space_id=space_id,
        created_by_user_id=user_id,
        label="online-binding-contract",
    )
    assistant_id, app_id = _insert_populated_resource_bindings(
        connection,
        tenant_id=tenant_id,
        user_id=user_id,
        space_id=space_id,
        skill_id=skill_id,
        skill_revision_id=revision_id,
        row_count=50_000,
    )

    stop_writer = Event()
    writer_ready = Event()
    writer_iterations = [0]
    writer_errors: list[BaseException] = []
    migration_errors: list[BaseException] = []

    def keep_reader_and_writer_active() -> None:
        writer_connection = psycopg2.connect(
            host=test_settings.postgres_host,
            port=test_settings.postgres_port,
            dbname=test_settings.postgres_db,
            user=test_settings.postgres_user,
            password=test_settings.postgres_password,
        )
        writer_connection.autocommit = True
        try:
            with writer_connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = '2s'")
                writer_ready.set()
                while not stop_writer.is_set():
                    cursor.execute(
                        """
                        SELECT updated_at
                        FROM assistant_skill_bindings
                        WHERE assistant_id = %s AND skill_id = %s
                        """,
                        (assistant_id, skill_id),
                    )
                    cursor.fetchone()
                    cursor.execute(
                        """
                        UPDATE assistant_skill_bindings
                        SET updated_at = clock_timestamp()
                        WHERE assistant_id = %s AND skill_id = %s
                        """,
                        (assistant_id, skill_id),
                    )
                    cursor.execute(
                        """
                        SELECT updated_at
                        FROM app_skill_bindings
                        WHERE app_id = %s AND skill_id = %s
                        """,
                        (app_id, skill_id),
                    )
                    cursor.fetchone()
                    cursor.execute(
                        """
                        UPDATE app_skill_bindings
                        SET updated_at = clock_timestamp()
                        WHERE app_id = %s AND skill_id = %s
                        """,
                        (app_id, skill_id),
                    )
                    writer_iterations[0] += 1
                    sleep(0.002)
        except BaseException as error:
            writer_errors.append(error)
        finally:
            writer_connection.close()

    def run_scope_migration() -> None:
        try:
            command.upgrade(
                _alembic_config(config.get_main_option("sqlalchemy.url")),
                PRE_PERMISSION_CONVERGENCE_REVISION,
            )
        except BaseException as error:
            migration_errors.append(error)

    writer = Thread(target=keep_reader_and_writer_active, daemon=True)
    writer.start()
    assert writer_ready.wait(timeout=5)
    writer_start_deadline = monotonic() + 5
    while (
        writer_iterations[0] < 2
        and not writer_errors
        and monotonic() < writer_start_deadline
    ):
        sleep(0.002)
    assert not writer_errors
    assert writer_iterations[0] >= 2

    migration = Thread(target=run_scope_migration, daemon=True)
    migration.start()

    observed_validations: set[str] = set()
    exclusive_locks_during_validation: list[str] = []
    while migration.is_alive():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT activity.query,
                       EXISTS (
                           SELECT 1
                           FROM pg_locks AS held_lock
                           JOIN pg_class AS relation
                             ON relation.oid = held_lock.relation
                           WHERE held_lock.pid = activity.pid
                             AND held_lock.granted
                             AND held_lock.mode = 'AccessExclusiveLock'
                             AND relation.relname = ANY(%s)
                       )
                FROM pg_stat_activity AS activity
                WHERE activity.datname = current_database()
                  AND activity.pid <> pg_backend_pid()
                  AND activity.query LIKE 'ALTER TABLE %%VALIDATE CONSTRAINT%%'
                """,
                (list(("assistant_skill_bindings", "app_skill_bindings")),),
            )
            validation_rows = cursor.fetchall()

        for query, has_exclusive_lock in validation_rows:
            for table in ("assistant_skill_bindings", "app_skill_bindings"):
                if f"ALTER TABLE {table} VALIDATE CONSTRAINT" in query:
                    observed_validations.add(table)
                    if has_exclusive_lock:
                        exclusive_locks_during_validation.append(table)
        sleep(0.001)

    migration.join(timeout=5)
    stop_writer.set()
    writer.join(timeout=5)

    assert not migration_errors
    assert not writer_errors
    assert writer_iterations[0] > 2
    assert observed_validations == {
        "assistant_skill_bindings",
        "app_skill_bindings",
    }
    assert exclusive_locks_during_validation == []


def test_upgrade_recovers_indexes_and_round_trips_role_backfill(
    pre_skills_database: MigrationDatabase,
):
    connection = pre_skills_database.connection
    config = pre_skills_database.alembic_config

    tenant_id = _insert_tenant(connection, "lifecycle")
    organization_space_id = _insert_space(connection, tenant_id, "organization")
    _insert_space(
        connection,
        tenant_id,
        "shared",
        tenant_space_id=organization_space_id,
    )

    role_ids = {
        "owner": _insert_role(
            connection,
            tenant_id=tenant_id,
            label="owner",
            permissions=["admin"],
            predefined_source="Owner",
        ),
        "user": _insert_role(
            connection,
            tenant_id=tenant_id,
            label="user",
            permissions=["assistants", "apps"],
            predefined_source="User",
        ),
        "ai_configurator": _insert_role(
            connection,
            tenant_id=tenant_id,
            label="ai-configurator",
            permissions=["AI", "assistants", "apps"],
            predefined_source="AI Configurator",
        ),
        "assistants": _insert_role(
            connection,
            tenant_id=tenant_id,
            label="assistants",
            permissions=["assistants"],
        ),
        "apps": _insert_role(
            connection,
            tenant_id=tenant_id,
            label="apps",
            permissions=["apps"],
        ),
        "admin": _insert_role(
            connection,
            tenant_id=tenant_id,
            label="admin",
            permissions=["admin"],
        ),
        "ai": _insert_role(
            connection,
            tenant_id=tenant_id,
            label="ai",
            permissions=["AI"],
        ),
        "unrelated": _insert_role(
            connection,
            tenant_id=tenant_id,
            label="unrelated",
            permissions=["insights"],
        ),
        "already_granted": _insert_role(
            connection,
            tenant_id=tenant_id,
            label="already-granted",
            permissions=["assistants", "skills"],
        ),
        "already_managed": _insert_role(
            connection,
            tenant_id=tenant_id,
            label="already-managed",
            permissions=["AI", "skills", "skills_management"],
        ),
    }

    with connection.cursor() as cursor:
        cursor.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_spaces_tenant_id_id")
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cursor.execute(
                """
                CREATE UNIQUE INDEX CONCURRENTLY uq_spaces_tenant_id_id
                ON spaces (tenant_id)
                """
            )
        cursor.execute(
            """
            SELECT indisvalid
            FROM pg_index
            WHERE indexrelid = 'uq_spaces_tenant_id_id'::regclass
            """
        )
        invalid_index = cursor.fetchone()

    assert invalid_index == (False,)
    command.upgrade(config, SKILLS_HEAD_REVISION)
    command.upgrade(config, SKILLS_HEAD_REVISION)

    assert _current_revision(connection) == SKILLS_HEAD_REVISION
    owner_permissions = _permissions(connection, role_ids["owner"])
    assert owner_permissions.count("skills") == 1
    assert owner_permissions.count("skills_management") == 1

    for role_name in ("user", "ai_configurator", "unrelated"):
        permissions = _permissions(connection, role_ids[role_name])
        assert "skills" not in permissions
        assert "skills_management" not in permissions

    for role_name in ("assistants", "apps"):
        permissions = _permissions(connection, role_ids[role_name])
        assert permissions.count("skills") == 1
        assert "skills_management" not in permissions

    for role_name in ("admin", "ai"):
        permissions = _permissions(connection, role_ids[role_name])
        assert permissions.count("skills") == 1
        assert permissions.count("skills_management") == 1

    assert _permissions(connection, role_ids["already_granted"]).count("skills") == 1
    already_managed_permissions = _permissions(connection, role_ids["already_managed"])
    assert already_managed_permissions.count("skills") == 1
    assert already_managed_permissions.count("skills_management") == 1

    expected_indexes = {
        "uq_assistants_space_id_id",
        "uq_apps_space_id_id",
        "uq_spaces_tenant_id_id",
        "uq_governance_policies_tenant_id_id",
        "ix_assistant_skill_bindings_skill_id",
        "ix_assistant_skill_bindings_tenant_skill_space",
        "ix_app_skill_bindings_skill_id",
        "ix_app_skill_bindings_tenant_skill_space",
        "ix_app_runs_skill_provenance_gin",
        "ix_governance_policy_skill_bindings_skill_id",
        "ix_governance_policy_skill_bindings_tenant_space",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT index_class.relname, index_state.indisvalid,
                   index_state.indisunique,
                   pg_get_indexdef(index_state.indexrelid)
            FROM pg_index AS index_state
            JOIN pg_class AS index_class
              ON index_class.oid = index_state.indexrelid
            WHERE index_class.relname = ANY(%s)
            """,
            (list(expected_indexes),),
        )
        indexes = {
            name: (is_valid, is_unique, definition)
            for name, is_valid, is_unique, definition in cursor.fetchall()
        }

    assert indexes.keys() == expected_indexes
    assert all(index[0] for index in indexes.values())
    assert indexes["uq_spaces_tenant_id_id"][1] is True
    assert "(tenant_id, id)" in indexes["uq_spaces_tenant_id_id"][2]
    assert (
        "USING gin (skill_provenance jsonb_path_ops)"
        in indexes["ix_app_runs_skill_provenance_gin"][2]
    )
    assert (
        "(tenant_id, skill_space_id)"
        in indexes["ix_governance_policy_skill_bindings_tenant_space"][2]
    )
    assert (
        "(tenant_id, skill_space_id)"
        in indexes["ix_assistant_skill_bindings_tenant_skill_space"][2]
    )
    assert (
        "(tenant_id, skill_space_id)"
        in indexes["ix_app_skill_bindings_tenant_skill_space"][2]
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'skills'
              AND column_name = ANY(%s)
            ORDER BY column_name
            """,
            (["first_published_at", "published_revision_number"],),
        )
        publication_columns = cursor.fetchall()

    assert publication_columns == [
        ("first_published_at", "YES"),
        ("published_revision_number", "YES"),
    ]
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name, column_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = ANY(%s)
              AND column_name = ANY(%s)
            ORDER BY table_name, column_name
            """,
            (
                ["assistant_skill_bindings", "app_skill_bindings"],
                ["skill_space_id", "tenant_id"],
            ),
        )
        binding_scope_columns = cursor.fetchall()

    assert binding_scope_columns == [
        ("app_skill_bindings", "skill_space_id", "NO"),
        ("app_skill_bindings", "tenant_id", "NO"),
        ("assistant_skill_bindings", "skill_space_id", "NO"),
        ("assistant_skill_bindings", "tenant_id", "NO"),
    ]

    command.downgrade(config, SKILLS_SCHEMA_REVISION)
    assert _current_revision(connection) == SKILLS_SCHEMA_REVISION
    owner_permissions = _permissions(connection, role_ids["owner"])
    assert "skills" not in owner_permissions
    assert "skills_management" not in owner_permissions
    # The already-shipped 1300 downgrade removes the two permissions globally;
    # it did not persist enough provenance to reconstruct earlier custom grants.
    assert "skills" not in _permissions(connection, role_ids["already_granted"])
    already_managed_permissions = _permissions(connection, role_ids["already_managed"])
    assert "skills" not in already_managed_permissions
    assert "skills_management" not in already_managed_permissions

    command.downgrade(config, PRE_SKILLS_REVISION)
    assert _current_revision(connection) == PRE_SKILLS_REVISION
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT to_regclass('public.skills'),
                   to_regclass('public.skill_revisions'),
                   to_regclass('public.assistant_skill_bindings'),
                   to_regclass('public.app_skill_bindings'),
                   to_regclass('public.governance_policy_skill_bindings'),
                   to_regclass('public.uq_spaces_tenant_id_id')
            """
        )
        removed_relations = cursor.fetchone()
        cursor.execute(
            """
            SELECT count(*)
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND column_name = 'skill_provenance'
              AND table_name IN ('questions', 'app_runs')
            """
        )
        provenance_columns = cursor.fetchone()

    assert removed_relations == (None, None, None, None, None, None)
    assert provenance_columns == (0,)

    command.upgrade(config, SKILLS_HEAD_REVISION)
    assert _current_revision(connection) == SKILLS_HEAD_REVISION
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.skills')")
        restored_skills_table = cursor.fetchone()
    assert restored_skills_table == ("skills",)


def test_provenance_index_build_allows_app_run_writes(
    pre_skills_database: MigrationDatabase,
    test_settings,
):
    connection = pre_skills_database.connection
    config = pre_skills_database.alembic_config
    command.upgrade(config, SKILLS_PERMISSION_REVISION)

    tenant_id = _insert_tenant(connection, "index")
    user_id = _insert_user(connection, tenant_id, "index-user")
    space_id = _insert_space(connection, tenant_id, "index-space")
    app_id = _insert_app(
        connection,
        tenant_id=tenant_id,
        user_id=user_id,
        space_id=space_id,
    )
    completion_model_id = _insert_completion_model(connection)
    skill_id = str(uuid4())
    app_run_id = _insert_app_run(
        connection,
        tenant_id=tenant_id,
        user_id=user_id,
        app_id=app_id,
        completion_model_id=completion_model_id,
        skill_id=skill_id,
    )

    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.ix_app_runs_skill_provenance_gin')")
        assert cursor.fetchone() == (None,)

    connection_parameters = {
        "host": test_settings.postgres_host,
        "port": test_settings.postgres_port,
        "dbname": test_settings.postgres_db,
        "user": test_settings.postgres_user,
        "password": test_settings.postgres_password,
    }
    old_snapshot = psycopg2.connect(**connection_parameters)
    observer = psycopg2.connect(**connection_parameters)
    writer = psycopg2.connect(**connection_parameters)
    observer.autocommit = True
    migration_errors: Queue[BaseException] = Queue()
    migration_config = _alembic_config(test_settings.sync_database_url)

    def upgrade_index() -> None:
        try:
            command.upgrade(migration_config, SKILLS_PROVENANCE_INDEX_REVISION)
        except BaseException as error:
            migration_errors.put(error)

    migration_thread = Thread(target=upgrade_index, name="skills-index-migration")
    migration_started = False
    try:
        old_snapshot.set_session(
            isolation_level="REPEATABLE READ",
            readonly=False,
            autocommit=False,
        )
        with old_snapshot.cursor() as cursor:
            cursor.execute(
                "SELECT output_text FROM app_runs WHERE id = %s",
                (app_run_id,),
            )
            assert cursor.fetchone() == (None,)

        migration_thread.start()
        migration_started = True
        _wait_for_concurrent_index_validation(
            observer,
            migration_thread,
            migration_errors,
        )

        with writer.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '1s'")
            cursor.execute("SET LOCAL statement_timeout = '2s'")
            cursor.execute(
                """
                UPDATE app_runs
                SET output_text = 'written during index build'
                WHERE id = %s
                """,
                (app_run_id,),
            )
            assert cursor.rowcount == 1
        writer.commit()
    finally:
        old_snapshot.rollback()
        if migration_started:
            migration_thread.join(timeout=10)
        old_snapshot.close()
        observer.close()
        writer.close()

    assert migration_started
    assert not migration_thread.is_alive(), "Index migration did not finish"
    try:
        migration_error = migration_errors.get_nowait()
    except Empty:
        migration_error = None
    if migration_error is not None:
        raise migration_error

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT index_state.indisready, index_state.indisvalid
            FROM pg_index AS index_state
            WHERE index_state.indexrelid =
                  'ix_app_runs_skill_provenance_gin'::regclass
            """
        )
        assert cursor.fetchone() == (True, True)
        cursor.execute("ANALYZE app_runs")
        cursor.execute("SET enable_seqscan = off")
        cursor.execute(
            """
            EXPLAIN (COSTS OFF)
            SELECT 1
            FROM app_runs
            WHERE skill_provenance @> %s::jsonb
            """,
            (json.dumps([{"skill_id": skill_id}]),),
        )
        query_plan = "\n".join(row[0] for row in cursor.fetchall())

    assert "ix_app_runs_skill_provenance_gin" in query_plan


def test_database_enforces_skill_scope_revision_and_lifecycle_invariants(
    pre_skills_database: MigrationDatabase,
):
    connection = pre_skills_database.connection
    command.upgrade(
        pre_skills_database.alembic_config,
        SKILLS_HEAD_REVISION,
    )

    tenant_a = _insert_tenant(connection, "tenant-a")
    tenant_b = _insert_tenant(connection, "tenant-b")
    user_a = _insert_user(connection, tenant_a, "user-a")
    user_b = _insert_user(connection, tenant_b, "user-b")
    organization_space_a = _insert_space(connection, tenant_a, "A organization")
    organization_space_b = _insert_space(connection, tenant_b, "B organization")
    space_a = _insert_space(
        connection,
        tenant_a,
        "A shared",
        tenant_space_id=organization_space_a,
    )
    sibling_space_a = _insert_space(
        connection,
        tenant_a,
        "A sibling shared",
        tenant_space_id=organization_space_a,
    )

    assistant_id = _insert_assistant(
        connection,
        user_id=user_a,
        space_id=space_a,
    )
    app_id = _insert_app(
        connection,
        tenant_id=tenant_a,
        user_id=user_a,
        space_id=space_a,
    )
    policy_id = _insert_policy(connection, tenant_a)

    primary_skill, primary_revision = _insert_skill(
        connection,
        space_id=space_a,
        created_by_user_id=user_a,
        label="primary",
    )
    peer_skill, peer_revision = _insert_skill(
        connection,
        space_id=space_a,
        created_by_user_id=user_a,
        label="peer",
    )
    sibling_skill, sibling_revision = _insert_skill(
        connection,
        space_id=sibling_space_a,
        created_by_user_id=user_a,
        label="sibling",
    )
    governance_skill, governance_revision = _insert_skill(
        connection,
        space_id=organization_space_a,
        created_by_user_id=user_a,
        label="governance",
    )
    foreign_skill, foreign_revision = _insert_skill(
        connection,
        space_id=organization_space_b,
        created_by_user_id=user_b,
        label="foreign",
    )

    _assert_constraint(
        connection,
        expected="fk_skills_current_revision",
        statement="""
            INSERT INTO skills (
                id, space_id, slug, is_active, current_revision_number,
                created_by_user_id, created_at, updated_at
            )
            VALUES (%s, %s, %s, true, 99, %s, now(), now())
        """,
        parameters=(
            str(uuid4()),
            space_a,
            f"invalid-pointer-{uuid4().hex[:8]}",
            user_a,
        ),
    )
    _assert_constraint(
        connection,
        expected="ck_skills_published_requires_first_published_at",
        statement="""
            UPDATE skills
            SET published_revision_number = 1
            WHERE id = %s
        """,
        parameters=(primary_skill,),
    )
    _assert_constraint(
        connection,
        expected="ck_skills_published_active",
        statement="""
            UPDATE skills
            SET published_revision_number = 1,
                first_published_at = now(),
                is_active = false
            WHERE id = %s
        """,
        parameters=(primary_skill,),
    )
    _assert_constraint(
        connection,
        expected="fk_skills_published_revision",
        statement="""
            UPDATE skills
            SET published_revision_number = 99,
                first_published_at = now()
            WHERE id = %s
        """,
        parameters=(primary_skill,),
    )
    _assert_constraint(
        connection,
        expected="ck_assistant_skill_bindings_position_nonnegative",
        statement="""
            INSERT INTO assistant_skill_bindings (
                assistant_id, tenant_id, space_id, skill_space_id,
                skill_id, skill_revision_id, position
            )
            VALUES (%s, %s, %s, %s, %s, %s, -1)
        """,
        parameters=(
            assistant_id,
            tenant_a,
            space_a,
            space_a,
            primary_skill,
            primary_revision,
        ),
    )
    _assert_constraint(
        connection,
        expected="fk_assistant_skill_bindings_skill_space",
        statement="""
            INSERT INTO assistant_skill_bindings (
                assistant_id, tenant_id, space_id, skill_space_id,
                skill_id, skill_revision_id, position
            )
            VALUES (%s, %s, %s, %s, %s, %s, 0)
        """,
        parameters=(
            assistant_id,
            tenant_a,
            space_a,
            organization_space_b,
            foreign_skill,
            foreign_revision,
        ),
    )
    _assert_constraint(
        connection,
        expected="fk_app_skill_bindings_skill_space",
        statement="""
            INSERT INTO app_skill_bindings (
                app_id, tenant_id, space_id, skill_space_id,
                skill_id, skill_revision_id, position
            )
            VALUES (%s, %s, %s, %s, %s, %s, 0)
        """,
        parameters=(
            app_id,
            tenant_a,
            space_a,
            organization_space_b,
            foreign_skill,
            foreign_revision,
        ),
    )
    _assert_constraint(
        connection,
        expected="fk_assistant_skill_bindings_parent_space",
        statement="""
            INSERT INTO assistant_skill_bindings (
                assistant_id, tenant_id, space_id, skill_space_id,
                skill_id, skill_revision_id, position
            )
            VALUES (%s, %s, %s, %s, %s, %s, 0)
        """,
        parameters=(
            assistant_id,
            tenant_b,
            space_a,
            organization_space_b,
            foreign_skill,
            foreign_revision,
        ),
    )
    _assert_constraint(
        connection,
        expected="fk_assistant_skill_bindings_revision",
        statement="""
            INSERT INTO assistant_skill_bindings (
                assistant_id, tenant_id, space_id, skill_space_id,
                skill_id, skill_revision_id, position
            )
            VALUES (%s, %s, %s, %s, %s, %s, 0)
        """,
        parameters=(
            assistant_id,
            tenant_a,
            space_a,
            space_a,
            primary_skill,
            peer_revision,
        ),
    )
    _assert_constraint(
        connection,
        expected="fk_governance_policy_skill_bindings_space",
        statement="""
            INSERT INTO governance_policy_skill_bindings (
                policy_id, tenant_id, skill_space_id, skill_id,
                skill_revision_id, position
            )
            VALUES (%s, %s, %s, %s, %s, 0)
        """,
        parameters=(
            policy_id,
            tenant_a,
            organization_space_b,
            foreign_skill,
            foreign_revision,
        ),
    )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO assistant_skill_bindings (
                assistant_id, tenant_id, space_id, skill_space_id,
                skill_id, skill_revision_id, position
            )
            VALUES (%s, %s, %s, %s, %s, %s, 0)
            """,
            (
                assistant_id,
                tenant_a,
                space_a,
                organization_space_a,
                governance_skill,
                governance_revision,
            ),
        )
        cursor.execute(
            "DELETE FROM assistant_skill_bindings WHERE assistant_id = %s",
            (assistant_id,),
        )
        cursor.execute(
            """
            INSERT INTO app_skill_bindings (
                app_id, tenant_id, space_id, skill_space_id,
                skill_id, skill_revision_id, position
            )
            VALUES (%s, %s, %s, %s, %s, %s, 0)
            """,
            (
                app_id,
                tenant_a,
                space_a,
                sibling_space_a,
                sibling_skill,
                sibling_revision,
            ),
        )
        cursor.execute(
            "DELETE FROM app_skill_bindings WHERE app_id = %s",
            (app_id,),
        )
        cursor.execute(
            """
            INSERT INTO assistant_skill_bindings (
                assistant_id, tenant_id, space_id, skill_space_id,
                skill_id, skill_revision_id, position
            )
            VALUES (%s, %s, %s, %s, %s, %s, 0)
            """,
            (
                assistant_id,
                tenant_a,
                space_a,
                space_a,
                primary_skill,
                primary_revision,
            ),
        )

    _assert_constraint(
        connection,
        expected="uq_assistant_skill_bindings_assistant_id_position",
        statement="""
            INSERT INTO assistant_skill_bindings (
                assistant_id, tenant_id, space_id, skill_space_id,
                skill_id, skill_revision_id, position
            )
            VALUES (%s, %s, %s, %s, %s, %s, 0)
        """,
        parameters=(
            assistant_id,
            tenant_a,
            space_a,
            space_a,
            peer_skill,
            peer_revision,
        ),
    )
    _assert_constraint(
        connection,
        expected={
            "fk_assistant_skill_bindings_skill",
            "fk_assistant_skill_bindings_revision",
        },
        statement="DELETE FROM skills WHERE id = %s",
        parameters=(primary_skill,),
    )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO app_skill_bindings (
                app_id, tenant_id, space_id, skill_space_id,
                skill_id, skill_revision_id, position
            )
            VALUES (%s, %s, %s, %s, %s, %s, 0)
            """,
            (
                app_id,
                tenant_a,
                space_a,
                space_a,
                peer_skill,
                peer_revision,
            ),
        )
        cursor.execute(
            """
            INSERT INTO governance_policy_skill_bindings (
                policy_id, tenant_id, skill_space_id, skill_id,
                skill_revision_id, position
            )
            VALUES (%s, %s, %s, %s, %s, 0)
            """,
            (
                policy_id,
                tenant_a,
                organization_space_a,
                governance_skill,
                governance_revision,
            ),
        )

        cursor.execute("DELETE FROM assistants WHERE id = %s", (assistant_id,))
        cursor.execute("DELETE FROM apps WHERE id = %s", (app_id,))
        cursor.execute(
            "DELETE FROM governance_policies WHERE id = %s",
            (policy_id,),
        )
        cursor.execute(
            """
            SELECT
                (SELECT count(*) FROM assistant_skill_bindings
                 WHERE assistant_id = %s),
                (SELECT count(*) FROM app_skill_bindings
                 WHERE app_id = %s),
                (SELECT count(*) FROM governance_policy_skill_bindings
                 WHERE policy_id = %s)
            """,
            (assistant_id, app_id, policy_id),
        )
        binding_counts = cursor.fetchone()

        cursor.execute("DELETE FROM skills WHERE id = %s", (primary_skill,))
        cursor.execute("SELECT count(*) FROM skills WHERE id = %s", (primary_skill,))
        deleted_skill_count = cursor.fetchone()

    assert binding_counts == (0, 0, 0)
    assert deleted_skill_count == (0,)


def test_binding_scope_downgrade_fails_without_losing_cross_space_bindings(
    pre_skills_database: MigrationDatabase,
):
    connection = pre_skills_database.connection
    config = pre_skills_database.alembic_config
    command.upgrade(config, SKILLS_HEAD_REVISION)

    tenant_id = _insert_tenant(connection, "downgrade")
    user_id = _insert_user(connection, tenant_id, "downgrade")
    organization_space_id = _insert_space(connection, tenant_id, "organization")
    resource_space_id = _insert_space(
        connection,
        tenant_id,
        "resource",
        tenant_space_id=organization_space_id,
    )
    assistant_id = _insert_assistant(
        connection,
        user_id=user_id,
        space_id=resource_space_id,
    )
    skill_id, revision_id = _insert_skill(
        connection,
        space_id=organization_space_id,
        created_by_user_id=user_id,
        label="downgrade",
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO assistant_skill_bindings (
                assistant_id, tenant_id, space_id, skill_space_id,
                skill_id, skill_revision_id, position
            )
            VALUES (%s, %s, %s, %s, %s, %s, 0)
            """,
            (
                assistant_id,
                tenant_id,
                resource_space_id,
                organization_space_id,
                skill_id,
                revision_id,
            ),
        )

    with pytest.raises(DBAPIError, match="Cannot downgrade Skill bindings"):
        command.downgrade(config, PRE_RESOURCE_BINDING_SCOPE_REVISION)

    assert _current_revision(connection) == SKILLS_HEAD_REVISION
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
            FROM assistant_skill_bindings
            WHERE assistant_id = %s
            """,
            (assistant_id,),
        )
        binding_count = cursor.fetchone()
        cursor.execute(
            "DELETE FROM assistant_skill_bindings WHERE assistant_id = %s",
            (assistant_id,),
        )

    assert binding_count == (1,)
    command.downgrade(config, PRE_RESOURCE_BINDING_SCOPE_REVISION)
    assert _current_revision(connection) == PRE_RESOURCE_BINDING_SCOPE_REVISION
    command.upgrade(config, SKILLS_HEAD_REVISION)


def test_binding_scope_upgrade_keeps_legacy_binding_writes_compatible(
    pre_skills_database: MigrationDatabase,
):
    connection = pre_skills_database.connection
    config = pre_skills_database.alembic_config
    command.upgrade(config, PRE_RESOURCE_BINDING_SCOPE_REVISION)

    tenant_id = _insert_tenant(connection, "rolling")
    user_id = _insert_user(connection, tenant_id, "rolling")
    space_id = _insert_space(connection, tenant_id, "rolling")
    assistant_id = _insert_assistant(
        connection,
        user_id=user_id,
        space_id=space_id,
    )
    app_id = _insert_app(
        connection,
        tenant_id=tenant_id,
        user_id=user_id,
        space_id=space_id,
    )
    skill_id, revision_id = _insert_skill(
        connection,
        space_id=space_id,
        created_by_user_id=user_id,
        label="rolling",
    )

    def insert_legacy_bindings() -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO assistant_skill_bindings (
                    assistant_id, space_id, skill_id, skill_revision_id, position
                )
                VALUES (%s, %s, %s, %s, 0)
                """,
                (assistant_id, space_id, skill_id, revision_id),
            )
            cursor.execute(
                """
                INSERT INTO app_skill_bindings (
                    app_id, space_id, skill_id, skill_revision_id, position
                )
                VALUES (%s, %s, %s, %s, 0)
                """,
                (app_id, space_id, skill_id, revision_id),
            )

    insert_legacy_bindings()
    command.upgrade(config, SKILLS_HEAD_REVISION)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT tenant_id, skill_space_id
            FROM assistant_skill_bindings
            WHERE assistant_id = %s
            """,
            (assistant_id,),
        )
        upgraded_assistant_scope = cursor.fetchone()
        cursor.execute(
            """
            SELECT tenant_id, skill_space_id
            FROM app_skill_bindings
            WHERE app_id = %s
            """,
            (app_id,),
        )
        upgraded_app_scope = cursor.fetchone()
        cursor.execute(
            "DELETE FROM assistant_skill_bindings WHERE assistant_id = %s",
            (assistant_id,),
        )
        cursor.execute(
            "DELETE FROM app_skill_bindings WHERE app_id = %s",
            (app_id,),
        )

    assert upgraded_assistant_scope == (tenant_id, space_id)
    assert upgraded_app_scope == (tenant_id, space_id)

    insert_legacy_bindings()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT tenant_id, skill_space_id
            FROM assistant_skill_bindings
            WHERE assistant_id = %s
            """,
            (assistant_id,),
        )
        rolling_assistant_scope = cursor.fetchone()
        cursor.execute(
            """
            SELECT tenant_id, skill_space_id
            FROM app_skill_bindings
            WHERE app_id = %s
            """,
            (app_id,),
        )
        rolling_app_scope = cursor.fetchone()

    assert rolling_assistant_scope == (tenant_id, space_id)
    assert rolling_app_scope == (tenant_id, space_id)
