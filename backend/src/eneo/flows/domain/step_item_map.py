from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from eneo.main.exceptions import BadRequestException


@dataclass(frozen=True, slots=True)
class FlowStepItemMapConfig:
    enabled: bool = False
    max_items: int | None = None


def build_step_item_map_config(
    step_input_config: dict[str, Any] | None,
) -> FlowStepItemMapConfig:
    if not isinstance(step_input_config, dict):
        return FlowStepItemMapConfig()

    raw_config = step_input_config.get("item_map")
    if raw_config is None or raw_config is False:
        return FlowStepItemMapConfig()
    if raw_config is True:
        return FlowStepItemMapConfig(enabled=True)
    if not isinstance(raw_config, Mapping):
        raise BadRequestException("Step input_config.item_map must be an object.")

    typed_config = cast(Mapping[str, object], raw_config)
    raw_enabled = typed_config.get("enabled", True)
    if not isinstance(raw_enabled, bool):
        raise BadRequestException(
            "Step input_config.item_map.enabled must be a boolean."
        )
    raw_max_items = typed_config.get("max_items")
    if raw_max_items is not None and (
        not isinstance(raw_max_items, int)
        or isinstance(raw_max_items, bool)
        or raw_max_items <= 0
    ):
        raise BadRequestException(
            "Step input_config.item_map.max_items must be a positive integer."
        )
    return FlowStepItemMapConfig(enabled=raw_enabled, max_items=raw_max_items)
