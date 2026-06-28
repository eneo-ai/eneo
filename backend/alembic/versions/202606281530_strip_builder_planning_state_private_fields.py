"""strip unused private fields from builder planning state

Revision ID: 202606281530_builder_state
Revises: 202606281300
Create Date: 2026-06-28 15:30:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "202606281530_builder_state"
down_revision = "202606281300"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE builder_sessions
            SET planning_state_jsonb = planning_state_jsonb - 'phase' - 'evidence'
            WHERE planning_state_jsonb IS NOT NULL
              AND (
                planning_state_jsonb ? 'phase'
                OR planning_state_jsonb ? 'evidence'
              )
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE builder_sessions
            SET planning_state_jsonb = jsonb_set(
                jsonb_set(
                    planning_state_jsonb,
                    '{phase}',
                    CASE
                        WHEN planning_state_jsonb ? 'phase'
                        THEN planning_state_jsonb->'phase'
                        ELSE '"awaiting_input"'::jsonb
                    END,
                    true
                ),
                '{evidence}',
                CASE
                    WHEN planning_state_jsonb ? 'evidence'
                    THEN planning_state_jsonb->'evidence'
                    ELSE
                        '{
                            "conversation_message_ids": [],
                            "attachment_digest_hashes": [],
                            "raw_prompt_hash": ""
                        }'::jsonb
                END,
                true
            )
            WHERE planning_state_jsonb IS NOT NULL
              AND (
                NOT (planning_state_jsonb ? 'phase')
                OR NOT (planning_state_jsonb ? 'evidence')
              )
            """
        )
    )
