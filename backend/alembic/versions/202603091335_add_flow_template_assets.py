"""add_flow_template_assets

Revision ID: 202603091335
Revises: 202603072230
Create Date: 2026-03-09 13:35:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic
revision = "202603091335"
down_revision = "202603072230"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flow_template_assets",
        sa.Column(
            "flow_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "file_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("checksum", sa.String(), nullable=False),
        sa.Column("mimetype", sa.String(), nullable=True),
        sa.Column(
            "placeholders",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="ready",
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ready','needs_action','read_only','unavailable')",
            name="ck_flow_template_assets_status",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_template_assets_flow_tenant",
        ),
        sa.ForeignKeyConstraint(["flow_id"], ["flows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_flow_template_assets_id_tenant_id"),
    )
    op.create_index(
        op.f("ix_flow_template_assets_flow_id"),
        "flow_template_assets",
        ["flow_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_flow_template_assets_space_id"),
        "flow_template_assets",
        ["space_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_flow_template_assets_tenant_id"),
        "flow_template_assets",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_flow_template_assets_file_id"),
        "flow_template_assets",
        ["file_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_template_assets_flow_active",
        "flow_template_assets",
        ["flow_id", "updated_at"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_flow_template_assets_flow_active", table_name="flow_template_assets")
    op.drop_index(op.f("ix_flow_template_assets_file_id"), table_name="flow_template_assets")
    op.drop_index(op.f("ix_flow_template_assets_tenant_id"), table_name="flow_template_assets")
    op.drop_index(op.f("ix_flow_template_assets_space_id"), table_name="flow_template_assets")
    op.drop_index(op.f("ix_flow_template_assets_flow_id"), table_name="flow_template_assets")
    op.drop_table("flow_template_assets")
