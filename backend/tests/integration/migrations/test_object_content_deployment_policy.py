from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202607241100"
POLICY_REVISION = "202607251700"
SEED_VARIABLES = (
    "UPLOAD_FILE_TO_SESSION_MAX_SIZE",
    "UPLOAD_IMAGE_TO_SESSION_MAX_SIZE",
    "UPLOAD_MAX_FILE_SIZE",
    "TRANSCRIPTION_MAX_FILE_SIZE",
)


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


@pytest.fixture
def round_trip_db(test_settings):
    config = _alembic_cfg(test_settings.sync_database_url)
    connection = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    connection.autocommit = True
    command.upgrade(config, POLICY_REVISION)
    try:
        yield connection, config
    finally:
        connection.close()


def _policy_limits(connection) -> tuple[int, int, int, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                session_file_limit_bytes,
                session_image_limit_bytes,
                knowledge_file_limit_bytes,
                transcription_audio_limit_bytes
            FROM object_content_deployment_policy
            WHERE id = 1
            """
        )
        return tuple(cursor.fetchone())


def _current_revision(connection) -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        return cursor.fetchone()[0]


def _column_exists(connection, table: str, column: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = %s
                  AND column_name = %s
            )
            """,
            (table, column),
        )
        return bool(cursor.fetchone()[0])


def test_upgrade_preserves_exact_legacy_values_once(round_trip_db, monkeypatch) -> None:
    connection, config = round_trip_db
    command.downgrade(config, PRE_REVISION)
    for variable, value in zip(SEED_VARIABLES, ("11", "12", "13", "14")):
        monkeypatch.setenv(variable, value)

    command.upgrade(config, POLICY_REVISION)
    assert _policy_limits(connection) == (11, 12, 13, 14)

    for variable in SEED_VARIABLES:
        monkeypatch.setenv(variable, "999")
    command.upgrade(config, POLICY_REVISION)
    assert _policy_limits(connection) == (11, 12, 13, 14)


def test_upgrade_uses_defaults_only_for_absent_values(
    round_trip_db, monkeypatch
) -> None:
    connection, config = round_trip_db
    command.downgrade(config, PRE_REVISION)
    for variable in SEED_VARIABLES:
        monkeypatch.delenv(variable, raising=False)

    command.upgrade(config, POLICY_REVISION)

    assert _policy_limits(connection) == (
        10 * 1024**2,
        10 * 1024**2,
        10 * 1024**2,
        200 * 1024**2,
    )


def test_database_limit_constraint_matches_json_safe_integer_contract(
    round_trip_db,
) -> None:
    connection, _config = round_trip_db
    maximum = 9_007_199_254_740_991
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE object_content_deployment_policy
            SET
                session_file_limit_bytes = %s,
                session_image_limit_bytes = %s,
                knowledge_file_limit_bytes = %s,
                transcription_audio_limit_bytes = %s
            WHERE id = 1
            """,
            (maximum, maximum, maximum, maximum),
        )

    with pytest.raises(psycopg2.errors.CheckViolation):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE object_content_deployment_policy
                SET session_file_limit_bytes = %s
                WHERE id = 1
                """,
                (maximum + 1,),
            )


def test_invalid_present_seed_rolls_back_and_names_variable(
    round_trip_db, monkeypatch
) -> None:
    connection, config = round_trip_db
    command.downgrade(config, PRE_REVISION)
    monkeypatch.setenv("UPLOAD_MAX_FILE_SIZE", "")

    with pytest.raises(ValueError, match="UPLOAD_MAX_FILE_SIZE"):
        command.upgrade(config, POLICY_REVISION)

    assert _current_revision(connection) == PRE_REVISION
    assert not _column_exists(connection, "users", "is_platform_admin")
    assert not _column_exists(
        connection,
        "object_content_deployment_policy",
        "id",
    )


def test_downgrade_reupgrade_and_actor_delete_are_safe(
    round_trip_db, monkeypatch
) -> None:
    connection, config = round_trip_db
    command.downgrade(config, PRE_REVISION)
    actor_user_id = str(uuid4())
    survivor_user_id = str(uuid4())
    tenant_id = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenants (id, name, quota_limit, state)
            VALUES (%s, %s, 1000000, 'active')
            """,
            (tenant_id, f"policy-migration-{uuid4().hex[:8]}"),
        )
        for user_id in (actor_user_id, survivor_user_id):
            cursor.execute(
                """
                INSERT INTO users (
                    id, email, email_verified, is_active, state, used_tokens,
                    tenant_id, is_system_user
                )
                VALUES (%s, %s, true, true, 'active', 0, %s, false)
                """,
                (user_id, f"{user_id}@example.com", tenant_id),
            )
    for variable in SEED_VARIABLES:
        monkeypatch.setenv(variable, "17")

    command.upgrade(config, POLICY_REVISION)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT is_platform_admin FROM users WHERE id = %s",
            (actor_user_id,),
        )
        assert cursor.fetchone()[0] is False
        cursor.execute(
            """
            UPDATE object_content_deployment_policy
            SET updated_by_actor = 'platform_admin', updated_by_user_id = %s
            WHERE id = 1
            """,
            (actor_user_id,),
        )
        cursor.execute("DELETE FROM users WHERE id = %s", (actor_user_id,))
        cursor.execute(
            """
            SELECT updated_by_actor, updated_by_user_id
            FROM object_content_deployment_policy
            WHERE id = 1
            """
        )
        assert cursor.fetchone() == ("platform_admin", None)

    command.downgrade(config, PRE_REVISION)
    assert not _column_exists(connection, "users", "is_platform_admin")
    command.upgrade(config, POLICY_REVISION)
    assert _current_revision(connection) == POLICY_REVISION
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT is_platform_admin FROM users WHERE id = %s",
            (survivor_user_id,),
        )
        assert cursor.fetchone()[0] is False
        cursor.execute(
            """
            SELECT revision, new_write_storage_target, updated_by_actor
            FROM object_content_deployment_policy
            WHERE id = 1
            """
        )
        assert cursor.fetchone() == (1, "postgres_inline", "migration")
