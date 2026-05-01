"""backfill cost columns from LiteLLM for existing models

Walks all completion, embedding and transcription rows whose cost columns
are NULL and tries to look up matching prices in `litellm.model_cost`.
Anything not found stays NULL — the UI already handles missing prices
("–" + "Cost unknown" tooltip).

Why a data migration:
  - Existing tenants populated their model tables before the cost columns
    existed. Hand-editing each row is tedious; clicking "Lookup defaults"
    in the edit dialog works but only one model at a time.
  - Idempotent: only NULL cells are touched. Re-running is a no-op.

Notes:
  - Token-priced models (completion + embedding) get
    ``input_cost_per_token`` / ``output_cost_per_token`` from LiteLLM as-is.
  - Transcription gets ``cost_per_minute`` derived from
    ``input_cost_per_second × 60`` (LiteLLM's native unit).
  - Lookup tries the bare model name first, then ``<provider>/<name>``
    variants, mirroring `/model-defaults/`.

Revision ID: 20260501_backfill_model_costs
Revises: 20260430_add_model_costs
Create Date: 2026-05-01 09:00:00.000000
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = "20260501_backfill_model_costs"
down_revision = "20260430_add_model_costs"
branch_labels = None
depends_on = None


def _load_model_cost() -> dict[str, dict[str, Any]]:
    """Import LiteLLM lazily so non-runtime tooling (alembic --help, etc.)
    doesn't pay the import cost. Returns an empty dict if the package isn't
    available — the migration then becomes a no-op rather than crashing."""
    try:
        import litellm  # type: ignore[import-not-found]
    except Exception:
        return {}
    return getattr(litellm, "model_cost", {}) or {}


def _lookup(model_cost: dict[str, dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Mirror the resolution logic from `/model-defaults/`: exact match first,
    then `<provider>/<name>` for every prefix that appears in the cost map.
    """
    if not name:
        return None
    if name in model_cost:
        return model_cost[name]
    prefixes: set[str] = set()
    for key in model_cost:
        if "/" in key:
            prefixes.add(key.split("/")[0])
    for prefix in sorted(prefixes):
        candidate = f"{prefix}/{name}"
        info = model_cost.get(candidate)
        if info is not None:
            return info
    return None


def _backfill_token_costs(connection: sa.Connection, table: str, model_cost: dict[str, Any]) -> int:
    """Fill input/output_cost_per_token where NULL. Returns count updated."""
    rows = connection.execute(
        sa.text(
            f"SELECT id, name FROM {table} "
            "WHERE input_cost_per_token IS NULL OR output_cost_per_token IS NULL"
        )
    ).mappings().all()

    updates = 0
    for row in rows:
        info = _lookup(model_cost, row["name"])
        if info is None:
            continue
        in_rate = info.get("input_cost_per_token")
        out_rate = info.get("output_cost_per_token")
        if in_rate is None and out_rate is None:
            continue
        connection.execute(
            sa.text(
                f"UPDATE {table} "
                "SET input_cost_per_token = COALESCE(input_cost_per_token, :in_rate), "
                "    output_cost_per_token = COALESCE(output_cost_per_token, :out_rate) "
                "WHERE id = :id"
            ),
            {"id": row["id"], "in_rate": in_rate, "out_rate": out_rate},
        )
        updates += 1
    return updates


def _backfill_per_minute(connection: sa.Connection, model_cost: dict[str, Any]) -> int:
    """Fill cost_per_minute (transcription) where NULL. Returns count updated."""
    rows = connection.execute(
        sa.text(
            "SELECT id, name FROM transcription_models WHERE cost_per_minute IS NULL"
        )
    ).mappings().all()

    updates = 0
    for row in rows:
        info = _lookup(model_cost, row["name"])
        if info is None:
            continue
        per_second = info.get("input_cost_per_second")
        if not isinstance(per_second, (int, float)):
            continue
        per_minute = per_second * 60
        connection.execute(
            sa.text(
                "UPDATE transcription_models SET cost_per_minute = :rate WHERE id = :id"
            ),
            {"id": row["id"], "rate": per_minute},
        )
        updates += 1
    return updates


def upgrade() -> None:
    model_cost = _load_model_cost()
    if not model_cost:
        # Either litellm isn't installed in the migration environment or its
        # cost map is empty. Either way, leave NULLs as-is — admins can use
        # the "Lookup defaults" button per row when ready.
        return

    bind = op.get_bind()
    completion_n = _backfill_token_costs(bind, "completion_models", model_cost)
    embedding_n = _backfill_token_costs(bind, "embedding_models", model_cost)
    transcription_n = _backfill_per_minute(bind, model_cost)

    print(  # noqa: T201 — surface progress in alembic output
        f"[backfill_model_costs] completion={completion_n} "
        f"embedding={embedding_n} transcription={transcription_n}"
    )


def downgrade() -> None:
    # No-op: we wouldn't know which rows were backfilled vs. set by hand,
    # and resetting prices would lose admin-entered values. Use the schema
    # downgrade in 20260430_add_model_costs to drop the columns entirely.
    pass
