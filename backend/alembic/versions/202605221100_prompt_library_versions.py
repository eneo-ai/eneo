"""add prompt_library version snapshots

Revision ID: 202605221100
Revises: 202605221000
Create Date: 2026-05-22
"""

import sqlalchemy as sa

from alembic import op

revision = "202605221100"
down_revision = "202605221000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "prompt_library",
        sa.Column("current_version", sa.Integer(), server_default="1", nullable=False),
    )

    op.create_table(
        "prompt_library_versions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("prompt_library_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
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
            ["prompt_library_id"], ["prompt_library.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "prompt_library_id",
            "version",
            name="uq_prompt_library_versions_entry_version",
        ),
    )
    op.create_index(
        "ix_prompt_library_versions_prompt_library_id",
        "prompt_library_versions",
        ["prompt_library_id"],
    )
    op.create_index(
        "ix_prompt_library_versions_tenant_id",
        "prompt_library_versions",
        ["tenant_id"],
    )

    op.execute(
        """
        INSERT INTO prompt_library_versions (
            prompt_library_id,
            tenant_id,
            version,
            name,
            description,
            text,
            created_by_user_id,
            created_at,
            updated_at
        )
        SELECT
            id,
            tenant_id,
            1,
            name,
            description,
            text,
            created_by_user_id,
            created_at,
            updated_at
        FROM prompt_library
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_prompt_library_versions_tenant_id",
        table_name="prompt_library_versions",
    )
    op.drop_index(
        "ix_prompt_library_versions_prompt_library_id",
        table_name="prompt_library_versions",
    )
    op.drop_table("prompt_library_versions")
    op.drop_column("prompt_library", "current_version")
