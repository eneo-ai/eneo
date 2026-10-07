"""Searching a SharePoint library by text and column values.

The picker's tree is read folder by folder, so a person cannot see a file
they have not browsed to. A library search asks Graph for every list item
whose columns match, or every drive item whose name or content matches, and
hands back flat file rows with the path they live at.
"""

import unicodedata
from typing import Any, cast
from urllib.parse import unquote

from eneo.info_blobs.info_blob import SourceMetadataEntry
from eneo.integration.infrastructure.content_service.sharepoint_metadata import (
    SharePointColumnCatalog,
    extract_source_metadata,
)

# Enough to choose from; a wider net wants a narrower search, not more rows.
MAX_SEARCH_RESULTS = 200
# Graph rejects longer search text; what a person types is cut here first.
MAX_SEARCH_TEXT_LENGTH = 200


def clean_search_text(text: str) -> str:
    """The free text as sent to Graph: trimmed, control characters out, capped."""
    cleaned = "".join(ch for ch in text if ch.isprintable() or ch == " ")
    return " ".join(cleaned.split())[:MAX_SEARCH_TEXT_LENGTH]


def parse_filter_params(raw_filters: list[str]) -> dict[str, str]:
    """``Column:value`` query parameters as a mapping; malformed ones are ignored."""
    filters: dict[str, str] = {}
    for raw in raw_filters:
        name, separator, value = raw.partition(":")
        if not separator or not name.strip() or not value.strip():
            continue
        filters[name.strip()] = value.strip()
    return filters


def _odata_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _boolean_filter_value(value: str) -> bool:
    return value.lower() in ("true", "yes", "ja", "1")


def build_odata_filter(
    catalog: SharePointColumnCatalog, filters: dict[str, str]
) -> tuple[str | None, dict[str, str]]:
    """One indexed scalar predicate for Graph, with remaining filters local.

    Graph list-item queries support one indexed field at a time. Multi-value
    choices and non-indexed columns are checked against raw fields while paging.
    Unknown or non-filterable columns fail before a request is made.
    """
    invalid = [
        name
        for name in filters
        if name not in catalog.columns or not catalog.columns[name].filterable
    ]
    if invalid:
        raise ValueError("Unknown filter column: " + ", ".join(sorted(invalid)))
    expression: str | None = None
    residual: dict[str, str] = {}
    for name, value in filters.items():
        column = catalog.columns[name]
        if expression is not None or not column.indexed or column.multiple_values:
            residual[name] = value
            continue
        if column.kind == "boolean":
            truthy = _boolean_filter_value(value)
            expression = f"fields/{name} eq {'true' if truthy else 'false'}"
        else:
            expression = f"fields/{name} eq {_odata_string(value)}"
    return expression, residual


def drive_item_matches_filters(
    drive_item: dict[str, object],
    catalog: SharePointColumnCatalog,
    filters: dict[str, str],
) -> bool:
    """Compare raw column values on a Graph text hit, before display limits."""
    if not filters:
        return True
    list_item = drive_item.get("listItem")
    if not isinstance(list_item, dict):
        raise ValueError("Could not read column values for filtered search")
    return _fields_match_filters(
        cast(dict[str, object], list_item).get("fields"), catalog, filters
    )


def list_item_matches_filters(
    list_item: dict[str, object],
    catalog: SharePointColumnCatalog,
    filters: dict[str, str],
) -> bool:
    """The same filter semantics for a fields/driveItem list-item response."""
    return _fields_match_filters(list_item.get("fields"), catalog, filters)


def _fields_match_filters(
    fields: object, catalog: SharePointColumnCatalog, filters: dict[str, str]
) -> bool:
    if not filters:
        return True
    if not isinstance(fields, dict):
        raise ValueError("Could not read column values for filtered search")
    fields = cast(dict[str, object], fields)
    for name, wanted in filters.items():
        value = fields.get(name)
        if catalog.columns[name].kind == "boolean":
            if not isinstance(value, bool) or value != _boolean_filter_value(wanted):
                return False
        else:
            values = cast(list[object], value) if isinstance(value, list) else [value]
            if not any(
                isinstance(entry, str) and entry.casefold() == wanted.casefold()
                for entry in values
            ):
                return False
    return True


def library_path(parent_reference: dict[str, Any] | None, name: str) -> str:
    """``/Folder/Sub/name`` from Graph's ``parentReference.path``.

    Graph writes the parent as ``/drives/{id}/root:/Folder/Sub``; the part
    after ``root:`` is the folder path, empty at the root. It arrives
    percent-encoded, so it is decoded and NFC-normalised the way the sync
    treats the same value, or a hit would never match the tree's paths.
    """
    raw = (parent_reference or {}).get("path")
    folder = ""
    if isinstance(raw, str):
        _, marker, rest = raw.partition("root:")
        folder = unicodedata.normalize("NFC", unquote(rest)) if marker else ""
    folder = folder.rstrip("/")
    return f"{folder}/{name}" if folder else f"/{name}"


def _file_row(
    drive_item: dict[str, Any],
    fields: dict[str, Any] | None,
    catalog: SharePointColumnCatalog,
) -> dict[str, Any] | None:
    if "file" not in drive_item or not drive_item.get("id"):
        return None
    name = str(drive_item.get("name") or "")
    if not name:
        return None
    source = {"listItem": {"fields": fields}} if fields is not None else drive_item
    return {
        "id": drive_item["id"],
        "name": name,
        "type": "file",
        "path": library_path(drive_item.get("parentReference"), name),
        "has_children": False,
        "size": drive_item.get("size"),
        "modified": drive_item.get("lastModifiedDateTime"),
        "web_url": drive_item.get("webUrl", ""),
        "source_metadata": extract_source_metadata(source, catalog),
    }


def row_from_list_item(
    list_item: dict[str, Any], catalog: SharePointColumnCatalog
) -> dict[str, Any] | None:
    """A list item fetched with ``$expand=fields,driveItem`` as a file row."""
    drive_item = list_item.get("driveItem")
    if not isinstance(drive_item, dict):
        return None
    fields = list_item.get("fields")
    return _file_row(
        cast(dict[str, Any], drive_item),
        cast(dict[str, Any], fields) if isinstance(fields, dict) else None,
        catalog,
    )


def row_from_drive_item(
    drive_item: dict[str, Any], catalog: SharePointColumnCatalog
) -> dict[str, Any] | None:
    """A drive item fetched with the list item expansion as a file row."""
    return _file_row(drive_item, None, catalog)


def row_matches(row: dict[str, Any], text: str, residual: dict[str, str]) -> bool:
    """The checks Graph could not do: free text and non-indexable columns."""
    entries = [
        entry
        if isinstance(entry, SourceMetadataEntry)
        else SourceMetadataEntry.model_validate(entry)
        for entry in cast(list[Any], row.get("source_metadata") or [])
    ]
    if text:
        # Only what the results list can highlight: a hit on the folder path
        # alone would show a row with nothing marked.
        needle = text.lower()
        haystack = [str(row.get("name", ""))]
        for entry in entries:
            haystack.append(entry.label)
            haystack.extend(
                entry.value if isinstance(entry.value, list) else [entry.value]
            )
        if not any(needle in part.lower() for part in haystack):
            return False
    for name, wanted in residual.items():
        entry = next((e for e in entries if e.name == name), None)
        if entry is None:
            return False
        values = entry.value if isinstance(entry.value, list) else [entry.value]
        if not any(value.lower() == wanted.lower() for value in values):
            return False
    return True


def filter_columns(catalog: SharePointColumnCatalog) -> list[dict[str, Any]]:
    """The catalog's filterable columns as the API presents them."""
    return [
        {
            "name": column.name,
            "label": column.label,
            "kind": column.kind,
            "choices": list(column.choices),
        }
        for column in catalog.columns.values()
        if column.filterable
    ]
