"""Retain summarization input references in provider-call receipts.

Revision ID: 202609211100
Revises: 202609211000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202609211100"
down_revision = "202609211000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "flow_provider_calls",
        sa.Column(
            "summarization_input", postgresql.JSONB(none_as_null=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE flow_provider_calls IN ACCESS EXCLUSIVE MODE")
    retained = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM flow_provider_calls "
                "WHERE summarization_input IS NOT NULL)"
            )
        )
        .scalar_one()
    )
    if retained:
        raise RuntimeError(
            "Refusing to downgrade while summarization receipts retain input references."
        )
    op.drop_column("flow_provider_calls", "summarization_input")
