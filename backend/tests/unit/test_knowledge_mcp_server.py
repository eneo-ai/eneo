"""Unit tests for the loopback knowledge-MCP server.

Covers the ephemeral-server builder (its tool defs must mirror what the
endpoint actually exposes), token scoping, and the conversion of search hits
into MCP content blocks that the citation pipeline consumes.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from eneo.authentication.auth_service import AuthService
from eneo.knowledge_mcp.server import (
    KNOWLEDGE_SERVER_NAME,
    MAX_RESULTS_CEILING,
    _assistant_id_from_token,
    _clamp_max_results,
    _pick_embedding_model,
    _search_result_content,
    build_knowledge_mcp_server,
    mcp,
)


def _chunk(**overrides):
    defaults = dict(
        info_blob_id=uuid4(),
        info_blob_title="Waste sorting guide",
        chunk_no=3,
        text="Garden waste is collected every other week.",
        score=0.87,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestBuildKnowledgeMcpServer:
    @pytest.mark.asyncio
    async def test_tool_entities_mirror_live_tool_list(self):
        server = await build_knowledge_mcp_server(token="tok", tenant_id=uuid4())

        live_tools = await mcp.list_tools()
        assert [t.name for t in server.tools] == [t.name for t in live_tools]
        assert [t.input_schema for t in server.tools] == [
            t.inputSchema for t in live_tools
        ]
        assert {"search_knowledge", "list_knowledge_sources"} <= {
            t.name for t in server.tools
        }

    @pytest.mark.asyncio
    async def test_server_is_bearer_authenticated_loopback(self):
        server = await build_knowledge_mcp_server(token="tok", tenant_id=uuid4())

        assert server.name == KNOWLEDGE_SERVER_NAME
        assert server.http_auth_type == "bearer"
        assert server.http_auth_config_schema == {"token": "tok"}
        assert server.http_url.endswith("/internal-mcp/knowledge/mcp")
        assert server.is_enabled


@pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")
class TestTokenScoping:
    """The dev-env JWT secret is short; the warning is about the env, not the code."""

    def _user(self):
        return SimpleNamespace(email="anna@kommun.se", username="anna")

    def test_scoped_token_round_trips_assistant_id(self):
        assistant_id = uuid4()
        token = AuthService(api_key_repo=MagicMock()).create_scoped_mcp_token(
            self._user(), assistant_id=assistant_id
        )

        assert _assistant_id_from_token(token) == assistant_id

    def test_unscoped_access_token_is_rejected(self):
        token = AuthService(api_key_repo=MagicMock()).create_access_token_for_user(
            self._user()
        )

        with pytest.raises(ValueError):
            _assistant_id_from_token(token)


class TestSearchResultContent:
    def test_chunks_become_embedded_resources_with_meta(self):
        chunk = _chunk()
        content = _search_result_content("garden waste", [chunk])

        assert content[0].type == "text"
        assert "garden waste" in content[0].text

        resource = content[1].resource
        assert str(resource.uri) == (
            f"eneo://info-blob/{chunk.info_blob_id}#chunk-{chunk.chunk_no}"
        )
        assert resource.text == (
            "Title: Waste sorting guide\n\nGarden waste is collected every other week."
        )
        assert resource.meta == {
            "info_blob_id": str(chunk.info_blob_id),
            "score": 0.87,
        }

    def test_untitled_chunk_gets_placeholder_title(self):
        content = _search_result_content("q", [_chunk(info_blob_title=None)])
        assert content[1].resource.text.startswith("Title: Untitled source")

    def test_no_hits_yields_plain_text_answer(self):
        content = _search_result_content("obscure query", [])
        assert len(content) == 1
        assert content[0].type == "text"
        assert "No results" in content[0].text

    def test_max_results_is_clamped_to_ceiling(self):
        assert _clamp_max_results(500) == MAX_RESULTS_CEILING
        assert _clamp_max_results(0) == 1
        assert _clamp_max_results(8) == 8


class TestPickEmbeddingModel:
    def test_first_non_empty_source_wins(self):
        collection_model = MagicMock()
        assistant = SimpleNamespace(
            collections=[SimpleNamespace(embedding_model=collection_model)],
            websites=[SimpleNamespace(embedding_model=MagicMock())],
            integration_knowledge_list=[],
        )
        assert _pick_embedding_model(assistant) is collection_model

    def test_none_when_no_knowledge(self):
        assistant = SimpleNamespace(
            collections=[], websites=[], integration_knowledge_list=[]
        )
        assert _pick_embedding_model(assistant) is None
