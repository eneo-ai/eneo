"""A stored tool call shows the view approved for its tool now: the one it was
stored with gives way to the current one, calls of one tool share a lookup,
and a call whose tool shows no view now keeps what was stored."""

from unittest.mock import AsyncMock
from uuid import uuid4

from eneo.mcp_apps.application import current_views
from eneo.mcp_apps.application.current_views import show_current_views
from eneo.mcp_apps.domain.mcp_app_view import MCP_APP_MIME, McpAppViewInfo
from eneo.questions.question import ToolCallInfo

SERVER_ID = uuid4()


def _enabled(monkeypatch, enabled: bool = True) -> None:
    settings = current_views.get_settings().model_copy(
        update={"mcp_apps_enabled": enabled}
    )
    monkeypatch.setattr(current_views, "get_settings", lambda: settings)


def _call(tool_name: str, view_id=None, server_id=SERVER_ID) -> ToolCallInfo:
    return ToolCallInfo(
        server_name="charts",
        tool_name=tool_name,
        app_view=(
            {"view_id": str(view_id), "mcp_server_id": str(server_id), "ui": {}}
            if view_id
            else None
        ),
    )


def _view(ui_meta: dict | None = None) -> McpAppViewInfo:
    return McpAppViewInfo(
        view_id=uuid4(),
        mcp_server_id=SERVER_ID,
        uri="ui://charts/chart-new.html",
        mime_type=MCP_APP_MIME,
        ui_meta=ui_meta,
    )


async def test_a_stored_view_gives_way_to_the_one_approved_now(monkeypatch):
    _enabled(monkeypatch)
    current = _view({"prefersBorder": True})
    first, second = _call("create_chart", uuid4()), _call("create_chart", uuid4())
    plain = _call("compute")
    repo = AsyncMock()
    repo.approved_for_tools.return_value = {(SERVER_ID, "create_chart"): current}

    await show_current_views([first, plain, second], repo)

    expected = {
        "view_id": str(current.view_id),
        "mcp_server_id": str(SERVER_ID),
        "ui": {"prefersBorder": True},
    }
    assert first.app_view == expected
    assert second.app_view == expected
    assert plain.app_view is None
    assert set(repo.approved_for_tools.await_args.args[0]) == {
        (SERVER_ID, "create_chart")
    }


async def test_a_call_whose_tool_shows_no_view_now_keeps_what_was_stored(monkeypatch):
    _enabled(monkeypatch)
    stored = uuid4()
    call = _call("create_chart", stored)
    repo = AsyncMock()
    repo.approved_for_tools.return_value = {}

    await show_current_views([call], repo)

    assert call.app_view is not None
    assert call.app_view["view_id"] == str(stored)


async def test_nothing_is_looked_up_without_views_or_with_apps_off(monkeypatch):
    repo = AsyncMock()
    _enabled(monkeypatch)
    await show_current_views([_call("compute")], repo)
    _enabled(monkeypatch, False)
    await show_current_views([_call("create_chart", uuid4())], repo)

    repo.approved_for_tools.assert_not_awaited()
