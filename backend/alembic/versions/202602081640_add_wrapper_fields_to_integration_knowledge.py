"""add_wrapper_fields_to_integration_knowledge

Revision ID: add_integration_wrappers
Revises: add_failure_summary
Create Date: 2026-02-08 16:40:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = "add_integration_wrappers"
down_revision = "add_failure_summary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integration_knowledge",
        sa.Column("wrapper_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "integration_knowledge",
        sa.Column("wrapper_name", sa.Text(), nullable=True),
    )
    op.create_index(
        op.f("ix_integration_knowledge_wrapper_id"),
        "integration_knowledge",
        ["wrapper_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_integration_knowledge_wrapper_id"), table_name="integration_knowledge")
    op.drop_column("integration_knowledge", "wrapper_name")
    op.drop_column("integration_knowledge", "wrapper_id")
