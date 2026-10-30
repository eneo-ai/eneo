"""Integrate the final core Flow schema with existing platform tables.

Revision ID: 202608201100
Revises: 202608201000
Create Date: 2026-08-20 11:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202608201100"
down_revision = "202608201000"
branch_labels = None
depends_on = None


def _backfill_service_principals() -> None:
    op.execute(
        sa.text(
            """
            CREATE TEMP TABLE service_api_key_chains ON COMMIT DROP AS
            WITH RECURSIVE chains(key_id, root_key_id, path) AS (
                SELECT
                    api_key.id,
                    api_key.id,
                    ARRAY[api_key.id]
                FROM api_keys_v2 AS api_key
                LEFT JOIN api_keys_v2 AS service_parent
                  ON service_parent.id = api_key.rotated_from_key_id
                 AND service_parent.ownership = 'service'
                WHERE api_key.ownership = 'service'
                  AND service_parent.id IS NULL

                UNION ALL

                SELECT
                    child.id,
                    chains.root_key_id,
                    chains.path || child.id
                FROM api_keys_v2 AS child
                JOIN chains ON child.rotated_from_key_id = chains.key_id
                WHERE child.ownership = 'service'
                  AND NOT child.id = ANY(chains.path)
            )
            SELECT key_id, root_key_id
            FROM chains
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TEMP TABLE service_principal_backfill ON COMMIT DROP AS
            SELECT root_key_id, gen_random_uuid() AS service_principal_id
            FROM (
                SELECT DISTINCT root_key_id
                FROM service_api_key_chains
            ) AS roots
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO service_principals (
                id,
                tenant_id,
                display_name,
                description,
                scope_type,
                scope_id,
                state,
                created_by_user_id,
                created_at,
                updated_at
            )
            SELECT
                backfill.service_principal_id,
                root_key.tenant_id,
                root_key.name,
                root_key.description,
                root_key.scope_type,
                root_key.scope_id,
                'active',
                root_key.created_by_user_id,
                now(),
                now()
            FROM service_principal_backfill AS backfill
            JOIN api_keys_v2 AS root_key
              ON root_key.id = backfill.root_key_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE api_keys_v2 AS api_key
            SET service_principal_id = backfill.service_principal_id
            FROM service_api_key_chains AS chains
            JOIN service_principal_backfill AS backfill
              ON backfill.root_key_id = chains.root_key_id
            WHERE api_key.id = chains.key_id
            """
        )
    )


def _assert_service_principal_backfill() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE
                missing_service_principals integer;
                user_keys_with_service_principals integer;
                tenant_mismatches integer;
            BEGIN
                SELECT count(*)
                INTO missing_service_principals
                FROM api_keys_v2
                WHERE ownership = 'service'
                  AND service_principal_id IS NULL;

                IF missing_service_principals > 0 THEN
                    RAISE EXCEPTION
                        'Cannot introduce service principals: % service keys have no principal backfill.',
                        missing_service_principals;
                END IF;

                SELECT count(*)
                INTO user_keys_with_service_principals
                FROM api_keys_v2
                WHERE ownership = 'user'
                  AND service_principal_id IS NOT NULL;

                IF user_keys_with_service_principals > 0 THEN
                    RAISE EXCEPTION
                        'Cannot introduce service principals: % user keys have a service principal.',
                        user_keys_with_service_principals;
                END IF;

                SELECT count(*)
                INTO tenant_mismatches
                FROM api_keys_v2 AS api_key
                JOIN service_principals AS principal
                  ON principal.id = api_key.service_principal_id
                WHERE api_key.tenant_id <> principal.tenant_id;

                IF tenant_mismatches > 0 THEN
                    RAISE EXCEPTION
                        'Cannot introduce service principals: % API keys cross tenant boundaries.',
                        tenant_mismatches;
                END IF;
            END $$;
            """
        )
    )


def _add_validated_check(table: str, name: str, condition: str) -> None:
    op.create_check_constraint(
        name,
        table,
        condition,
        postgresql_not_valid=True,
    )
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def _add_service_principal_integration() -> None:
    op.add_column(
        "api_keys_v2",
        sa.Column(
            "service_principal_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    _backfill_service_principals()
    _assert_service_principal_backfill()
    _add_validated_check(
        "api_keys_v2",
        "ck_api_keys_v2_service_principal_required",
        "ownership <> 'service' OR service_principal_id IS NOT NULL",
    )
    _add_validated_check(
        "api_keys_v2",
        "ck_api_keys_v2_user_without_service_principal",
        "ownership <> 'user' OR service_principal_id IS NULL",
    )
    op.create_foreign_key(
        "fk_api_keys_v2_service_principal",
        "api_keys_v2",
        "service_principals",
        ["service_principal_id"],
        ["id"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )
    op.execute(
        "ALTER TABLE api_keys_v2 VALIDATE CONSTRAINT fk_api_keys_v2_service_principal"
    )
    op.create_index(
        "idx_api_keys_v2_service_principal_id",
        "api_keys_v2",
        ["service_principal_id"],
        postgresql_where=sa.text("service_principal_id IS NOT NULL"),
    )


def _add_file_ownership() -> None:
    op.add_column(
        "files",
        sa.Column(
            "owner_type",
            sa.String(),
            nullable=False,
            server_default="user",
        ),
    )
    op.add_column(
        "files",
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "files",
        sa.Column("owner_service_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute("UPDATE files SET owner_user_id = user_id")
    op.create_foreign_key(
        "fk_files_owner_user_id",
        "files",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )
    op.create_foreign_key(
        "fk_files_owner_service_id",
        "files",
        "service_principals",
        ["owner_service_id"],
        ["id"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )
    op.execute("ALTER TABLE files VALIDATE CONSTRAINT fk_files_owner_user_id")
    op.execute("ALTER TABLE files VALIDATE CONSTRAINT fk_files_owner_service_id")
    _add_validated_check(
        "files",
        "ck_files_owner_type",
        "owner_type IN ('user','service_key')",
    )
    _add_validated_check(
        "files",
        "ck_files_owner_identity",
        "(owner_type = 'user' AND owner_user_id IS NOT NULL "
        "AND owner_service_id IS NULL) OR "
        "(owner_type = 'service_key' AND owner_user_id IS NULL "
        "AND owner_service_id IS NOT NULL)",
    )
    op.create_index(
        "ix_files_service_owner_created_at",
        "files",
        ["tenant_id", "owner_service_id", "created_at"],
        postgresql_where=sa.text("owner_type = 'service_key'"),
    )
    op.drop_constraint("files_users_fkey", "files", type_="foreignkey")
    op.drop_column("files", "user_id")


def _add_assistant_integration() -> None:
    op.add_column(
        "assistants",
        sa.Column(
            "hidden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "assistants",
        sa.Column(
            "origin",
            sa.String(length=32),
            nullable=False,
            server_default="user",
        ),
    )
    op.add_column(
        "assistants",
        sa.Column("managing_flow_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_assistants_managing_flow_id_flows",
        "assistants",
        "flows",
        ["managing_flow_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    _add_validated_check(
        "assistants",
        "ck_assistants_origin",
        "origin IN ('user','flow_managed')",
    )
    _add_validated_check(
        "assistants",
        "ck_assistants_origin_flow_owner",
        "(origin = 'user' AND managing_flow_id IS NULL) OR "
        "(origin = 'flow_managed' AND managing_flow_id IS NOT NULL)",
    )
    _add_validated_check(
        "assistants",
        "ck_assistants_flow_managed_hidden",
        "origin <> 'flow_managed' OR hidden = true",
    )
    op.create_index(
        "ix_assistants_origin_managing_flow",
        "assistants",
        ["origin", "managing_flow_id"],
    )


def _add_retention_integration() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "flow_settings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "tenants",
        sa.Column("flow_run_history_retention_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "flow_runtime_upload_abandonment_days",
            sa.Integer(),
            nullable=True,
        ),
    )
    _add_validated_check(
        "tenants",
        "ck_tenants_flow_run_history_retention_days_range",
        "flow_run_history_retention_days IS NULL OR "
        "(flow_run_history_retention_days BETWEEN 1 AND 2555)",
    )
    _add_validated_check(
        "tenants",
        "ck_tenants_flow_runtime_upload_abandonment_days_range",
        "flow_runtime_upload_abandonment_days IS NULL OR "
        "(flow_runtime_upload_abandonment_days BETWEEN 1 AND 2555)",
    )


def upgrade() -> None:
    _add_service_principal_integration()
    _add_file_ownership()
    _add_assistant_integration()
    _add_retention_integration()
    op.add_column(
        "audit_logs",
        sa.Column("actor_api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_audit_logs_actor_api_key_id",
        "audit_logs",
        "api_keys_v2",
        ["actor_api_key_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_audit_actor_api_key",
        "audit_logs",
        ["tenant_id", "actor_api_key_id", "timestamp"],
    )
    op.add_column(
        "completion_models",
        sa.Column(
            "supports_strict_tool_schema",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def _restore_legacy_file_ownership() -> None:
    service_owned_count = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM files WHERE owner_type = 'service_key'"))
        .scalar_one()
    )
    if service_owned_count:
        raise RuntimeError(
            "Cannot downgrade Flow integration while service-owned files exist"
        )
    op.add_column(
        "files",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute("UPDATE files SET user_id = owner_user_id")
    op.alter_column(
        "files",
        "user_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.create_foreign_key(
        "files_users_fkey",
        "files",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index("ix_files_service_owner_created_at", table_name="files")
    op.drop_constraint("ck_files_owner_identity", "files", type_="check")
    op.drop_constraint("ck_files_owner_type", "files", type_="check")
    op.drop_constraint("fk_files_owner_service_id", "files", type_="foreignkey")
    op.drop_constraint("fk_files_owner_user_id", "files", type_="foreignkey")
    op.drop_column("files", "owner_service_id")
    op.drop_column("files", "owner_user_id")
    op.drop_column("files", "owner_type")


def downgrade() -> None:
    op.drop_column("completion_models", "supports_strict_tool_schema")
    op.drop_index("idx_audit_actor_api_key", table_name="audit_logs")
    op.drop_constraint(
        "fk_audit_logs_actor_api_key_id", "audit_logs", type_="foreignkey"
    )
    op.drop_column("audit_logs", "actor_api_key_id")

    op.drop_constraint(
        "ck_tenants_flow_runtime_upload_abandonment_days_range",
        "tenants",
        type_="check",
    )
    op.drop_constraint(
        "ck_tenants_flow_run_history_retention_days_range",
        "tenants",
        type_="check",
    )
    op.drop_column("tenants", "flow_runtime_upload_abandonment_days")
    op.drop_column("tenants", "flow_run_history_retention_days")
    op.drop_column("tenants", "flow_settings")

    op.drop_index("ix_assistants_origin_managing_flow", table_name="assistants")
    op.drop_constraint("ck_assistants_flow_managed_hidden", "assistants", type_="check")
    op.drop_constraint("ck_assistants_origin_flow_owner", "assistants", type_="check")
    op.drop_constraint("ck_assistants_origin", "assistants", type_="check")
    op.drop_constraint(
        "fk_assistants_managing_flow_id_flows",
        "assistants",
        type_="foreignkey",
    )
    op.drop_column("assistants", "managing_flow_id")
    op.drop_column("assistants", "origin")
    op.drop_column("assistants", "hidden")

    _restore_legacy_file_ownership()

    op.drop_index("idx_api_keys_v2_service_principal_id", table_name="api_keys_v2")
    op.drop_constraint(
        "fk_api_keys_v2_service_principal", "api_keys_v2", type_="foreignkey"
    )
    op.drop_constraint(
        "ck_api_keys_v2_user_without_service_principal",
        "api_keys_v2",
        type_="check",
    )
    op.drop_constraint(
        "ck_api_keys_v2_service_principal_required",
        "api_keys_v2",
        type_="check",
    )
    op.drop_column("api_keys_v2", "service_principal_id")
