"""Preserve undeclared input and output capacity.

Revision ID: 202609161100
Revises: 202609161030
"""

import sqlalchemy as sa

from alembic import op

revision = "202609161100"
down_revision = "202609161030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("completion_models") as batch:
        batch.alter_column(
            "max_input_tokens", existing_type=sa.Integer(), nullable=True
        )
        batch.alter_column(
            "max_output_tokens", existing_type=sa.Integer(), nullable=True
        )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        connection.execute(
            sa.text("LOCK TABLE completion_models IN ACCESS EXCLUSIVE MODE")
        )
    if connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM completion_models "
            "WHERE max_input_tokens IS NULL OR max_output_tokens IS NULL)"
        )
    ).scalar():
        raise RuntimeError(
            "Cannot downgrade with undeclared model capacity; declare both ceilings first"
        )
    with op.batch_alter_table("completion_models") as batch:
        batch.alter_column(
            "max_input_tokens", existing_type=sa.Integer(), nullable=False
        )
        batch.alter_column(
            "max_output_tokens", existing_type=sa.Integer(), nullable=False
        )
