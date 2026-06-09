"""backfill null service completion_model_kwargs

Some legacy `services` rows carry NULL in the `completion_model_kwargs`
JSONB column. The runtime read path now coerces NULL to `ModelKwargs()`
via a `mode="before"` validator, but we still backfill the column so
that:

  - Analytics and ad-hoc SQL don't have to special-case NULL.
  - A future NOT NULL constraint can be added without a separate cleanup
    migration first.
  - `assistants.completion_model_kwargs` and `apps.completion_model_kwargs`
    are already non-NULL in practice; aligning `services` removes a
    cross-domain inconsistency.

The number of affected rows is small in every deployment we have data
for, so a single UPDATE is fine — no batching or lock-management is
needed.

Revision ID: f8c4e1b9d2a7
Revises: 92cfef80384c
Create Date: 2026-04-27 09:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic
revision = "f8c4e1b9d2a7"
down_revision = "92cfef80384c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE services
        SET completion_model_kwargs = '{}'::jsonb
        WHERE completion_model_kwargs IS NULL
        """
    )


def downgrade() -> None:
    # Intentionally a no-op: after upgrade, previously-NULL rows are
    # indistinguishable from rows that were always `{}`, so there is no
    # safe way to reverse without corrupting data that was already empty
    # before the backfill.
    pass
