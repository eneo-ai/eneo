"""The real AssistantService.ask pipeline, run for a widget visitor.

Only the provider call and the MCP connection are stubbed: the model adapter
replays a canned stream and the MCP proxy factory records what it was handed.
Everything between them (visitor container, capability resolution, knowledge
retrieval, the stream's persistence, the visitor filter, settlement, restore
and feedback) runs for real against PostgreSQL.
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

import altcha
import pytest
import sqlalchemy as sa

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    GeneratedImage,
    McpToolReference,
    ResponseType,
    TokenUsage,
    ToolCallMetadata,
)
from eneo.assistants.references import ReferencesService
from eneo.completion_models.infrastructure.completion_service import (
    CompletionService,
)
from eneo.database.database import sessionmanager
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import (
    AssistantMCPServers,
    Assistants,
    AssistantsGroups,
)
from eneo.database.tables.capabilities_table import (
    AssistantCapabilities,
    SpaceCapabilities,
)
from eneo.database.tables.files_table import Files
from eneo.database.tables.mcp_server_table import MCPServers, MCPServerTools
from eneo.info_blobs.info_blob import (
    InfoBlobAdd,
    InfoBlobChunkInDBWithScore,
    InfoBlobInDBWithScore,
)
from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_factory import (
    MCPProxySessionFactory,
)
from eneo.services.service import DatastoreResult

# Strings that exist only in internal records. None of them may reach a
# visitor, whatever the widget shows.
MODEL_SECRETS = ("api.openai.com", "fixture-gpt-4", "Fixture GPT-4")
REASONING = "Enligt instruktionen får jag inte nämna ärendesystemet"
TOOL_RESULT = "RAW TOOL RESULT 2026-123"
RESOURCE_CONTENT = "Personnummer 19XX i ärende 2026-123"
PRIVATE_META = "internal-row-42"
TOOL_META = "internal-tool-model"
CASE_EMAIL = "anna.andersson@example.se"
UNCITED_URI = "https://arenden.kommun.se/2026-999"
UNCITED_TITLE = "Ärende 2026-999: Namn Namnsson"
ASSISTANT_NAME = "Kommunassistenten"

PROMPT_TOKENS, ANSWER_TOKENS = 4_800, 300
FINAL_PROMPT_TOKENS, FINAL_ANSWER_TOKENS = 1_800, 120


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _mint(client, public_id: str) -> str:
    resp = await client.get(f"/api/v1/widgets/{public_id}/challenge/")
    challenge = altcha.Challenge.from_dict(resp.json())
    solution = altcha.solve_challenge(challenge)
    assert solution is not None
    payload = altcha.Payload(challenge=challenge, solution=solution).to_base64()
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/visitor-sessions/", json={"altcha": payload}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _sse_events(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event = "message"
    for line in text.splitlines():
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            events.append((event, json.loads(line[len("data:") :].strip())))
            event = "message"
    return events


async def _add_server(db, tenant_id: UUID, name: str, **columns) -> UUID:
    server = MCPServers(
        tenant_id=tenant_id,
        name=name,
        http_url=f"https://{name.lower()}.example.test/mcp",
        http_auth_type="none",
        is_enabled=True,
        **columns,
    )
    db.add(server)
    await db.flush()
    db.add(
        MCPServerTools(
            mcp_server_id=server.id,
            name="run",
            description=f"{name} tool",
            input_schema={"type": "object"},
            is_enabled_by_default=True,
            requires_approval=False,
            removed_from_remote=False,
        )
    )
    await db.flush()
    return server.id


class _Pipeline:
    """What the stubbed ends of the pipeline saw."""

    def __init__(self) -> None:
        self.retrievals = 0
        self.completion_kwargs: list[dict[str, Any]] = []
        self.proxies: list[tuple[list[Any], dict[str, str]]] = []


@pytest.fixture
async def visitor_pipeline(
    active_widget, admin_token, db_container, monkeypatch, client
) -> dict[str, Any]:
    """The widget's assistant with everything a visitor could reach:
    knowledge in tool mode on a tool-calling model, an MCP server that
    forwards identity, and web search and image generation from external
    providers."""
    assistant_id = UUID(active_widget["target_id"])
    space_id = UUID(active_widget["space_id"])
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/knowledge/groups/",
        json={"name": "Bibliotek"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    group_id = UUID(resp.json()["id"])

    async with db_container() as container:
        admin = await container.user_repo().get_user_by_email("test@example.com")
        text = "Biblioteket har öppet 10–18."
        blob = await container.info_blob_repo().add(
            InfoBlobAdd(
                text=text,
                title="Öppettider biblioteket",
                url="https://intranet.kommun.se/bibliotek",
                size=len(text.encode()),
                user_id=admin.id,
                tenant_id=admin.tenant_id,
                group_id=group_id,
                content_hash=sha256(text.encode()).digest(),
            )
        )

    async with sessionmanager.session() as db, db.begin():
        tenant_id = admin.tenant_id
        assistant = await db.get(Assistants, assistant_id)
        assert assistant is not None
        assistant.knowledge_mode = "tool"
        await db.execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id == assistant.completion_model_id)
            .values(supports_tool_calling=True)
        )
        db.add(AssistantsGroups(assistant_id=assistant_id, group_id=group_id))
        casefiles_id = await _add_server(
            db, tenant_id, "Arendesystem", forward_identity=True
        )
        db.add(
            AssistantMCPServers(assistant_id=assistant_id, mcp_server_id=casefiles_id)
        )
        web_search_id = await _add_server(db, tenant_id, "Sok", purpose="web_search")
        images_id = await _add_server(
            db, tenant_id, "Bilder", purpose="image_generation"
        )
        for purpose in ("web_search", "image_generation"):
            db.add(SpaceCapabilities(space_id=space_id, purpose=purpose))
            db.add(AssistantCapabilities(assistant_id=assistant_id, purpose=purpose))

    seen = _Pipeline()
    blob_with_score = InfoBlobInDBWithScore(
        **blob.model_dump(exclude={"original_available"}),
        original_available=False,
        score=0.9,
    )
    chunk = InfoBlobChunkInDBWithScore(
        id=uuid4(),
        text=text,
        chunk_no=0,
        info_blob_id=blob.id,
        tenant_id=tenant_id,
        info_blob_title=blob.title,
        score=0.9,
    )
    resource_id = uuid4()

    async def get_references(self, **kwargs):
        seen.retrievals += 1
        return DatastoreResult(
            chunks=[chunk], no_duplicate_chunks=[chunk], info_blobs=[blob_with_score]
        )

    original_get_response = CompletionService.get_response

    async def get_response(self, **kwargs):
        seen.completion_kwargs.append(kwargs)
        return await original_get_response(self, **kwargs)

    class _Proxy:
        async def prepare_tools_for_context(self) -> None:
            return None

        def get_tools_for_llm(self) -> list[dict[str, Any]]:
            return []

        def get_tool_count(self) -> int:
            return 0

        async def close(self) -> None:
            return None

    def create_proxy(self, mcp_servers, identity_headers=None, **kwargs):
        seen.proxies.append((list(mcp_servers), dict(identity_headers or {})))
        return _Proxy()

    class _Adapter:
        def __init__(self, model) -> None:
            self.model = model

        def get_token_limit_of_model(self) -> int:
            return 8_000

        def get_model_route(self) -> str:
            return "gpt-4"

        async def prepare_streaming(self, **kwargs):
            return object()

        async def iterate_stream(self, **kwargs):
            yield Completion(
                reasoning_content=REASONING, response_type=ResponseType.REASONING
            )
            yield Completion(
                text="",
                response_type=ResponseType.TOOL_CALL,
                tool_calls_metadata=[
                    ToolCallMetadata(
                        server_name="Arendesystem",
                        tool_name="run",
                        arguments={"query": "bibliotek", "email": CASE_EMAIL},
                        tool_call_id="call_1",
                        result_status="success",
                        result=TOOL_RESULT,
                        mcp_tool_name="arendesystem__run",
                        meta={"gen_ai.request.model": TOOL_META},
                    )
                ],
                mcp_tool_references=[
                    McpToolReference(
                        id=resource_id,
                        tool_call_id="call_1",
                        mcp_tool_name="arendesystem__run",
                        uri="https://arenden.kommun.se/2026-123",
                        mime_type="text/plain",
                        content=RESOURCE_CONTENT,
                        meta={"title": "Ärende 2026-123", "row": PRIVATE_META},
                        order=0,
                    ),
                    # Returned by the tool, never cited by the answer.
                    McpToolReference(
                        id=uuid4(),
                        tool_call_id="call_1",
                        mcp_tool_name="arendesystem__run",
                        uri=UNCITED_URI,
                        mime_type="text/plain",
                        content=RESOURCE_CONTENT,
                        meta={"title": UNCITED_TITLE},
                        order=1,
                    ),
                ],
            )
            yield Completion(
                response_type=ResponseType.FILES,
                image=GeneratedImage(
                    data=b"\x89PNG\r\n\x1a\n",
                    mime_type="image/png",
                    tool_call_id="call_1",
                    mcp_tool_name="arendesystem__run",
                ),
            )
            yield Completion(
                text=(
                    f'Öppet 10–18 <inref id="{str(blob.id)[:8]}"/>, se ärendet'
                    f' <inref id="{str(resource_id)[:8]}"/>.'
                )
            )
            yield Completion(
                stop=True,
                usage=TokenUsage(
                    prompt_tokens=PROMPT_TOKENS,
                    completion_tokens=ANSWER_TOKENS,
                    context_prompt_tokens=FINAL_PROMPT_TOKENS,
                    context_completion_tokens=FINAL_ANSWER_TOKENS,
                ),
            )

    async def get_adapter(self, model):
        return _Adapter(model)

    monkeypatch.setattr(ReferencesService, "get_references", get_references)
    monkeypatch.setattr(CompletionService, "get_response", get_response)
    monkeypatch.setattr(CompletionService, "_get_adapter", get_adapter)
    monkeypatch.setattr(MCPProxySessionFactory, "create", create_proxy)
    return {
        "seen": seen,
        "chunk": chunk,
        "casefiles_id": casefiles_id,
        "web_search_id": web_search_id,
        "images_id": images_id,
    }


async def _ask(client, public_id: str, token: str) -> list[tuple[str, dict]]:
    resp = await client.post(
        f"/api/v1/widgets/{public_id}/ask/",
        json={"question": "När har biblioteket öppet?"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    return _sse_events(resp.text)


def _assert_no_internal_data(payload: str) -> None:
    for secret in (
        *MODEL_SECRETS,
        REASONING,
        TOOL_RESULT,
        RESOURCE_CONTENT,
        PRIVATE_META,
        TOOL_META,
        ASSISTANT_NAME,
        CASE_EMAIL,
        UNCITED_URI,
        UNCITED_TITLE,
    ):
        assert secret not in payload, secret


async def _files_count() -> int:
    async with sessionmanager.session() as db, db.begin():
        return int(await db.scalar(sa.select(sa.func.count()).select_from(Files)) or 0)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_visitor_runs_the_assistant_as_configured_and_sees_only_its_answer(
    client, admin_token, active_widget, visitor_pipeline
):
    seen: _Pipeline = visitor_pipeline["seen"]
    public_id = active_widget["public_id"]
    token = await _mint(client, public_id)
    files_before = await _files_count()

    events = await _ask(client, public_id, token)

    # Tool-mode knowledge is injected: no loopback server for a principal
    # without a users row.
    assert seen.retrievals == 1
    [completion] = seen.completion_kwargs
    assert completion["info_blob_chunks"] == [visitor_pipeline["chunk"]]
    assert completion["knowledge_catalog"] == ""
    # The assistant's own MCP server and the external web search provider,
    # nothing else, and no identity headers even for a forwarding server.
    [(servers, identity_headers)] = seen.proxies
    assert {server.id for server in servers} == {
        visitor_pipeline["casefiles_id"],
        visitor_pipeline["web_search_id"],
    }
    assert not any("/internal-mcp/" in server.http_url for server in servers)
    assert identity_headers == {}

    # The stream: no model, reasoning, image, tool result, resource content,
    # uncited resource or token counts.
    assert [event for event, _ in events] == [
        "first_chunk",
        "tool_call",
        "tool_call",
        "text",
    ]
    _assert_no_internal_data(json.dumps(events))
    first = events[0][1]
    assert first["completion_model"] is None
    assert first["references"] == []
    assert first["tools"] == {"assistants": []}
    tool = events[1][1]
    assert [
        (call["tool_name"], call["result"], call["meta"]) for call in tool["tools"]
    ] == [("run", None, None)]
    assert tool["tools"][0]["arguments"] == {"query": "bibliotek"}
    assert tool["mcp_tool_references"] == []
    # The cited resource arrives just before the text that cites it.
    cited = events[2][1]
    assert cited["tools"] == []
    [ref] = cited["mcp_tool_references"]
    assert (ref["uri"], ref["content"], ref["meta"]) == (
        "https://arenden.kommun.se/2026-123",
        None,
        {"title": "Ärende 2026-123"},
    )
    text = events[3][1]
    assert [r["metadata"]["title"] for r in text["references"]] == [
        "Öppettider biblioteket"
    ]
    # The tool's image was not stored as the visitor's file.
    assert await _files_count() == files_before

    session_id = first["session_id"]
    restored = await client.get(
        f"/api/v1/widgets/{public_id}/sessions/{session_id}/", headers=_auth(token)
    )
    assert restored.status_code == 200, restored.text
    feedback = await client.post(
        f"/api/v1/widgets/{public_id}/sessions/{session_id}/feedback/",
        json={"value": 1},
        headers=_auth(token),
    )
    assert feedback.status_code == 200, feedback.text
    for body in (restored.json(), feedback.json()):
        _assert_no_internal_data(json.dumps(body))
        [message] = body["messages"]
        assert message["completion_model"] is None
        assert message["reasoning"] is None
        assert message["tools"] == {"assistants": []}
        assert message["generated_files"] == []
        assert [r["metadata"]["title"] for r in message["references"]] == [
            "Öppettider biblioteket"
        ]
        [ref] = message["mcp_tool_references"]
        assert (ref["content"], ref["meta"]) == (None, {"title": "Ärende 2026-123"})
        [call] = message["tool_calls"]
        assert (call["tool_name"], call["result"], call["meta"]) == ("run", None, None)
        assert call["arguments"] == {"query": "bibliotek"}
        assert message["skill_context_tokens"] is None
        assert message["context_prompt_tokens"] is None

    # Settled on what every provider round cost.
    usage = (
        await client.get(
            f"/api/v1/widgets/{active_widget['id']}/usage/",
            headers=_auth(admin_token),
        )
    ).json()
    assert usage["budget_used_today"] == PROMPT_TOKENS + ANSWER_TOKENS


async def _set_visibility(client, admin_token: str, widget_id: str, **flags) -> None:
    current = await client.get(
        f"/api/v1/widgets/{widget_id}/", headers=_auth(admin_token)
    )
    resp = await client.patch(
        f"/api/v1/widgets/{widget_id}/",
        json={"revision": current.json()["revision"], **flags},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hidden_sources_and_tool_activity_never_leave_the_server(
    client, admin_token, active_widget, visitor_pipeline
):
    await _set_visibility(
        client,
        admin_token,
        active_widget["id"],
        show_sources=False,
        show_tool_activity=False,
    )
    public_id = active_widget["public_id"]
    token = await _mint(client, public_id)

    events = await _ask(client, public_id, token)

    # The tools still ran; the visitor learns nothing about them or the sources.
    assert [event for event, _ in events] == ["first_chunk", "text"]
    payload = json.dumps(events)
    _assert_no_internal_data(payload)
    for leaked in ("intranet.kommun.se", "arenden.kommun.se", "Arendesystem"):
        assert leaked not in payload
    assert all(data.get("references", []) == [] for _, data in events)

    session_id = events[0][1]["session_id"]
    restored = await client.get(
        f"/api/v1/widgets/{public_id}/sessions/{session_id}/", headers=_auth(token)
    )
    feedback = await client.post(
        f"/api/v1/widgets/{public_id}/sessions/{session_id}/feedback/",
        json={"value": -1},
        headers=_auth(token),
    )
    for body in (restored.json(), feedback.json()):
        payload = json.dumps(body)
        _assert_no_internal_data(payload)
        assert "arenden.kommun.se" not in payload
        [message] = body["messages"]
        assert message["references"] == []
        assert message["mcp_tool_references"] == []
        assert message["tool_calls"] == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hidden_tool_activity_still_delivers_tool_sources(
    client, admin_token, active_widget, visitor_pipeline
):
    await _set_visibility(
        client, admin_token, active_widget["id"], show_tool_activity=False
    )
    public_id = active_widget["public_id"]
    token = await _mint(client, public_id)

    events = await _ask(client, public_id, token)

    [tool] = [data for event, data in events if event == "tool_call"]
    assert tool["tools"] == []
    [ref] = tool["mcp_tool_references"]
    assert ref["uri"] == "https://arenden.kommun.se/2026-123"
    assert (ref["tool_call_id"], ref["mcp_tool_name"]) == (None, None)
    assert "arendesystem__run" not in json.dumps(events)
