"""change_user_quota_limit_to_bigint

Revision ID: e23b168d0080
Revises: 20260116_update_audit_actor_fk
Create Date: 2026-01-22 10:35:04.389328

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = 'e23b168d0080'
down_revision = '20260116_update_audit_actor_fk'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Change users.quota_limit from INTEGER to BIGINT to support values > 2GB
    # 10GB in bytes = 10,737,418,240 which exceeds INTEGER max (2,147,483,647)
    op.alter_column('users', 'quota_limit',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=True)


def downgrade() -> None:
    # Revert to INTEGER (will truncate values > 2GB)
    op.alter_column('users', 'quota_limit',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_nullable=True)
