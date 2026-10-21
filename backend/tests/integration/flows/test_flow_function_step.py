"""Function steps call a capability provider's tool with bound arguments."""

import base64
from types import SimpleNamespace
from uuid import UUID

import pytest

from eneo.assistants.assistant_service import AssistantService
from eneo.database.tables.capabilities_table import SpaceCapabilities
from eneo.flows.definition import ComposeStep, FlowDefinition, FunctionStep
from eneo.flows.flow_models import FlowRunStatus
from eneo.flows.step_runners import STEP_FUNCTION_FAILED
from eneo.main.exceptions import BadRequestException
from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_factory import (
    MCPProxySessionFactory,
)
from tests.integration.flows.conftest import topic_field

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class FakeProxy:
    def __init__(self, result):
        self.result = result
        self.calls = []
        self.allowed = {}

    def allow_file_references(self, refs):
        self.allowed.update(refs)

    def set_document_template(self, reference):
        pass

    async def prepare_tools_for_context(self):
        pass

    def prefixed_tool_name(self, server_id, name):
        return f"srv__{name}"

    async def call_tools_parallel(self, calls):
        self.calls.extend(calls)
        return [self.result]

    async def close(self):
        pass


@pytest.fixture
def providers(monkeypatch):
    """One provider per purpose, each with one tool and its input schema."""
    holder = SimpleNamespace(proxy=None, purposes=[], result=None)
    tools = {
        "image_generation": SimpleNamespace(
            name="generate_image",
            description="Make a picture",
            input_schema={
                "type": "object",
                "required": ["prompt"],
                "properties": {
                    "prompt": {"type": "string"},
                    "size": {"type": "string"},
                },
            },
        ),
        "web_search": SimpleNamespace(
            name="search",
            description="Search the web",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}},
            },
        ),
    }

    async def _capability_server(self, *, assistant_id, purpose):
        holder.purposes.append(purpose)
        tool = tools.get(purpose)
        if tool is None:
            return None
        return SimpleNamespace(
            id=UUID(int=1 if purpose == "image_generation" else 2),
            name=f"{purpose} provider",
            purpose=purpose,
            tools=[tool],
        )

    def _create(self, servers, identity_headers=None, **_kwargs):
        holder.proxy = FakeProxy(holder.result)
        return holder.proxy

    monkeypatch.setattr(AssistantService, "capability_server", _capability_server)
    monkeypatch.setattr(MCPProxySessionFactory, "create", _create)
    return holder


async def _space(container, member_space, completion_model_factory, name, *purposes):
    session = container.session()
    model = await completion_model_factory(session, f"{name}-model")
    space = await member_space(session, f"{name} Space", [model.id])
    for purpose in purposes:
        session.add(SpaceCapabilities(purpose=purpose, space_id=space.id))
    await session.flush()
    await container.flow_authoring_assistant_service().get_or_create(space.id)
    return space


def _image_flow() -> FlowDefinition:
    return FlowDefinition(
        form_fields=[topic_field()],
        steps=[
            FunctionStep(
                key="picture",
                name="Bild",
                purpose="image_generation",
                tool="generate_image",
                arguments={
                    "prompt": "A poster about {{form.topic}}",
                    "size": "1024x1024",
                },
            ),
            ComposeStep(
                key="caption",
                name="Text",
                template="Bild: {{steps.picture}} ({{steps.picture.json.seed}})",
            ),
        ],
    )


async def test_function_step_calls_the_tool_and_keeps_its_image(
    db_container,
    member_space,
    completion_model_factory,
    publish_flow,
    provider,
    providers,
):
    providers.result = {
        "content": [
            {"type": "text", "text": '{"seed": 42}'},
            {
                "type": "image",
                "data": base64.b64encode(PNG).decode(),
                "mime_type": "image/png",
            },
        ]
    }
    async with db_container() as container:
        space = await _space(
            container,
            member_space,
            completion_model_factory,
            "image",
            "image_generation",
        )
        flow = await publish_flow(container, space, _image_flow())
        run_service = container.flow_run_service()
        run = await run_service.create_run(
            flow.id, values={"topic": "harbours"}, files={}
        )
        await run_service.execute_run(run.id)

        finished = await run_service.get_run(run.id, flow_id=flow.id)
        assert finished.status == FlowRunStatus.COMPLETED, finished.error
        assert providers.proxy.calls == [
            (
                "srv__generate_image",
                {"prompt": "A poster about harbours", "size": "1024x1024"},
            )
        ]
        picture = finished.steps[0]
        assert picture.input_payload_json["tool"] == "generate_image"
        assert picture.output_payload_json["value"] == {"seed": 42}
        assert [f.name for f in picture.result_files] == ["picture-1.png"]
        assert (
            finished.steps[1].output_payload_json["text"] == 'Bild: {"seed": 42} (42)'
        )
        assert [f.name for f in finished.result_files] == ["picture-1.png"]


async def test_function_steps_need_the_function_enabled_and_a_known_tool(
    db_container,
    member_space,
    completion_model_factory,
    publish_flow,
    provider,
    providers,
):
    async with db_container() as container:
        space = await _space(container, member_space, completion_model_factory, "nofn")
        with pytest.raises(
            BadRequestException, match="image_generation function is not enabled"
        ):
            await publish_flow(container, space, _image_flow())

        enabled = await _space(
            container, member_space, completion_model_factory, "wrongtool", "web_search"
        )
        definition = FlowDefinition(
            form_fields=[topic_field()],
            steps=[
                FunctionStep(
                    key="s",
                    name="S",
                    purpose="web_search",
                    tool="browse",
                    arguments={"query": "{{form.topic}}"},
                )
            ],
        )
        with pytest.raises(
            BadRequestException, match="tool the provider no longer offers"
        ):
            await publish_flow(container, enabled, definition)


async def test_arguments_the_tool_rejects_fail_before_the_call(
    db_container,
    member_space,
    completion_model_factory,
    publish_flow,
    provider,
    providers,
):
    providers.result = {"content": [{"type": "text", "text": "never"}]}
    async with db_container() as container:
        space = await _space(
            container, member_space, completion_model_factory, "schema", "web_search"
        )
        definition = FlowDefinition(
            form_fields=[topic_field()],
            steps=[
                FunctionStep(
                    key="s",
                    name="S",
                    purpose="web_search",
                    tool="search",
                    arguments={"q": "{{form.topic}}"},
                )
            ],
        )
        flow = await publish_flow(container, space, definition)
        run_service = container.flow_run_service()
        run = await run_service.create_run(flow.id, values={"topic": "x"}, files={})
        await run_service.execute_run(run.id)
        finished = await run_service.get_run(run.id, flow_id=flow.id)
        assert finished.status == FlowRunStatus.FAILED
        assert finished.error.code == STEP_FUNCTION_FAILED
        assert "query" in finished.error.message
        assert providers.proxy is None


async def test_the_panel_lists_the_functions_a_step_can_call(
    client,
    bearer,
    flows_enabled,
    db_container,
    member_space,
    completion_model_factory,
    providers,
):
    """GET /flows/functions/ says per purpose whether the space enables it and
    which tools its provider offers, as list_functions tells the chat."""
    async with db_container() as container:
        space = await _space(
            container,
            member_space,
            completion_model_factory,
            "Functions Space",
            "image_generation",
            "charts",
        )
        space_id = space.id

    response = await client.get(
        "/api/v1/flows/functions/", params={"space_id": str(space_id)}, headers=bearer
    )
    assert response.status_code == 200, response.text
    by_purpose = {item["purpose"]: item for item in response.json()}
    assert set(by_purpose) == {
        "web_search",
        "image_generation",
        "file_analysis",
        "file_creation",
        "charts",
        "compute",
    }
    image = by_purpose["image_generation"]
    assert image["enabled_in_space"] and image["available"]
    assert image["provider"] == "image_generation provider"
    assert [tool["name"] for tool in image["tools"]] == ["generate_image"]
    assert image["tools"][0]["input_schema"]["required"] == ["prompt"]
    # Enabled in the space but no provider serves it.
    charts = by_purpose["charts"]
    assert charts["enabled_in_space"] and not charts["available"]
    assert charts["tools"] == []
    # Not enabled: the provider is never asked.
    assert not by_purpose["web_search"]["enabled_in_space"]
    assert "web_search" not in providers.purposes
