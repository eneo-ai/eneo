"""Record the forwarding facts of a step attempt's first model call next to its resolved inputs.

Revision ID: 202610250900
Revises: 202610241100
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202610250900"
down_revision = "202610241100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "flow_step_attempt_resolved_inputs",
        sa.Column(
            "forwarding_facts_jsonb",
            postgresql.JSONB(none_as_null=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    # The facts are measurements derived at run time, not evidence: dropping
    # them loses no record a later read depends on.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("flow_step_attempt_resolved_inputs", "forwarding_facts_jsonb")
