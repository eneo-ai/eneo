"""add governed reasoning effort

Revision ID: 202608121500
Revises: 202608101300
Create Date: 2026-08-12 15:00:00.000000
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608121500"
down_revision: str | None = "202608101300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _trusted_legacy_capabilities() -> dict[str, object]:
    unsupported = {"supported": False}
    return {
        "temperature": unsupported,
        "top_p": unsupported,
        "reasoning_effort": {
            "supported": True,
            "control": "select",
            "options": ["low", "medium", "high"],
        },
        "verbosity": {
            "supported": True,
            "control": "select",
            "options": ["low", "medium", "high"],
        },
        "presence_penalty": unsupported,
        "frequency_penalty": unsupported,
        "top_k": unsupported,
    }


def upgrade() -> None:
    # Older capability discovery advertised literal `none` for every route
    # with the generic reasoning parameter. Remove that unverified choice;
    # refreshed snapshots add it back only when LiteLLM explicitly confirms
    # route support.
    op.execute(
        sa.text(
            """
            UPDATE completion_models
            SET model_kwargs_capabilities = jsonb_set(
                model_kwargs_capabilities,
                '{reasoning_effort,options}',
                (model_kwargs_capabilities #> '{reasoning_effort,options}') - 'none',
                false
            )
            WHERE jsonb_typeof(
                model_kwargs_capabilities #> '{reasoning_effort,options}'
            ) = 'array'
              AND (model_kwargs_capabilities #> '{reasoning_effort,options}') ? 'none'
              AND NOT model_kwargs_capabilities ? '_evidence'
            """
        )
    )
    # The original GPT-5 catalog backfill predates persisted evidence tags.
    # Trust only its exact post-cleanup shape; arbitrary untagged JSON remains
    # rejected by the domain loader.
    op.execute(
        sa.text(
            """
            UPDATE completion_models
            SET model_kwargs_capabilities = jsonb_set(
                model_kwargs_capabilities,
                '{_evidence}',
                '"catalog_backfill"'::jsonb,
                true
            )
            WHERE model_kwargs_capabilities = CAST(:capabilities AS jsonb)
            """
        ).bindparams(capabilities=json.dumps(_trusted_legacy_capabilities()))
    )

    op.add_column(
        "governance_policies",
        sa.Column(
            "reasoning_policy_configured",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "governance_policies",
        sa.Column("default_reasoning_effort", sa.String(), nullable=True),
    )
    op.add_column(
        "governance_policies",
        sa.Column(
            "allow_user_reasoning_effort",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    # Do not restore `none`: legacy snapshots never proved exact route support.
    op.execute(
        sa.text(
            """
            UPDATE completion_models
            SET model_kwargs_capabilities = model_kwargs_capabilities - '_evidence'
            WHERE model_kwargs_capabilities ->> '_evidence' = 'catalog_backfill'
            """
        )
    )
    op.drop_column("governance_policies", "allow_user_reasoning_effort")
    op.drop_column("governance_policies", "default_reasoning_effort")
    op.drop_column("governance_policies", "reasoning_policy_configured")
