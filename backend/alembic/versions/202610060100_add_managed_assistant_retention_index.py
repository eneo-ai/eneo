"""add the ordered managed-assistant retention index

Revision ID: 202610060100
Revises: 202610041300
Create Date: 2026-10-06 01:00:00.000000

Concurrent creation keeps assistant writes available. A failed concurrent build
can leave an invalid index, which must be removed before retrying the upgrade.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610060100"
down_revision: str = "202610041300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "ix_assistants_flow_managed_created_at_id"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            if not op.get_context().as_sql:
                valid = (
                    op.get_bind()
                    .execute(
                        sa.text(
                            "SELECT indisvalid FROM pg_index "
                            "WHERE indexrelid = to_regclass(:name)"
                        ),
                        {"name": _INDEX_NAME},
                    )
                    .scalar()
                )
                if valid is False:
                    op.drop_index(
                        _INDEX_NAME,
                        table_name="assistants",
                        postgresql_concurrently=True,
                    )
            op.create_index(
                _INDEX_NAME,
                "assistants",
                ["created_at", "id"],
                postgresql_where=sa.text("origin = 'flow_managed'"),
                postgresql_concurrently=True,
                if_not_exists=True,
            )
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            op.drop_index(
                _INDEX_NAME,
                table_name="assistants",
                postgresql_concurrently=True,
                if_exists=True,
            )
        finally:
            op.execute("RESET lock_timeout")
