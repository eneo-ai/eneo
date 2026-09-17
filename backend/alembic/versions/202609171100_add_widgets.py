"""add widgets

Revision ID: 202609171100
Revises: 202609171000
Create Date: 2026-09-17 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202609171100"
down_revision: str | None = "202609171000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "widgets",
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
        sa.Column("public_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("space_id", sa.UUID(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(), server_default="draft", nullable=False),
        sa.Column("token_generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "texts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "theme",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "limits",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "privacy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("language", sa.String(), server_default="auto", nullable=False),
        sa.Column(
            "allowed_origins",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "bot_protection", sa.String(), server_default="altcha", nullable=False
        ),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("activated_by_user_id", sa.UUID(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["activated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_widgets_public_id"),
    )
    op.create_index("ix_widgets_tenant_status", "widgets", ["tenant_id", "status"])
    op.create_index("ix_widgets_space_id", "widgets", ["space_id"])
    op.create_index("ix_widgets_target", "widgets", ["target_type", "target_id"])

    # Widget sessions belong to a widget + pseudonymous visitor instead of a
    # user or an API key; exactly one principal column is set per row.
    op.add_column("sessions", sa.Column("widget_id", sa.UUID(), nullable=True))
    op.add_column("sessions", sa.Column("visitor_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "sessions_widget_id_fkey",
        "sessions",
        "widgets",
        ["widget_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # The ORM has declared this constraint since service-key sessions landed,
    # but not every database received it; drop it wherever it exists.
    op.execute(
        "ALTER TABLE sessions DROP CONSTRAINT IF EXISTS ck_sessions_user_xor_api_key"
    )
    op.create_check_constraint(
        "ck_sessions_single_principal",
        "sessions",
        "(user_id IS NOT NULL)::int + (api_key_id IS NOT NULL)::int"
        " + (widget_id IS NOT NULL)::int = 1",
    )
    op.create_check_constraint(
        "ck_sessions_visitor_requires_widget",
        "sessions",
        "(visitor_id IS NULL) = (widget_id IS NULL)",
    )
    op.create_index(
        "ix_sessions_widget_visitor_created",
        "sessions",
        ["widget_id", "visitor_id", sa.text("created_at DESC")],
    )

    op.add_column(
        "tenants",
        sa.Column(
            "widget_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    # Existing Owner roles keep parity with predefined_roles.yml, which grants
    # `widgets` to new tenants.
    op.execute(
        """
        UPDATE roles
        SET permissions = array_append(permissions, 'widgets')
        WHERE predefined_source = 'Owner'
          AND NOT ('widgets' = ANY(permissions));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_remove(permissions, 'widgets')
        WHERE predefined_source = 'Owner';
        """
    )
    op.drop_column("tenants", "widget_policy")

    op.drop_index("ix_sessions_widget_visitor_created", table_name="sessions")
    op.drop_constraint("ck_sessions_visitor_requires_widget", "sessions", type_="check")
    op.drop_constraint("ck_sessions_single_principal", "sessions", type_="check")
    # Widget sessions cannot satisfy the two-principal constraint; drop them.
    op.execute("DELETE FROM sessions WHERE widget_id IS NOT NULL")
    op.create_check_constraint(
        "ck_sessions_user_xor_api_key",
        "sessions",
        "(user_id IS NOT NULL) <> (api_key_id IS NOT NULL)",
    )
    op.drop_constraint("sessions_widget_id_fkey", "sessions", type_="foreignkey")
    op.drop_column("sessions", "visitor_id")
    op.drop_column("sessions", "widget_id")

    op.drop_index("ix_widgets_target", table_name="widgets")
    op.drop_index("ix_widgets_space_id", table_name="widgets")
    op.drop_index("ix_widgets_tenant_status", table_name="widgets")
    op.drop_table("widgets")
