from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from eneo.model_providers.domain.model_defaults_lookup import resolve_model_defaults

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


def lookup_model_defaults(
    *model_names: str | None, provider_type: str | None = None
) -> ModelDefaults | None:
    info = resolve_model_defaults(_get_model_cost(), list(model_names), provider_type)
    return _build_defaults(info) if info is not None else None
