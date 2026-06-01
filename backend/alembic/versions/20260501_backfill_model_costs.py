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


# Inlined from intric.model_providers.domain.model_defaults_lookup so this
# migration stays runnable on a fresh DB even if the app module is later
# moved or renamed. Keep semantics in sync with that module if either
# changes — both paths must agree on which LiteLLM row a given
# (name, provider_type) maps to.
def resolve_model_defaults(
    model_cost: dict[str, dict[str, Any]],
    names: list[str | None] | str,
    provider_type: str | None,
) -> dict[str, Any] | None:
    candidates: list[str] = [
        n for n in ([names] if isinstance(names, str) else names) if n
    ]
    if not candidates:
        return None

    if provider_type:
        for n in candidates:
            info = model_cost.get(f"{provider_type}/{n}")
            if info is not None:
                return info

    for n in candidates:
        info = model_cost.get(n)
        if info is not None:
            return info

    if provider_type is None:
        prefixes = {key.split("/", 1)[0] for key in model_cost if "/" in key}
        for n in candidates:
            matching = [p for p in prefixes if f"{p}/{n}" in model_cost]
            if len(matching) == 1:
                return model_cost[f"{matching[0]}/{n}"]
    return None


def is_ambiguous(model_cost: dict[str, Any], name: str | None) -> bool:
    if not name or name in model_cost:
        return False
    prefixes = {
        key.split("/", 1)[0]
        for key in model_cost
        if "/" in key and key.split("/", 1)[1] == name
    }
    return len(prefixes) > 1


def _load_model_cost() -> dict[str, dict[str, Any]]:
    """Import LiteLLM lazily so non-runtime tooling (alembic --help, etc.)
    doesn't pay the import cost. Returns an empty dict if the package isn't
    available — the migration then becomes a no-op rather than crashing."""
    try:
        import litellm  # type: ignore[import-not-found]
    except Exception:
        return {}
    return getattr(litellm, "model_cost", {}) or {}


def _backfill_token_costs(
    connection: sa.Connection, table: str, model_cost: dict[str, Any]
) -> tuple[int, int]:
    """Fill input/output_cost_per_token where NULL.

    Returns ``(updated, ambiguous)`` — ``ambiguous`` counts rows that had no
    provider hint AND matched more than one provider prefix in LiteLLM, which
    are left untouched so admins can disambiguate via "Lookup defaults" in the
    UI rather than receive a silently-wrong price.
    """
    rows = connection.execute(
        sa.text(
            f"SELECT t.id, t.name, t.litellm_model_name, mp.provider_type "
            f"FROM {table} t "
            "LEFT JOIN model_providers mp ON mp.id = t.provider_id "
            "WHERE t.input_cost_per_token IS NULL "
            "   OR t.output_cost_per_token IS NULL"
        )
    ).mappings().all()

    updates = 0
    ambiguous = 0
    for row in rows:
        info = resolve_model_defaults(
            model_cost,
            [row["litellm_model_name"], row["name"]],
            row["provider_type"],
        )
        if info is None:
            if row["provider_type"] is None and is_ambiguous(model_cost, row["name"]):
                ambiguous += 1
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
    return updates, ambiguous


def _backfill_per_minute(
    connection: sa.Connection, model_cost: dict[str, Any]
) -> tuple[int, int]:
    """Fill cost_per_minute (transcription) where NULL.

    Same return shape as ``_backfill_token_costs`` — see that docstring.
    """
    rows = connection.execute(
        sa.text(
            "SELECT t.id, t.name, t.model_name, mp.provider_type "
            "FROM transcription_models t "
            "LEFT JOIN model_providers mp ON mp.id = t.provider_id "
            "WHERE t.cost_per_minute IS NULL"
        )
    ).mappings().all()

    updates = 0
    ambiguous = 0
    for row in rows:
        info = resolve_model_defaults(
            model_cost,
            [row["model_name"], row["name"]],
            row["provider_type"],
        )
        if info is None:
            if row["provider_type"] is None and is_ambiguous(model_cost, row["name"]):
                ambiguous += 1
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
    return updates, ambiguous


def upgrade() -> None:
    model_cost = _load_model_cost()
    if not model_cost:
        # Either litellm isn't installed in the migration environment or its
        # cost map is empty. Either way, leave NULLs as-is — admins can use
        # the "Lookup defaults" button per row when ready.
        return

    bind = op.get_bind()
    completion_n, completion_amb = _backfill_token_costs(bind, "completion_models", model_cost)
    embedding_n, embedding_amb = _backfill_token_costs(bind, "embedding_models", model_cost)
    transcription_n, transcription_amb = _backfill_per_minute(bind, model_cost)

    ambiguous_total = completion_amb + embedding_amb + transcription_amb
    print(  # noqa: T201 — surface progress in alembic output
        f"[backfill_model_costs] completion={completion_n} "
        f"embedding={embedding_n} transcription={transcription_n}"
        + (
            f" skipped_ambiguous={ambiguous_total} (multiple providers in"
            " LiteLLM matched these names; set prices manually via the admin UI)"
            if ambiguous_total
            else ""
        )
    )


def downgrade() -> None:
    # No-op: we wouldn't know which rows were backfilled vs. set by hand,
    # and resetting prices would lose admin-entered values. Use the schema
    # downgrade in 20260430_add_model_costs to drop the columns entirely.
    pass
