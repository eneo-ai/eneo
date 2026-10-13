"""Tool-level MCP `_meta` follows the same approval lifecycle as the rest of
the tool contract: discovery stages it as pending, approval activates it, and
any live divergence from the approved value counts as definition drift."""

from uuid import uuid4

from eneo.mcp_servers.domain.entities.mcp_server import MCPServerTool

UI_META = {"io.modelcontextprotocol/ui": {"resourceUri": "ui://weather/dashboard"}}


def _approved_tool(meta: dict | None) -> MCPServerTool:
    return MCPServerTool(
        mcp_server_id=uuid4(),
        name="get_weather",
        description="Current weather",
        input_schema={"type": "object"},
        meta=meta,
    )


class TestDefinitionDrift:
    def test_meta_only_change_is_drift(self):
        tool = _approved_tool(meta=None)

        assert tool.has_definition_drift(
            description="Current weather",
            input_schema={"type": "object"},
            meta=UI_META,
        )

    def test_identical_meta_is_not_drift(self):
        tool = _approved_tool(meta=UI_META)

        equal_copy = {
            "io.modelcontextprotocol/ui": {"resourceUri": "ui://weather/dashboard"}
        }
        assert not tool.has_definition_drift(
            description="Current weather",
            input_schema={"type": "object"},
            meta=equal_copy,
        )

    def test_meta_removal_is_drift(self):
        tool = _approved_tool(meta=UI_META)

        assert tool.has_definition_drift(
            description="Current weather",
            input_schema={"type": "object"},
            meta=None,
        )


class TestPendingDiscovery:
    def test_meta_is_staged_not_active(self):
        tool = MCPServerTool.pending_discovery(
            mcp_server_id=uuid4(),
            name="get_weather",
            title="Weather",
            description="Current weather",
            input_schema={"type": "object"},
            meta=UI_META,
        )

        assert tool.meta is None
        assert tool.pending_meta == UI_META
        assert tool.requires_approval is True


VIEW_META = {"ui": {"resourceUri": "ui://weather/dashboard"}}
OTHER_VIEW_META = {"ui": {"resourceUri": "ui://weather/forecast"}}


def _tool_with_approved_view() -> MCPServerTool:
    tool = _approved_tool(meta=VIEW_META)
    tool.ui_resource_sha256 = "a" * 64
    return tool


class TestApprovedView:
    def test_changed_view_content_is_drift(self):
        tool = _tool_with_approved_view()

        assert tool.has_definition_drift(
            description="Current weather",
            input_schema={"type": "object"},
            meta=VIEW_META,
            ui_resource_sha256="b" * 64,
        )

    def test_observation_without_the_view_is_not_drift(self):
        tool = _tool_with_approved_view()

        assert not tool.has_definition_drift(
            description="Current weather",
            input_schema={"type": "object"},
            meta=VIEW_META,
        )

    def test_approval_without_a_view_keeps_the_view_of_the_same_resource(self):
        tool = _tool_with_approved_view()
        tool.pending_description = "Weather right now"
        tool.pending_meta = VIEW_META
        tool.requires_approval = True

        tool.approve_pending()

        assert tool.description == "Weather right now"
        assert tool.ui_resource_sha256 == "a" * 64

    def test_approval_never_carries_a_view_over_to_another_resource(self):
        tool = _tool_with_approved_view()
        tool.pending_meta = OTHER_VIEW_META
        tool.requires_approval = True

        tool.approve_pending()

        assert tool.meta == OTHER_VIEW_META
        assert tool.ui_resource_sha256 is None


def test_approving_metadata_removal_clears_the_old_view():
    tool = _tool_with_approved_view()
    tool.pending_meta = None
    tool.requires_approval = True
    tool.approve_pending()
    assert tool.meta is None
    assert tool.ui_resource_sha256 is None
    assert not tool.requires_approval
