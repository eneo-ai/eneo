"""add_conversation_retention_policies
Revision ID: ba700144afe5
Revises: audit_performance_indexes
Create Date: 2025-11-14 07:44:23.261647
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = 'ba700144afe5'
down_revision = 'audit_performance_indexes'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Add data_retention_days to spaces table with CHECK constraint
    op.add_column('spaces', sa.Column('data_retention_days', sa.Integer(), nullable=True))
    op.create_check_constraint(
        'ck_spaces_data_retention_days_range',
        'spaces',
        'data_retention_days IS NULL OR (data_retention_days >= 1 AND data_retention_days <= 2555)'
    )

    # Add conversation retention fields to audit_retention_policies table
    op.add_column(
        'audit_retention_policies',
        sa.Column('conversation_retention_enabled', sa.Boolean(), nullable=False, server_default='false')
    )
    op.add_column(
        'audit_retention_policies',
        sa.Column('conversation_retention_days', sa.Integer(), nullable=True)
    )
    op.create_check_constraint(
        'ck_audit_retention_policies_conversation_retention_days_range',
        'audit_retention_policies',
        'conversation_retention_days IS NULL OR (conversation_retention_days >= 1 AND conversation_retention_days <= 2555)'
    )

    # Add CHECK constraints to existing assistants.data_retention_days
    op.create_check_constraint(
        'ck_assistants_data_retention_days_range',
        'assistants',
        'data_retention_days IS NULL OR (data_retention_days >= 1 AND data_retention_days <= 2555)'
    )

    # Add CHECK constraints to existing apps.data_retention_days
    op.create_check_constraint(
        'ck_apps_data_retention_days_range',
        'apps',
        'data_retention_days IS NULL OR (data_retention_days >= 1 AND data_retention_days <= 2555)'
    )

    # Add performance indexes for retention cleanup queries
    op.create_index(
        'ix_questions_assistant_created',
        'questions',
        ['assistant_id', 'created_at'],
        postgresql_using='btree',
    )

    op.create_index(
        'ix_app_runs_app_created',
        'app_runs',
        ['app_id', 'created_at'],
        postgresql_using='btree',
    )

def downgrade() -> None:
    # Drop performance indexes
    op.drop_index('ix_questions_assistant_created', table_name='questions')
    op.drop_index('ix_app_runs_app_created', table_name='app_runs')

    # Drop CHECK constraints from apps
    op.drop_constraint('ck_apps_data_retention_days_range', 'apps', type_='check')

    # Drop CHECK constraints from assistants
    op.drop_constraint('ck_assistants_data_retention_days_range', 'assistants', type_='check')

    # Drop audit_retention_policies conversation retention fields and constraints
    op.drop_constraint('ck_audit_retention_policies_conversation_retention_days_range', 'audit_retention_policies', type_='check')
    op.drop_column('audit_retention_policies', 'conversation_retention_days')
    op.drop_column('audit_retention_policies', 'conversation_retention_enabled')

    # Drop spaces data_retention_days column and constraint
    op.drop_constraint('ck_spaces_data_retention_days_range', 'spaces', type_='check')
    op.drop_column('spaces', 'data_retention_days')