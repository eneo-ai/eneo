from dataclasses import dataclass
from typing import Any, Protocol

from typing_extensions import TypedDict

# Owned by the domain layer; re-exported here so existing infrastructure importers
# keep working without the domain importing upward.
from eneo.integration.domain.value_objects import (
    OAuthResource,
    SkippedDetail,
    SyncMetadata,
)

__all__ = [
    "GraphParentReference",
    "SharePointFileContent",
    "SharePointItem",
    "OAuthResource",
    "SkippedDetail",
    "SyncStats",
    "SyncMetadata",
    "SharePointTokenProtocol",
    "SharePointWebhookResourceData",
    "SharePointWebhookNotification",
    "SharePointWebhookPayload",
]


class GraphParentReference(TypedDict, total=False):
    id: str
    driveId: str
    siteId: str
    path: str


class GraphListItem(TypedDict, total=False):
    fields: dict[str, object]


class SharePointItem(TypedDict, total=False):
    id: str
    name: str
    webUrl: str
    cTag: str
    deleted: bool | dict[str, Any]
    folder: dict[str, Any]
    file: dict[str, Any]
    parentReference: GraphParentReference
    size: int
    title: str
    description: str
    createdDateTime: str
    lastModifiedDateTime: str
    listItem: GraphListItem


@dataclass(frozen=True, slots=True)
class SharePointFileContent:
    """What downloading a file yields.

    The extracted text is always present; the bytes only for the kinds of
    file whose original is kept (see ``content_service.originals``), so a
    large presentation never sits in memory longer than its extraction.

    ``index_text`` is the schema-plus-sample form of a table over the index
    budget. Publication indexes it only when the original is actually
    retained, since the sample tells the model the table tools hold the full
    file; otherwise the complete ``text`` is indexed. None when the text
    itself is what gets indexed.
    """

    text: str
    content_type: str
    file_name: str
    data: bytes | None = None
    index_text: str | None = None


class SyncStats(TypedDict):
    files_processed: int
    files_deleted: int
    out_of_scope_deleted: int
    folders_processed: int
    pages_processed: int
    skipped_items: int
    skipped_details: list[SkippedDetail]


class SharePointTokenProtocol(Protocol):
    access_token: str
    base_url: str


class SharePointWebhookResourceData(TypedDict, total=False):
    id: str
    changeKey: str


class SharePointWebhookNotification(TypedDict, total=False):
    clientState: str
    changeKey: str
    resource: str
    resourceData: SharePointWebhookResourceData


class SharePointWebhookPayload(TypedDict, total=False):
    value: list[SharePointWebhookNotification]
