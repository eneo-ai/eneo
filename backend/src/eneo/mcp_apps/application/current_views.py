"""The view a stored tool call shows when its conversation is read again.

A tool call is stored with the view approved for its tool when it was made. A
server's views change with its releases, and a bundled server's follow every
release of the runtime image: the stored view is then no longer the approved
one, and no link is minted for it. So a call that is read back shows the view
approved for its tool now. Nothing but an approved view is ever shown, and a
conversation outlives the releases of the servers it used.

A call whose tool shows no view now (it was disabled, or lost its view) keeps
what was stored, which is not served.
"""

from collections.abc import Iterable
from typing import TYPE_CHECKING
from uuid import UUID

from eneo.main.config import get_settings

if TYPE_CHECKING:
    from eneo.mcp_apps.infrastructure.repo_impl.mcp_app_view_repo_impl import (
        McpAppViewRepo,
    )
    from eneo.questions.question import ToolCallInfo


def _server_id(call: "ToolCallInfo") -> UUID | None:
    try:
        return UUID(str((call.app_view or {}).get("mcp_server_id")))
    except ValueError:
        return None


async def show_current_views(
    calls: "Iterable[ToolCallInfo]", repo: "McpAppViewRepo"
) -> None:
    """Point every call that shows a view at the one approved for its tool now."""
    if not get_settings().mcp_apps_enabled:
        return
    by_tool: "dict[tuple[UUID, str], list[ToolCallInfo]]" = {}
    for call in calls:
        server_id = _server_id(call)
        if server_id is not None:
            by_tool.setdefault((server_id, call.tool_name), []).append(call)
    if not by_tool:
        return

    current = await repo.approved_for_tools(by_tool.keys())
    for tool, shown in by_tool.items():
        view = current.get(tool)
        if view is None:
            continue
        for call in shown:
            call.app_view = {
                "view_id": str(view.view_id),
                "mcp_server_id": str(view.mcp_server_id),
                "ui": view.ui_meta or {},
            }
