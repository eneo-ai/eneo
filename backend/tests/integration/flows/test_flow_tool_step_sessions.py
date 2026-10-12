"""A flow with a tool step on real sessions: the service the container builds
reads the chain with the real facts reader, in the transaction it writes in."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.database.tables.flow_tables import FlowVersions
from eneo.database.tables.mcp_server_table import (
    MCPServers,
    MCPServerTools,
    SpacesMCPServers,
)
from eneo.flows.domain.canonical_json_hash import canonical_json_hash
from eneo.flows.domain.flow import FlowStep
from eneo.main.exceptions import BadRequestException
from eneo.prompts.api.prompt_models import PromptCreate
from tests.integration.flows.test_flow_assistant_update_siblings import (
    _admin_token_and_space,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"case_id": {"type": "string"}},
}


@dataclass(frozen=True)
class ToolFlow:
    """A draft flow in a shared space whose one step reads an approved tool
    of a general MCP server. The space has not activated the server yet."""

    flow_id: UUID
    assistant_id: UUID
    space_id: UUID
    server_id: UUID
    tool_id: UUID

    @property
    def tool_config(self) -> dict[str, object]:
        return {
            "mcp_server_id": str(self.server_id),
            "tool_id": str(self.tool_id),
            "arguments": {"case_id": "A-17"},
        }


def _tool_step(assistant_id: UUID, tool_config: dict[str, object]) -> FlowStep:
    return FlowStep(
        assistant_id=assistant_id,
        step_order=1,
        user_description="Hämta ärendet",
        input_source="tool",
        input_type="json",
        input_config={"tool": tool_config},
        output_mode="pass_through",
        output_type="text",
    )


@pytest.fixture
async def tool_flow(
    client, db_container, admin_user, patch_auth_service_jwt
) -> AsyncIterator[ToolFlow]:
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    async with db_container() as container:
        session = container.session()
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"tool-step-{uuid4()}",
            http_url="https://cases.example.org/mcp",
            http_auth_type="none",
            is_enabled=True,
        )
        session.add(server)
        await session.flush()
        tool = MCPServerTools(
            mcp_server_id=server.id, name="lookup_case", input_schema=_SCHEMA
        )
        session.add(tool)
        await session.flush()
        server_id, tool_id = server.id, tool.id
    async with db_container() as container:
        service = container.flow_service()
        flow = await service.create_flow(
            space_id=space_id, name="Verktygssteg", description=None, steps=[]
        )
        assistant, _ = await service.create_flow_assistant(
            flow_id=flow.id, name="steg1"
        )
        await service.update_flow_assistant(
            flow_id=flow.id,
            assistant_id=assistant.id,
            update=AssistantUpdateCommand(prompt=PromptCreate(text="Läs svaret.")),
        )
        created = ToolFlow(flow.id, assistant.id, space_id, server_id, tool_id)
        await service.update_flow(
            flow_id=flow.id, steps=[_tool_step(assistant.id, created.tool_config)]
        )
    yield created
    async with db_container() as container:
        await container.session().execute(
            sa.delete(MCPServers).where(MCPServers.id == server_id)
        )


async def _stored_versions(db_container, flow_id: UUID) -> list[dict[str, object]]:
    async with db_container() as container:
        return list(
            await container.session().scalars(
                sa.select(FlowVersions.definition_json).where(
                    FlowVersions.flow_id == flow_id
                )
            )
        )


async def test_publish_asks_the_stored_chain_and_stores_the_pin(
    db_container, tool_flow: ToolFlow
) -> None:
    # Kills the mutants where the container builds the flow service without
    # the facts reader, or with a reader on another session than the one the
    # publication is written in: the space's activation below is not committed
    # when the publish reads it. Also kills a publish that stores no pin, and
    # one that leaves the pin in the editable step.
    async with db_container() as container:
        with pytest.raises(BadRequestException) as refused:
            await container.flow_service().publish_flow(flow_id=tool_flow.flow_id)
        refusal_code, refusal_context = refused.value.code, refused.value.context
    assert refusal_code == "typed_io_tool_not_allowed"
    assert refusal_context == {
        "step_order": 1,
        "refusal": "server_not_in_space",
        "mcp_server_id": str(tool_flow.server_id),
        "tool_id": str(tool_flow.tool_id),
    }
    assert await _stored_versions(db_container, tool_flow.flow_id) == []

    async with db_container() as container:
        container.session().add(
            SpacesMCPServers(
                space_id=tool_flow.space_id, mcp_server_id=tool_flow.server_id
            )
        )
        await container.session().flush()
        published = await container.flow_service().publish_flow(
            flow_id=tool_flow.flow_id
        )

    assert published.published_version == 1
    assert published.steps[0].input_config == {"tool": tool_flow.tool_config}
    (definition,) = await _stored_versions(db_container, tool_flow.flow_id)
    assert definition["steps"][0]["input_config"]["tool"] == {
        **tool_flow.tool_config,
        "tool_name": "lookup_case",
        "input_schema_sha256": canonical_json_hash(_SCHEMA),
    }
