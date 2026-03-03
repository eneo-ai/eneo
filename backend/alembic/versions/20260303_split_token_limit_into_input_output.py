"""split token_limit into max_input_tokens and max_output_tokens

Revision ID: 20260303_split_token_limit
Revises: 9d2a6c01f3e7
Create Date: 2026-03-03
"""

import sqlalchemy as sa
from alembic import op

revision = "20260303_split_token_limit"
down_revision = "9d2a6c01f3e7"
branch_labels = None
depends_on = None


def _lookup_litellm_values():
    """Build a dict of {model_name: (max_input, max_output)} from litellm model_cost."""
    try:
        from litellm import model_cost

        result = {}
        for key, info in model_cost.items():
            max_input = info.get("max_input_tokens")
            max_output = info.get("max_output_tokens")
            if max_input and max_output:
                result[key] = (int(max_input), int(max_output))
        return result
    except Exception:
        return {}


def upgrade() -> None:
    # 1. Add nullable columns
    op.add_column(
        "completion_models",
        sa.Column("max_input_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "completion_models",
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
    )

    # 2. Populate from litellm model_cost where possible, else fall back
    litellm_map = _lookup_litellm_values()

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, name, litellm_model_name, token_limit "
            "FROM completion_models"
        )
    ).fetchall()

    for row in rows:
        model_id, name, litellm_model_name, token_limit = row

        max_input = None
        max_output = None

        # Try litellm_model_name first, then plain name
        for lookup_key in [litellm_model_name, name]:
            if lookup_key and lookup_key in litellm_map:
                max_input, max_output = litellm_map[lookup_key]
                break

        # Fallback for custom/vLLM models
        if max_input is None:
            max_input = token_limit
            max_output = min(token_limit // 4, 4096)

        conn.execute(
            sa.text(
                "UPDATE completion_models "
                "SET max_input_tokens = :max_input, max_output_tokens = :max_output "
                "WHERE id = :id"
            ),
            {"max_input": max_input, "max_output": max_output, "id": model_id},
        )

    # 3. Make NOT NULL
    op.alter_column(
        "completion_models", "max_input_tokens", nullable=False
    )
    op.alter_column(
        "completion_models", "max_output_tokens", nullable=False
    )

    # 4. Drop old column
    op.drop_column("completion_models", "token_limit")


def downgrade() -> None:
    # Recreate token_limit from max_input_tokens
    op.add_column(
        "completion_models",
        sa.Column("token_limit", sa.Integer(), nullable=True),
    )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE completion_models SET token_limit = max_input_tokens"
        )
    )

    op.alter_column("completion_models", "token_limit", nullable=False)

    op.drop_column("completion_models", "max_output_tokens")
    op.drop_column("completion_models", "max_input_tokens")
