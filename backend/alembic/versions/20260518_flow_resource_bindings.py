"""add flow resource bindings

Revision ID: 20260518_flow_resource_bindings
Revises: 20260515_flow_run_error
Create Date: 2026-05-18 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260518_flow_resource_bindings"
down_revision = "20260515_flow_run_error"
branch_labels = None
depends_on = None

SLOT_KIND_VALUES = (
    "model",
    "knowledge",
    "mcp_server",
    "mcp_tool",
    "template_asset",
)
LOCAL_RESOURCE_KIND_VALUES = (
    "completion_model",
    "transcription_model",
    "collection",
    "website",
    "integration_knowledge",
    "mcp_server",
    "mcp_tool",
    "template_asset",
)
SLOT_LOCAL_KIND_PAIR_VALUES = (
    ("model", "completion_model"),
    ("model", "transcription_model"),
    ("knowledge", "collection"),
    ("knowledge", "integration_knowledge"),
    ("knowledge", "website"),
    ("mcp_server", "mcp_server"),
    ("mcp_tool", "mcp_tool"),
    ("template_asset", "template_asset"),
)
SOURCE_VALUES = (
    "ai_builder",
    "package_import",
    "manual_admin",
)
RESOURCE_SLOT_PATTERN = r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$"
UUID_SHAPED_RESOURCE_REF_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def _check_values(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


def _check_value_pairs(values: tuple[tuple[str, str], ...]) -> str:
    return ",".join(f"('{left}','{right}')" for left, right in values)


def upgrade() -> None:
    op.create_table(
        "flow_resource_bindings",
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
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slot_kind", sa.String(length=32), nullable=False),
        sa.Column("slot", sa.String(length=96), nullable=False),
        sa.Column("slot_label", sa.String(length=160), nullable=False),
        sa.Column("local_resource_kind", sa.String(length=64), nullable=False),
        sa.Column("local_resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            f"slot_kind IN ({_check_values(SLOT_KIND_VALUES)})",
            name=op.f("ck_flow_resource_bindings_slot_kind"),
        ),
        sa.CheckConstraint(
            f"slot ~ '{RESOURCE_SLOT_PATTERN}'",
            name=op.f("ck_flow_resource_bindings_slot_format"),
        ),
        sa.CheckConstraint(
            f"slot !~* '{UUID_SHAPED_RESOURCE_REF_PATTERN}'",
            name=op.f("ck_flow_resource_bindings_slot_not_uuid"),
        ),
        sa.CheckConstraint(
            "length(btrim(slot_label)) > 0",
            name=op.f("ck_flow_resource_bindings_slot_label_not_empty"),
        ),
        sa.CheckConstraint(
            f"local_resource_kind IN ({_check_values(LOCAL_RESOURCE_KIND_VALUES)})",
            name=op.f("ck_flow_resource_bindings_local_resource_kind"),
        ),
        sa.CheckConstraint(
            "(slot_kind, local_resource_kind) IN "
            f"({_check_value_pairs(SLOT_LOCAL_KIND_PAIR_VALUES)})",
            name=op.f("ck_flow_resource_bindings_slot_local_kind_pair"),
        ),
        sa.CheckConstraint(
            f"source IN ({_check_values(SOURCE_VALUES)})",
            name=op.f("ck_flow_resource_bindings_source"),
        ),
        sa.ForeignKeyConstraint(
            ["flow_id"],
            ["flows.id"],
            name=op.f("fk_flow_resource_bindings_flow_id_flows"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            name=op.f("fk_flow_resource_bindings_flow_tenant"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["spaces.id"],
            name=op.f("fk_flow_resource_bindings_space_id_spaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_flow_resource_bindings_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flow_resource_bindings")),
        sa.UniqueConstraint(
            "flow_id",
            "slot_kind",
            "slot",
            name="uq_flow_resource_bindings_flow_slot",
        ),
    )
    op.create_index(
        "ix_flow_resource_bindings_flow_id",
        "flow_resource_bindings",
        ["flow_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_resource_bindings_local_target",
        "flow_resource_bindings",
        ["local_resource_kind", "local_resource_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_resource_bindings_space_id",
        "flow_resource_bindings",
        ["space_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_resource_bindings_tenant_flow",
        "flow_resource_bindings",
        ["tenant_id", "flow_id"],
        unique=False,
    )
    op.create_index(
        "ix_flow_resource_bindings_tenant_id",
        "flow_resource_bindings",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("flow_resource_bindings")
