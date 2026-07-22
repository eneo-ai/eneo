"""add the App-run Skill provenance index without blocking writes

Revision ID: 202607221400
Revises: 202607221300
Create Date: 2026-07-22 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607221400"
down_revision: str | None = "202607221300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "ix_app_runs_skill_provenance_gin"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # A failed concurrent build can leave an invalid index behind. Removing
        # it first makes retrying this unapplied migration safe.
        op.drop_index(
            _INDEX_NAME,
            table_name="app_runs",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.create_index(
            _INDEX_NAME,
            "app_runs",
            ["skill_provenance"],
            unique=False,
            postgresql_using="gin",
            postgresql_ops={"skill_provenance": "jsonb_path_ops"},
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            _INDEX_NAME,
            table_name="app_runs",
            if_exists=True,
            postgresql_concurrently=True,
        )
