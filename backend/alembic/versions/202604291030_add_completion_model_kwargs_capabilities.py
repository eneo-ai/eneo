"""add completion model kwargs capabilities

Store model-specific parameter capabilities as data instead of deriving them
from model-name substrings at runtime. The backfill preserves the behavior that
existing GPT-5 rows had before this migration; future rows must opt in through
the explicit JSONB metadata.

Revision ID: 202604291030
Revises: 202604281200
Create Date: 2026-04-29 10:30:00.000000
"""

import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic
revision = "202604291030"
down_revision = "202604281200"
branch_labels = None
depends_on = None


def _unsupported() -> dict[str, object]:
    return {"supported": False}


def _reasoning_capabilities(
    *, reasoning_options: list[str], include_verbosity: bool
) -> dict[str, object]:
    return {
        "temperature": _unsupported(),
        "top_p": _unsupported(),
        "reasoning_effort": {
            "supported": True,
            "control": "select",
            "options": reasoning_options,
        },
        "verbosity": {
            "supported": include_verbosity,
            "control": "select" if include_verbosity else None,
            "options": ["low", "medium", "high"] if include_verbosity else None,
        },
        "presence_penalty": _unsupported(),
        "frequency_penalty": _unsupported(),
        "top_k": _unsupported(),
    }


def _backfill_gpt5_capabilities(
    *, name_pattern: str, capabilities: dict[str, object]
) -> None:
    op.execute(
        sa.text(
            """
            UPDATE completion_models
            SET model_kwargs_capabilities = CAST(:capabilities AS jsonb)
            WHERE model_kwargs_capabilities IS NULL
              AND reasoning IS TRUE
              AND lower(name) LIKE :name_pattern
            """
        ).bindparams(
            capabilities=json.dumps(capabilities),
            name_pattern=name_pattern,
        )
    )


def upgrade() -> None:
    op.add_column(
        "completion_models",
        sa.Column(
            "model_kwargs_capabilities",
            JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    _backfill_gpt5_capabilities(
        name_pattern="gpt-5.%",
        capabilities=_reasoning_capabilities(
            reasoning_options=["none", "low", "medium", "high"],
            include_verbosity=True,
        ),
    )
    _backfill_gpt5_capabilities(
        name_pattern="gpt-5%",
        capabilities=_reasoning_capabilities(
            reasoning_options=["low", "medium", "high"],
            include_verbosity=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("completion_models", "model_kwargs_capabilities")
