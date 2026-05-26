"""add published flow version pointer foreign key

Revision ID: 20260526_flow_published_fk
Revises: 20260526_flow_webhook_deliveries
Create Date: 2026-05-26 22:20:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260526_flow_published_fk"
down_revision = "20260526_flow_webhook_deliveries"
branch_labels = None
depends_on = None


_CONSTRAINT_NAME = "fk_flows_published_version"


def upgrade() -> None:
    bind = op.get_bind()
    orphan_count = int(
        bind.scalar(
            sa.text(
                """
                SELECT count(*)
                FROM flows AS flow
                LEFT JOIN flow_versions AS version
                  ON version.flow_id = flow.id
                 AND version.version = flow.published_version
                WHERE flow.published_version IS NOT NULL
                  AND version.flow_id IS NULL
                """
            )
        )
        or 0
    )
    if orphan_count > 0:
        raise RuntimeError(
            f"Cannot add {_CONSTRAINT_NAME}: {orphan_count} flows.published_version "
            "values do not reference flow_versions."
        )

    op.create_foreign_key(
        _CONSTRAINT_NAME,
        "flows",
        "flow_versions",
        ["id", "published_version"],
        ["flow_id", "version"],
        ondelete="NO ACTION",
        onupdate="NO ACTION",
        postgresql_not_valid=True,
    )
    op.execute(f"ALTER TABLE flows VALIDATE CONSTRAINT {_CONSTRAINT_NAME}")


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, "flows", type_="foreignkey")
