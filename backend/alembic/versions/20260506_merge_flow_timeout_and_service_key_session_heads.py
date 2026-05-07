"""Merge flow timeout and service-key session migration heads."""

from __future__ import annotations

revision = "20260506_merge_flow_session"
down_revision = ("202605061100", "20260506_flow_step_timeout")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
