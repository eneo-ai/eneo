"""repair remaining stamped schema drift

Revision ID: 20260410_schema_drift_guard
Revises: 20260410_mcp_sec_guard
Create Date: 2026-04-10 09:35:00.000000
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260410_schema_drift_guard"
down_revision = "20260410_mcp_sec_guard"
branch_labels = None
depends_on = None


def _add_fk_if_missing(constraint_name: str, ddl: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = '{constraint_name}'
            ) THEN
                {ddl}
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    # Repair additional ORM-vs-physical-schema drift observed in dev databases
    # stamped at head. These are intentionally idempotent and additive.
    op.execute(
        """
        ALTER TABLE group_chats
        ADD COLUMN IF NOT EXISTS icon_id uuid
        """
    )
    _add_fk_if_missing(
        "fk_group_chats_icon_id",
        """
        ALTER TABLE group_chats
        ADD CONSTRAINT fk_group_chats_icon_id
        FOREIGN KEY (icon_id)
        REFERENCES icons(id)
        ON DELETE SET NULL;
        """,
    )

    op.execute(
        """
        ALTER TABLE groups_spaces
        ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now()
        """
    )
    op.execute(
        """
        ALTER TABLE websites_spaces
        ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now()
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS mcp_server_settings (
            tenant_id uuid NOT NULL,
            mcp_server_id uuid NOT NULL,
            is_org_enabled boolean NOT NULL DEFAULT true,
            env_vars jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, mcp_server_id)
        )
        """
    )
    _add_fk_if_missing(
        "fk_mcp_server_settings_tenant_id",
        """
        ALTER TABLE mcp_server_settings
        ADD CONSTRAINT fk_mcp_server_settings_tenant_id
        FOREIGN KEY (tenant_id)
        REFERENCES tenants(id)
        ON DELETE CASCADE;
        """,
    )
    _add_fk_if_missing(
        "fk_mcp_server_settings_mcp_server_id",
        """
        ALTER TABLE mcp_server_settings
        ADD CONSTRAINT fk_mcp_server_settings_mcp_server_id
        FOREIGN KEY (mcp_server_id)
        REFERENCES mcp_servers(id)
        ON DELETE CASCADE;
        """,
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_action_config (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            tenant_id uuid NOT NULL,
            action varchar(100) NOT NULL,
            enabled boolean NOT NULL DEFAULT true,
            PRIMARY KEY (tenant_id, action, id)
        )
        """
    )
    _add_fk_if_missing(
        "fk_audit_action_config_tenant_id",
        """
        ALTER TABLE audit_action_config
        ADD CONSTRAINT fk_audit_action_config_tenant_id
        FOREIGN KEY (tenant_id)
        REFERENCES tenants(id)
        ON DELETE CASCADE;
        """,
    )


def downgrade() -> None:
    # No-op intentionally: this guard repairs drifted development DBs without
    # taking ownership of columns/tables that belong to earlier feature work.
    pass
