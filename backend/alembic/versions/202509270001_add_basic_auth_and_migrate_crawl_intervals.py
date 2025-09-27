"""add basic auth to websites and migrate crawl intervals

Revision ID: 202509270001
Revises: 2f8e9a1b3c5d
Create Date: 2025-09-27 00:00:01.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '202509270001'
down_revision = '2f8e9a1b3c5d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add basic authentication fields to websites table and migrate crawl intervals.

    This migration:
    1. Adds basic auth fields to websites table (requires_auth, auth_username, etc.)
    2. Migrates deprecated crawl intervals to supported ones:
       - every_3_days -> every_other_day (closest equivalent)
       - every_2_weeks -> weekly (more frequent, better for users)
       - monthly -> weekly (more frequent, better for users)

    The rationale for interval migration is to ensure users get more frequent updates
    rather than less, providing better user experience for website content monitoring.
    """

    # Add basic auth fields to websites table
    op.add_column('websites', sa.Column('requires_auth', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('websites', sa.Column('auth_username', sa.String(), nullable=True))
    op.add_column('websites', sa.Column('encrypted_auth_password', sa.String(), nullable=True))
    op.add_column('websites', sa.Column('auth_last_verified', sa.TIMESTAMP(timezone=True), nullable=True))

    # Update websites with deprecated intervals to new supported intervals
    # This handles websites that may have been set to deprecated intervals

    # Map every_3_days to every_other_day (closest equivalent)
    op.execute("""
        UPDATE websites
        SET update_interval = 'every_other_day'
        WHERE update_interval = 'every_3_days'
    """)

    # Map every_2_weeks to weekly (more frequent is better for users)
    op.execute("""
        UPDATE websites
        SET update_interval = 'weekly'
        WHERE update_interval = 'every_2_weeks'
    """)

    # Map monthly to weekly (more frequent is better for users)
    op.execute("""
        UPDATE websites
        SET update_interval = 'weekly'
        WHERE update_interval = 'monthly'
    """)


def downgrade() -> None:
    """
    Reverse both the basic auth and interval migrations.

    Note: Interval migration is lossy - we can't perfectly restore the original
    intervals since multiple deprecated intervals map to the same new interval.
    """

    # Remove basic auth fields from websites table
    op.drop_column('websites', 'auth_last_verified')
    op.drop_column('websites', 'encrypted_auth_password')
    op.drop_column('websites', 'auth_username')
    op.drop_column('websites', 'requires_auth')

    # Note: Interval migration downgrade is not implemented as it's lossy
    # All websites will keep their migrated intervals (every_other_day, weekly)
    # This is acceptable since the new intervals are more user-friendly