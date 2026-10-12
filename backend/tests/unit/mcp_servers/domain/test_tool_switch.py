"""The order of the instance admin's switch and the space's, for every case."""

from __future__ import annotations

import pytest

from eneo.mcp_servers.domain.tool_switch import ToolSwitch, tool_switch

ON, FOR_ALL, BY_DEFAULT, IN_SPACE = (
    ToolSwitch.ON,
    ToolSwitch.OFF_FOR_ALL,
    ToolSwitch.OFF_BY_DEFAULT,
    ToolSwitch.OFF_IN_SPACE,
)


# Each row names what a wrong order would get wrong: the instance admin's off
# beats a space's on; a space's own switch beats the default in both
# directions; with no switch at all the tool's default decides.
@pytest.mark.parametrize(
    ("enabled_by_default", "tenant_setting", "space_override", "expected"),
    [
        (True, False, None, FOR_ALL),
        (True, False, True, FOR_ALL),
        (True, False, False, FOR_ALL),
        (False, False, True, FOR_ALL),
        (False, False, None, FOR_ALL),
        (False, False, False, FOR_ALL),
        (True, None, None, ON),
        (True, True, None, ON),
        (False, True, None, ON),
        (False, None, None, BY_DEFAULT),
        (False, None, True, ON),
        (False, True, True, ON),
        (True, None, True, ON),
        (True, True, True, ON),
        (True, None, False, IN_SPACE),
        (True, True, False, IN_SPACE),
        (False, True, False, IN_SPACE),
        (False, None, False, IN_SPACE),
    ],
)
def test_the_instance_switch_comes_first_then_the_space(
    enabled_by_default: bool,
    tenant_setting: bool | None,
    space_override: bool | None,
    expected: ToolSwitch,
) -> None:
    assert (
        tool_switch(
            enabled_by_default=enabled_by_default,
            tenant_setting=tenant_setting,
            space_override=space_override,
        )
        is expected
    )
