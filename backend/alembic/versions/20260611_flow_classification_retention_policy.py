"""add Flow classification retention policies

The supporting tenant-paired unique index is created concurrently before it is
attached as a unique constraint. If an interrupted upgrade leaves that index
invalid, drop `ix_security_classifications_id_tenant_id_unique` and rerun.

Revision ID: 20260611_flow_class_retention
Revises: 20260610_flow_retention_anchor
Create Date: 2026-06-11 12:12:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260611_flow_class_retention"
down_revision = "20260610_flow_retention_anchor"
branch_labels = None
depends_on = None

_POLICY_TABLE = "flow_classification_retention_policies"
_SECURITY_CLASSIFICATIONS_TABLE = "security_classifications"
_SECURITY_CLASSIFICATIONS_TENANT_UNIQUE = "uq_security_classifications_id_tenant_id"
_SECURITY_CLASSIFICATIONS_TENANT_UNIQUE_INDEX = (
    "ix_security_classifications_id_tenant_id_unique"
)
_POLICY_PRIMARY_KEY = "pk_flow_classification_retention_policies"
_POLICY_TENANT_FK = "fk_flow_classification_retention_policies_tenant"
_POLICY_CLASSIFICATION_TENANT_FK = (
    "fk_flow_classification_retention_policies_classification_tenant"
)
_POLICY_DAYS_CHECK = "ck_flow_classification_retention_policy_days_range"
_POLICY_DAYS_CHECK_SQL = "data_retention_days >= 1 AND data_retention_days <= 2555"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS
            {_SECURITY_CLASSIFICATIONS_TENANT_UNIQUE_INDEX}
            ON {_SECURITY_CLASSIFICATIONS_TABLE} (id, tenant_id)
            """
        )
    op.execute(
        f"""
        ALTER TABLE {_SECURITY_CLASSIFICATIONS_TABLE}
        ADD CONSTRAINT {_SECURITY_CLASSIFICATIONS_TENANT_UNIQUE}
        UNIQUE USING INDEX {_SECURITY_CLASSIFICATIONS_TENANT_UNIQUE_INDEX}
        """
    )
    op.create_table(
        _POLICY_TABLE,
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("security_classification_id", sa.UUID(), nullable=False),
        sa.Column("data_retention_days", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "security_classification_id",
            name=_POLICY_PRIMARY_KEY,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
            name=_POLICY_TENANT_FK,
        ),
        sa.ForeignKeyConstraint(
            ["security_classification_id", "tenant_id"],
            ["security_classifications.id", "security_classifications.tenant_id"],
            ondelete="CASCADE",
            name=_POLICY_CLASSIFICATION_TENANT_FK,
        ),
        sa.CheckConstraint(
            _POLICY_DAYS_CHECK_SQL,
            name=_POLICY_DAYS_CHECK,
        ),
    )


def downgrade() -> None:
    op.drop_table(_POLICY_TABLE)
    op.drop_constraint(
        _SECURITY_CLASSIFICATIONS_TENANT_UNIQUE,
        _SECURITY_CLASSIFICATIONS_TABLE,
        type_="unique",
    )
    with op.get_context().autocommit_block():
        op.execute(
            f"DROP INDEX CONCURRENTLY IF EXISTS "
            f"{_SECURITY_CLASSIFICATIONS_TENANT_UNIQUE_INDEX}"
        )
