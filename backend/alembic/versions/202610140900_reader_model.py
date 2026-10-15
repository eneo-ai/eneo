"""Reader model: tenant default, space choice and personal-space policy

The digest tools read long sources and attached files part by part before
the turn's model writes the answer. That per-segment reading is many short
calls on which a slow or reasoning turn model spends minutes, so a fast
reader model can take it instead. The choice lives where the material's
security classification is governed: an organisation default on one
completion model (``is_reader``, one per tenant like ``is_default``), a
choice per space (``reader_model_id`` with ``reader_model_inherit`` saying
whether the organisation default applies), and the same pair on the
personal-space policy.

Revision ID: 202610140900
Revises: 202610131800
Create Date: 2026-10-14

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "202610140900"
down_revision = "202610131800"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "completion_models",
        sa.Column("is_reader", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    for table in ("spaces", "governance_policies"):
        op.add_column(
            table,
            sa.Column(
                "reader_model_id",
                sa.UUID(),
                sa.ForeignKey(
                    "completion_models.id",
                    name=f"fk_{table}_reader_model_id_completion_models",
                    ondelete="SET NULL",
                ),
                nullable=True,
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "reader_model_inherit",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )


def downgrade() -> None:
    for table in ("governance_policies", "spaces"):
        op.drop_column(table, "reader_model_inherit")
        op.drop_column(table, "reader_model_id")
    op.drop_column("completion_models", "is_reader")
