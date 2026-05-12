"""enforce sessions.user_id XOR sessions.api_key_id at the DB layer

202605061100 made `sessions.user_id` nullable and introduced `api_key_id`
to support service-key sessions. The application contract — documented in
`sessions_table.py` — is that *exactly one* of the two columns is set per
row: a session is either a user session or a service-key session, never
both and never neither.

That invariant was previously enforced only by the calling code. A bug in
any future write path (or a manual DB tweak) could land a NULL/NULL row
that is invisible to user-scoped listings and dereferences nothing
useful. Add the constraint at the DB layer so violations fail-loud
instead of accumulating silently.

Revision ID: 20260512_sessions_xor_check
Revises: 20260512_merge_heads
Create Date: 2026-05-12 11:30:00
"""

from alembic import op

# revision identifiers, used by Alembic
revision = "20260512_sessions_xor_check"
down_revision = "20260512_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_sessions_user_xor_api_key",
        "sessions",
        "(user_id IS NOT NULL) <> (api_key_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_sessions_user_xor_api_key", "sessions", type_="check"
    )
