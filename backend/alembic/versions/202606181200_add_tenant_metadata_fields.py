"""add tenant metadata fields and space metadata json

Revision ID: 202606181200
Revises: 202605251000
Create Date: 2026-06-18 12:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "202606181200"
down_revision = "202605251000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "spaces",
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    op.create_table(
        "tenant_metadata_fields",
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("field_type", sa.String(length=32), nullable=False),
        sa.Column(
            "visible_on_assistants",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "visible_on_spaces",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_tenant_metadata_fields_tenant_name",
        ),
    )
    op.create_index(
        "ix_tenant_metadata_fields_tenant_id",
        "tenant_metadata_fields",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tenant_metadata_fields_tenant_id",
        table_name="tenant_metadata_fields",
    )
    op.drop_table("tenant_metadata_fields")
    op.drop_column("spaces", "metadata_json")
