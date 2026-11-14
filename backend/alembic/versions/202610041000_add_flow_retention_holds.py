"""add flow_retention_holds and the two retention permissions

Revision ID: 202610041000
Revises: 202610021015
Create Date: 2026-10-04 10:00:00.000000

A new, empty table: CREATE TABLE and its indexes run in the revision's
transaction and take locks only on the new table (plus a SHARE ROW EXCLUSIVE on
tenants, flows and users for the foreign keys, released at commit).
lock_timeout bounds those waits.

retention_manage and retention_holds are explicit per-role grants. The upgrade
gives them to no role, the predefined Owner included: who may change retention
rules and lift legal holds is the organisation's choice, made in role editing
after the upgrade. The role templates do not carry them either.

The downgrade removes the two values from every role, because the previous
release cannot read a role that holds them. It does not remember which roles
held them, so upgrading again gives them back to none; an administrator grants
them again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202610041000"
down_revision: str | None = "202610021015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "flow_retention_holds"
_REASON_MAX = 512
_RETENTION_PERMISSIONS = ("retention_manage", "retention_holds")


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
        sa.Column("flow_run_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("review_by", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_actor", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "released_by_actor", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("released_by_user_id", sa.UUID(), nullable=True),
        sa.Column("release_reason", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="flow_retention_holds_pkey"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
            name="flow_retention_holds_tenant_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_retention_holds_flow_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
            name="flow_retention_holds_created_by_user_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["released_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
            name="flow_retention_holds_released_by_user_id_fkey",
        ),
        sa.CheckConstraint(
            f"char_length(reason) BETWEEN 1 AND {_REASON_MAX}",
            name="ck_flow_retention_holds_reason_length",
        ),
        sa.CheckConstraint(
            "ends_at IS NULL OR ends_at > created_at",
            name="ck_flow_retention_holds_ends_after_created",
        ),
        sa.CheckConstraint(
            "review_by > created_at",
            name="ck_flow_retention_holds_review_after_created",
        ),
        sa.CheckConstraint(
            "(released_at IS NULL AND released_by_actor IS NULL AND "
            "released_by_user_id IS NULL AND release_reason IS NULL) OR "
            "(released_at IS NOT NULL AND released_by_actor IS NOT NULL AND "
            "release_reason IS NOT NULL AND "
            f"char_length(release_reason) BETWEEN 1 AND {_REASON_MAX})",
            name="ck_flow_retention_holds_release_complete",
        ),
    )
    op.create_index(
        "ix_flow_retention_holds_active_flow_id",
        _TABLE,
        ["flow_id"],
        postgresql_where=sa.text("released_at IS NULL"),
    )
    op.create_index(
        "ix_flow_retention_holds_active_flow_run_id",
        _TABLE,
        ["flow_run_id"],
        postgresql_where=sa.text("released_at IS NULL AND flow_run_id IS NOT NULL"),
    )
    op.create_index(
        "ix_flow_retention_holds_flow_id_tenant_id",
        _TABLE,
        ["flow_id", "tenant_id"],
    )
    op.create_index(
        "ix_flow_retention_holds_tenant_created",
        _TABLE,
        ["tenant_id", "created_at"],
    )
    for column in ("created_by_user_id", "released_by_user_id"):
        op.create_index(
            f"ix_{_TABLE}_{column}",
            _TABLE,
            [column],
            postgresql_where=sa.text(f"{column} IS NOT NULL"),
        )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for permission in _RETENTION_PERMISSIONS:
        op.execute(
            "UPDATE roles SET permissions = "
            f"array_remove(permissions, '{permission}') "
            f"WHERE '{permission}' = ANY(permissions)"
        )
    op.drop_table(_TABLE)
