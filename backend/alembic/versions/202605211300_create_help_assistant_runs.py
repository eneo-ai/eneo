"""create help_assistant_runs

Canonical record of a single help-assistant run. One-to-one with a
``sessions`` row (``session_id`` UNIQUE) — each helper invocation produces
exactly one row here. ``tenant_id`` is explicit per PRD §6 because every
list/read of this table, and every retention/cleanup sweep, hits it on the
hot path; the redundancy avoids joining via ``spaces.tenant_id`` on those
queries.

``target_id`` carries no FK so the row survives target deletion for audit;
identity is preserved in the linked session and in the assignment-history
table. ``assistant_id`` and ``actor_user_id`` are ``ON DELETE SET NULL`` so
that archiving a helper or deleting a user leaves the audit trail intact.

Indexes:
- ``ix_help_assistant_runs_tenant_id`` / ``ix_help_assistant_runs_org_space_id``
  — basic FK lookups used by tenant-scoped reads.
- ``ix_help_assistant_runs_tenant_created_at`` on
  ``(tenant_id, created_at DESC)`` — supports retention sweeps and the
  "recent runs in this tenant" admin view.

The ``uq_help_assistant_runs_session_id`` UNIQUE constraint is also backed
by a unique index, so no explicit secondary index on ``session_id`` is
needed.

Entity, repo, service, and router land in later steps. This migration is
schema-only.

Revision ID: 202605211300
Revises: 202605211200
Create Date: 2026-05-21
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = "202605211300"
down_revision = "202605211200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "help_assistant_runs",
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("org_space_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("assistant_id", sa.UUID(), nullable=True),
        sa.Column("target_type", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="in_progress",
            nullable=False,
        ),
        sa.Column(
            "completed_at", sa.TIMESTAMP(timezone=True), nullable=True
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
            ["session_id"], ["sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id", name="uq_help_assistant_runs_session_id"
        ),
    )
    op.create_index(
        op.f("ix_help_assistant_runs_org_space_id"),
        "help_assistant_runs",
        ["org_space_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_help_assistant_runs_tenant_id"),
        "help_assistant_runs",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_help_assistant_runs_tenant_created_at",
        "help_assistant_runs",
        ["tenant_id", sa.text("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_help_assistant_runs_tenant_created_at",
        table_name="help_assistant_runs",
    )
    op.drop_index(
        op.f("ix_help_assistant_runs_tenant_id"),
        table_name="help_assistant_runs",
    )
    op.drop_index(
        op.f("ix_help_assistant_runs_org_space_id"),
        table_name="help_assistant_runs",
    )
    op.drop_table("help_assistant_runs")
