"""add provider snapshots for migration history and lifecycle cleanup indexes

Revision ID: 20260403_cleanup_history
Revises: 20260402_lifecycle
Create Date: 2026-04-03

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260403_cleanup_history"
down_revision = "20260402_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "completion_model_migration_history",
        sa.Column("from_provider_type", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "completion_model_migration_history",
        sa.Column("to_provider_type", sa.String(length=255), nullable=True),
    )

    op.execute(
        """
        UPDATE completion_model_migration_history AS history
        SET from_provider_type = providers.provider_type
        FROM completion_models AS models
        LEFT JOIN model_providers AS providers ON models.provider_id = providers.id
        WHERE history.from_model_id = models.id
          AND history.from_provider_type IS NULL
        """
    )
    op.execute(
        """
        UPDATE completion_model_migration_history AS history
        SET to_provider_type = providers.provider_type
        FROM completion_models AS models
        LEFT JOIN model_providers AS providers ON models.provider_id = providers.id
        WHERE history.to_model_id = models.id
          AND history.to_provider_type IS NULL
        """
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
    op.drop_column("completion_model_migration_history", "to_provider_type")
    op.drop_column("completion_model_migration_history", "from_provider_type")
