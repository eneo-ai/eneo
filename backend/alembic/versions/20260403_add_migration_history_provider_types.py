"""add provider snapshots for migration history and lifecycle cleanup indexes

Revision ID: 20260403_cleanup_history
Revises: 20260402_lifecycle
Create Date: 2026-04-03

"""

import sqlalchemy as sa

from alembic import op

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
    # Build the new indexes without holding a table-level lock — on a large
    # `completion_models` table the default CREATE INDEX would block writes
    # for the duration of the build. See 202604221200 for the same pattern,
    # including notes on INVALID-index recovery if CONCURRENTLY fails
    # mid-build (Alembic still marks the migration applied).
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_completion_models_deleted_at
            ON completion_models (deleted_at);
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_completion_models_migrated_to_model_id
            ON completion_models (migrated_to_model_id);
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_completion_models_migrated_to_model_id;"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_completion_models_deleted_at;"
        )
    op.drop_column("completion_model_migration_history", "to_provider_type")
    op.drop_column("completion_model_migration_history", "from_provider_type")
