"""Add compose_text flow output mode."""

from __future__ import annotations

from alembic import op

revision = "202607081035_compose_text"
down_revision = "202607061230_no_text_doc_pass"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_flow_steps_output_mode"
_TABLE = "flow_steps"
_OLD_VALUES = "'pass_through','http_post','transcribe_only','template_fill','render_verbatim'"
_NEW_VALUES = "'pass_through','compose_text','http_post','transcribe_only','template_fill','render_verbatim'"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        f"output_mode IN ({_NEW_VALUES})",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        f"output_mode IN ({_OLD_VALUES})",
    )
