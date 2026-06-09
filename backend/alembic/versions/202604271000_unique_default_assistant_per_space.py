"""enforce a single default assistant per space

The space-load path can drop a corrupt default-assistant row, after which a
read used to auto-create a replacement default while the original row stayed
behind — silently producing multiple defaults per space. The read path is now
guarded, but there is no DB-level guarantee. This migration:

  1. De-duplicates any existing defaults, keeping the earliest-created default
     per space and clearing `is_default` on the rest (rows are never deleted).
  2. Adds a partial unique index so a space can never again hold more than one
     default assistant.

Rows with a NULL `space_id` are left untouched — defaults always belong to a
space, and a partial index on a nullable column would not constrain them.

Revision ID: a1d4c7e90f23
Revises: f8c4e1b9d2a7
Create Date: 2026-04-27 10:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic
revision = "a1d4c7e90f23"
down_revision = "f8c4e1b9d2a7"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_assistants_one_default_per_space"


def upgrade() -> None:
    op.execute(
        """
        UPDATE assistants AS a
        SET is_default = false
        WHERE a.is_default
          AND a.space_id IS NOT NULL
          AND a.id <> (
              SELECT keep.id
              FROM assistants AS keep
              WHERE keep.is_default
                AND keep.space_id = a.space_id
              ORDER BY keep.created_at, keep.id
              LIMIT 1
          )
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX {INDEX_NAME}
        ON assistants (space_id)
        WHERE is_default
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
