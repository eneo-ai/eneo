"""Retain accepted provider job identities throughout the call lifecycle.

Revision ID: 202609201100
Revises: 202609201000
"""

import sqlalchemy as sa

from alembic import op

revision = "202609201100"
down_revision = "202609201000"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_flow_provider_calls_lifecycle_shape"
_TABLE = "flow_provider_calls"
_OLD_SHAPE = (
    "(status = 'started' AND finished_at IS NULL AND outcome_reason IS NULL "
    "AND response_model IS NULL AND provider_response_id IS NULL "
    "AND num_tokens_input IS NULL AND num_tokens_output IS NULL "
    "AND input_source IS NULL AND output_source IS NULL) OR "
    "(status = 'completed' AND outcome_reason IS NULL AND input_source IS NOT NULL "
    "AND output_source IS NOT NULL AND finished_at IS NOT NULL) OR "
    "(status = 'rejected' AND finished_at IS NOT NULL AND outcome_reason IN "
    "('response_format_rejected','provider_rejected','budget_exhausted') "
    "AND response_model IS NULL AND provider_response_id IS NULL "
    "AND num_tokens_input IS NULL AND num_tokens_output IS NULL "
    "AND input_source IS NULL AND output_source IS NULL) OR "
    "(status = 'outcome_unknown' AND finished_at IS NOT NULL AND outcome_reason IN "
    "('request_timeout','run_cancelled','worker_interrupted','provider_error',"
    "'request_cancelled','stale_started') "
    "AND response_model IS NULL AND provider_response_id IS NULL "
    "AND num_tokens_input IS NULL AND num_tokens_output IS NULL "
    "AND input_source IS NULL AND output_source IS NULL)"
)
_NEW_SHAPE = _OLD_SHAPE.replace("AND provider_response_id IS NULL ", "")


def _install_constraint(shape: str) -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_CONSTRAINT} CHECK ({shape}) NOT VALID"
    )
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            op.execute(f"ALTER TABLE {_TABLE} VALIDATE CONSTRAINT {_CONSTRAINT}")
        finally:
            op.execute("RESET lock_timeout")


def upgrade() -> None:
    _install_constraint(_NEW_SHAPE)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(f"LOCK TABLE {_TABLE} IN ACCESS EXCLUSIVE MODE")
    retained = (
        op.get_bind()
        .execute(
            sa.text(
                f"SELECT count(*) FROM {_TABLE} "
                "WHERE status != 'completed' AND provider_response_id IS NOT NULL"
            )
        )
        .scalar_one()
    )
    if retained:
        raise RuntimeError(
            f"Refusing to downgrade 202609201100: {retained} provider-call receipt(s) "
            "retain accepted job identities that the previous constraint cannot hold."
        )
    _install_constraint(_OLD_SHAPE)
