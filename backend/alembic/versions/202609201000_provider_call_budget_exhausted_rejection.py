"""Allow the budget_exhausted rejection reason on flow provider calls.

A provider-call receipt written while the step's execution budget ran out is
settled as a known refusal (nothing was sent, nothing billed) instead of
being left open. The lifecycle constraint enumerates rejection reasons, so
the new reason needs the constraint recreated.

The widened check is installed NOT VALID inside the DDL transaction (a short
exclusive lock, no row scan) and validated afterwards in its own autocommit
statement, so receipt reads and writes are not blocked for the duration of
the scan. The downgrade refuses to run while budget_exhausted receipts
exist: rewriting them to a provider-side reason would misattribute evidence.

Revision ID: 202609201000
Revises: 202609181000
"""

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

revision = "202609201000"
down_revision = "202609181000"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_flow_provider_calls_lifecycle_shape"
_TABLE = "flow_provider_calls"

_STARTED = (
    "(status = 'started' AND finished_at IS NULL AND outcome_reason IS NULL "
    "AND response_model IS NULL AND provider_response_id IS NULL "
    "AND num_tokens_input IS NULL AND num_tokens_output IS NULL "
    "AND input_source IS NULL AND output_source IS NULL)"
)
_COMPLETED = (
    "(status = 'completed' AND outcome_reason IS NULL AND input_source IS NOT NULL "
    "AND output_source IS NOT NULL AND finished_at IS NOT NULL)"
)
_SETTLED_TAIL = (
    "AND response_model IS NULL AND provider_response_id IS NULL "
    "AND num_tokens_input IS NULL AND num_tokens_output IS NULL "
    "AND input_source IS NULL AND output_source IS NULL)"
)
_UNKNOWN = (
    "(status = 'outcome_unknown' AND finished_at IS NOT NULL AND outcome_reason IN "
    "('request_timeout','run_cancelled','worker_interrupted','provider_error',"
    "'request_cancelled','stale_started') " + _SETTLED_TAIL
)


def _lifecycle_shape(rejection_reasons: str) -> str:
    rejected = (
        "(status = 'rejected' AND finished_at IS NOT NULL AND outcome_reason IN "
        f"({rejection_reasons}) " + _SETTLED_TAIL
    )
    return " OR ".join((_STARTED, _COMPLETED, rejected, _UNKNOWN))


_OLD_REASONS = "'response_format_rejected','provider_rejected'"
_NEW_REASONS = "'response_format_rejected','provider_rejected','budget_exhausted'"


def _install_constraint(reasons: str) -> None:
    """Drop and re-add the lifecycle check without scanning existing rows;
    validation runs separately, outside the DDL transaction."""
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_CONSTRAINT} "
        f"CHECK ({_lifecycle_shape(reasons)}) NOT VALID"
    )


def _validate_constraint() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TABLE {_TABLE} VALIDATE CONSTRAINT {_CONSTRAINT}")


def count_budget_exhausted_receipts(connection: Connection) -> int:
    """Receipts that only the widened constraint admits; the downgrade refuses
    while any exist (shared with the integration test that proves it)."""
    return int(
        connection.execute(
            sa.text(
                f"SELECT count(*) FROM {_TABLE} "
                "WHERE status = 'rejected' AND outcome_reason = 'budget_exhausted'"
            )
        ).scalar_one()
    )


def refuse_downgrade_if_budget_exhausted_receipts(connection: Connection) -> None:
    settled = count_budget_exhausted_receipts(connection)
    if settled:
        raise RuntimeError(
            f"Refusing to downgrade 202609201000: {settled} provider-call receipt(s) "
            "are settled as budget_exhausted and the previous constraint cannot "
            "hold them without misattributing the outcome. Keep this revision."
        )


def upgrade() -> None:
    _install_constraint(_NEW_REASONS)
    _validate_constraint()


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    refuse_downgrade_if_budget_exhausted_receipts(op.get_bind())
    _install_constraint(_OLD_REASONS)
    _validate_constraint()
