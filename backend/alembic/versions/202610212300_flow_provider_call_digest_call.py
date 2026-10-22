"""Record the stage and sources of long-material digest calls in provider-call receipts.

Revision ID: 202610212300
Revises: 202610212200
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202610212300"
down_revision = "202610212200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "flow_provider_calls",
        sa.Column("digest_call", postgresql.JSONB(none_as_null=True), nullable=True),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE flow_provider_calls IN ACCESS EXCLUSIVE MODE")
    retained = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM flow_provider_calls "
                "WHERE digest_call IS NOT NULL)"
            )
        )
        .scalar_one()
    )
    if retained:
        raise RuntimeError(
            "Refusing to downgrade while provider-call receipts record digest calls."
        )
    op.drop_column("flow_provider_calls", "digest_call")
