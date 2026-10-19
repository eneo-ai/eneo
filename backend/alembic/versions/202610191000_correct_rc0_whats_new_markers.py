"""Correct 2.3 RC0 progress recorded under the not-yet-released final id.

RC0 used the content version (2.3.0) as the notification identity. Without
this one-time correction, monotonic progress would suppress every later RC
and the final release. Only this unreleased version is affected; seen and
announced progress remain independent. Ship before the first 2.3 final.

Revision ID: 202610191000
Revises: 202610161200
Create Date: 2026-10-19
"""

from alembic import op

revision = "202610191000"
down_revision = "202610161200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE whats_new_state SET seen_version = '2.3.0-rc.0' "
        "WHERE seen_version = '2.3.0'"
    )
    op.execute(
        "UPDATE whats_new_state SET announced_version = '2.3.0-rc.0' "
        "WHERE announced_version = '2.3.0'"
    )


def downgrade() -> None:
    # A correction of recorded history cannot be undone safely: converting RC0
    # back to the final id would hide the final release again. No schema changed.
    pass
