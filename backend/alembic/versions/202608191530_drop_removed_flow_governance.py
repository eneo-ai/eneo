"""Drop partial rerun and retention-governance schema.

Revision ID: 202608191530
Revises: 202608181700, 202608181000
Create Date: 2026-08-19 15:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202608191530"
down_revision: str | Sequence[str] | None = ("202608181700", "202608181000")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The invalidation rows reference both operations and attempts, so remove
    # them before severing the attempt-side rerun lineage.
    op.drop_table("flow_run_rerun_invalidated_steps")
    op.drop_column("flow_step_attempts", "superseded_by_attempt_id")
    op.drop_column("flow_step_attempts", "predecessor_attempt_id")
    op.drop_column("flow_step_attempts", "rerun_operation_id")
    op.drop_table("flow_run_rerun_operations")

    op.drop_table("flow_classification_retention_policies")
    op.drop_column("tenants", "flow_run_history_no_purge")
    op.drop_column("tenants", "flow_run_history_minimum_retention_days")


def downgrade() -> None:
    # This private pre-release branch explicitly does not preserve removed
    # governance data. Phase 5 replaces its full migration history with the
    # final core and Builder revisions.
    raise RuntimeError(
        "Removed Flow rerun and retention-governance schema cannot be restored"
    )
