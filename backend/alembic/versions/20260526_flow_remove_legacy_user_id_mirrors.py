"""remove legacy files.user_id mirror

Revision ID: 20260526_flow_user_mirror_drop
Revises: 20260526_flow_published_fk
Create Date: 2026-05-26 23:50:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260526_flow_user_mirror_drop"
down_revision = "20260526_flow_published_fk"
branch_labels = None
depends_on = None


def _assert_typed_file_owner_is_canonical() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM files
                    WHERE owner_type NOT IN ('user', 'service_key')
                       OR (
                            owner_type = 'user'
                            AND (
                                owner_user_id IS NULL
                                OR owner_api_key_id IS NOT NULL
                                OR user_id IS DISTINCT FROM owner_user_id
                            )
                        )
                       OR (
                            owner_type = 'service_key'
                            AND (
                                owner_api_key_id IS NULL
                                OR owner_user_id IS NOT NULL
                                OR user_id IS NOT NULL
                            )
                        )
                ) THEN
                    RAISE EXCEPTION 'Cannot drop files.user_id: typed file owner fields are missing or disagree with the legacy mirror.';
                END IF;
            END $$;
            """
        )
    )


def upgrade() -> None:
    _assert_typed_file_owner_is_canonical()

    op.drop_constraint("files_users_fkey", "files", type_="foreignkey")
    op.drop_column("files", "user_id")


def downgrade() -> None:
    op.add_column("files", sa.Column("user_id", sa.UUID(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE files
            SET user_id = owner_user_id
            WHERE owner_type = 'user'
            """
        )
    )
    op.create_foreign_key(
        "files_users_fkey",
        "files",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
        postgresql_not_valid=True,
    )
    op.execute("ALTER TABLE files VALIDATE CONSTRAINT files_users_fkey")
