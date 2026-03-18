"""repair_completion_model_output_tokens

Repair legacy completion_models rows that still carry synthetic
max_output_tokens values from the old min(input/4, 4096) rule.

Revision ID: 202603151045
Revises: 202603121400
Create Date: 2026-03-15 10:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "202603151045"
down_revision = "202603121400"
branch_labels = None
depends_on = None


def _lookup_model_cost_defaults(litellm_module, *model_names: str | None):
    def _build(info):
        return (
            info.get("max_input_tokens"),
            info.get("max_output_tokens"),
        )

    for model_name in model_names:
        if not model_name:
            continue
        info = litellm_module.model_cost.get(model_name)
        if info is not None:
            return _build(info)

    prefixes = {
        key.split("/", 1)[0]
        for key in litellm_module.model_cost
        if "/" in key
    }
    for model_name in model_names:
        if not model_name or "/" in model_name:
            continue
        for prefix in sorted(prefixes):
            info = litellm_module.model_cost.get(f"{prefix}/{model_name}")
            if info is not None:
                return _build(info)

    return (None, None)


def upgrade() -> None:
    try:
        import litellm
    except ImportError:
        return

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, name, litellm_model_name, token_limit, "
            "max_input_tokens, max_output_tokens "
            "FROM completion_models"
        )
    ).fetchall()

    for row in rows:
        current_input = row.max_input_tokens or row.token_limit
        current_output = row.max_output_tokens
        default_input, default_output = _lookup_model_cost_defaults(
            litellm, row.litellm_model_name, row.name
        )

        updates: dict[str, int | str] = {"id": row.id}

        if current_input is None and isinstance(default_input, int):
            updates["max_input_tokens"] = default_input

        legacy_output = (
            isinstance(current_input, int)
            and isinstance(current_output, int)
            and current_output == min(int(current_input) // 4, 4096)
        )
        if isinstance(default_output, int) and (
            current_output is None or legacy_output
        ):
            updates["max_output_tokens"] = default_output

        if len(updates) == 1:
            continue

        assignments = []
        if "max_input_tokens" in updates:
            assignments.append("max_input_tokens = :max_input_tokens")
        if "max_output_tokens" in updates:
            assignments.append("max_output_tokens = :max_output_tokens")

        conn.execute(
            sa.text(
                "UPDATE completion_models "
                f"SET {', '.join(assignments)} "
                "WHERE id = :id"
            ),
            updates,
        )


def downgrade() -> None:
    pass
