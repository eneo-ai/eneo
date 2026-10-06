"""Index complete input-binding keysets for audio retention discovery.

Revision ID: 202610062000
Revises: 202610061900

Concurrent construction keeps binding writes available. Replace an invalid
index left by an interrupted build before retrying. No row data changes.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610062000"
down_revision: str = "202610061900"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_flow_run_step_input_files_created_id"
_TABLE = "flow_run_step_input_files"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            if not op.get_context().as_sql:
                valid = (
                    op.get_bind()
                    .execute(
                        sa.text(
                            "SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:name)"
                        ),
                        {"name": _INDEX},
                    )
                    .scalar()
                )
                if valid is False:
                    op.drop_index(
                        _INDEX,
                        table_name=_TABLE,
                        postgresql_concurrently=True,
                        if_exists=True,
                    )
            op.create_index(
                _INDEX,
                _TABLE,
                ["created_at", "id"],
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
                _INDEX, table_name=_TABLE, postgresql_concurrently=True, if_exists=True
            )
        finally:
            op.execute("RESET lock_timeout")
