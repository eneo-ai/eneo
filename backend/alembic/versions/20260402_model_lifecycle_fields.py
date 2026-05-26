"""add model lifecycle fields for migration and soft-delete

Add migrated_to_model_id and deleted_at to completion_models.
Change questions.completion_model_id FK from SET NULL to RESTRICT
to prevent silent loss of historical question attribution.

Revision ID: 20260402_lifecycle
Revises: fix_migration_history
Create Date: 2026-04-02

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic
revision = "20260402_lifecycle"
down_revision = "fix_migration_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add migrated_to_model_id (self-referencing FK with RESTRICT)
    op.add_column(
        "completion_models",
        sa.Column("migrated_to_model_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_completion_models_migrated_to",
        "completion_models",
        "completion_models",
        ["migrated_to_model_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # 2. Add deleted_at for soft-delete
    op.add_column(
        "completion_models",
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    # 3. Change questions.completion_model_id FK from SET NULL to RESTRICT
    op.drop_constraint(
        "questions_completion_model_id_fkey", "questions", type_="foreignkey"
    )
    op.create_foreign_key(
        "questions_completion_model_id_fkey",
        "questions",
        "completion_models",
        ["completion_model_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    # Revert questions FK to SET NULL
    op.drop_constraint(
        "questions_completion_model_id_fkey", "questions", type_="foreignkey"
    )
    op.create_foreign_key(
        "questions_completion_model_id_fkey",
        "questions",
        "completion_models",
        ["completion_model_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Remove deleted_at
    op.drop_column("completion_models", "deleted_at")

    # Remove migrated_to_model_id
    op.drop_constraint(
        "fk_completion_models_migrated_to", "completion_models", type_="foreignkey"
    )
    op.drop_column("completion_models", "migrated_to_model_id")
