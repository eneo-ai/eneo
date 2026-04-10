"""ensure MCP security and tool sync columns exist

Revision ID: 20260410_mcp_sec_guard
Revises: 20260410_embed_nick_guard
Create Date: 2026-04-10 09:20:00.000000
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260410_mcp_sec_guard"
down_revision = "20260410_embed_nick_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Repair stamped databases where the canonical mcp_security_classification
    # migration is considered applied but its physical columns are absent.
    op.execute(
        """
        ALTER TABLE mcp_servers
        ADD COLUMN IF NOT EXISTS security_classification_id uuid
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_mcp_servers_security_classification_id'
            ) THEN
                ALTER TABLE mcp_servers
                ADD CONSTRAINT fk_mcp_servers_security_classification_id
                FOREIGN KEY (security_classification_id)
                REFERENCES security_classifications(id)
                ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        ALTER TABLE mcp_server_tools
        ADD COLUMN IF NOT EXISTS pending_description text,
        ADD COLUMN IF NOT EXISTS pending_input_schema jsonb,
        ADD COLUMN IF NOT EXISTS requires_approval boolean NOT NULL DEFAULT false,
        ADD COLUMN IF NOT EXISTS removed_from_remote boolean NOT NULL DEFAULT false
        """
    )
    op.execute(
        """
        UPDATE mcp_server_tools
        SET requires_approval = false
        WHERE requires_approval IS NULL
        """
    )
    op.execute(
        """
        UPDATE mcp_server_tools
        SET removed_from_remote = false
        WHERE removed_from_remote IS NULL
        """
    )
    op.execute(
        """
        ALTER TABLE mcp_server_tools
        ALTER COLUMN requires_approval SET DEFAULT false,
        ALTER COLUMN requires_approval SET NOT NULL,
        ALTER COLUMN removed_from_remote SET DEFAULT false,
        ALTER COLUMN removed_from_remote SET NOT NULL
        """
    )


def downgrade() -> None:
    # No-op intentionally: these columns are owned by the earlier canonical
    # mcp_security_classification migration. This guard only repairs drifted DBs.
    pass
