"""Keep settings-only saves from changing conversation activity.

Revision ID: 202611201001
Revises: 202611201000
"""

from alembic import op

revision = "202611201001"
down_revision = "202611201000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("LOCK TABLE sessions IN ACCESS EXCLUSIVE MODE NOWAIT")
    op.execute("DROP TRIGGER update_session_modtime ON sessions")
    op.execute(
        """
        CREATE TRIGGER update_session_modtime
        BEFORE UPDATE ON sessions
        FOR EACH ROW
        WHEN (
            OLD.settings IS NOT DISTINCT FROM NEW.settings
            OR (to_jsonb(OLD) - 'settings') IS DISTINCT FROM (to_jsonb(NEW) - 'settings')
        )
        EXECUTE FUNCTION update_updated_at_column()
        """
    )


def downgrade() -> None:
    op.execute("LOCK TABLE sessions IN ACCESS EXCLUSIVE MODE NOWAIT")
    op.execute("DROP TRIGGER update_session_modtime ON sessions")
    op.execute(
        """
        CREATE TRIGGER update_session_modtime
        BEFORE UPDATE ON sessions
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column()
        """
    )
