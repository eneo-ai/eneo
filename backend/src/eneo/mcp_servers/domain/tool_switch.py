"""Whether a tool is switched on for a space.

The instance admin's switch comes first, then the space's. This module is the
one owner of that order: the space settings and what an assistant is offered
both ask here.
"""

from enum import Enum


class ToolSwitch(Enum):
    ON = "on"
    # The instance admin switched the tool off; a space cannot turn it on.
    OFF_FOR_ALL = "off_for_all"
    # No switch is set and the tool is off by default; a space may turn it on.
    OFF_BY_DEFAULT = "off_by_default"
    OFF_IN_SPACE = "off_in_space"


def tool_switch(
    *,
    enabled_by_default: bool,
    tenant_setting: bool | None,
    space_override: bool | None,
) -> ToolSwitch:
    """The state of one tool for one space; None means that level has no row."""
    if tenant_setting is False:
        return ToolSwitch.OFF_FOR_ALL
    if space_override is not None:
        return ToolSwitch.ON if space_override else ToolSwitch.OFF_IN_SPACE
    if tenant_setting or enabled_by_default:
        return ToolSwitch.ON
    return ToolSwitch.OFF_BY_DEFAULT
