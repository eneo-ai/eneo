"""add flow package imports

Revision ID: 20260519_flow_package_imports
Revises: 20260518_plan_bindings_json
Create Date: 2026-05-19 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260519_flow_package_imports"
down_revision = "20260518_plan_bindings_json"
branch_labels = None
depends_on = None

SOURCE_VALUES = ("file_upload",)
STATUS_VALUES = ("draft_created", "failed")


def _check_values(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "flow_package_imports",
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("package_id", sa.String(length=128), nullable=False),
        sa.Column("package_version", sa.String(length=64), nullable=False),
        sa.Column("content_checksum", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "import_plan_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "selected_mappings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "failure_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.CheckConstraint(
            f"source IN ({_check_values(SOURCE_VALUES)})",
            name=op.f("ck_flow_package_imports_source"),
        ),
        sa.CheckConstraint(
            f"status IN ({_check_values(STATUS_VALUES)})",
            name=op.f("ck_flow_package_imports_status"),
        ),
        sa.CheckConstraint(
            "content_checksum ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_flow_package_imports_content_checksum"),
        ),
        sa.CheckConstraint(
            "("
            "status = 'draft_created' AND flow_id IS NOT NULL AND failure_json IS NULL"
            ") OR ("
            "status = 'failed' AND flow_id IS NULL AND failure_json IS NOT NULL"
            ")",
            name=op.f("ck_flow_package_imports_terminal_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_flow_package_imports_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id"],
            ["flows.id"],
            name=op.f("fk_flow_package_imports_flow_id_flows"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["spaces.id"],
            name=op.f("fk_flow_package_imports_space_id_spaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_flow_package_imports_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flow_package_imports")),
    )
    op.create_index(
        "ix_flow_package_imports_flow_id",
        "flow_package_imports",
        ["flow_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_package_imports_space_checksum_created",
        "flow_package_imports",
        ["space_id", "content_checksum", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_flow_package_imports_space_id",
        "flow_package_imports",
        ["space_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_package_imports_tenant_id",
        "flow_package_imports",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_package_imports_tenant_space_created",
        "flow_package_imports",
        ["tenant_id", "space_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("flow_package_imports")
