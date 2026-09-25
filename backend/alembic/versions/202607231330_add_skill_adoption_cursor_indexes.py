"""add cursor indexes for Skill adoption resources

Revision ID: 202607231330
Revises: 202607231200
Create Date: 2026-07-23 13:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607231330"
down_revision: str | None = "202607231200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ASSISTANT_INDEX = "ix_assistant_skill_bindings_skill_id_assistant_id"
_APP_INDEX = "ix_app_skill_bindings_skill_id_app_id"
_OLD_ASSISTANT_INDEX = "ix_assistant_skill_bindings_skill_id"
_OLD_APP_INDEX = "ix_app_skill_bindings_skill_id"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # A failed concurrent build can leave an invalid index behind. Dropping
        # it first keeps a retry of this unapplied migration safe.
        op.drop_index(
            _ASSISTANT_INDEX,
            table_name="assistant_skill_bindings",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.create_index(
            _ASSISTANT_INDEX,
            "assistant_skill_bindings",
            ["skill_id", "assistant_id"],
            postgresql_concurrently=True,
        )
        op.drop_index(
            _APP_INDEX,
            table_name="app_skill_bindings",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.create_index(
            _APP_INDEX,
            "app_skill_bindings",
            ["skill_id", "app_id"],
            postgresql_concurrently=True,
        )
        op.drop_index(
            _OLD_ASSISTANT_INDEX,
            table_name="assistant_skill_bindings",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.drop_index(
            _OLD_APP_INDEX,
            table_name="app_skill_bindings",
            if_exists=True,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            _OLD_ASSISTANT_INDEX,
            table_name="assistant_skill_bindings",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.create_index(
            _OLD_ASSISTANT_INDEX,
            "assistant_skill_bindings",
            ["skill_id"],
            postgresql_concurrently=True,
        )
        op.drop_index(
            _OLD_APP_INDEX,
            table_name="app_skill_bindings",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.create_index(
            _OLD_APP_INDEX,
            "app_skill_bindings",
            ["skill_id"],
            postgresql_concurrently=True,
        )
        op.drop_index(
            _ASSISTANT_INDEX,
            table_name="assistant_skill_bindings",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.drop_index(
            _APP_INDEX,
            table_name="app_skill_bindings",
            if_exists=True,
            postgresql_concurrently=True,
        )
