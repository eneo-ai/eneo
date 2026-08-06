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
from eneo.info_blobs.info_blob_repo import InfoBlobListing
from eneo.internal_mcp.foundation import assistant_id_from_token
from eneo.internal_mcp.knowledge import (
    DESCRIPTION_SOURCES_CAP,
    KNOWLEDGE_SERVER_NAME,
    MAX_RESULTS_CEILING,
    NOT_FOUND_MESSAGE,
    OVERVIEW_MAX_CHUNKS_PER_DOC,
    OVERVIEW_SAMPLE_DOCUMENTS,
    SCOPE_NOT_FOUND_MESSAGE,
    _blob_in_scope,
    _clamp_max_results,
    _diversify,
    _document_page_content,
    _excerpts_per_document,
    _fit_titles,
    _matching_sources,
    _overview_content,
    _pick_embedding_model,
    _resolve_search_params,
    _sample_targets,
    _search_result_content,
    _source_scopes,
    build_knowledge_mcp_server,
    describe_source,
    list_knowledge_sources,
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
        assert {
            "search_knowledge",
            "list_knowledge_sources",
            "read_source",
            "describe_source",
        } <= {t.name for t in server.tools}

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


def _assistant_with_sources(collections=(), websites=(), integrations=()):
    return SimpleNamespace(
        collections=[
            SimpleNamespace(id=i, name=n, embedding_model=MagicMock())
            for i, n in collections
        ],
        websites=[
            SimpleNamespace(id=i, name=n, url=u, embedding_model=MagicMock())
            for i, n, u in websites
        ],
        integration_knowledge_list=[
            SimpleNamespace(id=i, name=n, embedding_model=MagicMock())
            for i, n in integrations
        ],
    )


class TestMatchingSources:
    def test_each_source_type_resolves_to_a_single_source_scope(self):
        cid, wid, iid = uuid4(), uuid4(), uuid4()
        assistant = _assistant_with_sources(
            collections=[(cid, "Waste FAQ")],
            websites=[(wid, "Kommun", "https://kommun.se")],
            integrations=[(iid, "Confluence")],
        )

        collection_scope = _matching_sources(assistant, str(cid))[0]
        assert [c.id for c in collection_scope.collections] == [cid]
        assert collection_scope.websites == []
        assert collection_scope.integration_knowledge_list == []

        website_scope = _matching_sources(assistant, str(wid))[0]
        assert [w.id for w in website_scope.websites] == [wid]
        assert website_scope.collections == []

        integration_scope = _matching_sources(assistant, str(iid))[0]
        assert [k.id for k in integration_scope.integration_knowledge_list] == [iid]
        assert integration_scope.collections == []

    def test_foreign_id_matches_nothing(self):
        assistant = _assistant_with_sources(collections=[(uuid4(), "Waste FAQ")])
        assert _matching_sources(assistant, str(uuid4())) == []

    def test_name_match_is_case_insensitive(self):
        cid = uuid4()
        assistant = _assistant_with_sources(collections=[(cid, "Waste FAQ")])

        assert _matching_sources(assistant, "waste faq")[0].source_id == cid
        assert _matching_sources(assistant, "  Waste FAQ ")[0].source_id == cid

    def test_duplicate_names_are_reported_as_several_matches(self):
        assistant = _assistant_with_sources(
            collections=[(uuid4(), "Riktlinjer"), (uuid4(), "Riktlinjer")]
        )
        assert len(_matching_sources(assistant, "Riktlinjer")) == 2

    def test_unrecognised_text_matches_nothing(self):
        assistant = _assistant_with_sources(collections=[(uuid4(), "Waste FAQ")])
        assert _matching_sources(assistant, "not a source") == []

    def test_website_falls_back_to_url_as_its_name(self):
        wid = uuid4()
        assistant = _assistant_with_sources(websites=[(wid, None, "https://kommun.se")])

        scope = _source_scopes(assistant)[0]
        assert scope.name == "https://kommun.se"
        assert _matching_sources(assistant, "https://kommun.se")[0].source_id == wid


def _patch_search_context(monkeypatch, assistant, *, blob=None, chunks=()):
    """Patch the tool context with a datastore that records its scope kwargs."""
    calls: list[dict] = []

    async def semantic_search(query, **kwargs):
        calls.append({"query": query, **kwargs})
        return list(chunks)

    @asynccontextmanager
    async def fake_context(_ctx):
        async def get_assistant(_assistant_id):
            return assistant, []

        async def get_blob(_blob_id):
            if blob is None or blob.id != _blob_id:
                raise NotFoundException()
            return blob

        container = SimpleNamespace(
            assistant_service=lambda: SimpleNamespace(get_assistant=get_assistant),
            info_blob_repo=lambda: SimpleNamespace(get=get_blob),
            datastore=lambda: SimpleNamespace(semantic_search=semantic_search),
        )
        yield container, SimpleNamespace(), uuid4()

    monkeypatch.setattr(
        "eneo.internal_mcp.knowledge.internal_tool_context", fake_context
    )
    return calls


class TestSearchScoping:
    async def test_unscoped_search_spans_every_attached_source(self, monkeypatch):
        cid, wid = uuid4(), uuid4()
        assistant = _assistant_with_sources(
            collections=[(cid, "Waste FAQ")],
            websites=[(wid, "Kommun", "https://kommun.se")],
        )
        calls = _patch_search_context(monkeypatch, assistant)

        await search_knowledge("garden waste", ctx=None)

        assert [c.id for c in calls[0]["collections"]] == [cid]
        assert [w.id for w in calls[0]["websites"]] == [wid]
        assert calls[0]["info_blob_ids"] == []

    async def test_source_scope_excludes_the_other_sources(self, monkeypatch):
        cid, wid = uuid4(), uuid4()
        assistant = _assistant_with_sources(
            collections=[(cid, "Waste FAQ")],
            websites=[(wid, "Kommun", "https://kommun.se")],
        )
        calls = _patch_search_context(monkeypatch, assistant)

        await search_knowledge("garden waste", ctx=None, within=str(cid))

        assert [c.id for c in calls[0]["collections"]] == [cid]
        assert calls[0]["websites"] == []
        assert calls[0]["integration_knowledge_list"] == []
        assert calls[0]["info_blob_ids"] == []

    async def test_document_scope_passes_only_the_document(self, monkeypatch):
        cid, blob_id = uuid4(), uuid4()
        assistant = _assistant_with_sources(collections=[(cid, "Waste FAQ")])
        blob = SimpleNamespace(
            id=blob_id,
            title="Waste policy",
            group_id=cid,
            website_id=None,
            integration_knowledge_id=None,
        )
        calls = _patch_search_context(monkeypatch, assistant, blob=blob)

        await search_knowledge("garden waste", ctx=None, within=str(blob_id))

        assert calls[0]["info_blob_ids"] == [blob_id]
        assert calls[0]["collections"] == []
        assert calls[0]["websites"] == []
        assert calls[0]["integration_knowledge_list"] == []

    async def test_document_scope_returns_results_in_reading_order(self, monkeypatch):
        cid, blob_id = uuid4(), uuid4()
        assistant = _assistant_with_sources(collections=[(cid, "Waste FAQ")])
        blob = SimpleNamespace(
            id=blob_id,
            title="Waste policy",
            group_id=cid,
            website_id=None,
            integration_knowledge_id=None,
        )
        chunks = [
            _chunk(info_blob_id=blob_id, chunk_no=7, score=0.9),
            _chunk(info_blob_id=blob_id, chunk_no=2, score=0.8),
        ]
        _patch_search_context(monkeypatch, assistant, blob=blob, chunks=chunks)

        content = await search_knowledge("waste", ctx=None, within=str(blob_id))

        assert [c.resource.meta["score"] for c in content[1:]] == [0.8, 0.9]

    async def test_out_of_scope_within_is_indistinguishable_from_missing(
        self, monkeypatch
    ):
        assistant = _assistant_with_sources(collections=[(uuid4(), "Waste FAQ")])
        _patch_search_context(monkeypatch, assistant)

        foreign_source = await search_knowledge("q", ctx=None, within=str(uuid4()))
        nonsense = await search_knowledge("q", ctx=None, within="not-an-id")

        assert foreign_source[0].text == SCOPE_NOT_FOUND_MESSAGE
        assert nonsense[0].text == SCOPE_NOT_FOUND_MESSAGE

    async def test_ambiguous_source_name_asks_for_the_id(self, monkeypatch):
        assistant = _assistant_with_sources(
            collections=[(uuid4(), "Riktlinjer"), (uuid4(), "Riktlinjer")]
        )
        _patch_search_context(monkeypatch, assistant)

        content = await search_knowledge("q", ctx=None, within="Riktlinjer")

        assert "source_id" in content[0].text
        assert "Riktlinjer" in content[0].text


class TestFitTitles:
    def _listings(self, count):
        return [
            InfoBlobListing(id=uuid4(), title=f"Dokument {i}", url=None)
            for i in range(count)
        ]

    def test_all_titles_kept_when_they_fit(self):
        listings = self._listings(5)
        kept, lines = _fit_titles(listings, budget=10_000)

        assert len(kept) == 5
        assert lines[0].startswith("- Dokument 0  document_id: ")

    def test_budget_cuts_the_tail(self):
        listings = self._listings(50)
        kept, lines = _fit_titles(listings, budget=300)

        assert 0 < len(kept) < 50
        assert sum(len(line) + 1 for line in lines) <= 300

    def test_first_title_is_kept_even_when_it_alone_exceeds_the_budget(self):
        kept, lines = _fit_titles(self._listings(3), budget=1)

        assert len(kept) == 1
        assert len(lines) == 1

    def test_untitled_listing_falls_back_to_url_then_placeholder(self):
        blob_id = uuid4()
        _, lines = _fit_titles(
            [
                InfoBlobListing(id=blob_id, title=None, url="https://kommun.se/sida"),
                InfoBlobListing(id=uuid4(), title=None, url=None),
            ],
            budget=10_000,
        )

        assert lines[0].startswith("- https://kommun.se/sida")
        assert lines[1].startswith("- Untitled source")


class TestSampleTargets:
    def test_every_document_sampled_when_below_the_cap(self):
        listings = [
            InfoBlobListing(id=uuid4(), title=f"D{i}", url=None) for i in range(4)
        ]
        assert _sample_targets(listings, 12) == listings

    def test_targets_are_spread_rather_than_the_first_n(self):
        listings = [
            InfoBlobListing(id=uuid4(), title=f"D{i}", url=None) for i in range(100)
        ]
        targets = _sample_targets(listings, OVERVIEW_SAMPLE_DOCUMENTS)

        assert len(targets) == OVERVIEW_SAMPLE_DOCUMENTS
        assert targets[-1] != listings[OVERVIEW_SAMPLE_DOCUMENTS - 1]
        assert listings.index(targets[-1]) > 50

    def test_empty_listing_samples_nothing(self):
        assert _sample_targets([], 12) == []


class TestExcerptsPerDocument:
    def test_few_documents_get_several_passages_each(self):
        assert _excerpts_per_document(1) == OVERVIEW_MAX_CHUNKS_PER_DOC
        assert _excerpts_per_document(3) == OVERVIEW_MAX_CHUNKS_PER_DOC
        assert _excerpts_per_document(4) == 3
        assert _excerpts_per_document(6) == 2

    def test_a_full_sample_takes_one_passage_each(self):
        assert _excerpts_per_document(OVERVIEW_SAMPLE_DOCUMENTS) == 1
        assert _excerpts_per_document(400) == 1

    def test_total_excerpts_never_exceed_the_document_budget(self):
        # _sample_targets caps the document count, so that is the whole domain.
        for count in range(1, OVERVIEW_SAMPLE_DOCUMENTS + 1):
            assert count * _excerpts_per_document(count) <= OVERVIEW_SAMPLE_DOCUMENTS

    def test_nothing_to_sample_needs_no_passages(self):
        assert _excerpts_per_document(0) == 0


class TestOverviewContent:
    def _scope(self):
        return _source_scopes(
            _assistant_with_sources(collections=[(uuid4(), "Waste FAQ")])
        )[0]

    def _excerpt(self, blob_id, chunk_no=4, text="Garden waste is collected."):
        return SimpleNamespace(info_blob_id=blob_id, chunk_no=chunk_no, text=text)

    def test_titles_and_excerpts_are_rendered_together(self):
        blob_id = uuid4()
        content = _overview_content(
            scope=self._scope(),
            total=1,
            offset=0,
            title_lines=[f"- Waste policy  document_id: {blob_id}"],
            excerpts=[self._excerpt(blob_id)],
            excerpt_titles={blob_id: "Waste policy"},
        )

        assert "Collection 'Waste FAQ' contains 1 document(s)" in content[0].text
        assert f"document_id: {blob_id}" in content[0].text
        assert "small sample, not the whole source" in content[1].text
        assert str(content[2].resource.uri) == (f"eneo://info-blob/{blob_id}#chunk-4")

    def test_caveat_counts_documents_rather_than_passages(self):
        blob_id = uuid4()
        content = _overview_content(
            scope=self._scope(),
            total=1,
            offset=0,
            title_lines=["- Waste policy"],
            excerpts=[
                self._excerpt(blob_id, chunk_no=2),
                self._excerpt(blob_id, chunk_no=6),
            ],
            excerpt_titles={blob_id: "Waste policy"},
        )

        assert "2 excerpt(s) sampled from 1 of these documents" in content[1].text

    def test_excerpts_are_citable_resources(self):
        blob_id = uuid4()
        content = _overview_content(
            scope=self._scope(),
            total=1,
            offset=0,
            title_lines=["- Waste policy"],
            excerpts=[self._excerpt(blob_id)],
            excerpt_titles={blob_id: "Waste policy"},
        )

        resource = content[-1].resource
        assert resource.meta["info_blob_id"] == str(blob_id)
        assert resource.text.startswith("Title: Waste policy")

    def test_resume_notice_appears_only_when_titles_were_cut(self):
        cut = _overview_content(
            scope=self._scope(),
            total=50,
            offset=0,
            title_lines=["- A", "- B"],
            excerpts=[],
            excerpt_titles={},
        )
        complete = _overview_content(
            scope=self._scope(),
            total=2,
            offset=0,
            title_lines=["- A", "- B"],
            excerpts=[],
            excerpt_titles={},
        )

        assert "offset=2" in cut[-1].text
        assert all("offset=" not in block.text for block in complete)

    def test_offset_is_reflected_in_the_shown_range(self):
        content = _overview_content(
            scope=self._scope(),
            total=100,
            offset=40,
            title_lines=["- A", "- B"],
            excerpts=[],
            excerpt_titles={},
        )

        assert "Showing 41-42" in content[0].text

    def test_empty_source_says_so_without_a_title_list(self):
        content = _overview_content(
            scope=self._scope(),
            total=0,
            offset=0,
            title_lines=[],
            excerpts=[],
            excerpt_titles={},
        )

        assert len(content) == 1
        assert "contains no documents" in content[0].text

    def test_offset_past_the_end_reports_the_document_count(self):
        content = _overview_content(
            scope=self._scope(),
            total=3,
            offset=99,
            title_lines=[],
            excerpts=[],
            excerpt_titles={},
        )

        assert "past the end" in content[0].text


def _patch_describe_context(monkeypatch, assistant, *, listings=(), excerpts=()):
    @asynccontextmanager
    async def fake_context(_ctx):
        async def get_assistant(_assistant_id):
            return assistant, []

        async def count_by_sources(**_kwargs):
            return len(listings)

        async def list_by_sources(**kwargs):
            offset = kwargs.get("offset", 0)
            return list(listings)[offset : offset + kwargs["limit"]]

        async def sample_evenly(**_kwargs):
            return list(excerpts)

        container = SimpleNamespace(
            assistant_service=lambda: SimpleNamespace(get_assistant=get_assistant),
            info_blob_repo=lambda: SimpleNamespace(
                count_by_sources=count_by_sources, list_by_sources=list_by_sources
            ),
            info_blob_chunk_repo=lambda: SimpleNamespace(sample_evenly=sample_evenly),
        )
        yield container, SimpleNamespace(), uuid4()

    monkeypatch.setattr(
        "eneo.internal_mcp.knowledge.internal_tool_context", fake_context
    )


class TestDescribeSource:
    async def test_sole_source_needs_no_source_id(self, monkeypatch):
        assistant = _assistant_with_sources(collections=[(uuid4(), "Waste FAQ")])
        _patch_describe_context(
            monkeypatch,
            assistant,
            listings=[InfoBlobListing(id=uuid4(), title="Waste policy", url=None)],
        )

        content = await describe_source(ctx=None)

        assert "Collection 'Waste FAQ'" in content[0].text

    async def test_several_sources_ask_which_one(self, monkeypatch):
        assistant = _assistant_with_sources(
            collections=[(uuid4(), "Waste FAQ"), (uuid4(), "Riktlinjer")]
        )
        _patch_describe_context(monkeypatch, assistant)

        content = await describe_source(ctx=None)

        assert "several knowledge sources" in content[0].text
        assert "source_id:" in content[0].text

    async def test_no_sources_says_so(self, monkeypatch):
        _patch_describe_context(monkeypatch, _assistant_with_sources())

        content = await describe_source(ctx=None)

        assert content[0].text == "This assistant has no knowledge sources attached."

    async def test_foreign_source_id_is_indistinguishable_from_missing(
        self, monkeypatch
    ):
        assistant = _assistant_with_sources(collections=[(uuid4(), "Waste FAQ")])
        _patch_describe_context(monkeypatch, assistant)

        content = await describe_source(ctx=None, source_id=str(uuid4()))

        assert content[0].text == SCOPE_NOT_FOUND_MESSAGE

    async def test_negative_offset_is_clamped_to_the_start(self, monkeypatch):
        cid = uuid4()
        assistant = _assistant_with_sources(collections=[(cid, "Waste FAQ")])
        _patch_describe_context(
            monkeypatch,
            assistant,
            listings=[InfoBlobListing(id=uuid4(), title="Waste policy", url=None)],
        )

        content = await describe_source(ctx=None, source_id=str(cid), offset=-5)

        assert "Showing 1-1" in content[0].text


class TestToolSteering:
    def test_search_knowledge_documents_both_modes(self):
        doc = search_knowledge.__doc__ or ""
        assert '"specific"' in doc
        assert '"overview"' in doc

    def test_read_source_documents_the_document_id_handle(self):
        assert "document_id" in (read_source.__doc__ or "")

    def test_search_knowledge_documents_the_within_handle(self):
        doc = search_knowledge.__doc__ or ""
        assert "within" in doc
        assert "describe_source" in doc

    def test_describe_source_states_it_needs_no_query(self):
        doc = describe_source.__doc__ or ""
        assert "without a search query" in doc
        assert "source_id" in doc

    def test_listing_explains_what_the_source_id_is_for(self):
        doc = list_knowledge_sources.__doc__ or ""
        assert "source_id" in doc
        assert "describe_source" in doc

    def test_not_found_messages_never_echo_what_was_asked_for(self):
        # An echo would confirm the id exists somewhere; both stay constant.
        assert "{" not in NOT_FOUND_MESSAGE
        assert "{" not in SCOPE_NOT_FOUND_MESSAGE


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
