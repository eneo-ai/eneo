"""Library search: filter building, row shaping and the fixture's whole-site search."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import aiohttp
import pytest

from eneo.integration.domain.entities.oauth_token import SharePointToken
from eneo.integration.domain.value_objects import IntegrationType
from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointContentClient,
)
from eneo.integration.infrastructure.content_service.sharepoint_metadata import (
    SharePointColumnCatalog,
)
from eneo.integration.infrastructure.preview_service import (
    sharepoint_tree_service as tree_module,
)
from eneo.integration.infrastructure.preview_service.sharepoint_search import (
    build_odata_filter,
    clean_search_text,
    filter_columns,
    library_path,
    parse_filter_params,
    row_from_drive_item,
    row_from_list_item,
    row_matches,
)
from eneo.integration.infrastructure.preview_service.sharepoint_tree_service import (
    SharePointTreeService,
)
from eneo.integration.sharepoint_fixture.models import SharePointFixtureScenario
from eneo.integration.sharepoint_fixture.service import SharePointFixtureService

COLUMNS = [
    {
        "name": "Dokumenttyp",
        "displayName": "Dokumenttyp",
        "choice": {"choices": ["Rutin", "Policy", "Protokoll"]},
    },
    {"name": "Extern", "displayName": "Extern publicering", "boolean": {}},
    {"name": "Verksamhet", "displayName": "Verksamhet", "term": {}},
    {"name": "Fritext", "displayName": "Fritext", "text": {}},
]
CATALOG = SharePointColumnCatalog.from_graph(COLUMNS)


class TestFilterParsingAndOData:
    def test_parses_column_value_pairs_and_ignores_malformed(self):
        assert parse_filter_params(
            ["Dokumenttyp:Rutin", "Extern: true", "junk", ":x", "a:"]
        ) == {
            "Dokumenttyp": "Rutin",
            "Extern": "true",
        }

    def test_only_filterable_columns_are_exposed(self):
        assert filter_columns(CATALOG) == [
            {
                "name": "Dokumenttyp",
                "label": "Dokumenttyp",
                "kind": "choice",
                "choices": ["Rutin", "Policy", "Protokoll"],
            },
            {
                "name": "Extern",
                "label": "Extern publicering",
                "kind": "boolean",
                "choices": [],
            },
        ]

    def test_builds_graph_filter_for_choice_and_boolean_and_keeps_the_rest(self):
        expr, residual = build_odata_filter(
            CATALOG,
            {
                "Dokumenttyp": "O'Neil",
                "Extern": "ja",
                "Verksamhet": "Vård",
                "Okänd": "x",
            },
        )
        assert expr == "fields/Dokumenttyp eq 'O''Neil' and fields/Extern eq true"
        assert residual == {"Verksamhet": "Vård", "Okänd": "x"}

    def test_no_filters_gives_no_expression(self):
        assert build_odata_filter(CATALOG, {}) == (None, {})


class TestRows:
    def test_path_is_read_from_the_parent_reference(self):
        assert library_path({"path": "/drives/b!x/root:/Rutiner/Larm"}, "a.docx") == (
            "/Rutiner/Larm/a.docx"
        )
        # Graph percent-encodes the parent path; the tree shows it decoded.
        assert (
            library_path(
                {"path": "/drives/b!x/root:/Styrande%20dokument/Policyer"}, "x.pdf"
            )
            == "/Styrande dokument/Policyer/x.pdf"
        )
        assert library_path({"path": "/drives/b!x/root:"}, "a.docx") == "/a.docx"
        assert library_path(None, "a.docx") == "/a.docx"

    def test_list_item_row_carries_properties_and_skips_folders(self):
        row = row_from_list_item(
            {
                "fields": {"Dokumenttyp": "Rutin", "Extern": True, "FileLeafRef": "x"},
                "driveItem": {
                    "id": "i1",
                    "name": "Larm.docx",
                    "file": {},
                    "size": 10,
                    "lastModifiedDateTime": "2026-01-01T00:00:00Z",
                    "webUrl": "https://x",
                    "parentReference": {"path": "/drives/d/root:/Rutiner"},
                },
            },
            CATALOG,
        )
        assert row is not None
        assert row["path"] == "/Rutiner/Larm.docx"
        assert [(e.label, e.value) for e in row["source_metadata"]] == [
            ("Dokumenttyp", "Rutin"),
            ("Extern publicering", "true"),
        ]
        folder = row_from_list_item(
            {"fields": {}, "driveItem": {"id": "f", "name": "Rutiner", "folder": {}}},
            CATALOG,
        )
        assert folder is None

    def test_drive_item_row_uses_the_expanded_list_item(self):
        row = row_from_drive_item(
            {
                "id": "i1",
                "name": "Larm.docx",
                "file": {},
                "listItem": {"fields": {"Dokumenttyp": "Rutin"}},
                "parentReference": {"path": "/drives/d/root:"},
            },
            CATALOG,
        )
        assert row is not None and row["source_metadata"][0].value == "Rutin"

    def test_text_and_residual_filters_are_checked_on_the_row(self):
        row = row_from_list_item(
            {
                "fields": {"Dokumenttyp": "Rutin", "Verksamhet": [{"Label": "Vård"}]},
                "driveItem": {"id": "i", "name": "Larm.docx", "file": {}},
            },
            CATALOG,
        )
        assert row is not None
        assert row_matches(row, "larm", {})
        assert row_matches(row, "rutin", {})
        # The folder path is shown but never highlighted, so it is not a hit.
        row["path"] = "/Brandskydd/Larm.docx"
        assert not row_matches(row, "brandskydd", {})
        assert row_matches(row, "", {"Verksamhet": "vård"})
        assert not row_matches(row, "", {"Verksamhet": "Skola"})
        assert not row_matches(row, "policy", {})


def _token() -> SharePointToken:
    return SharePointToken(
        id=uuid4(),
        access_token="token",
        refresh_token="refresh",
        token_type=IntegrationType.Sharepoint,
        user_integration=MagicMock(),
    )


def _client():
    client = MagicMock()
    client.list_item_fields_enabled = True
    client.get_list_columns = AsyncMock(return_value=COLUMNS)
    client.get_default_drive_id = AsyncMock(return_value="d1")
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    return client, context


def test_search_text_is_trimmed_cleaned_and_capped():
    assert clean_search_text("  larm \x00 natt  ") == "larm natt"
    assert len(clean_search_text("x" * 500)) == 200


class TestSearchLibrary:
    async def test_column_filters_alone_query_the_list_for_files(self):
        client, context = _client()
        raw_rows = [
            {
                "fields": {"Dokumenttyp": "Rutin"},
                "driveItem": {"id": "1", "name": "Larm.docx", "file": {}},
            },
            {
                "fields": {"Dokumenttyp": "Rutin"},
                "driveItem": {"id": "2", "name": "Brand.docx", "file": {}},
            },
            {
                "fields": {"Dokumenttyp": "Rutin"},
                "driveItem": {"id": "folder", "name": "Rutiner", "folder": {}},
            },
        ]

        async def filtered(drive_id, odata_filter, *, max_items, accept):
            # The client pages until enough rows pass; here it only applies the check.
            return [raw for raw in raw_rows if accept(raw)], True

        client.get_list_items_filtered = AsyncMock(side_effect=filtered)
        with patch(
            f"{tree_module.__name__}.SharePointContentClient", return_value=context
        ):
            result = await SharePointTreeService().search_library(
                _token(), site_id="s1", filters={"Dokumenttyp": "Rutin"}
            )

        call = client.get_list_items_filtered.await_args
        assert call.args == ("d1", "fields/Dokumenttyp eq 'Rutin'")
        assert call.kwargs["max_items"] == 200
        assert [row["name"] for row in result["items"]] == ["Larm.docx", "Brand.docx"]
        assert result["truncated"] is True

    @pytest.mark.parametrize("text", ["", "larm"])
    async def test_a_column_graph_cannot_compare_is_rejected(self, text):
        client, context = _client()
        client.get_list_items_filtered = AsyncMock()
        with patch(
            f"{tree_module.__name__}.SharePointContentClient", return_value=context
        ):
            with pytest.raises(ValueError, match="Unknown filter column: Ansvarig"):
                await SharePointTreeService().search_library(
                    _token(), site_id="s1", text=text, filters={"Ansvarig": "Anna"}
                )
        client.get_list_items_filtered.assert_not_awaited()

    async def test_text_alone_uses_the_drive_search(self):
        client, context = _client()
        client.search_drive_items = AsyncMock(
            return_value=([{"id": "1", "name": "Larm.docx", "file": {}}], False)
        )
        with patch(
            f"{tree_module.__name__}.SharePointContentClient", return_value=context
        ):
            result = await SharePointTreeService().search_library(
                _token(), drive_id="d1", text="larm"
            )

        call = client.search_drive_items.await_args
        assert call.args == ("d1", "larm")
        assert call.kwargs["max_items"] == 200
        assert [row["name"] for row in result["items"]] == ["Larm.docx"]

    @pytest.mark.parametrize(
        "external, expected", [("ja", "1"), ("false", "3"), ("nej", "3")]
    )
    @pytest.mark.parametrize("document_type", ["Rutin", "rutin", ["Rutin", "Policy"]])
    async def test_text_with_filters_preserves_content_only_search_hits(
        self, external, expected, document_type
    ):
        client, context = _client()
        # Graph matched "larm" in the body; it is absent from the visible row.
        raw_rows = [
            {
                "id": "1",
                "name": "Handbok.docx",
                "file": {},
                "listItem": {"fields": {"Dokumenttyp": document_type, "Extern": True}},
            },
            {
                "id": "2",
                "name": "Policy.docx",
                "file": {},
                "listItem": {"fields": {"Dokumenttyp": "Policy", "Extern": True}},
            },
            {
                "id": "3",
                "name": "Intern.docx",
                "file": {},
                "listItem": {"fields": {"Dokumenttyp": document_type, "Extern": False}},
            },
        ]

        async def search(drive_id, text, *, max_items, accept):
            return [raw for raw in raw_rows if accept(raw)], False

        async def filtered(drive_id, odata_filter, *, max_items, accept):
            return [
                raw
                for item in raw_rows
                if accept(
                    raw := {"fields": item["listItem"]["fields"], "driveItem": item}
                )
            ], False

        client.search_drive_items = AsyncMock(side_effect=search)
        client.get_list_items_filtered = AsyncMock(side_effect=filtered)
        with patch(
            f"{tree_module.__name__}.SharePointContentClient", return_value=context
        ):
            result = await SharePointTreeService().search_library(
                _token(),
                drive_id="d1",
                text="larm",
                filters={"Dokumenttyp": "Rutin", "Extern": external},
            )

        assert [row["id"] for row in result["items"]] == [expected]
        assert client.search_drive_items.await_args.args == ("d1", "larm")
        client.get_list_items_filtered.assert_not_awaited()

    async def test_filter_values_are_read_before_metadata_display_limits(self):
        client, context = _client()
        columns = [{"name": f"C{i}", "text": {}} for i in range(40)] + COLUMNS
        client.get_list_columns.return_value = columns
        raw = {
            "id": "1",
            "name": "Handbok.docx",
            "file": {},
            "listItem": {
                "fields": {**{f"C{i}": "v" for i in range(40)}, "Dokumenttyp": "Rutin"}
            },
        }

        async def search(drive_id, text, *, max_items, accept):
            return [raw] if accept(raw) else [], False

        client.search_drive_items = AsyncMock(side_effect=search)
        client.get_list_items_filtered = AsyncMock(return_value=([], False))
        with patch(
            f"{tree_module.__name__}.SharePointContentClient", return_value=context
        ):
            result = await SharePointTreeService().search_library(
                _token(), drive_id="d1", text="larm", filters={"Dokumenttyp": "Rutin"}
            )

        assert [row["id"] for row in result["items"]] == ["1"]
        assert len(result["items"][0]["source_metadata"]) == 40

    async def test_missing_fields_fail_explicitly_when_column_filters_are_active(self):
        client, context = _client()

        async def search(drive_id, text, *, max_items, accept):
            accept({"id": "1", "name": "Handbok.docx", "file": {}})
            return [], False

        client.search_drive_items = AsyncMock(side_effect=search)
        client.get_list_items_filtered = AsyncMock(return_value=([], False))
        with patch(
            f"{tree_module.__name__}.SharePointContentClient", return_value=context
        ):
            with pytest.raises(ValueError, match="Could not read column values"):
                await SharePointTreeService().search_library(
                    _token(),
                    drive_id="d1",
                    text="larm",
                    filters={"Dokumenttyp": "Rutin"},
                )

    async def test_empty_search_asks_graph_nothing(self):
        client, context = _client()
        with patch(
            f"{tree_module.__name__}.SharePointContentClient", return_value=context
        ):
            result = await SharePointTreeService().search_library(
                _token(), drive_id="d1"
            )
        assert result["items"] == []
        client.get_list_columns.assert_not_awaited()


def _paged_graph_client(responses):
    transport = MagicMock()
    transport.get = AsyncMock(side_effect=[{"value": COLUMNS}, *responses])
    transport.close = AsyncMock()
    with patch(
        "eneo.libs.clients.base_clients.WrappedAiohttpClient", return_value=transport
    ):
        client = SharePointContentClient(
            base_url="https://graph.microsoft.com",
            api_token="token",
            token_id=uuid4(),
            token_refresh_callback=AsyncMock(
                return_value={"access_token": "new-token"}
            ),
            include_list_item_fields=True,
            max_download_bytes=1,
        )
    return client


class TestSearchPagination:
    @pytest.mark.parametrize("text", ["", "larm"])
    async def test_token_refresh_mid_query_does_not_duplicate_accepted_files(
        self, text
    ):
        first = {
            "value": [
                {
                    "fields": {"Dokumenttyp": "Rutin"},
                    "driveItem": {"id": "1", "name": "A.docx", "file": {}},
                }
            ],
            "@odata.nextLink": "https://graph.microsoft.com/p2",
        }
        last = {
            "value": [
                {
                    "fields": {"Dokumenttyp": "Rutin"},
                    "driveItem": {"id": "2", "name": "B.docx", "file": {}},
                }
            ]
        }
        unauthorized = aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=401
        )
        if text:
            for page in [first, last]:
                for row in page["value"]:
                    row["driveItem"]["listItem"] = {"fields": row["fields"]}
                page["value"] = [row["driveItem"] for row in page["value"]]
        client = _paged_graph_client([first, unauthorized, first, last])

        with patch(
            f"{tree_module.__name__}.SharePointContentClient", return_value=client
        ):
            result = await SharePointTreeService().search_library(
                _token(),
                drive_id="d1",
                text=text,
                filters={"Dokumenttyp": "Rutin"},
                max_items=2,
            )

        assert [row["id"] for row in result["items"]] == ["1", "2"]
        assert result["truncated"] is False
        assert client.api_token == "new-token"

    @pytest.mark.parametrize("expansion_rejected", [False, True])
    async def test_folder_hits_do_not_consume_the_file_result_limit(
        self, expansion_rejected
    ):
        folders = [
            {"id": f"folder-{i}", "name": "Larm", "folder": {}} for i in range(200)
        ]
        files = [
            {"id": f"file-{i}", "name": f"Larm {i}.docx", "file": {}}
            for i in range(201)
        ]
        responses = [
            {"value": folders, "@odata.nextLink": "https://graph.microsoft.com/p2"},
            {"value": files},
        ]
        if expansion_rejected:
            responses.insert(
                0,
                aiohttp.ClientResponseError(
                    request_info=MagicMock(), history=(), status=400
                ),
            )
        client = _paged_graph_client(responses)

        with patch(
            f"{tree_module.__name__}.SharePointContentClient", return_value=client
        ):
            result = await SharePointTreeService().search_library(
                _token(), drive_id="d1", text="larm"
            )

        assert len(result["items"]) == 200
        assert [row["id"] for row in result["items"]] == [
            f"file-{i}" for i in range(200)
        ]
        assert result["truncated"] is True

    async def test_a_folder_only_search_stops_at_the_scan_budget_and_reports_truncation(
        self,
    ):
        page = {
            "value": [{"id": str(i), "name": "Larm", "folder": {}} for i in range(500)],
            "@odata.nextLink": "https://graph.microsoft.com/p2",
        }
        client = _paged_graph_client([page] * 5)

        with patch(
            f"{tree_module.__name__}.SharePointContentClient", return_value=client
        ):
            result = await SharePointTreeService().search_library(
                _token(), drive_id="d1", text="larm"
            )

        assert result["items"] == []
        assert result["truncated"] is True
        assert client.client.get.await_count == 5  # columns + four pages of 500

    async def test_column_filters_keep_paging_past_nonmatching_content_hits(self):
        rejected = [
            {
                "id": str(i),
                "name": "Larm.docx",
                "file": {},
                "listItem": {"fields": {"Dokumenttyp": "Policy"}},
            }
            for i in range(200)
        ]
        match = {
            "id": "match",
            "name": "Handbok.docx",
            "file": {},
            "listItem": {"fields": {"Dokumenttyp": "Rutin"}},
        }
        client = _paged_graph_client(
            [
                {
                    "value": rejected,
                    "@odata.nextLink": "https://graph.microsoft.com/p2",
                },
                {"value": [match]},
            ]
        )

        with patch(
            f"{tree_module.__name__}.SharePointContentClient", return_value=client
        ):
            result = await SharePointTreeService().search_library(
                _token(), drive_id="d1", text="larm", filters={"Dokumenttyp": "Rutin"}
            )

        assert [row["id"] for row in result["items"]] == ["match"]
        assert result["truncated"] is False

    async def test_rejected_expansion_does_not_silently_discard_filtered_hits(self):
        rejected = aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=400
        )
        client = _paged_graph_client(
            [rejected, {"value": [{"id": "1", "name": "Handbok.docx", "file": {}}]}]
        )

        with patch(
            f"{tree_module.__name__}.SharePointContentClient", return_value=client
        ):
            with pytest.raises(ValueError, match="Could not read column values"):
                await SharePointTreeService().search_library(
                    _token(),
                    drive_id="d1",
                    text="larm",
                    filters={"Dokumenttyp": "Rutin"},
                )


class TestFixtureSearch:
    def test_tree_exposes_the_profile_columns(self):
        response = SharePointFixtureService().get_tree(
            SharePointFixtureScenario.REPRESENTATIVE,
            site_id="fixture-site-leadership-se",
            drive_id=None,
        )
        by_name = {column.name: column for column in response.columns}
        assert by_name["Dokumenttyp"].kind == "choice"
        assert "Policy" in by_name["Dokumenttyp"].choices
        assert by_name["Extern"].kind == "boolean"

    def test_search_covers_the_whole_site_and_combines_text_with_filters(self):
        service = SharePointFixtureService()
        external = service.get_search(
            SharePointFixtureScenario.REPRESENTATIVE,
            site_id="fixture-site-leadership-se",
            drive_id=None,
            filters={"Extern": "true"},
        )
        assert external.items and all(
            any(e.name == "Extern" and e.value == "true" for e in item.source_metadata)
            for item in external.items
        )
        policies = service.get_search(
            SharePointFixtureScenario.REPRESENTATIVE,
            site_id="fixture-site-leadership-se",
            drive_id=None,
            text="distans",
            filters={"Dokumenttyp": "Policy"},
        )
        assert [item.name for item in policies.items] == [
            "Policy för distansarbete.docx"
        ]
        assert policies.items[0].path.startswith("/01 – Styrande dokument/Policyer/")
        nothing = service.get_search(
            SharePointFixtureScenario.REPRESENTATIVE,
            site_id="fixture-site-leadership-se",
            drive_id=None,
        )
        assert nothing.items == []


class TestRecordsFixture:
    """The metadata-heavy site exists to exercise the picker with many columns."""

    def test_exposes_more_than_a_dozen_filterable_columns_with_their_values(self):
        response = SharePointFixtureService().get_tree(
            SharePointFixtureScenario.REPRESENTATIVE,
            site_id="fixture-site-records-centre",
            drive_id=None,
        )
        by_name = {column.name: column for column in response.columns}
        assert len(by_name) >= 16
        assert by_name["Status"].choices == ["Gällande", "Under revidering", "Upphävd"]
        assert by_name["Granskad"].kind == "boolean"
        assert "Lagrum" not in by_name, "free-text columns are searched, not filtered"

    def test_filters_combine_across_many_columns(self):
        service = SharePointFixtureService()
        hits = service.get_search(
            SharePointFixtureScenario.REPRESENTATIVE,
            site_id="fixture-site-records-centre",
            drive_id=None,
            filters={"Dokumenttyp": "Rutin", "Status": "Gällande", "Extern": "false"},
        )
        assert [item.name for item in hits.items] == [
            "Rutin för larm inom hemtjänsten.docx"
        ]
        archived = service.get_search(
            SharePointFixtureScenario.REPRESENTATIVE,
            site_id="fixture-site-records-centre",
            drive_id=None,
            text="2021",
            filters={"Arkiveras": "true"},
        )
        assert [item.name for item in archived.items] == [
            "Riktlinje för distansarbete 2021 (upphävd).docx"
        ]
