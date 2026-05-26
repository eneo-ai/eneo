"""remove legacy Flow user id mirrors

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


def _assert_typed_identity_is_canonical() -> None:
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

                IF EXISTS (
                    SELECT 1
                    FROM flow_runs
                    WHERE principal_type NOT IN ('user', 'service_key')
                       OR (
                            principal_type = 'user'
                            AND (
                                principal_user_id IS NULL
                                OR principal_api_key_id IS NOT NULL
                                OR user_id IS DISTINCT FROM principal_user_id
                            )
                        )
                       OR (
                            principal_type = 'service_key'
                            AND (
                                principal_api_key_id IS NULL
                                OR principal_user_id IS NOT NULL
                                OR user_id IS NOT NULL
                            )
                        )
                ) THEN
                    RAISE EXCEPTION 'Cannot drop flow_runs.user_id: typed Flow run principal fields are missing or disagree with the legacy mirror.';
                END IF;
            END $$;
            """
        )
    )


def upgrade() -> None:
    _assert_typed_identity_is_canonical()

    op.drop_constraint("files_users_fkey", "files", type_="foreignkey")
    op.drop_column("files", "user_id")

    op.drop_constraint("flow_runs_user_id_fkey", "flow_runs", type_="foreignkey")
    op.drop_column("flow_runs", "user_id")


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
        ondelete="SET NULL",
        postgresql_not_valid=True,
    )
    op.execute("ALTER TABLE files VALIDATE CONSTRAINT files_users_fkey")

    op.add_column("flow_runs", sa.Column("user_id", sa.UUID(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE flow_runs
            SET user_id = principal_user_id
            WHERE principal_type = 'user'
            """
        )
    )
    op.create_foreign_key(
        "flow_runs_user_id_fkey",
        "flow_runs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
        postgresql_not_valid=True,
    )
    op.execute("ALTER TABLE flow_runs VALIDATE CONSTRAINT flow_runs_user_id_fkey")
