"""A create plan whose step reads an MCP tool of the space is applied and
published through the API: a tool step the Builder compiles is one publish
accepts and pins. The server and its tools are neutral seeds."""

from __future__ import annotations

from uuid import UUID

import pytest
import sqlalchemy as sa

from eneo.database.tables.mcp_server_table import MCPServers
from eneo.flows.ai_builder.ai_builder_create_compile_context import (
    CreateCompileContext,
)
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    compile_create_intent_to_spec,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_tool_catalog import tool_ref
from eneo.flows.flow_authoring_spec import InputType, OutputType
from tests.integration.flows.ai_builder.test_ai_builder_space_tool_catalog import (
    _ADDRESS,
    _seed_space_tools,
)
from tests.integration.flows.test_ai_builder_session_api_regressions import (
    _create_proposed_ai_builder_plan,
    _create_space_with_planner_model,
    bearer_token,  # noqa: F401  (registers the fixture)
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_a_compiled_tool_step_is_applied_and_published_with_its_pin(
    client,
    bearer_token,  # noqa: F811
    completion_model_factory,
    db_container,
) -> None:
    # Kills: a tool configuration publish refuses (ids, arguments, input
    # type), and a run-form field the argument reads lost on apply.
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name="AI Builder tool step publish",
    )
    lookup_id = await _seed_space_tools(db_container, UUID(space_id))
    async with db_container() as container:
        options = await container.flow_service().list_space_tool_options(
            space_id=UUID(space_id)
        )
    catalog = build_ai_builder_resource_catalog(
        available_models=None, available_kbs=None, tool_options=options
    )
    server_id = next(
        option.mcp_server_id
        for option in catalog.tools.usable_by_ref.values()
        if option.tool_id == lookup_id
    )
    spec = compile_create_intent_to_spec(
        parse_create_flow_intent_arguments(
            {
                "flow_name": "Ärende",
                "plan_rationale": "Slå upp ärendet och sammanfatta det.",
                "steps": [
                    {
                        "name": "Slå upp",
                        "instructions": "Ta ut ärendets status.",
                        "tool_use": {
                            "use_ref": "lookup",
                            "tool_ref": tool_ref(server_id, lookup_id),
                            "arguments": [
                                {
                                    "name": "case_id",
                                    "source": "run_input",
                                    "field_name": "case_id",
                                    "field_label": "Ärendenummer",
                                }
                            ],
                        },
                        "output_fields": [
                            {
                                "name": "status",
                                "field_type": "string",
                                "description": "Ärendets status.",
                            }
                        ],
                    },
                    {"name": "Sammanfatta", "instructions": "Sammanfatta ärendet."},
                ],
            }
        ),
        context=CreateCompileContext(
            runtime_input_type=InputType.TEXT, final_output_type=OutputType.TEXT
        ),
        tool_catalog=catalog.tools,
    )
    _, _, plan_id, _ = await _create_proposed_ai_builder_plan(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        space_id=space_id,
        spec=spec,
    )
    headers = {"Authorization": f"Bearer {bearer_token}"}

    approved = await client.post(
        f"/api/v1/flows/ai-builder/plans/{plan_id}/approve", headers=headers
    )
    applied = await client.post(
        f"/api/v1/flows/ai-builder/plans/{plan_id}/apply", json={}, headers=headers
    )
    assert approved.status_code == 200, approved.text
    assert applied.status_code == 200, applied.text
    flow_id = applied.json()["flow_id"]
    published = await client.post(f"/api/v1/flows/{flow_id}/publish/", headers=headers)
    flow = await client.get(f"/api/v1/flows/{flow_id}/", headers=headers)

    assert published.status_code == 200, published.text
    steps = flow.json()["steps"]
    assert [(step["input_source"], step["input_type"]) for step in steps] == [
        ("tool", "text"),
        ("previous_step", "text"),
    ]
    assert steps[0]["input_config"]["tool"]["arguments"] == {
        "case_id": "{{ flow_input.case_id }}"
    }
    assert steps[0]["input_config"]["tool"]["tool_id"] == str(lookup_id)
    assert [
        (field["name"], field["type"])
        for field in flow.json()["metadata_json"]["form_schema"]["fields"]
    ] == [("case_id", "text")]
    async with db_container() as container:
        await container.session().execute(
            sa.delete(MCPServers).where(MCPServers.http_url == _ADDRESS)
        )
