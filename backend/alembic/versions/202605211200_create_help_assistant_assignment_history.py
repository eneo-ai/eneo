"""create help_assistant_assignment_history

Append-only audit trail for help-assistant role reassignments. Rows are
written when the assistant filling a role slot is reset, reassigned, or
unassigned. ``assistant_id`` and ``replaced_by_assistant_id`` are
``ON DELETE SET NULL`` so the "archive replaced helpers" admin action can
hard-delete the underlying assistant rows while keeping the audit trail
intact — ``assistant_name_snapshot`` retains identity. Tenant scoping
derives from ``spaces.tenant_id`` via ``org_space_id``; no separate
``tenant_id`` column per PRD §3.

The composite index ``ix_help_assistant_assignment_history_lookup`` on
``(org_space_id, kind, replaced_at DESC)`` supports the "list history for
a kind in this org-space" query that powers the admin history pane.

Entity, repo, service, and router come in later steps. This migration is
schema-only.

Revision ID: 202605211200
Revises: 202605211100
Create Date: 2026-05-21
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = "202605211200"
down_revision = "202605211100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "help_assistant_assignment_history",
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
        sa.Column("org_space_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("assistant_id", sa.UUID(), nullable=True),
        sa.Column(
            "assistant_name_snapshot", sa.String(length=255), nullable=False
        ),
        sa.Column("replaced_by_assistant_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.String(length=50), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "replaced_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["assistant_id"], ["assistants.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["org_space_id"], ["spaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_assistant_id"], ["assistants.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_help_assistant_assignment_history_kind"),
        "help_assistant_assignment_history",
        ["kind"],
        unique=False,
    )
    op.create_index(
        op.f("ix_help_assistant_assignment_history_org_space_id"),
        "help_assistant_assignment_history",
        ["org_space_id"],
        unique=False,
    )
    op.create_index(
        "ix_help_assistant_assignment_history_lookup",
        "help_assistant_assignment_history",
        ["org_space_id", "kind", sa.text("replaced_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_help_assistant_assignment_history_lookup",
        table_name="help_assistant_assignment_history",
    )
    op.drop_index(
        op.f("ix_help_assistant_assignment_history_org_space_id"),
        table_name="help_assistant_assignment_history",
    )
    op.drop_index(
        op.f("ix_help_assistant_assignment_history_kind"),
        table_name="help_assistant_assignment_history",
    )
    op.drop_table("help_assistant_assignment_history")
