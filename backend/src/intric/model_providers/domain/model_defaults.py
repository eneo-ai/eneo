from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelDefaults:
    max_input_tokens: int | None
    max_output_tokens: int | None
    supports_vision: bool
    supports_function_calling: bool
    supports_reasoning: bool


def _build_defaults(info: dict) -> ModelDefaults:
    return ModelDefaults(
        max_input_tokens=info.get("max_input_tokens"),
        max_output_tokens=info.get("max_output_tokens"),
        supports_vision=info.get("supports_vision", False),
        supports_function_calling=info.get("supports_function_calling", False),
        supports_reasoning=info.get("supports_reasoning", False),
    )


def _get_model_cost() -> dict:
    import litellm

    return litellm.model_cost


def _lookup_exact(model_cost: dict, model_name: str) -> ModelDefaults | None:
    info = model_cost.get(model_name)
    if info is None:
        return None
    return _build_defaults(info)


def _lookup_prefixed(model_cost: dict, model_name: str) -> ModelDefaults | None:
    prefixes = {
        key.split("/", 1)[0]
        for key in model_cost
        if "/" in key
    }
    for prefix in sorted(prefixes):
        defaults = _lookup_exact(model_cost, f"{prefix}/{model_name}")
        if defaults is not None:
            return defaults
    return None


def lookup_model_defaults(*model_names: str | None) -> ModelDefaults | None:
    model_cost = _get_model_cost()
    for model_name in model_names:
        if not model_name:
            continue
        defaults = _lookup_exact(model_cost, model_name)
        if defaults is not None:
            return defaults

    for model_name in model_names:
        if not model_name or "/" in model_name:
            continue
        defaults = _lookup_prefixed(model_cost, model_name)
        if defaults is not None:
            return defaults

    return None
