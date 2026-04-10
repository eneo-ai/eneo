from __future__ import annotations

from dataclasses import dataclass
from typing import cast

ModelCost = dict[str, dict[str, object]]


@dataclass(frozen=True)
class ModelDefaults:
    max_input_tokens: int | None
    max_output_tokens: int | None
    supports_vision: bool
    supports_function_calling: bool
    supports_reasoning: bool


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _bool_value(value: object) -> bool:
    return value if isinstance(value, bool) else False


def _build_defaults(info: dict[str, object]) -> ModelDefaults:
    return ModelDefaults(
        max_input_tokens=_optional_int(info.get("max_input_tokens")),
        max_output_tokens=_optional_int(info.get("max_output_tokens")),
        supports_vision=_bool_value(info.get("supports_vision")),
        supports_function_calling=_bool_value(info.get("supports_function_calling")),
        supports_reasoning=_bool_value(info.get("supports_reasoning")),
    )


def _get_model_cost() -> ModelCost:
    import litellm

    raw_model_cost = getattr(litellm, "model_cost", {})
    return cast(ModelCost, raw_model_cost)


def _lookup_exact(model_cost: ModelCost, model_name: str) -> ModelDefaults | None:
    info = model_cost.get(model_name)
    if info is None:
        return None
    return _build_defaults(info)


def _lookup_prefixed(model_cost: ModelCost, model_name: str) -> ModelDefaults | None:
    prefixes = {key.split("/", 1)[0] for key in model_cost if "/" in key}
    for prefix in sorted(prefixes):
        defaults = _lookup_exact(model_cost, f"{prefix}/{model_name}")
        if defaults is not None:
            return defaults
    return None


def lookup_model_defaults(*model_names: str | None) -> ModelDefaults | None:
    try:
        model_cost = _get_model_cost()
    except TypeError:
        model_cost = cast(ModelCost, _get_model_cost)
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
