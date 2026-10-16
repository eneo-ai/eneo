"""Create and edit sessions in one space give the planner the same catalogue
of the space's MCP tools, read through the editor's grant chain, with no
server address, credential or unapproved text in what the provider gets."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.database.tables.mcp_server_table import (
    MCPServers,
    MCPServerTools,
    SpacesMCPServers,
    SpacesMCPServerTools,
)
from eneo.flows.ai_builder.ai_builder_tool_catalog import tool_ref
from eneo.prompts.api.prompt_models import PromptCreate
from tests.integration.flows.ai_builder.test_ai_builder_unsupported_saved_steps_api import (
    _drive_to_answer,
)
from tests.integration.flows.test_ai_builder_session_api_regressions import (
    _classifier_reading_nothing,
    _create_ai_builder_session,
    _create_space_with_planner_model,
    _make_flow_step,
    _make_llm_response,
    _route,
    bearer_token,  # noqa: F401  (registers the fixture)
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_ADDRESS = "https://mcp-private-host.example/internal-path"
_CREDENTIAL = "sk-live-tool-server-credential"
_PENDING = "Text an administrator has not approved"
_HEADING = "MCP tools in this space"
_REFUSED_HEADING = "Not usable in this space"


async def _seed_space_tools(db_container, space_id: UUID) -> UUID:
    """Two usable tools and one the space switched off, on a server with an
    address, a credential and a pending definition."""
    async with db_container() as container:
        session = container.session()
        server = MCPServers(
            tenant_id=container.user().tenant_id,
            name=f"Cases {uuid4().hex[:6]}",
            http_url=_ADDRESS,
            http_auth_type="none",
            env_vars={"API_TOKEN": _CREDENTIAL},
            is_enabled=True,
        )
        session.add(server)
        await session.flush()
        lookup = MCPServerTools(
            mcp_server_id=server.id,
            name="lookup_case",
            description="Slår upp ett ärende.",
            input_schema={
                "type": "object",
                "properties": {"case_id": {"type": "string"}},
            },
            pending_description=_PENDING,
        )
        listing = MCPServerTools(
            mcp_server_id=server.id, name="list_cases", description="Listar ärenden."
        )
        closing = MCPServerTools(
            mcp_server_id=server.id, name="close_case", description="Stänger."
        )
        session.add_all([lookup, listing, closing])
        session.add(SpacesMCPServers(space_id=space_id, mcp_server_id=server.id))
        await session.flush()
        session.add(
            SpacesMCPServerTools(
                space_id=space_id, mcp_server_tool_id=closing.id, is_enabled=False
            )
        )
        await session.flush()
        return lookup.id


async def _saved_flow_id(db_container, space_id: UUID) -> str:
    async with db_container() as container:
        flow_service = container.flow_service()
        flow = await flow_service.create_flow(
            space_id=space_id, name="Ärendeflöde", description=None, steps=[]
        )
        assistant, _ = await flow_service.create_flow_assistant(
            flow_id=flow.id, name="steg1"
        )
        await flow_service.update_flow_assistant(
            flow_id=flow.id,
            assistant_id=assistant.id,
            update=AssistantUpdateCommand(prompt=PromptCreate(text="Sammanfatta.")),
        )
        await flow_service.update_flow(
            flow_id=flow.id,
            steps=[
                _make_flow_step(
                    assistant_id=assistant.id,
                    step_order=1,
                    user_description="Sammanfatta",
                )
            ],
        )
        return str(flow.id)


def _tool_blocks(provider: AsyncMock, since: int) -> list[str]:
    """The tool blocks of the system prompts sent since call ``since``."""
    blocks = []
    for call in provider.await_args_list[since:]:
        for message in call.kwargs.get("messages", []):
            content = str(message.get("content"))
            if message.get("role") == "system" and _HEADING in content:
                start = content.index(_HEADING)
                end = content.find("\n\n", start)
                blocks.append(content[start : end if end != -1 else None])
    return blocks


async def test_create_and_edit_sessions_give_the_planner_the_same_tool_catalogue(
    client,
    bearer_token,  # noqa: F811
    completion_model_factory,
    db_container,
) -> None:
    # Kills: the catalogue read for an edit session only (create has no
    # flow), read by another key than the session's space, dropped between
    # the router, the service and the planner request, the switched-off
    # tool offered, a catalogue kept from an earlier turn of the session;
    # pins that no address, credential or pending text of the server reaches
    # the provider.
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name=f"Tool catalogue {uuid4().hex[:6]}",
        planner_model_overrides={"max_input_tokens": 128_000},
        planner_model_is_only_space_model=True,
    )
    lookup_id = await _seed_space_tools(db_container, UUID(space_id))
    flow_id = await _saved_flow_id(db_container, UUID(space_id))
    provider = AsyncMock(return_value=_make_llm_response(content="unused"))

    blocks: dict[str, list[str]] = {}
    sessions: dict[str, str] = {}
    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
            new=provider,
        ),
        _classifier_reading_nothing(),
        patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(return_value=_route(kwargs={"api_key": "sk-test"})),
        ),
    ):
        for kind, target in (("create", None), ("edit", flow_id)):
            calls_before = provider.await_count
            sessions[kind] = await _create_ai_builder_session(
                client=client,
                bearer_token=bearer_token,
                space_id=space_id,
                target_kind=kind,
                flow_id=target,
            )
            await _drive_to_answer(
                client=client,
                token=bearer_token,
                session_id=sessions[kind],
                edit_context=None,
            )
            blocks[kind] = _tool_blocks(provider, calls_before)
        # A tool switched off in the space between two turns of one session
        # is gone from the next turn's catalogue.
        async with db_container() as container:
            container.session().add(
                SpacesMCPServerTools(
                    space_id=UUID(space_id),
                    mcp_server_tool_id=lookup_id,
                    is_enabled=False,
                )
            )
        calls_before = provider.await_count
        await _drive_to_answer(
            client=client,
            token=bearer_token,
            session_id=sessions["create"],
            edit_context=None,
        )
        blocks["after_switch_off"] = _tool_blocks(provider, calls_before)

    disclosed = json.dumps(
        [call.kwargs.get("messages") for call in provider.await_args_list],
        ensure_ascii=False,
    )
    for secret in (_ADDRESS, "mcp-private-host", _CREDENTIAL, _PENDING):
        assert secret not in disclosed, secret
    create_block = blocks["create"][0]
    assert create_block == blocks["edit"][0]
    assert create_block.index('"list_cases"') < create_block.index('"lookup_case"')
    assert '"case_id"' in create_block and "Slår upp ett ärende." in create_block
    # A refused tool is named after the usable ones, with its refusal only.
    usable, refused = create_block.split(_REFUSED_HEADING)
    assert "close_case" not in usable and "Stänger." not in create_block
    assert '"close_case"' in refused and "reason=tool_switched_off_in_space" in refused
    later_usable = blocks["after_switch_off"][0].split(_REFUSED_HEADING)[0]
    assert '"list_cases"' in later_usable and "lookup_case" not in later_usable
    async with db_container() as container:
        await container.session().execute(
            sa.delete(MCPServers).where(MCPServers.http_url == _ADDRESS)
        )


async def test_a_session_lists_its_spaces_tools_by_ref_without_any_address(
    client,
    bearer_token,  # noqa: F811
    completion_model_factory,
    db_container,
) -> None:
    # Kills: a list read by another key than the session's space, a refused
    # tool left out (guidance needs it), a ref other than the planner's, an
    # address or credential in the answer.
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name=f"Tool list {uuid4().hex[:6]}",
    )
    lookup_id = await _seed_space_tools(db_container, UUID(space_id))
    session_id = await _create_ai_builder_session(
        client=client, bearer_token=bearer_token, space_id=space_id
    )

    response = await client.get(
        f"/api/v1/flows/ai-builder/sessions/{session_id}/tools",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["over_bound"] is False
    tools = body["tools"]
    assert [(tool["tool_name"], tool["refusal"]) for tool in tools] == [
        ("close_case", "tool_switched_off_in_space"),
        ("list_cases", None),
        ("lookup_case", None),
    ]
    assert {key for tool in tools for key in tool} == {
        "ref",
        "mcp_server_id",
        "mcp_server_name",
        "mcp_server_security_level",
        "tool_id",
        "tool_name",
        "tool_description",
        "refusal",
    }
    lookup = next(tool for tool in tools if tool["tool_id"] == str(lookup_id))
    assert lookup["ref"] == tool_ref(UUID(lookup["mcp_server_id"]), lookup_id)
    assert lookup["tool_description"] == "Slår upp ett ärende."
    for secret in (_ADDRESS, "mcp-private-host", _CREDENTIAL, _PENDING):
        assert secret not in response.text, secret
    async with db_container() as container:
        await container.session().execute(
            sa.delete(MCPServers).where(MCPServers.http_url == _ADDRESS)
        )
