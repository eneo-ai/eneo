"""PostgreSQL contract tests for the first-class Skills migrations.

Run in the migration-isolation lane:

    pytest -m migration_isolation \
        tests/integration/migrations/test_skills_schema_round_trip.py -v
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extensions import connection as PgConnection

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_SKILLS_REVISION = "202607071200"
SKILLS_SCHEMA_REVISION = "202607151200"
SKILLS_HEAD_REVISION = "202607151300"


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
) -> str:
    role_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO roles (
                id, name, permissions, tenant_id, predefined_source,
                created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, NULL, now(), now())
            """,
            (role_id, f"Skills {label} {uuid4().hex[:6]}", permissions, tenant_id),
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
    for qualifying_role in ("assistants", "apps", "admin", "ai", "already_granted"):
        permissions = _permissions(connection, role_ids[qualifying_role])
        assert permissions.count("skills") == 1
    for qualifying_role in ("admin", "ai", "already_managed"):
        permissions = _permissions(connection, role_ids[qualifying_role])
        assert permissions.count("skills_management") == 1
    for use_only_role in ("assistants", "apps", "already_granted"):
        assert "skills_management" not in _permissions(
            connection, role_ids[use_only_role]
        )
    assert "skills" not in _permissions(connection, role_ids["unrelated"])
    assert "skills_management" not in _permissions(connection, role_ids["unrelated"])

    expected_indexes = {
        "uq_assistants_space_id_id",
        "uq_apps_space_id_id",
        "uq_spaces_tenant_id_id",
        "uq_governance_policies_tenant_id_id",
        "ix_assistant_skill_bindings_skill_id",
        "ix_app_skill_bindings_skill_id",
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
        "(tenant_id, skill_space_id)"
        in indexes["ix_governance_policy_skill_bindings_tenant_space"][2]
    )

    command.downgrade(config, SKILLS_SCHEMA_REVISION)
    assert _current_revision(connection) == SKILLS_SCHEMA_REVISION
    for role_id in role_ids.values():
        assert "skills" not in _permissions(connection, role_id)
        assert "skills_management" not in _permissions(connection, role_id)

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
        expected="ck_assistant_skill_bindings_position_nonnegative",
        statement="""
            INSERT INTO assistant_skill_bindings (
                assistant_id, skill_id, skill_revision_id, space_id, position
            )
            VALUES (%s, %s, %s, %s, -1)
        """,
        parameters=(assistant_id, primary_skill, primary_revision, space_a),
    )
    _assert_constraint(
        connection,
        expected="fk_assistant_skill_bindings_skill",
        statement="""
            INSERT INTO assistant_skill_bindings (
                assistant_id, skill_id, skill_revision_id, space_id, position
            )
            VALUES (%s, %s, %s, %s, 0)
        """,
        parameters=(
            assistant_id,
            sibling_skill,
            sibling_revision,
            space_a,
        ),
    )
    _assert_constraint(
        connection,
        expected="fk_app_skill_bindings_skill",
        statement="""
            INSERT INTO app_skill_bindings (
                app_id, skill_id, skill_revision_id, space_id, position
            )
            VALUES (%s, %s, %s, %s, 0)
        """,
        parameters=(app_id, sibling_skill, sibling_revision, space_a),
    )
    _assert_constraint(
        connection,
        expected="fk_assistant_skill_bindings_revision",
        statement="""
            INSERT INTO assistant_skill_bindings (
                assistant_id, skill_id, skill_revision_id, space_id, position
            )
            VALUES (%s, %s, %s, %s, 0)
        """,
        parameters=(assistant_id, primary_skill, peer_revision, space_a),
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
                assistant_id, skill_id, skill_revision_id, space_id, position
            )
            VALUES (%s, %s, %s, %s, 0)
            """,
            (assistant_id, primary_skill, primary_revision, space_a),
        )

    _assert_constraint(
        connection,
        expected="uq_assistant_skill_bindings_assistant_id_position",
        statement="""
            INSERT INTO assistant_skill_bindings (
                assistant_id, skill_id, skill_revision_id, space_id, position
            )
            VALUES (%s, %s, %s, %s, 0)
        """,
        parameters=(assistant_id, peer_skill, peer_revision, space_a),
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
                app_id, skill_id, skill_revision_id, space_id, position
            )
            VALUES (%s, %s, %s, %s, 0)
            """,
            (app_id, peer_skill, peer_revision, space_a),
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
