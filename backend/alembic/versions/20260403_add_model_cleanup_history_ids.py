"""add original ids for migration history and lifecycle cleanup indexes

Revision ID: 20260403_cleanup_history
Revises: 20260402_lifecycle
Create Date: 2026-04-03

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = "20260403_cleanup_history"
down_revision = "20260402_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "completion_model_migration_history",
        sa.Column("from_model_original_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "completion_model_migration_history",
        sa.Column("to_model_original_id", UUID(as_uuid=True), nullable=True),
    )

    op.execute(
        """
        UPDATE completion_model_migration_history
        SET from_model_original_id = from_model_id
        WHERE from_model_original_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE completion_model_migration_history
        SET to_model_original_id = to_model_id
        WHERE to_model_original_id IS NULL
        """
    )

    op.create_index(
        "idx_migration_history_from_model_original",
        "completion_model_migration_history",
        ["from_model_original_id"],
        unique=False,
    )
    op.create_index(
        "idx_migration_history_to_model_original",
        "completion_model_migration_history",
        ["to_model_original_id"],
        unique=False,
    )
    op.create_index(
        "ix_completion_models_deleted_at",
        "completion_models",
        ["deleted_at"],
        unique=False,
    )
    op.create_index(
        "ix_completion_models_migrated_to_model_id",
        "completion_models",
        ["migrated_to_model_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_completion_models_migrated_to_model_id", table_name="completion_models")
    op.drop_index("ix_completion_models_deleted_at", table_name="completion_models")
    op.drop_index(
        "idx_migration_history_to_model_original",
        table_name="completion_model_migration_history",
    )
    op.drop_index(
        "idx_migration_history_from_model_original",
        table_name="completion_model_migration_history",
    )
    op.drop_column("completion_model_migration_history", "to_model_original_id")
    op.drop_column("completion_model_migration_history", "from_model_original_id")
