from __future__ import annotations

import pytest

from eneo.flows.step_item_map import build_step_item_map_config
from eneo.main.exceptions import BadRequestException


def test_build_step_item_map_config_defaults_to_disabled() -> None:
    assert build_step_item_map_config(None).enabled is False
    assert build_step_item_map_config({"item_map": False}).enabled is False


@pytest.mark.parametrize(
    "item_map",
    [
        True,
        {"enabled": True},
    ],
)
def test_build_step_item_map_config_accepts_enabled_values(item_map: object) -> None:
    assert build_step_item_map_config({"item_map": item_map}).enabled is True


@pytest.mark.parametrize(
    "item_map",
    [
        0,
        {"enabled": "true"},
    ],
)
def test_build_step_item_map_config_rejects_invalid_values(item_map: object) -> None:
    with pytest.raises(BadRequestException, match="item_map"):
        build_step_item_map_config({"item_map": item_map})
