"""add embeddable widgets

Creates the widget feature's own schema in its released shape: templates,
widgets, daily usage with durable budget reservations, and the tenant widget
policy. Existing Owner roles receive the `widgets` permission that
predefined_roles.yml grants new tenants.

Nothing here touches the chat tables. 202609231701 changes `sessions` and
`questions` separately because it has to run outside a transaction.

Revision ID: 202609231700
Revises: 202609231001
Create Date: 2026-09-23 17:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "202609231700"
down_revision: str | None = "202609231001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "id",
            sa.UUID(),
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
    ]


def _jsonb(name: str, default: str) -> sa.Column:
    return sa.Column(
        name, JSONB(), server_default=sa.text(f"'{default}'::jsonb"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "widget_templates",
        *_base_columns(),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), server_default="", nullable=False),
        _jsonb("texts", "{}"),
        _jsonb("theme", "{}"),
        sa.Column("language", sa.String(), server_default="auto", nullable=False),
        sa.Column(
            "is_default", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        _jsonb("locked_groups", "[]"),
        sa.Column("published", JSONB(), nullable=True),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("published_by_user_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"],
            ["users.id"],
            name="fk_widget_templates_published_by_user_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_widget_templates_tenant_id", "widget_templates", ["tenant_id"])
    op.create_index(
        "uq_widget_templates_tenant_default",
        "widget_templates",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.create_table(
        "widgets",
        *_base_columns(),
        sa.Column("public_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("space_id", sa.UUID(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(), server_default="draft", nullable=False),
        sa.Column("token_generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        _jsonb("texts", "{}"),
        _jsonb("theme", "{}"),
        _jsonb("limits", "{}"),
        _jsonb("privacy", "{}"),
        sa.Column("language", sa.String(), server_default="auto", nullable=False),
        _jsonb("allowed_origins", "[]"),
        sa.Column(
            "bot_protection", sa.String(), server_default="altcha", nullable=False
        ),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("activated_by_user_id", sa.UUID(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("template_id", sa.UUID(), nullable=True),
        sa.Column(
            "show_sources", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
        sa.Column(
            "show_tool_activity",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["activated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["widget_templates.id"],
            name="fk_widgets_template_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_widgets_public_id"),
    )
    op.create_index("ix_widgets_tenant_status", "widgets", ["tenant_id", "status"])
    op.create_index("ix_widgets_space_id", "widgets", ["space_id"])
    op.create_index("ix_widgets_target", "widgets", ["target_type", "target_id"])
    op.create_index("ix_widgets_template_id", "widgets", ["template_id"])

    op.create_table(
        "widget_daily_usage",
        *_base_columns(),
        sa.Column("widget_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("questions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("blocked_budget", sa.Integer(), server_default="0", nullable=False),
        sa.Column("blocked_rate", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("helpful", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unhelpful", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["widget_id"], ["widgets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "widget_id", "day", name="uq_widget_daily_usage_widget_day"
        ),
        sa.CheckConstraint(
            "reserved_tokens >= 0", name="ck_widget_usage_reserved_tokens"
        ),
    )

    op.create_table(
        "widget_budget_reservations",
        *_base_columns(),
        sa.Column("widget_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), server_default="reserved", nullable=False),
        sa.ForeignKeyConstraint(
            ["widget_id", "day"],
            ["widget_daily_usage.widget_id", "widget_daily_usage.day"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("tokens >= 0", name="ck_widget_reservation_tokens"),
        sa.CheckConstraint(
            "state IN ('reserved', 'settled', 'released')",
            name="ck_widget_reservation_state",
        ),
    )
    op.create_index(
        "ix_widget_budget_reservations_day", "widget_budget_reservations", ["day"]
    )

    op.add_column("tenants", _jsonb("widget_policy", "{}"))

    op.execute(
        sa.text(
            "UPDATE roles SET permissions = array_append(permissions, 'widgets') "
            "WHERE predefined_source = 'Owner' "
            "AND NOT ('widgets' = ANY(permissions))"
        )
    )


def downgrade() -> None:
    # Older code rejects unknown permissions, so custom roles lose it too.
    op.execute(
        sa.text(
            "UPDATE roles SET permissions = array_remove(permissions, 'widgets') "
            "WHERE 'widgets' = ANY(permissions)"
        )
    )
    op.drop_column("tenants", "widget_policy")
    op.drop_table("widget_budget_reservations")
    op.drop_table("widget_daily_usage")
    op.drop_table("widgets")
    op.drop_table("widget_templates")
