"""Provider-aware resolver for LiteLLM's ``model_cost`` map.

Single source of truth used by:
  - ``/api/v1/admin/model-providers/model-defaults/`` (interactive lookup).
  - ``20260501_backfill_model_costs.py`` (one-shot data migration).

Both call paths need identical semantics so the wizard's "Lookup defaults"
button and the bulk backfill don't disagree about which LiteLLM row a given
``(name, provider_type)`` pair maps to.

Resolution order:
  1. If ``provider_type`` is known, prefer the prefixed entry
     ``{provider_type}/{name}`` so Azure-served ``gpt-4o`` picks up
     ``azure/gpt-4o`` prices and not the bare ``gpt-4o`` (OpenAI) entry.
  2. Exact ``name`` match — LiteLLM lists many models (esp. OpenAI
     embeddings) only by bare name.
  3. When provider context is missing, accept a prefixed variant only when
     *exactly one* provider prefix matches. Multiple matches → skip,
     because picking alphabetically silently writes wrong prices to billing
     columns and the data integrity cost outweighs the convenience.
"""

from __future__ import annotations

from typing import Any


def resolve_model_defaults(
    model_cost: dict[str, dict[str, Any]],
    names: list[str | None] | str,
    provider_type: str | None,
) -> dict[str, Any] | None:
    """Resolve a LiteLLM cost entry for the given candidate name(s).

    ``names`` accepts either a single string or a list; the list form lets
    callers try multiple candidates in priority order (e.g.
    ``[litellm_model_name, display_name]`` so an operator override wins over
    the display name).

    Returns the raw ``model_cost`` row, or ``None`` if no unambiguous match.
    """
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
    """True iff ``name`` appears under more than one provider prefix and is
    not listed without prefix. Used by the backfill to count rows that were
    deliberately skipped so admins can disambiguate via the UI."""
    if not name or name in model_cost:
        return False
    prefixes = {
        key.split("/", 1)[0]
        for key in model_cost
        if "/" in key and key.split("/", 1)[1] == name
    }
    return len(prefixes) > 1
