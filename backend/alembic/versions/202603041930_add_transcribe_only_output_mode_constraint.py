"""Allow transcribe_only as a valid flow step output mode.

Revision ID: 202603041930
Revises: c6ee835cbc43
Create Date: 2026-03-04 19:30:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "202603041930"
down_revision = "c6ee835cbc43"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_flow_steps_output_mode", "flow_steps", type_="check")
    op.create_check_constraint(
        "ck_flow_steps_output_mode",
        "flow_steps",
        "output_mode IN ('pass_through','http_post','transcribe_only')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_flow_steps_output_mode", "flow_steps", type_="check")
    op.create_check_constraint(
        "ck_flow_steps_output_mode",
        "flow_steps",
        "output_mode IN ('pass_through','http_post')",
    )
