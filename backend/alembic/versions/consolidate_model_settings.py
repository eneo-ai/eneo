"""consolidate_model_settings

Moves settings columns (is_enabled, is_default, security_classification_id)
from separate settings tables directly onto the model tables.

This is possible now that we have tenant-specific models - each tenant has
their own model row, so settings can be stored directly on the model.

Revision ID: consolidate_model_settings
Revises: migrate_global_to_tenant_models
Create Date: 2025-12-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic
revision = 'consolidate_model_settings'
down_revision = 'migrate_global_to_tenant_models'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    print("\n" + "=" * 60)
    print("MIGRATION: Consolidate Model Settings")
    print("=" * 60)

    # =========================================================================
    # PHASE 1: Add new columns to model tables
    # =========================================================================
    print("\n[1/4] Adding new columns to model tables...")

    # CompletionModels
    op.add_column('completion_models', sa.Column('is_enabled', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('completion_models', sa.Column('is_default', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('completion_models', sa.Column('security_classification_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_completion_models_security_classification',
        'completion_models', 'security_classifications',
        ['security_classification_id'], ['id'],
        ondelete='SET NULL'
    )
    print("  ✓ Added columns to completion_models")

    # EmbeddingModels
    op.add_column('embedding_models', sa.Column('is_enabled', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('embedding_models', sa.Column('is_default', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('embedding_models', sa.Column('security_classification_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_embedding_models_security_classification',
        'embedding_models', 'security_classifications',
        ['security_classification_id'], ['id'],
        ondelete='SET NULL'
    )
    print("  ✓ Added columns to embedding_models")

    # TranscriptionModels
    op.add_column('transcription_models', sa.Column('is_enabled', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('transcription_models', sa.Column('is_default', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('transcription_models', sa.Column('security_classification_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_transcription_models_security_classification',
        'transcription_models', 'security_classifications',
        ['security_classification_id'], ['id'],
        ondelete='SET NULL'
    )
    print("  ✓ Added columns to transcription_models")

    # =========================================================================
    # PHASE 2: Migrate data from settings tables
    # =========================================================================
    print("\n[2/4] Migrating data from settings tables...")

    # Completion models - migrate settings for tenant-specific models
    result = conn.execute(text("""
        UPDATE completion_models cm
        SET
            is_enabled = COALESCE(cms.is_org_enabled, true),
            is_default = COALESCE(cms.is_org_default, false),
            security_classification_id = cms.security_classification_id
        FROM completion_model_settings cms
        WHERE cm.id = cms.completion_model_id
          AND cm.tenant_id = cms.tenant_id
          AND cm.tenant_id IS NOT NULL
    """))
    print(f"  ✓ Migrated completion model settings ({result.rowcount} rows)")

    # Embedding models
    result = conn.execute(text("""
        UPDATE embedding_models em
        SET
            is_enabled = COALESCE(ems.is_org_enabled, true),
            is_default = COALESCE(ems.is_org_default, false),
            security_classification_id = ems.security_classification_id
        FROM embedding_model_settings ems
        WHERE em.id = ems.embedding_model_id
          AND em.tenant_id = ems.tenant_id
          AND em.tenant_id IS NOT NULL
    """))
    print(f"  ✓ Migrated embedding model settings ({result.rowcount} rows)")

    # Transcription models
    result = conn.execute(text("""
        UPDATE transcription_models tm
        SET
            is_enabled = COALESCE(tms.is_org_enabled, true),
            is_default = COALESCE(tms.is_org_default, false),
            security_classification_id = tms.security_classification_id
        FROM transcription_model_settings tms
        WHERE tm.id = tms.transcription_model_id
          AND tm.tenant_id = tms.tenant_id
          AND tm.tenant_id IS NOT NULL
    """))
    print(f"  ✓ Migrated transcription model settings ({result.rowcount} rows)")

    # =========================================================================
    # PHASE 3: Create indexes for new columns
    # =========================================================================
    print("\n[3/4] Creating indexes...")

    op.create_index('idx_completion_models_is_enabled', 'completion_models', ['is_enabled'])
    op.create_index('idx_completion_models_is_default', 'completion_models', ['is_default'])
    op.create_index('idx_embedding_models_is_enabled', 'embedding_models', ['is_enabled'])
    op.create_index('idx_embedding_models_is_default', 'embedding_models', ['is_default'])
    op.create_index('idx_transcription_models_is_enabled', 'transcription_models', ['is_enabled'])
    op.create_index('idx_transcription_models_is_default', 'transcription_models', ['is_default'])
    print("  ✓ Created indexes")

    # =========================================================================
    # PHASE 4: Drop settings tables
    # =========================================================================
    print("\n[4/4] Dropping settings tables...")

    op.drop_table('completion_model_settings')
    print("  ✓ Dropped completion_model_settings")

    op.drop_table('embedding_model_settings')
    print("  ✓ Dropped embedding_model_settings")

    op.drop_table('transcription_model_settings')
    print("  ✓ Dropped transcription_model_settings")

    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE!")
    print("=" * 60)
    print("\nSettings have been consolidated into model tables.")
    print("The separate settings tables have been removed.")
    print("=" * 60 + "\n")


def downgrade() -> None:
    """
    Recreate settings tables and migrate data back.
    """
    conn = op.get_bind()

    # Recreate completion_model_settings
    op.create_table(
        'completion_model_settings',
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('completion_model_id', UUID(as_uuid=True), sa.ForeignKey('completion_models.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('is_org_enabled', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('is_org_default', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('security_classification_id', UUID(as_uuid=True), sa.ForeignKey('security_classifications.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Recreate embedding_model_settings
    op.create_table(
        'embedding_model_settings',
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('embedding_model_id', UUID(as_uuid=True), sa.ForeignKey('embedding_models.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('is_org_enabled', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('is_org_default', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('security_classification_id', UUID(as_uuid=True), sa.ForeignKey('security_classifications.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Recreate transcription_model_settings
    op.create_table(
        'transcription_model_settings',
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('transcription_model_id', UUID(as_uuid=True), sa.ForeignKey('transcription_models.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('is_org_enabled', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('is_org_default', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('security_classification_id', UUID(as_uuid=True), sa.ForeignKey('security_classifications.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Migrate data back from model tables to settings tables
    conn.execute(text("""
        INSERT INTO completion_model_settings (tenant_id, completion_model_id, is_org_enabled, is_org_default, security_classification_id)
        SELECT tenant_id, id, is_enabled, is_default, security_classification_id
        FROM completion_models
        WHERE tenant_id IS NOT NULL
    """))

    conn.execute(text("""
        INSERT INTO embedding_model_settings (tenant_id, embedding_model_id, is_org_enabled, is_org_default, security_classification_id)
        SELECT tenant_id, id, is_enabled, is_default, security_classification_id
        FROM embedding_models
        WHERE tenant_id IS NOT NULL
    """))

    conn.execute(text("""
        INSERT INTO transcription_model_settings (tenant_id, transcription_model_id, is_org_enabled, is_org_default, security_classification_id)
        SELECT tenant_id, id, is_enabled, is_default, security_classification_id
        FROM transcription_models
        WHERE tenant_id IS NOT NULL
    """))

    # Drop indexes
    op.drop_index('idx_completion_models_is_enabled', 'completion_models')
    op.drop_index('idx_completion_models_is_default', 'completion_models')
    op.drop_index('idx_embedding_models_is_enabled', 'embedding_models')
    op.drop_index('idx_embedding_models_is_default', 'embedding_models')
    op.drop_index('idx_transcription_models_is_enabled', 'transcription_models')
    op.drop_index('idx_transcription_models_is_default', 'transcription_models')

    # Drop foreign keys
    op.drop_constraint('fk_completion_models_security_classification', 'completion_models', type_='foreignkey')
    op.drop_constraint('fk_embedding_models_security_classification', 'embedding_models', type_='foreignkey')
    op.drop_constraint('fk_transcription_models_security_classification', 'transcription_models', type_='foreignkey')

    # Drop columns from model tables
    op.drop_column('completion_models', 'is_enabled')
    op.drop_column('completion_models', 'is_default')
    op.drop_column('completion_models', 'security_classification_id')

    op.drop_column('embedding_models', 'is_enabled')
    op.drop_column('embedding_models', 'is_default')
    op.drop_column('embedding_models', 'security_classification_id')

    op.drop_column('transcription_models', 'is_enabled')
    op.drop_column('transcription_models', 'is_default')
    op.drop_column('transcription_models', 'security_classification_id')
