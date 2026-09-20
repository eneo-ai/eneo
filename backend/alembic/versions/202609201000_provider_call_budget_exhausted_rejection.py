"""Allow the budget_exhausted rejection reason on flow provider calls.

A provider-call receipt written while the step's execution budget ran out is
settled as a known refusal (nothing was sent, nothing billed) instead of
being left open. The lifecycle constraint enumerates rejection reasons, so
the new reason needs the constraint recreated.

Revision ID: 202609201000
Revises: 202609181000
"""

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


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _lifecycle_shape(_NEW_REASONS))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    # Rows settled with the new reason would violate the old shape; there are
    # none before this revision, and a downgrade after use must clear them.
    op.execute(
        f"UPDATE {_TABLE} SET outcome_reason = 'provider_rejected' "
        "WHERE status = 'rejected' AND outcome_reason = 'budget_exhausted'"
    )
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _lifecycle_shape(_OLD_REASONS))
