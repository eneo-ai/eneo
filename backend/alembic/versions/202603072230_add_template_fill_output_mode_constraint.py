"""Allow template_fill as a valid flow step output mode.

Revision ID: 202603072230
Revises: 202603042120
Create Date: 2026-03-07 22:30:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "202603072230"
down_revision = "202603042120"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_flow_steps_output_mode", "flow_steps", type_="check")
    op.create_check_constraint(
        "ck_flow_steps_output_mode",
        "flow_steps",
        "output_mode IN ('pass_through','http_post','transcribe_only','template_fill')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_flow_steps_output_mode", "flow_steps", type_="check")
    op.create_check_constraint(
        "ck_flow_steps_output_mode",
        "flow_steps",
        "output_mode IN ('pass_through','http_post','transcribe_only')",
    )
