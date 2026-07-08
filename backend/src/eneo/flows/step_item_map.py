from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from eneo.main.exceptions import BadRequestException


@dataclass(frozen=True, slots=True)
class FlowStepItemMapConfig:
    enabled: bool = False


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
        raise BadRequestException("Step input_config.item_map.enabled must be a boolean.")
    return FlowStepItemMapConfig(enabled=raw_enabled)
