"""Unit tests for knowledge-mode gating in ``Assistant.ask``.

The invariants: inject mode (no loopback server provided) retrieves on every
turn; tool mode (loopback server provided) skips retrieval, exposes the server
alongside external MCP servers, and injects only a token-cheap source catalog.
External MCP servers are always passed regardless of knowledge.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.assistant import Assistant
from eneo.services.service import DatastoreResult


def _assistant(**overrides):
    completion_model = MagicMock(vision=True, max_input_tokens=100_000)
    defaults = dict(
        id=uuid4(),
        user=MagicMock(),
        name="Test assistant",
        space_id=uuid4(),
        prompt=None,
        completion_model=completion_model,
        completion_model_kwargs=ModelKwargs(),
        logging_enabled=False,
        collections=[MagicMock(name="collection")],
        websites=[],
        attachments=[],
        mcp_servers=[],
        published=False,
    )
    defaults.update(overrides)
    return Assistant(**defaults)


def _references_service():
    service = MagicMock()
    service.get_references = AsyncMock(
        return_value=DatastoreResult(chunks=[], no_duplicate_chunks=[], info_blobs=[])
    )
    return service


def _completion_service():
    service = MagicMock()
    service.get_response = AsyncMock(return_value=MagicMock())
    return service


class TestKnowledgeModeGating:
    @pytest.mark.asyncio
    async def test_inject_mode_retrieves_and_gets_no_knowledge_server(self):
        assistant = _assistant()
        references_service = _references_service()
        completion_service = _completion_service()

        await assistant.ask(
            question="Hello",
            completion_service=completion_service,
            references_service=references_service,
        )

        references_service.get_references.assert_awaited_once()
        kwargs = completion_service.get_response.await_args.kwargs
        assert kwargs["mcp_servers"] == []
        assert kwargs["knowledge_catalog"] == ""

    @pytest.mark.asyncio
    async def test_tool_mode_skips_retrieval_and_attaches_server(self):
        external_server = MagicMock()
        knowledge_server = MagicMock()
        assistant = _assistant(mcp_servers=[external_server])
        references_service = _references_service()
        completion_service = _completion_service()

        await assistant.ask(
            question="Hello",
            completion_service=completion_service,
            references_service=references_service,
            knowledge_mcp_server=knowledge_server,
        )

        references_service.get_references.assert_not_awaited()
        kwargs = completion_service.get_response.await_args.kwargs
        # Knowledge server first: its tools lead the tool array and win any
        # prefixed-name collision (first-registered-wins in the proxy).
        assert kwargs["mcp_servers"] == [knowledge_server, external_server]
        assert kwargs["info_blob_chunks"] == []
        assert kwargs["knowledge_catalog"] != ""

    @pytest.mark.asyncio
    async def test_knowledge_and_external_mcp_coexist_in_inject_mode(self):
        external_server = MagicMock()
        assistant = _assistant(mcp_servers=[external_server])
        references_service = _references_service()
        completion_service = _completion_service()

        await assistant.ask(
            question="Hello",
            completion_service=completion_service,
            references_service=references_service,
        )

        references_service.get_references.assert_awaited_once()
        kwargs = completion_service.get_response.await_args.kwargs
        assert kwargs["mcp_servers"] == [external_server]

    @pytest.mark.asyncio
    async def test_no_knowledge_means_no_retrieval_either_way(self):
        assistant = _assistant(collections=[])
        references_service = _references_service()
        completion_service = _completion_service()

        await assistant.ask(
            question="Hello",
            completion_service=completion_service,
            references_service=references_service,
        )

        references_service.get_references.assert_not_awaited()


class TestKnowledgeCatalog:
    def test_lists_each_source_by_name(self):
        collection = MagicMock()
        collection.name = "Waste FAQ"
        website = MagicMock(url="https://kommun.se")
        website.name = "Municipal site"
        integration = MagicMock()
        integration.name = "Sharepoint HR"
        assistant = _assistant(
            collections=[collection],
            websites=[website],
            integration_knowledge_list=[integration],
        )

        catalog = assistant.build_knowledge_catalog()

        assert "Collection 'Waste FAQ'" in catalog
        assert "Website 'Municipal site'" in catalog
        assert "Integration 'Sharepoint HR'" in catalog

    def test_website_without_name_falls_back_to_url(self):
        website = MagicMock(url="https://kommun.se")
        website.name = None
        assistant = _assistant(collections=[], websites=[website])

        assert "Website 'https://kommun.se'" in assistant.build_knowledge_catalog()

    def test_empty_without_knowledge(self):
        assistant = _assistant(collections=[])
        assert assistant.build_knowledge_catalog() == ""

    def test_catalog_enforces_search_first_and_strict_grounding(self):
        catalog = _assistant().build_knowledge_catalog()

        assert "ALWAYS search with knowledge__search_knowledge" in catalog
        assert "could not be found in the knowledge sources" in catalog
        assert "never answer from general knowledge" in catalog

    def test_catalog_defers_to_other_tools_only_for_live_data_and_actions(self):
        catalog = _assistant().build_knowledge_catalog()

        assert "take precedence over every other tool" in catalog
        assert "clearly for live data" in catalog

    def test_catalog_states_knowledge_tools_win_ties(self):
        # When another server exposes a similarly named search tool, the
        # catalog must resolve the tie toward the built-in knowledge tools.
        catalog = _assistant().build_knowledge_catalog()

        assert "call knowledge__search_knowledge FIRST" in catalog

    def test_catalog_routes_meta_questions_to_the_builtin_listing_tool(self):
        # "What knowledge do you have?" must go to the built-in listing tool,
        # not a similarly purposed listing tool from another server.
        catalog = _assistant().build_knowledge_catalog()

        assert "answer with knowledge__list_knowledge_sources" in catalog
        assert "never with a listing tool from another server" in catalog

    def test_catalog_tool_names_match_proxy_prefixing(self):
        # The catalog hardcodes the prefixed tool names; they must match what
        # the proxy actually derives from the knowledge server's name.
        from eneo.internal_mcp.knowledge import KNOWLEDGE_SERVER_NAME
        from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session import (
            MCPProxySession,
        )

        prefix = MCPProxySession(mcp_servers=[])._sanitize_name(
            KNOWLEDGE_SERVER_NAME.lower()
        )
        catalog = _assistant().build_knowledge_catalog()

        assert f"{prefix}__search_knowledge" in catalog
        assert f"{prefix}__read_source" in catalog
        assert f"{prefix}__list_knowledge_sources" in catalog
