"""Library search: filter building, row shaping and the fixture's whole-site search."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from eneo.integration.domain.entities.oauth_token import SharePointToken
from eneo.integration.domain.value_objects import IntegrationType
from eneo.integration.infrastructure.content_service.sharepoint_metadata import (
    SharePointColumnCatalog,
)
from eneo.integration.infrastructure.preview_service import (
    sharepoint_tree_service as tree_module,
)
from eneo.integration.infrastructure.preview_service.sharepoint_search import (
    build_odata_filter,
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


class TestSearchLibrary:
    async def test_column_filters_query_the_list_and_text_narrows_the_rows(self):
        client, context = _client()
        client.get_list_items_filtered = AsyncMock(
            return_value=(
                [
                    {
                        "fields": {"Dokumenttyp": "Rutin"},
                        "driveItem": {"id": "1", "name": "Larm.docx", "file": {}},
                    },
                    {
                        "fields": {"Dokumenttyp": "Rutin"},
                        "driveItem": {"id": "2", "name": "Brand.docx", "file": {}},
                    },
                ],
                True,
            )
        )
        with patch(
            f"{tree_module.__name__}.SharePointContentClient", return_value=context
        ):
            result = await SharePointTreeService().search_library(
                _token(), site_id="s1", text="larm", filters={"Dokumenttyp": "Rutin"}
            )

        client.get_list_items_filtered.assert_awaited_once_with(
            "d1", "fields/Dokumenttyp eq 'Rutin'", max_items=200
        )
        assert [row["name"] for row in result["items"]] == ["Larm.docx"]
        assert result["truncated"] is True

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

        client.search_drive_items.assert_awaited_once_with("d1", "larm", max_items=200)
        assert [row["name"] for row in result["items"]] == ["Larm.docx"]

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
