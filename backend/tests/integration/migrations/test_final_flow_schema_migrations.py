"""Migration contracts for the final two-revision core Flow schema."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import (
    current_revisions,
    reset_public_schema,
)

pytestmark = pytest.mark.migration_isolation

DEVELOP_REVISION = "202608181000"
CORE_SCHEMA_REVISION = "202608201000"
CORE_HEAD_REVISION = "202608201100"

CORE_TABLES = {
    "flow_package_imports",
    "flow_provider_calls",
    "flow_resource_bindings",
    "flow_run_audit_outbox",
    "flow_run_review_checkpoints",
    "flow_run_step_input_files",
    "flow_run_step_result_files",
    "flow_run_webhook_deliveries",
    "flow_runs",
    "flow_runtime_uploaded_files",
    "flow_step_attempt_resolved_inputs",
    "flow_step_attempts",
    "flow_step_results",
    "flow_steps",
    "flow_template_assets",
    "flow_versions",
    "flows",
    "provider_token_usages",
    "service_principals",
}
BUILDER_TABLES = {"builder_sessions", "builder_session_files", "builder_plans"}
REMOVED_PRIVATE_TABLES = {
    "flow_classification_retention_policies",
    "flow_run_rerun_invalidated_steps",
    "flow_run_rerun_operations",
}

# The files schema at CORE_HEAD_REVISION, read by name, as the revision left it
# when it copied user_id into a new owner_user_id column. Renaming the column
# instead must arrive at exactly this schema; only the column's position differs.
FILES_SCHEMA_AT_CORE_HEAD = {
    "columns": {
        "blob": ("bytea", False, None),
        "checksum": ("character varying", False, None),
        "created_at": ("timestamp with time zone", True, "now()"),
        "file_type": ("character varying", True, "'text'::character varying"),
        "id": ("uuid", True, "gen_random_uuid()"),
        "mimetype": ("character varying", False, None),
        "name": ("character varying", True, None),
        "owner_service_id": ("uuid", False, None),
        "owner_type": ("character varying", True, "'user'::character varying"),
        "owner_user_id": ("uuid", False, None),
        "parent_file_id": ("uuid", False, None),
        "size": ("integer", False, None),
        "tenant_id": ("uuid", True, None),
        "text": ("text", False, None),
        "transcription": ("character varying", False, None),
        "updated_at": ("timestamp with time zone", True, "now()"),
    },
    "constraints": {
        "ck_files_owner_identity": (
            "CHECK (((((owner_type)::text = 'user'::text) AND "
            "(owner_user_id IS NOT NULL) AND (owner_service_id IS NULL)) OR "
            "(((owner_type)::text = 'service_key'::text) AND "
            "(owner_user_id IS NULL) AND (owner_service_id IS NOT NULL))))",
            " ",
            True,
        ),
        "ck_files_owner_type": (
            "CHECK (((owner_type)::text = ANY ((ARRAY['user'::character varying, "
            "'service_key'::character varying])::text[])))",
            " ",
            True,
        ),
        "files_parent_file_id_fkey": (
            "FOREIGN KEY (parent_file_id) REFERENCES files(id) ON DELETE CASCADE",
            "c",
            True,
        ),
        "files_pkey": ("PRIMARY KEY (id)", " ", True),
        "files_tenants_fkey": (
            "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE",
            "c",
            True,
        ),
        "fk_files_owner_service_id": (
            "FOREIGN KEY (owner_service_id) REFERENCES service_principals(id) "
            "ON DELETE RESTRICT",
            "r",
            True,
        ),
        "fk_files_owner_user_id": (
            "FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE RESTRICT",
            "r",
            True,
        ),
        "uq_files_id_tenant_id": ("UNIQUE (id, tenant_id)", " ", True),
    },
    "indexes": {
        "files_pkey": (
            "CREATE UNIQUE INDEX files_pkey ON public.files USING btree (id)",
            True,
        ),
        "ix_files_checksum": (
            "CREATE INDEX ix_files_checksum ON public.files USING btree (checksum)",
            True,
        ),
        "ix_files_parent_file_id": (
            "CREATE INDEX ix_files_parent_file_id ON public.files "
            "USING btree (parent_file_id)",
            True,
        ),
        "ix_files_service_owner_created_at": (
            "CREATE INDEX ix_files_service_owner_created_at ON public.files "
            "USING btree (tenant_id, owner_service_id, created_at) "
            "WHERE ((owner_type)::text = 'service_key'::text)",
            True,
        ),
        "uq_files_id_tenant_id": (
            "CREATE UNIQUE INDEX uq_files_id_tenant_id ON public.files "
            "USING btree (id, tenant_id)",
            True,
        ),
    },
}


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parents[3]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


@pytest.fixture
def migration_db(test_settings):
    cfg = _alembic_cfg(test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True

    reset_public_schema(conn)
    command.upgrade(cfg, DEVELOP_REVISION)
    try:
        yield conn, cfg
    finally:
        reset_public_schema(conn)
        command.upgrade(cfg, "head")
        conn.close()


def test_final_core_revision_owns_only_surviving_core_schema(migration_db) -> None:
    conn, cfg = migration_db

    assert not CORE_TABLES & _public_tables(conn)
    command.upgrade(cfg, CORE_SCHEMA_REVISION)

    tables = _public_tables(conn)
    assert CORE_TABLES <= tables
    assert not BUILDER_TABLES & tables
    assert not REMOVED_PRIVATE_TABLES & tables
    assert _column_exists(conn, "flow_step_attempts", "dispatch_task_id")
    assert not _column_exists(conn, "flow_step_attempts", "celery_task_id")
    assert not _constraint_exists(
        conn,
        "security_classifications",
        "uq_security_classifications_id_tenant_id",
    )

    command.upgrade(cfg, CORE_HEAD_REVISION)
    assert current_revisions(conn) == {CORE_HEAD_REVISION}
    assert _column_exists(conn, "api_keys_v2", "service_principal_id")
    assert _column_exists(conn, "files", "owner_service_id")
    assert _column_exists(conn, "audit_logs", "actor_api_key_id")
    assert _column_exists(conn, "completion_models", "supports_strict_tool_schema")
    assert _column_exists(conn, "tenants", "flow_settings")


def test_integration_backfills_owners_and_survives_full_round_trip(
    migration_db,
) -> None:
    conn, cfg = migration_db
    command.upgrade(cfg, CORE_SCHEMA_REVISION)
    seeded = _seed_develop_shaped_data(conn)

    command.upgrade(cfg, CORE_HEAD_REVISION)
    first_principal_id = _assert_integration_backfill(conn, seeded)
    assert _constraint_is_validated(conn, "ck_api_keys_v2_service_principal_required")
    assert _constraint_is_validated(conn, "ck_files_owner_identity")
    assert _constraint_is_validated(
        conn, "ck_tenants_flow_run_history_retention_days_range"
    )

    command.downgrade(cfg, DEVELOP_REVISION)
    assert current_revisions(conn) == {DEVELOP_REVISION}
    assert not CORE_TABLES & _public_tables(conn)
    assert _column_exists(conn, "files", "user_id")
    assert not _column_exists(conn, "files", "owner_user_id")
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM files WHERE id = %s", (seeded["file_id"],))
        assert cur.fetchone()[0] == str(seeded["user_id"])
        cur.execute(
            "SELECT count(*) FROM api_keys_v2 WHERE id = ANY(%s)",
            (list(seeded["service_key_ids"]),),
        )
        assert cur.fetchone()[0] == 2

    command.upgrade(cfg, CORE_HEAD_REVISION)
    replayed_principal_id = _assert_integration_backfill(conn, seeded)
    assert replayed_principal_id != first_principal_id
    assert current_revisions(conn) == {CORE_HEAD_REVISION}


def test_final_constraints_reject_cross_owner_and_invalid_retention(
    migration_db,
) -> None:
    conn, cfg = migration_db
    command.upgrade(cfg, CORE_SCHEMA_REVISION)
    seeded = _seed_develop_shaped_data(conn)
    command.upgrade(cfg, CORE_HEAD_REVISION)
    principal_id = _assert_integration_backfill(conn, seeded)

    with pytest.raises(psycopg2.Error):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE files SET owner_service_id = %s WHERE id = %s",
                (principal_id, seeded["file_id"]),
            )
    conn.rollback()

    with pytest.raises(psycopg2.Error):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tenants SET flow_run_history_retention_days = 0 WHERE id = %s",
                (seeded["tenant_id"],),
            )
    conn.rollback()


def test_owner_upgrade_rewrites_no_file_row_and_matches_the_copied_owner_schema(
    migration_db,
) -> None:
    conn, cfg = migration_db
    command.upgrade(cfg, CORE_SCHEMA_REVISION)
    seeded = _seed_develop_shaped_data(conn)
    row_versions = _file_row_versions(conn)
    filenode = _files_filenode(conn)

    command.upgrade(cfg, CORE_HEAD_REVISION)

    assert len(row_versions) == len(seeded["file_owners"])
    assert _file_row_versions(conn) == row_versions
    assert _files_filenode(conn) == filenode
    with conn.cursor() as cur:
        cur.execute("SELECT id, owner_type, owner_user_id, owner_service_id FROM files")
        assert sorted(cur.fetchall()) == sorted(
            (str(file_id), "user", str(user_id), None)
            for file_id, user_id in seeded["file_owners"].items()
        )
    upgraded = _files_schema(conn)
    assert upgraded == FILES_SCHEMA_AT_CORE_HEAD
    assert "files_users_fkey" not in upgraded["constraints"]

    reset_public_schema(conn)
    command.upgrade(cfg, CORE_HEAD_REVISION)
    assert _files_schema(conn) == FILES_SCHEMA_AT_CORE_HEAD


def test_file_owner_rules_after_upgrade_and_downgrade_refusal(migration_db) -> None:
    conn, cfg = migration_db
    command.upgrade(cfg, CORE_SCHEMA_REVISION)
    seeded = _seed_develop_shaped_data(conn)
    command.upgrade(cfg, CORE_HEAD_REVISION)
    tenant_id = seeded["tenant_id"]
    user_id = seeded["user_id"]
    principal_id = _insert_service_principal(conn, tenant_id=tenant_id)

    _insert_owned_file(conn, tenant_id, "user", user_id, None)
    _insert_owned_file(conn, tenant_id, "service_key", None, principal_id)

    rejected = [
        (("user", None, None), "ck_files_owner_identity"),
        (("user", user_id, principal_id), "ck_files_owner_identity"),
        (("service_key", None, None), "ck_files_owner_identity"),
        (("service_key", user_id, None), "ck_files_owner_identity"),
        (("user", uuid4(), None), "fk_files_owner_user_id"),
        (("service_key", None, uuid4()), "fk_files_owner_service_id"),
    ]
    for owner, constraint in rejected:
        with pytest.raises(psycopg2.Error) as error:
            _insert_owned_file(conn, tenant_id, *owner)
        assert error.value.diag.constraint_name == constraint, owner

    with pytest.raises(psycopg2.Error) as error, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s", (seeded["second_user_id"],))
    assert error.value.diag.constraint_name == "fk_files_owner_user_id"
    with pytest.raises(psycopg2.Error) as error, conn.cursor() as cur:
        cur.execute("DELETE FROM service_principals WHERE id = %s", (principal_id,))
    assert error.value.diag.constraint_name == "fk_files_owner_service_id"

    schema = _files_schema(conn)
    with pytest.raises(RuntimeError, match="service-owned files exist"):
        command.downgrade(cfg, CORE_SCHEMA_REVISION)
    assert current_revisions(conn) == {CORE_HEAD_REVISION}
    assert _files_schema(conn) == schema


def test_downgrade_restores_develop_file_owner_from_either_layout(
    migration_db,
) -> None:
    conn, cfg = migration_db
    command.upgrade(cfg, CORE_SCHEMA_REVISION)
    seeded = _seed_develop_shaped_data(conn)
    develop_schema = _files_schema(conn)
    owners = {
        str(file_id): str(user_id) for file_id, user_id in seeded["file_owners"].items()
    }

    for owner_column in ("renamed", "appended"):
        command.upgrade(cfg, CORE_HEAD_REVISION)
        if owner_column == "appended":
            _append_owner_user_column_as_the_copying_revision_did(conn)
        row_versions = _file_row_versions(conn)

        command.downgrade(cfg, CORE_SCHEMA_REVISION)

        assert _files_schema(conn) == develop_schema, owner_column
        assert _file_row_versions(conn) == row_versions, owner_column
        with conn.cursor() as cur:
            cur.execute("SELECT id, user_id FROM files")
            assert dict(cur.fetchall()) == owners, owner_column

    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s", (seeded["second_user_id"],))
        cur.execute(
            "SELECT count(*) FROM files WHERE id = %s", (seeded["second_file_id"],)
        )
        assert cur.fetchone()[0] == 0


def test_migrated_audit_source_permits_abandonment(migration_db) -> None:
    conn, cfg = migration_db
    command.upgrade(cfg, "head")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'flow_run_audit_outbox'::regclass "
            "AND conname = 'ck_flow_run_audit_outbox_source'"
        )
        assert "'abandonment_reconciler'" in cur.fetchone()[0]


def _seed_develop_shaped_data(conn) -> dict[str, object]:
    tenant_id = uuid4()
    user_id = uuid4()
    second_user_id = uuid4()
    file_id = uuid4()
    derived_file_id = uuid4()
    second_file_id = uuid4()
    tenant_name = f"final-flow-migration-{tenant_id}"

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
        for seeded_user_id in (user_id, second_user_id):
            cur.execute(
                """
                INSERT INTO users (
                    id, username, email, email_verified, salt, password, is_active,
                    state, used_tokens, tenant_id, quota_limit
                )
                VALUES (%s, %s, %s, true, NULL, NULL, true, 'active', 0, %s, NULL)
                """,
                (
                    seeded_user_id,
                    f"user-{seeded_user_id}",
                    f"{seeded_user_id}@example.test",
                    tenant_id,
                ),
            )
        cur.execute(
            """
            INSERT INTO files (id, name, mimetype, file_type, user_id, tenant_id)
            VALUES (%s, 'source.pdf', 'application/pdf', 'document', %s, %s)
            """,
            (file_id, user_id, tenant_id),
        )
        cur.execute(
            """
            INSERT INTO files (
                id, name, mimetype, file_type, user_id, tenant_id, parent_file_id
            )
            VALUES (%s, 'page-1.png', 'image/png', 'image', %s, %s, %s)
            """,
            (derived_file_id, user_id, tenant_id, file_id),
        )
        cur.execute(
            """
            INSERT INTO files (id, name, mimetype, file_type, user_id, tenant_id)
            VALUES (%s, 'notes.txt', 'text/plain', 'text', %s, %s)
            """,
            (second_file_id, second_user_id, tenant_id),
        )

    root_key_id = _insert_api_key(
        conn,
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        ownership="service",
        name="Service root",
    )
    child_key_id = _insert_api_key(
        conn,
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        ownership="service",
        name="Service child",
        rotated_from_key_id=root_key_id,
    )
    user_key_id = _insert_api_key(
        conn,
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        ownership="user",
        name="User key",
    )
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "second_user_id": second_user_id,
        "file_id": file_id,
        "second_file_id": second_file_id,
        "file_owners": {
            file_id: user_id,
            derived_file_id: user_id,
            second_file_id: second_user_id,
        },
        "service_key_ids": (root_key_id, child_key_id),
        "user_key_id": user_key_id,
    }


def _insert_service_principal(conn, *, tenant_id: UUID) -> UUID:
    principal_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO service_principals (id, tenant_id, display_name, scope_type)
            VALUES (%s, %s, 'File owner', 'tenant')
            """,
            (principal_id, tenant_id),
        )
    return principal_id


def _insert_owned_file(
    conn,
    tenant_id: UUID,
    owner_type: str,
    owner_user_id: UUID | None,
    owner_service_id: UUID | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO files (
                id, name, mimetype, file_type, tenant_id,
                owner_type, owner_user_id, owner_service_id
            )
            VALUES (%s, 'owned.txt', 'text/plain', 'text', %s, %s, %s, %s)
            """,
            (uuid4(), tenant_id, owner_type, owner_user_id, owner_service_id),
        )


def _append_owner_user_column_as_the_copying_revision_did(conn) -> None:
    """Lay files out as the revision did before it renamed user_id.

    That revision added owner_user_id as a new column and copied user_id into it,
    so the column came after every develop column and user_id was left as a
    dropped attribute. The two constraints on the column are recreated from their
    own definitions, so the schema read by name does not change.
    """
    schema = _files_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'files'::regclass
              AND conname IN ('fk_files_owner_user_id', 'ck_files_owner_identity')
            """
        )
        definitions = cur.fetchall()
        cur.execute("ALTER TABLE files ADD COLUMN copied_owner_user_id uuid")
        cur.execute("UPDATE files SET copied_owner_user_id = owner_user_id")
        cur.execute("ALTER TABLE files DROP COLUMN owner_user_id")
        cur.execute(
            "ALTER TABLE files RENAME COLUMN copied_owner_user_id TO owner_user_id"
        )
        for name, definition in definitions:
            cur.execute(f"ALTER TABLE files ADD CONSTRAINT {name} {definition}")
    assert len(definitions) == 2
    assert _files_schema(conn) == schema


def _file_row_versions(conn) -> dict[str, tuple[str, str]]:
    """Each file row's transaction id and physical place; an UPDATE changes both."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, xmin::text, ctid::text FROM files")
        return {file_id: (xmin, ctid) for file_id, xmin, ctid in cur.fetchall()}


def _files_filenode(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_relation_filenode('files')")
        return cur.fetchone()[0]


def _files_schema(conn) -> dict[str, dict[str, tuple]]:
    """The files table's columns, constraints and indexes, keyed by name."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT attribute.attname,
                   format_type(attribute.atttypid, attribute.atttypmod),
                   attribute.attnotnull,
                   pg_get_expr(column_default.adbin, column_default.adrelid)
            FROM pg_attribute AS attribute
            LEFT JOIN pg_attrdef AS column_default
              ON column_default.adrelid = attribute.attrelid
             AND column_default.adnum = attribute.attnum
            WHERE attribute.attrelid = 'files'::regclass
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
            """
        )
        columns = {name: tuple(rest) for name, *rest in cur.fetchall()}
        cur.execute(
            """
            SELECT conname, pg_get_constraintdef(oid), confdeltype, convalidated
            FROM pg_constraint
            WHERE conrelid = 'files'::regclass
            """
        )
        constraints = {name: tuple(rest) for name, *rest in cur.fetchall()}
        cur.execute(
            """
            SELECT index_class.relname,
                   pg_get_indexdef(index_row.indexrelid),
                   index_row.indisvalid
            FROM pg_index AS index_row
            JOIN pg_class AS index_class ON index_class.oid = index_row.indexrelid
            WHERE index_row.indrelid = 'files'::regclass
            """
        )
        indexes = {name: tuple(rest) for name, *rest in cur.fetchall()}
    return {"columns": columns, "constraints": constraints, "indexes": indexes}


def _insert_api_key(
    conn,
    *,
    tenant_id: UUID,
    created_by_user_id: UUID,
    ownership: str,
    name: str,
    rotated_from_key_id: UUID | None = None,
) -> UUID:
    key_id = uuid4()
    owner_user_id = created_by_user_id if ownership == "user" else None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO api_keys_v2 (
                id, tenant_id, ownership, owner_user_id, created_by_user_id,
                scope_type, scope_id, permission, key_type, key_hash,
                hash_version, key_prefix, key_suffix, name, state,
                rotated_from_key_id, delegation_depth
            )
            VALUES (
                %s, %s, %s, %s, %s, 'tenant', NULL, 'write', 'sk_', %s,
                'hmac_sha256', 'sk_', %s, %s, 'active', %s, 0
            )
            """,
            (
                key_id,
                tenant_id,
                ownership,
                owner_user_id,
                created_by_user_id,
                f"hash-{key_id}",
                str(key_id)[-8:],
                name,
                rotated_from_key_id,
            ),
        )
    return key_id


def _assert_integration_backfill(conn, seeded: dict[str, object]) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT owner_type, owner_user_id, owner_service_id
            FROM files
            WHERE id = %s
            """,
            (seeded["file_id"],),
        )
        assert cur.fetchone() == ("user", str(seeded["user_id"]), None)
        cur.execute(
            """
            SELECT service_principal_id
            FROM api_keys_v2
            WHERE id = ANY(%s)
            ORDER BY id
            """,
            (list(seeded["service_key_ids"]),),
        )
        principal_ids = [row[0] for row in cur.fetchall()]
        cur.execute(
            "SELECT service_principal_id FROM api_keys_v2 WHERE id = %s",
            (seeded["user_key_id"],),
        )
        assert cur.fetchone()[0] is None

    assert len(principal_ids) == 2
    assert principal_ids[0] is not None
    assert len(set(principal_ids)) == 1
    return str(principal_ids[0])


def _public_tables(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            """
        )
        return {row[0] for row in cur.fetchall()}


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = %s
                  AND column_name = %s
            )
            """,
            (table_name, column_name),
        )
        return cur.fetchone()[0]


def _constraint_exists(conn, table_name: str, constraint_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_constraint constraint_row
                JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
                WHERE table_row.relname = %s
                  AND constraint_row.conname = %s
            )
            """,
            (table_name, constraint_name),
        )
        return cur.fetchone()[0]


def _constraint_is_validated(conn, constraint_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT convalidated FROM pg_constraint WHERE conname = %s",
            (constraint_name,),
        )
        row = cur.fetchone()
    return bool(row and row[0])
