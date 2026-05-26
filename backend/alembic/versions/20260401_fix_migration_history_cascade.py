"""fix migration history cascade and add model names

Store model names directly in migration history so records survive
model deletion. Change FK ondelete from CASCADE to SET NULL.

Revision ID: fix_migration_history
Revises: 20260319_add_nickname
Create Date: 2026-04-01

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = "fix_migration_history"
down_revision = "20260319_add_nickname"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add name columns to store model names directly
    op.add_column(
        "completion_model_migration_history",
        sa.Column("from_model_name", sa.String(255), nullable=True),
    )
    op.add_column(
        "completion_model_migration_history",
        sa.Column("to_model_name", sa.String(255), nullable=True),
    )

    # Backfill names from existing model data
    op.execute("""
        UPDATE completion_model_migration_history h
        SET from_model_name = m.name
        FROM completion_models m
        WHERE h.from_model_id = m.id AND h.from_model_name IS NULL
    """)
    op.execute("""
        UPDATE completion_model_migration_history h
        SET to_model_name = m.name
        FROM completion_models m
        WHERE h.to_model_id = m.id AND h.to_model_name IS NULL
    """)

    # Drop old FK constraints with CASCADE
    op.drop_constraint(
        "completion_model_migration_history_from_model_id_fkey",
        "completion_model_migration_history",
        type_="foreignkey",
    )
    op.drop_constraint(
        "completion_model_migration_history_to_model_id_fkey",
        "completion_model_migration_history",
        type_="foreignkey",
    )

    # Make model ID columns nullable (model may be deleted)
    op.alter_column(
        "completion_model_migration_history",
        "from_model_id",
        nullable=True,
    )
    op.alter_column(
        "completion_model_migration_history",
        "to_model_id",
        nullable=True,
    )

    # Re-create FK constraints with SET NULL
    op.create_foreign_key(
        "completion_model_migration_history_from_model_id_fkey",
        "completion_model_migration_history",
        "completion_models",
        ["from_model_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "completion_model_migration_history_to_model_id_fkey",
        "completion_model_migration_history",
        "completion_models",
        ["to_model_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Drop new FK constraints
    op.drop_constraint(
        "completion_model_migration_history_from_model_id_fkey",
        "completion_model_migration_history",
        type_="foreignkey",
    )
    op.drop_constraint(
        "completion_model_migration_history_to_model_id_fkey",
        "completion_model_migration_history",
        type_="foreignkey",
    )

    # Make columns non-nullable again
    op.alter_column(
        "completion_model_migration_history",
        "from_model_id",
        nullable=False,
    )
    op.alter_column(
        "completion_model_migration_history",
        "to_model_id",
        nullable=False,
    )

    # Re-create old FK constraints with CASCADE
    op.create_foreign_key(
        "completion_model_migration_history_from_model_id_fkey",
        "completion_model_migration_history",
        "completion_models",
        ["from_model_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "completion_model_migration_history_to_model_id_fkey",
        "completion_model_migration_history",
        "completion_models",
        ["to_model_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Drop name columns
    op.drop_column("completion_model_migration_history", "to_model_name")
    op.drop_column("completion_model_migration_history", "from_model_name")
