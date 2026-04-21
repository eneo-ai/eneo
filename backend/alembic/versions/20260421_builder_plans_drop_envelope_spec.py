"""drop the spec duplicate inside builder_plans.envelope_json

Revision ID: 20260421_builder_envelope_slim
Revises: 20260419_builder_tenant_guard
Create Date: 2026-04-21 00:00:00.000000

`builder_plans.envelope_json` used to embed a full copy of the spec already
stored in `builder_plans.spec_json`. Two sources of truth for the same data,
drifting silently in tests and backfills. Strip the `spec` key from every
existing envelope_json. Writes going forward store only the metadata; the
repo re-hydrates `envelope.spec` from `spec_json` on read.

The migration refuses to run if any row has a NULL or non-object `spec_json`
or `envelope_json` — there is no production data to preserve, so failing
loudly is preferable to fabricating a spec from the stale duplicate.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260421_builder_envelope_slim"
down_revision = "20260419_builder_tenant_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    malformed = conn.execute(
        sa.text(
            "SELECT 1 FROM builder_plans "
            "WHERE spec_json IS NULL "
            "OR jsonb_typeof(spec_json::jsonb) <> 'object' "
            "OR envelope_json IS NULL "
            "OR jsonb_typeof(envelope_json::jsonb) <> 'object' "
            "LIMIT 1"
        )
    ).scalar()
    if malformed is not None:
        raise RuntimeError(
            "Cannot apply envelope_json.spec drop: at least one builder_plans "
            "row has a NULL or non-object spec_json / envelope_json. Fix by "
            "hand before re-running this migration."
        )
    op.execute(
        sa.text(
            "UPDATE builder_plans "
            "SET envelope_json = envelope_json - 'spec' "
            "WHERE envelope_json ? 'spec'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE builder_plans "
            "SET envelope_json = jsonb_set(envelope_json, '{spec}', spec_json, true) "
            "WHERE NOT (envelope_json ? 'spec')"
        )
    )
