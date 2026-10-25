"""add flow_suggestion_dismissals

The suggestions a flow's editors chose to hide, one row per flow and
suggestion fingerprint, shared by everyone who edits the flow. A dismissal
hides exactly the suggestion it names: a changed premise is another
fingerprint, so a dismissal lapses by itself. The rows go with their flow
(the flow FK cascades) and are never part of a flow package.

A new, empty table: CREATE TABLE and its indexes run in the revision's
transaction and take locks only on the new table (plus a SHARE ROW EXCLUSIVE
on tenants, flows and users for the foreign keys, released at commit).
lock_timeout bounds those waits. The downgrade drops the table and its
dismissals with it.

Revision ID: 202610251100
Revises: 202610250900
Create Date: 2026-10-25 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610251100"
down_revision: str | None = "202610250900"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "flow_suggestion_dismissals"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("flow_id", sa.UUID(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("dismissed_by", sa.UUID(), nullable=True),
        sa.Column(
            "dismissed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
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
        sa.PrimaryKeyConstraint("id", name="flow_suggestion_dismissals_pkey"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
            name="flow_suggestion_dismissals_tenant_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_suggestion_dismissals_flow_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["dismissed_by"],
            ["users.id"],
            ondelete="SET NULL",
            name="flow_suggestion_dismissals_dismissed_by_fkey",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "flow_id",
            "fingerprint",
            name="uq_flow_suggestion_dismissals_tenant_flow_fingerprint",
        ),
        sa.CheckConstraint(
            "fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_flow_suggestion_dismissals_fingerprint",
        ),
    )
    op.create_index(
        f"ix_{_TABLE}_dismissed_by",
        _TABLE,
        ["dismissed_by"],
        postgresql_where=sa.text("dismissed_by IS NOT NULL"),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_index(f"ix_{_TABLE}_dismissed_by", table_name=_TABLE)
    op.drop_table(_TABLE)
