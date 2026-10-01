"""SharePoint library columns as source metadata.

A document library carries a SharePoint list behind it; every file is also a
list item with the library's columns (``listItem.fields`` in Graph). Which of
those columns mean something to people is decided by the library's column
definitions, not by the field payload: the payload mixes the columns a site
owner added with dozens of system columns (``FileLeafRef``, ``_UIVersionString``,
``MediaServiceOCR`` and friends). This module turns the two into the ordered
``SourceMetadataEntry`` list stored on an info blob.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, cast

from eneo.info_blobs.info_blob import SourceMetadataEntry, SourceMetadataKind
from eneo.main.logging import get_logger

logger = get_logger(__name__)

# Graph query appended to drive item listings so each item carries its list
# item and the list item its column values.
LIST_ITEM_FIELDS_EXPAND = "listItem($expand=fields)"

MAX_ENTRIES = 40
MAX_VALUE_LENGTH = 500
MAX_LIST_VALUES = 20

# Built-in library columns that are neither hidden nor read-only in the column
# definitions but describe the file record rather than the document. Internal
# names, as Graph reports them.
_EXCLUDED_COLUMNS: frozenset[str] = frozenset(
    {
        "ID",
        "id",
        "FileLeafRef",
        "LinkFilename",
        "LinkFilenameNoMenu",
        "LinkTitle",
        "LinkTitleNoMenu",
        "DocIcon",
        "Edit",
        "FileSizeDisplay",
        "ItemChildCount",
        "FolderChildCount",
        "CheckoutUser",
        "CheckedOutTitle",
        "CheckedOutUserId",
        "IsCheckedoutToLocal",
        "ComplianceAssetId",
        "SharedWithUsers",
        "SharedWithDetails",
        "TriggerFlowInfo",
        "AppAuthor",
        "AppEditor",
        "TemplateUrl",
        "ParentVersionString",
        "ParentLeafName",
        "ContentTypeId",
        "Attachments",
        "Order",
        "GUID",
        "WorkflowVersion",
        "WorkflowInstanceID",
        "InstanceID",
        "owshiddenversion",
        "UniqueId",
        "SyncClientId",
        "ProgId",
        "ScopeId",
        "MetaInfo",
        "SortBehavior",
        "FSObjType",
        "FileRef",
        "FileDirRef",
        "File_x0020_Type",
        "File_x0020_Size",
        "HTML_x0020_File_x0020_Type",
        "ServerUrl",
        "EncodedAbsUrl",
        "BaseName",
        "FileSystemObjectType",
        "PermMask",
        "Combine",
        "RepairDocument",
        "SelectTitle",
        "SelectFilename",
        "NoExecute",
        "StreamHash",
        "SMTotalSize",
        "SMLastModifiedDate",
        "SMTotalFileStreamSize",
        "SMTotalFileCount",
        "ContentVersion",
        "AccessPolicy",
        "Restricted",
        "OriginatorId",
        "Created_x0020_Date",
        "Last_x0020_Modified",
        "Modified_x0020_By",
        "Created_x0020_By",
        "Author",
        "Editor",
        "Created",
        "Modified",
    }
)
_EXCLUDED_PREFIXES: tuple[str, ...] = ("_", "OData_", "MediaService", "xd_")


@dataclass(frozen=True, slots=True)
class SharePointColumn:
    name: str
    label: str
    kind: SourceMetadataKind


@dataclass(frozen=True, slots=True)
class SharePointColumnCatalog:
    """The columns of one library worth storing, keyed by internal name."""

    columns: dict[str, SharePointColumn] = field(
        default_factory=dict[str, SharePointColumn]
    )

    @classmethod
    def from_graph(cls, definitions: list[dict[str, Any]]) -> "SharePointColumnCatalog":
        columns: dict[str, SharePointColumn] = {}
        for definition in definitions:
            column = _column_from_definition(definition)
            if column is not None:
                columns[column.name] = column
        return cls(columns=columns)

    @property
    def is_empty(self) -> bool:
        return not self.columns


def _column_from_definition(definition: dict[str, Any]) -> SharePointColumn | None:
    name = definition.get("name")
    if not isinstance(name, str) or not name:
        return None
    if definition.get("hidden") or definition.get("readOnly"):
        return None
    if name in _EXCLUDED_COLUMNS or name.startswith(_EXCLUDED_PREFIXES):
        return None
    # Lookup and person columns only surface a numeric ``<name>LookupId`` in the
    # field payload; the readable value lives in another list we do not read.
    if "lookup" in definition or "personOrGroup" in definition:
        return None

    label = definition.get("displayName")
    if not isinstance(label, str) or not label.strip():
        label = name
    return SharePointColumn(
        name=name, label=label.strip()[:255], kind=_kind_of(definition)
    )


def _kind_of(definition: dict[str, Any]) -> SourceMetadataKind:
    if "dateTime" in definition:
        return "date"
    if "boolean" in definition:
        return "boolean"
    if "number" in definition or "currency" in definition:
        return "number"
    if "choice" in definition or "term" in definition:
        return "choice"
    if "hyperlinkOrPicture" in definition:
        return "url"
    return "text"


def extract_source_metadata(
    item: dict[str, Any], catalog: SharePointColumnCatalog
) -> list[SourceMetadataEntry]:
    """The item's column values that the catalog admits, in catalog order.

    ``item`` is a Graph driveItem fetched with ``LIST_ITEM_FIELDS_EXPAND``.
    Returns an empty list for items without a list item (deleted items,
    personal OneDrive roots) or without any admitted value.
    """
    if catalog.is_empty:
        return []
    list_item = item.get("listItem")
    if not isinstance(list_item, dict):
        return []
    fields = cast(dict[str, Any], list_item).get("fields")
    if not isinstance(fields, dict):
        return []
    fields = cast(dict[str, Any], fields)

    entries: list[SourceMetadataEntry] = []
    for column in catalog.columns.values():
        if column.name not in fields:
            continue
        value = _normalise_value(fields[column.name])
        if value is None:
            continue
        entries.append(
            SourceMetadataEntry(
                name=column.name, label=column.label, value=value, kind=column.kind
            )
        )
        if len(entries) >= MAX_ENTRIES:
            break
    return entries


def _normalise_scalar(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if isinstance(raw, (int, float)):
        return str(raw)
    if isinstance(raw, str):
        text = " ".join(raw.split())
        if not text:
            return None
        return text[:MAX_VALUE_LENGTH]
    if isinstance(raw, dict):
        # Managed metadata (term store) values: {"Label": ..., "TermGuid": ...}.
        # Hyperlink columns: {"Url": ..., "Description": ...}.
        for key in ("Label", "Description", "Url"):
            nested = cast(dict[str, Any], raw).get(key)
            if isinstance(nested, str) and nested.strip():
                return _normalise_scalar(nested)
        return None
    return None


def _normalise_value(raw: Any) -> str | list[str] | None:
    if isinstance(raw, list):
        values: list[str] = []
        for element in cast(list[Any], raw):
            scalar = _normalise_scalar(element)
            if scalar is not None and scalar not in values:
                values.append(scalar)
            if len(values) >= MAX_LIST_VALUES:
                break
        return values or None
    return _normalise_scalar(raw)


def source_metadata_fingerprint(entries: list[SourceMetadataEntry]) -> str:
    """Short, stable digest of the entries, for change detection."""
    canonical = json.dumps(
        [entry.model_dump() for entry in entries],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
