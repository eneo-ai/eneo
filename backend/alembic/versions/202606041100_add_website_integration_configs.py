"""add website integration configs

Revision ID: 202606041100
Revises: 202602121000_rename_integration_permission
Create Date: 2026-06-04 11:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "202606041100"
down_revision = "20260603_transcription_migrate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO integrations ("name", description, integration_type)
        SELECT
            'Website',
            'Website integrations sync sitemap-backed pages into reusable website knowledge sources.',
            'website'
        WHERE NOT EXISTS (
            SELECT 1 FROM integrations WHERE integration_type = 'website'
        );
        """
    )

    op.create_table(
        "website_integration_configs",
        sa.Column("tenant_integration_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("owner_type", sa.Text(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=True),
        sa.Column("owner_space_id", sa.UUID(), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sitemap_url", sa.Text(), nullable=False),
        sa.Column("markdown_endpoint_url", sa.Text(), nullable=True),
        sa.Column(
            "headers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "sync_status", sa.Text(), nullable=False, server_default=sa.text("'idle'")
        ),
        sa.Column("last_sitemap_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("last_sync_queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_integration_id"], ["tenant_integrations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_website_integration_configs_tenant_owner_type",
        "website_integration_configs",
        ["tenant_id", "owner_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_website_integration_configs_created_by_user_id"),
        "website_integration_configs",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_website_integration_configs_owner_space_id"),
        "website_integration_configs",
        ["owner_space_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_website_integration_configs_owner_user_id"),
        "website_integration_configs",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_website_integration_configs_tenant_integration_id"),
        "website_integration_configs",
        ["tenant_integration_id"],
        unique=False,
    )

    op.create_table(
        "website_integration_pages",
        sa.Column("website_integration_config_id", sa.UUID(), nullable=False),
        sa.Column("page_url", sa.Text(), nullable=False),
        sa.Column("website_id", sa.UUID(), nullable=False),
        sa.Column("sitemap_lastmod", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_fingerprint", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["website_integration_config_id"],
            ["website_integration_configs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["website_id"], ["websites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "website_integration_config_id",
            "page_url",
            name="uq_website_integration_page_config_url",
        ),
    )
    op.create_index(
        op.f("ix_website_integration_pages_website_id"),
        "website_integration_pages",
        ["website_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_website_integration_pages_website_integration_config_id"),
        "website_integration_pages",
        ["website_integration_config_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_website_integration_pages_website_integration_config_id"),
        table_name="website_integration_pages",
    )
    op.drop_index(
        op.f("ix_website_integration_pages_website_id"),
        table_name="website_integration_pages",
    )
    op.drop_table("website_integration_pages")

    op.drop_index(
        op.f("ix_website_integration_configs_tenant_integration_id"),
        table_name="website_integration_configs",
    )
    op.drop_index(
        op.f("ix_website_integration_configs_owner_user_id"),
        table_name="website_integration_configs",
    )
    op.drop_index(
        op.f("ix_website_integration_configs_owner_space_id"),
        table_name="website_integration_configs",
    )
    op.drop_index(
        op.f("ix_website_integration_configs_created_by_user_id"),
        table_name="website_integration_configs",
    )
    op.drop_index(
        "ix_website_integration_configs_tenant_owner_type",
        table_name="website_integration_configs",
    )
    op.drop_table("website_integration_configs")

    op.execute("DELETE FROM integrations WHERE integration_type = 'website';")
