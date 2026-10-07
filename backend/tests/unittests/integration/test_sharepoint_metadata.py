"""SharePoint library columns -> source metadata entries."""

from eneo.info_blobs.info_blob import SourceMetadataEntry
from eneo.integration.infrastructure.content_service.sharepoint_metadata import (
    MAX_ENTRIES,
    MAX_LIST_VALUES,
    MAX_VALUE_LENGTH,
    SharePointColumnCatalog,
    extract_source_metadata,
    source_metadata_fingerprint,
)

COLUMNS = [
    {"name": "Title", "displayName": "Rubrik", "text": {}},
    {"name": "Dokumenttyp", "displayName": "Dokumenttyp", "choice": {}},
    {"name": "Verksamhet", "displayName": "Verksamhet", "term": {}},
    {"name": "Giltig_x0020_till", "displayName": "Giltig till", "dateTime": {}},
    {"name": "Extern", "displayName": "Extern", "boolean": {}},
    {"name": "Version_x0020_nr", "displayName": "Versionsnummer", "number": {}},
    {"name": "Lank", "displayName": "Länk", "hyperlinkOrPicture": {}},
    # System and structural columns that must never become metadata.
    {"name": "FileLeafRef", "displayName": "Namn", "text": {}},
    {"name": "Created", "displayName": "Skapad", "dateTime": {}, "readOnly": True},
    {"name": "_UIVersionString", "displayName": "Version", "text": {}},
    {"name": "TaxCatchAll", "displayName": "Taxonomy Catch All", "hidden": True},
    {"name": "Ansvarig", "displayName": "Ansvarig", "personOrGroup": {}},
    {"name": "Projekt", "displayName": "Projekt", "lookup": {}},
    {"name": "MediaServiceOCR", "displayName": "OCR", "text": {}},
    {"displayName": "no name"},
]


def _item(fields: dict) -> dict:
    return {"id": "item-1", "name": "rutin.docx", "listItem": {"fields": fields}}


class TestColumnCatalog:
    def test_admits_only_user_facing_columns(self):
        catalog = SharePointColumnCatalog.from_graph(COLUMNS)

        assert list(catalog.columns) == [
            "Title",
            "Dokumenttyp",
            "Verksamhet",
            "Giltig_x0020_till",
            "Extern",
            "Version_x0020_nr",
            "Lank",
        ]

    def test_kind_follows_the_column_facet(self):
        catalog = SharePointColumnCatalog.from_graph(COLUMNS)

        assert catalog.columns["Title"].kind == "text"
        assert catalog.columns["Dokumenttyp"].kind == "choice"
        assert catalog.columns["Verksamhet"].kind == "choice"
        assert catalog.columns["Giltig_x0020_till"].kind == "date"
        assert catalog.columns["Extern"].kind == "boolean"
        assert catalog.columns["Version_x0020_nr"].kind == "number"
        assert catalog.columns["Lank"].kind == "url"

    def test_falls_back_to_internal_name_without_display_name(self):
        catalog = SharePointColumnCatalog.from_graph(
            [{"name": "Omrade", "displayName": "  "}]
        )
        assert catalog.columns["Omrade"].label == "Omrade"

    def test_empty_definitions_give_empty_catalog(self):
        assert SharePointColumnCatalog.from_graph([]).is_empty

    def test_catalog_keeps_indexing_and_choice_multiplicity_for_search(self):
        catalog = SharePointColumnCatalog.from_graph(
            [
                {
                    "name": "Topics",
                    "indexed": True,
                    "choice": {"choices": ["A", "B"], "displayAs": "checkBoxes"},
                },
                {
                    "name": "Type",
                    "choice": {"choices": ["Policy"], "displayAs": "dropDownMenu"},
                },
            ]
        )

        assert catalog.columns["Topics"].indexed is True
        assert catalog.columns["Topics"].multiple_values is True
        assert catalog.columns["Type"].indexed is False
        assert catalog.columns["Type"].multiple_values is False


class TestExtractSourceMetadata:
    def test_values_follow_column_order_and_normalise_per_kind(self):
        catalog = SharePointColumnCatalog.from_graph(COLUMNS)
        item = _item(
            {
                "FileLeafRef": "rutin.docx",
                "Extern": True,
                "Dokumenttyp": "Rutin",
                "Verksamhet": [
                    {"Label": "Äldreomsorg", "TermGuid": "a"},
                    {"Label": "Hemtjänst", "TermGuid": "b"},
                ],
                "Title": "  Rutin   för  larm ",
                "Giltig_x0020_till": "2027-01-31T00:00:00Z",
                "Version_x0020_nr": 3,
                "Lank": {"Url": "https://example.org", "Description": "Intranät"},
                "_UIVersionString": "4.0",
                "AnsvarigLookupId": "7",
            }
        )

        entries = extract_source_metadata(item, catalog)

        assert [(e.label, e.value, e.kind) for e in entries] == [
            ("Rubrik", "Rutin för larm", "text"),
            ("Dokumenttyp", "Rutin", "choice"),
            ("Verksamhet", ["Äldreomsorg", "Hemtjänst"], "choice"),
            ("Giltig till", "2027-01-31T00:00:00Z", "date"),
            ("Extern", "true", "boolean"),
            ("Versionsnummer", "3", "number"),
            ("Länk", "Intranät", "url"),
        ]
        assert all(isinstance(e, SourceMetadataEntry) for e in entries)

    def test_blank_and_null_values_are_left_out(self):
        catalog = SharePointColumnCatalog.from_graph(COLUMNS)
        item = _item({"Title": "   ", "Dokumenttyp": None, "Verksamhet": []})

        assert extract_source_metadata(item, catalog) == []

    def test_items_without_list_item_or_catalog_give_nothing(self):
        catalog = SharePointColumnCatalog.from_graph(COLUMNS)

        assert extract_source_metadata({"id": "x"}, catalog) == []
        assert extract_source_metadata({"listItem": {"fields": "?"}}, catalog) == []
        assert extract_source_metadata({"listItem": None}, catalog) == []
        assert (
            extract_source_metadata(_item({"Title": "A"}), SharePointColumnCatalog())
            == []
        )

    def test_long_values_and_lists_are_capped(self):
        catalog = SharePointColumnCatalog.from_graph(COLUMNS)
        item = _item(
            {
                "Title": "x" * (MAX_VALUE_LENGTH + 50),
                "Verksamhet": [f"v{i}" for i in range(MAX_LIST_VALUES + 10)],
            }
        )

        entries = {e.name: e for e in extract_source_metadata(item, catalog)}

        assert len(entries["Title"].value) == MAX_VALUE_LENGTH
        assert len(entries["Verksamhet"].value) == MAX_LIST_VALUES

    def test_duplicate_list_values_collapse(self):
        catalog = SharePointColumnCatalog.from_graph(COLUMNS)
        item = _item({"Verksamhet": ["A", "A", {"Label": "A"}, "B"]})

        [entry] = extract_source_metadata(item, catalog)
        assert entry.value == ["A", "B"]

    def test_entry_count_is_capped(self):
        definitions = [
            {"name": f"C{i}", "displayName": f"C{i}", "text": {}}
            for i in range(MAX_ENTRIES + 5)
        ]
        catalog = SharePointColumnCatalog.from_graph(definitions)
        item = _item({f"C{i}": "v" for i in range(MAX_ENTRIES + 5)})

        assert len(extract_source_metadata(item, catalog)) == MAX_ENTRIES


class TestFingerprint:
    def test_is_stable_and_sensitive_to_values(self):
        a = [SourceMetadataEntry(name="t", label="T", value="Rutin", kind="choice")]
        b = [SourceMetadataEntry(name="t", label="T", value="Policy", kind="choice")]

        assert source_metadata_fingerprint(
            a, title="Doc"
        ) == source_metadata_fingerprint(list(a), title="Doc")
        assert source_metadata_fingerprint(
            a, title="Doc"
        ) != source_metadata_fingerprint(b, title="Doc")
        assert len(source_metadata_fingerprint(a, title="Doc")) == 16

    def test_title_uses_the_same_whitespace_normalization_as_the_header(self):
        entries = [
            SourceMetadataEntry(name="t", label="T", value="Rutin", kind="choice")
        ]
        assert source_metadata_fingerprint(
            entries, title=" Doc "
        ) == source_metadata_fingerprint(entries, title="Doc")
        assert source_metadata_fingerprint(
            entries, title="Doc"
        ) != source_metadata_fingerprint(entries, title="Renamed")
