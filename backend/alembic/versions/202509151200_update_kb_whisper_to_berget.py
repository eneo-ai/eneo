# flake8: noqa

"""update kb whisper to berget
Revision ID: update_kb_whisper_to_berget
Revises: f6ae7dc6c04f
Create Date: 2025-09-15 12:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = 'update_kb_whisper_to_berget'
down_revision = 'f6ae7dc6c04f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Update the existing KB-Whisper model to use berget.ai
    conn = op.get_bind()
    
    conn.execute(
        sa.text("""
            UPDATE transcription_models 
            SET 
                base_url = 'https://api.berget.ai/v1',
                org = 'Berget',
                hosting = 'swe',
                description = 'Fine-tuned version of Whisper, specialized on the Swedish language. Hosted on Berget.ai.'
            WHERE model_name = 'KBLab/kb-whisper-large'
        """)
    )


def downgrade() -> None:
    # Revert back to intric hosting
    conn = op.get_bind()
    
    conn.execute(
        sa.text("""
            UPDATE transcription_models 
            SET 
                base_url = 'https://gpu3.intric.ai/v1/',
                org = 'KBLab',
                hosting = 'eu',
                description = 'Fine-tuned version of Whisper, specialized on the Swedish language.'
            WHERE model_name = 'KBLab/kb-whisper-large'
        """)
    )