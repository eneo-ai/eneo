"""A flow with a tool step on real sessions: the service the container builds
reads the chain with the real facts reader, in the transaction it writes in."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.authentication.principal_types import PrincipalType
from eneo.database.tables.flow_tables import FlowRuns, FlowVersions
from eneo.database.tables.mcp_server_table import (
    MCPServers,
    MCPServerTools,
    SpacesMCPServers,
)
from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassifications,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.domain.canonical_json_hash import canonical_json_hash
from eneo.flows.domain.flow import FlowStep
from eneo.flows.runtime import tasks as flow_runtime_tasks
from eneo.main.exceptions import BadRequestException
from eneo.mcp_servers.domain.unattended_tool_refusal import UnattendedToolRefusal
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


def _tool_step(
    assistant_id: UUID, tool_config: dict[str, object], **changes: object
) -> FlowStep:
    return FlowStep.model_validate(
        {
            "assistant_id": assistant_id,
            "step_order": 1,
            "user_description": "Hämta ärendet",
            "input_source": "tool",
            "input_type": "json",
            "input_config": {"tool": tool_config},
            "output_mode": "pass_through",
            "output_type": "text",
            **changes,
        }
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
            # An address the flow destination policy refuses, so that a run
            # ends at the step before anything goes out.
            http_url="http://127.0.0.1:9/mcp",
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


async def _classify_the_server(db_container, tool_flow: ToolFlow, level: int) -> UUID:
    """Classifications on for the organization, and the tool's server
    activated in the flow's space at ``level``."""
    async with db_container() as container:
        session = container.session()
        tenant_id = container.user().tenant_id
        classification = SecurityClassifications(
            tenant_id=tenant_id, name=f"niva-{uuid4().hex[:6]}", security_level=level
        )
        session.add(classification)
        await session.flush()
        await session.execute(
            sa.update(MCPServers)
            .where(MCPServers.id == tool_flow.server_id)
            .values(security_classification_id=classification.id)
        )
        session.add(
            SpacesMCPServers(
                space_id=tool_flow.space_id, mcp_server_id=tool_flow.server_id
            )
        )
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(security_enabled=True)
        )
        return classification.id


async def test_every_path_counts_the_servers_level_and_keeps_using_its_session(
    db_container, admin_user, tool_flow: ToolFlow
) -> None:
    # Kills the mutants where a path that runs the classification rule (save,
    # the change of the step's assistant, the preview, publish, the run's
    # preflight) is given no facts reader or one that cannot read on its
    # session, and where the reader's fresh read of rows the session already
    # holds (the space, the server, their classification and tenant) breaks
    # what the path does next in that session.
    classification_id = await _classify_the_server(db_container, tool_flow, level=2)
    # A step that renders its input runs no model, so nothing but the server
    # sets its level.
    rendering = {"input_type": "text", "output_mode": "render_verbatim"}
    step = _tool_step(
        tool_flow.assistant_id, tool_flow.tool_config, output_type="pdf", **rendering
    )
    below_the_server = step.model_copy(update={"output_classification_override": 1})

    async with db_container() as container:
        service = container.flow_service()
        with pytest.raises(BadRequestException) as refused:
            await service.update_flow(
                flow_id=tool_flow.flow_id, steps=[below_the_server]
            )
        refused_context = refused.value.context or {}
        saved = await service.update_flow(flow_id=tool_flow.flow_id, steps=[step])
        await service.update_flow_assistant(
            flow_id=tool_flow.flow_id,
            assistant_id=tool_flow.assistant_id,
            update=AssistantUpdateCommand(prompt=PromptCreate(text="Rendera svaret.")),
        )
        (explained,) = await service.preview_step_security_classification(
            flow_id=tool_flow.flow_id
        )
        published = await service.publish_flow(flow_id=tool_flow.flow_id)
        # The session still serves the rows the reader read fresh.
        space = await container.space_service().get_space(tool_flow.space_id)
        server_level = await container.session().scalar(
            sa.select(SecurityClassifications.security_level).where(
                SecurityClassifications.id == classification_id
            )
        )
        run = (
            await container.flow_run_service().create_run(
                flow_id=tool_flow.flow_id,
                input_payload_json={"text": "A-17"},
                expected_flow_version=1,
                idempotency_key=f"tool-step-sessions-{uuid4()}",
            )
        ).run

    assert (refused_context["required_level"], refused_context["cause"]) == (
        2,
        "external_source",
    )
    assert saved.steps[0].output_mode == "render_verbatim"
    assert (explained.external_source_level, explained.effective_output_level) == (2, 2)
    assert explained.violation is None
    assert published.published_version == 1
    assert (space.id, server_level) == (tool_flow.space_id, 2)

    try:
        result = await flow_runtime_tasks._execute_flow_run_async(
            run_id=run.id,
            flow_id=tool_flow.flow_id,
            tenant_id=admin_user.tenant_id,
            run_revision=run.revision,
            principal_type=PrincipalType.USER,
            principal_user_id=admin_user.id,
            principal_service_id=None,
            task_id=None,
            retry_count=0,
            invocation_deadline=None,
        )
    finally:
        await flow_runtime_tasks.execution_heartbeats().stop()

    # The preflight counted the server's level and let the run on; the step
    # then stopped at the server's address, which this test made a refused one.
    assert result["status"] == "failed"
    async with db_container() as container:
        ended = await container.flow_run_repo().get(
            run_id=run.id, tenant_id=admin_user.tenant_id, flow_id=tool_flow.flow_id
        )
        evidence_level = await container.session().scalar(
            sa.select(FlowRuns.evidence_classification_level).where(
                FlowRuns.id == run.id
            )
        )
    assert ended.error is not None
    assert ended.error.code.value == "typed_io_tool_destination_blocked"
    assert evidence_level == 2


async def test_the_tool_list_reads_the_stored_chain_for_the_flows_space(
    db_container, tool_flow: ToolFlow
) -> None:
    # Kills the mutants where the container's service has no reader for the
    # list, the list is read for another space, or the stored review state
    # does not reach the refusal.
    async with db_container() as container:
        session = container.session()
        session.add(
            SpacesMCPServers(
                space_id=tool_flow.space_id, mcp_server_id=tool_flow.server_id
            )
        )
        session.add(
            MCPServerTools(
                mcp_server_id=tool_flow.server_id,
                name="open_case",
                requires_approval=True,
            )
        )
        await session.flush()
        options = await container.flow_service().list_tool_options(
            flow_id=tool_flow.flow_id
        )

    assert [(o.tool_name, o.refusal, o.input_schema) for o in options] == [
        ("lookup_case", None, _SCHEMA),
        ("open_case", UnattendedToolRefusal.TOOL_WAITING_FOR_REVIEW, None),
    ]
    assert {o.mcp_server_id for o in options} == {tool_flow.server_id}
