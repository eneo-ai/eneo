"""What the server mapper reads from a row it did not fully load (#1200).

Both #1200 bugs came from reading an unloaded relationship as empty: tools
read as none approved, and a missing classification was written back as
NULL on the next update.
"""

from uuid import uuid4

import pytest

from eneo.database.tables.mcp_server_table import MCPServers, MCPServerTools
from eneo.mcp_servers.domain.entities.mcp_server import MCPServerToolsNotLoaded
from eneo.mcp_servers.infrastructure.mappers.mcp_server_mapper import MCPServerMapper
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)


def _row(**columns) -> MCPServers:
    return MCPServers(
        **{
            "id": uuid4(),
            "tenant_id": uuid4(),
            "name": "Provider",
            "http_url": "http://provider.example/mcp",
            "http_auth_type": "none",
            "purpose": "web_search",
            **columns,
        }
    )


def _approved_tool() -> MCPServerTools:
    return MCPServerTools(
        id=uuid4(),
        name="search",
        description="Search the web",
        input_schema={"type": "object"},
        is_enabled_by_default=True,
        removed_from_remote=False,
    )


def _classification() -> SecurityClassification:
    return SecurityClassification(
        id=uuid4(), tenant_id=uuid4(), name="Secret", security_level=2
    )


class TestTools:
    @pytest.mark.parametrize("read", ["tools", "usable_tools", "readiness_reason"])
    def test_tools_that_were_not_loaded_are_refused(self, read):
        # The proxy and governance policies read ``tools`` directly; as an
        # empty list it would offer nothing and disable nothing.
        server = MCPServerMapper.to_entity(_row())

        assert server.tools_loaded is False
        with pytest.raises(MCPServerToolsNotLoaded):
            getattr(server, read)

    def test_readiness_refuses_unloaded_tools_even_when_the_model_blocks(self):
        server = MCPServerMapper.to_entity(_row(http_auth_type="internal"))

        with pytest.raises(MCPServerToolsNotLoaded):
            _ = server.readiness_reason

    def test_loaded_empty_tools_have_no_approved_tools(self):
        server = MCPServerMapper.to_entity(_row(tools=[]))

        assert server.tools_loaded is True
        assert server.readiness_reason == "no_approved_tools"

    def test_loaded_approved_tool_is_ready(self):
        server = MCPServerMapper.to_entity(_row(tools=[_approved_tool()]))

        assert server.readiness_reason is None

    def test_tools_assigned_after_the_read_count_as_loaded(self):
        # Assistant and space projections read servers without their tools
        # and assign the projected ones afterwards.
        server = MCPServerMapper.to_entity(_row())

        server.tools = []

        assert server.readiness_reason == "no_approved_tools"


class TestSecurityClassification:
    def test_an_unloaded_classification_is_written_back_unchanged(self):
        classification_id = uuid4()

        server = MCPServerMapper.to_entity(
            _row(security_classification_id=classification_id)
        )

        assert server.security_classification is None
        assert (
            MCPServerMapper.to_db_dict(server)["security_classification_id"]
            == classification_id
        )

    def test_assigning_a_classification_writes_its_id(self):
        server = MCPServerMapper.to_entity(_row(security_classification_id=uuid4()))
        classification = _classification()

        server.security_classification = classification

        assert (
            MCPServerMapper.to_db_dict(server)["security_classification_id"]
            == classification.id
        )

    def test_clearing_the_classification_clears_its_id(self):
        server = MCPServerMapper.to_entity(_row(security_classification_id=uuid4()))

        server.security_classification = None

        assert MCPServerMapper.to_db_dict(server)["security_classification_id"] is None
