"""Unit tests for the loopback knowledge-MCP server.

Covers the ephemeral-server builder (its tool defs must mirror what the
endpoint actually exposes), token scoping, and the conversion of search hits
into MCP content blocks that the citation pipeline consumes.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from eneo.authentication.auth_service import AuthService
from eneo.internal_mcp.foundation import assistant_id_from_token
from eneo.internal_mcp.knowledge import (
    DESCRIPTION_SOURCES_CAP,
    KNOWLEDGE_SERVER_NAME,
    MAX_RESULTS_CEILING,
    _blob_in_scope,
    _clamp_max_results,
    _diversify,
    _document_page_content,
    _pick_embedding_model,
    _resolve_search_params,
    _search_result_content,
    build_knowledge_mcp_server,
    mcp,
    read_source,
    search_knowledge,
)
from eneo.main.exceptions import NotFoundException


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


def _patch_read_source_context(monkeypatch, *, blob=None, repo_error=None):
    assistant_id = uuid4()
    assistant = SimpleNamespace(
        collections=[SimpleNamespace(id=blob.group_id)]
        if blob is not None and blob.group_id is not None
        else [],
        websites=[],
        integration_knowledge_list=[],
    )

    @asynccontextmanager
    async def fake_context(_ctx):
        async def get_assistant(_assistant_id):
            return assistant, []

        async def get_blob(_blob_id):
            if repo_error is not None:
                raise repo_error
            if blob is None:
                raise NotFoundException()
            return blob

        container = SimpleNamespace(
            assistant_service=lambda: SimpleNamespace(get_assistant=get_assistant),
            info_blob_repo=lambda: SimpleNamespace(get=get_blob),
        )
        yield container, SimpleNamespace(), assistant_id

    monkeypatch.setattr(
        "eneo.internal_mcp.knowledge.internal_tool_context", fake_context
    )


class TestBuildKnowledgeMcpServer:
    @pytest.mark.asyncio
    async def test_tool_entities_mirror_live_tool_list(self):
        server = await build_knowledge_mcp_server(
            token="tok", tenant_id=uuid4(), source_labels=["Collection 'Waste FAQ'"]
        )

        live_tools = await mcp.list_tools()
        assert [t.name for t in server.tools] == [t.name for t in live_tools]
        assert [t.input_schema for t in server.tools] == [
            t.inputSchema for t in live_tools
        ]
        # Source enrichment may only append: the live docstring always leads.
        for entity, live in zip(server.tools, live_tools):
            assert entity.description.startswith(live.description)
        assert {"search_knowledge", "list_knowledge_sources", "read_source"} <= {
            t.name for t in server.tools
        }

    @pytest.mark.asyncio
    async def test_search_description_names_the_sources(self):
        server = await build_knowledge_mcp_server(
            token="tok", tenant_id=uuid4(), source_labels=["Collection 'testsamling'"]
        )

        by_name = {t.name: t for t in server.tools}
        live_by_name = {t.name: t for t in await mcp.list_tools()}

        assert "Collection 'testsamling'" in by_name["search_knowledge"].description
        assert by_name["read_source"].description == (
            live_by_name["read_source"].description
        )
        assert by_name["list_knowledge_sources"].description == (
            live_by_name["list_knowledge_sources"].description
        )

    @pytest.mark.asyncio
    async def test_source_listing_is_capped(self):
        labels = [f"Collection 'Samling {i}'" for i in range(15)]
        server = await build_knowledge_mcp_server(
            token="tok", tenant_id=uuid4(), source_labels=labels
        )

        description = next(
            t.description for t in server.tools if t.name == "search_knowledge"
        )
        assert all(label in description for label in labels[:DESCRIPTION_SOURCES_CAP])
        assert labels[DESCRIPTION_SOURCES_CAP] not in description
        assert "and 5 more" in description

    @pytest.mark.asyncio
    async def test_no_labels_leaves_descriptions_untouched(self):
        server = await build_knowledge_mcp_server(token="tok", tenant_id=uuid4())

        live_tools = await mcp.list_tools()
        assert [t.description for t in server.tools] == [
            t.description for t in live_tools
        ]

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
        token = AuthService().create_scoped_mcp_token(
            self._user(), assistant_id=assistant_id
        )

        assert assistant_id_from_token(token) == assistant_id

    def test_unscoped_access_token_is_rejected(self):
        token = AuthService().create_access_token_for_user(self._user())

        with pytest.raises(ValueError):
            assistant_id_from_token(token)


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
            f"Title: Waste sorting guide\n"
            f"document_id: {chunk.info_blob_id}\n\n"
            f"Garden waste is collected every other week."
        )
        assert resource.meta == {
            "title": "Waste sorting guide",
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
        assert "Retry once with different wording" in content[0].text
        # The fallback to other tools is proactive, not permission-gated.
        assert "without asking the user first" in content[0].text

    def test_max_results_is_clamped_to_ceiling(self):
        assert _clamp_max_results(500) == MAX_RESULTS_CEILING
        assert _clamp_max_results(0) == 1
        assert _clamp_max_results(8) == 8


class TestResolveSearchParams:
    def test_specific_defaults(self):
        assert _resolve_search_params("specific", None) == (10, 2, 6)

    def test_overview_defaults(self):
        assert _resolve_search_params("overview", None) == (60, None, 15)

    def test_explicit_max_results_overrides_cap(self):
        fetch, autocut, cap = _resolve_search_params("specific", 12)
        assert cap == 12
        assert fetch >= cap

        _, _, overview_cap = _resolve_search_params("overview", 3)
        assert overview_cap == 3

    def test_max_results_is_ceiling_clamped(self):
        assert _resolve_search_params("specific", 500)[2] == MAX_RESULTS_CEILING
        assert _resolve_search_params("overview", 500)[2] == MAX_RESULTS_CEILING


class TestDiversify:
    def test_coverage_before_depth(self):
        doc_a, doc_b, doc_c = uuid4(), uuid4(), uuid4()
        chunks = [
            _chunk(info_blob_id=doc_a, chunk_no=1),
            _chunk(info_blob_id=doc_a, chunk_no=2),
            _chunk(info_blob_id=doc_a, chunk_no=3),
            _chunk(info_blob_id=doc_b, chunk_no=1),
            _chunk(info_blob_id=doc_c, chunk_no=1),
        ]

        selected = _diversify(chunks, per_doc=2, cap=10)

        assert [(c.info_blob_id, c.chunk_no) for c in selected] == [
            (doc_a, 1),
            (doc_b, 1),
            (doc_c, 1),
            (doc_a, 2),
        ]

    def test_respects_total_cap(self):
        chunks = [_chunk(info_blob_id=uuid4()) for _ in range(5)]
        assert len(_diversify(chunks, per_doc=2, cap=2)) == 2


class TestBlobInScope:
    def _assistant(self, collections=(), websites=(), integrations=()):
        return SimpleNamespace(
            collections=[SimpleNamespace(id=i) for i in collections],
            websites=[SimpleNamespace(id=i) for i in websites],
            integration_knowledge_list=[SimpleNamespace(id=i) for i in integrations],
        )

    def _blob(self, group_id=None, website_id=None, integration_knowledge_id=None):
        return SimpleNamespace(
            group_id=group_id,
            website_id=website_id,
            integration_knowledge_id=integration_knowledge_id,
        )

    def test_matches_by_each_source_type(self):
        cid, wid, iid = uuid4(), uuid4(), uuid4()
        assistant = self._assistant(
            collections=[cid], websites=[wid], integrations=[iid]
        )

        assert _blob_in_scope(self._blob(group_id=cid), assistant)
        assert _blob_in_scope(self._blob(website_id=wid), assistant)
        assert _blob_in_scope(self._blob(integration_knowledge_id=iid), assistant)

    def test_rejects_foreign_and_unattached_blobs(self):
        assistant = self._assistant(collections=[uuid4()])

        assert not _blob_in_scope(self._blob(group_id=uuid4()), assistant)
        assert not _blob_in_scope(self._blob(), assistant)

    def test_group_blob_not_matched_by_website_assistant(self):
        assistant = self._assistant(websites=[uuid4()])
        assert not _blob_in_scope(self._blob(group_id=uuid4()), assistant)


class TestDocumentPageContent:
    def _blob(self, text):
        return SimpleNamespace(id=uuid4(), title="Waste policy", text=text)

    def test_short_document_fits_without_notice(self):
        blob = self._blob("Short policy text.")
        content = _document_page_content(blob, offset=0, page_cap=100)

        assert len(content) == 1
        resource = content[0].resource
        assert resource.text == (
            f"Title: Waste policy\ndocument_id: {blob.id}\n\nShort policy text."
        )
        assert str(resource.uri) == f"eneo://info-blob/{blob.id}"
        assert resource.meta["title"] == "Waste policy"

    def test_long_document_truncates_with_resume_offset(self):
        blob = self._blob("a" * 250)
        content = _document_page_content(blob, offset=0, page_cap=100)

        assert len(content) == 2
        assert len(content[0].resource.text.split("\n\n", 1)[1]) == 100
        assert "character 100 of 250" in content[1].text
        assert "offset=100" in content[1].text

    def test_offset_pages_through_the_document(self):
        blob = self._blob("a" * 150 + "b" * 50)
        content = _document_page_content(blob, offset=150, page_cap=100)

        assert len(content) == 1
        assert content[0].resource.text.endswith("b" * 50)

    def test_offset_past_end_reports_document_length(self):
        blob = self._blob("abc")
        content = _document_page_content(blob, offset=10, page_cap=100)

        assert len(content) == 1
        assert content[0].type == "text"
        assert "past the end" in content[0].text


class TestReadSourceErrors:
    @pytest.mark.asyncio
    async def test_missing_document_returns_safe_not_found(self, monkeypatch):
        _patch_read_source_context(monkeypatch, blob=None)

        content = await read_source(str(uuid4()), ctx=None)

        assert content[0].text == (
            "No document with that id in this assistant's knowledge sources."
        )

    @pytest.mark.asyncio
    async def test_unexpected_repository_error_propagates(self, monkeypatch):
        _patch_read_source_context(
            monkeypatch, repo_error=RuntimeError("database unavailable")
        )

        with pytest.raises(RuntimeError, match="database unavailable"):
            await read_source(str(uuid4()), ctx=None)


class TestToolSteering:
    def test_search_knowledge_documents_both_modes(self):
        doc = search_knowledge.__doc__ or ""
        assert '"specific"' in doc
        assert '"overview"' in doc

    def test_read_source_documents_the_document_id_handle(self):
        assert "document_id" in (read_source.__doc__ or "")


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
