from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional


def get_litellm_deprecation_date(
    model_name: str, provider_type: Optional[str] = None
) -> Optional[str]:
    """Look up deprecation_date for a model from LiteLLM's model_cost database.

    Args:
        model_name: The bare model identifier (e.g. "gpt-4o-2024-08-06").
        provider_type: The provider type (e.g. "openai", "anthropic").

    Returns:
        ISO date string (YYYY-MM-DD) if a deprecation date exists, else None.
    """
    import litellm

    cost_map: Dict[str, Any] = litellm.model_cost  # type: ignore[assignment]

    info: Optional[Dict[str, Any]] = None

    # Try prefixed key first (matches how TenantModelAdapter constructs litellm keys)
    if provider_type:
        info = cost_map.get(f"{provider_type}/{model_name}")

    # Fallback: try bare model name
    if info is None:
        info = cost_map.get(model_name)

    if info is None:
        return None

    result: Optional[str] = info.get("deprecation_date")
    return result


def is_model_deprecated(model_name: str, provider_type: Optional[str] = None) -> bool:
    """Check if a model's deprecation date has passed."""
    dep_date = get_litellm_deprecation_date(model_name, provider_type)
    if not dep_date:
        return False
    return dep_date <= date.today().isoformat()


def is_model_effectively_deprecated(
    model_name: str,
    provider_type: Optional[str] = None,
    manually_deprecated: bool = False,
) -> bool:
    """Return the persisted Eneo deprecation decision.

    LiteLLM metadata is advisory and may change on dependency upgrades. It is
    exposed through ``get_litellm_deprecation_date`` for admin/UI enrichment,
    but must not silently change access to an already configured Eneo model.
    """
    return manually_deprecated
