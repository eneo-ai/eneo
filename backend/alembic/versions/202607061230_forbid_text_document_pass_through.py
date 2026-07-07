"""Forbid legacy text-to-document pass-through Flow steps."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "202607061230_no_text_doc_pass"
down_revision = "202607061030_render_verbatim"
branch_labels = None
depends_on = None

_TABLE = "flow_steps"
_CONSTRAINT = "ck_flow_steps_no_text_document_pass_through"
_LEGACY_TUPLE_PREDICATE = (
    "input_type = 'text' "
    "AND output_mode = 'pass_through' "
    "AND output_type IN ('pdf', 'docx')"
)
_CHECK_SQL = (
    "NOT (input_type = 'text' "
    "AND output_mode = 'pass_through' "
    "AND output_type IN ('pdf','docx'))"
)


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE {_TABLE}
            SET output_mode = 'render_verbatim'
            WHERE {_LEGACY_TUPLE_PREDICATE};
            """
        )
    )
    op.create_check_constraint(_CONSTRAINT, _TABLE, _CHECK_SQL)


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.execute(
        sa.text(
            f"""
            UPDATE {_TABLE}
            SET output_mode = 'pass_through'
            WHERE input_type = 'text'
              AND output_mode = 'render_verbatim'
              AND output_type IN ('pdf', 'docx');
            """
        )
    )
