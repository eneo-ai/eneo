"""drop idx_usergroups_users_group_user

The index `idx_usergroups_users_group_user` was added in revision
`202604221200` to accelerate the inert-members summary anti-join
(`NOT EXISTS` scan over role grants for each group member). When
shared-spaces gating was narrowed to "create-only", the summary query
was removed and the index became an orphan — paying write amplification
on every `usergroups_users` INSERT/DELETE with zero readers.

`DROP INDEX CONCURRENTLY` avoids a write lock on the hot junction
table during the drop, mirroring how the original index was created.

Failure recovery: if the DROP fails mid-operation (connection loss,
statement timeout), the index may be left partially removed. Re-run
the migration; `IF EXISTS` makes it idempotent.

Revision ID: 202604231400
Revises: 202604221200
Create Date: 2026-04-23 14:00:00
"""

from alembic import op

revision = "202604231400"
down_revision = "202604221200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS idx_usergroups_users_group_user;"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_usergroups_users_group_user
            ON usergroups_users (user_group_id, user_id);
            """
        )
