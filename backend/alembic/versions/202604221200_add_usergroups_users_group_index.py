"""add composite index on usergroups_users(user_group_id, user_id)

The primary key on `usergroups_users` is `(user_id, user_group_id)` (see
`database/tables/users_table.py`). Queries that filter by `user_group_id`
first — notably the "inert members" summary used when attaching a group
to a shared space — cannot seek that PK and fall back to a bitmap/heap
scan across the whole junction table. On a 50k-user tenant with many
group memberships that scan dominates the query.

Adding a composite index with `user_group_id` as the leading column
turns the edge lookup into an index seek (O(log N + k)) without
changing correctness. `CONCURRENTLY` lets us ship without taking a
write lock.

Failure recovery: `CREATE INDEX CONCURRENTLY` can fail mid-build and
leave the index in an INVALID state (queries won't use it, but the
statement returns success to the transaction it ran in — Alembic marks
the migration applied). If you observe the inert-member query
regressing to a seq scan in production:

    -- check state
    SELECT indexrelid::regclass, indisvalid
    FROM pg_index
    WHERE indexrelid::regclass::text = 'idx_usergroups_users_group_user';

    -- if indisvalid = false, drop + rebuild concurrently:
    DROP INDEX CONCURRENTLY IF EXISTS idx_usergroups_users_group_user;
    CREATE INDEX CONCURRENTLY idx_usergroups_users_group_user
      ON usergroups_users (user_group_id, user_id);

Do not re-run the Alembic migration to recover — the IF NOT EXISTS
guard will skip the rebuild even when the existing index is INVALID.

Revision ID: 202604221200
Revises: unify_roles
Create Date: 2026-04-22 12:00:00
"""

from alembic import op

revision = "202604221200"
down_revision = "unify_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_usergroups_users_group_user
            ON usergroups_users (user_group_id, user_id);
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS idx_usergroups_users_group_user;"
        )
