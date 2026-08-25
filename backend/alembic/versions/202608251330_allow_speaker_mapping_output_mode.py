"""allow speaker_mapping output mode

Revision ID: 202608251330
Revises: 202608241100
Create Date: 2026-08-25 13:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202608251330"
down_revision: str | tuple[str, ...] | None = "202608241100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_flow_steps_output_mode", "flow_steps", type_="check")
    op.create_check_constraint(
        "ck_flow_steps_output_mode",
        "flow_steps",
        "output_mode IN ('pass_through','compose_text','http_post',"
        "'transcribe_only','template_fill','render_verbatim','speaker_mapping')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_flow_steps_output_mode", "flow_steps", type_="check")
    op.create_check_constraint(
        "ck_flow_steps_output_mode",
        "flow_steps",
        "output_mode IN ('pass_through','compose_text','http_post',"
        "'transcribe_only','template_fill','render_verbatim')",
    )
