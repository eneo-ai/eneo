from typing import Any, Protocol

from typing_extensions import TypedDict

# Owned by the domain layer; re-exported here so existing infrastructure importers
# keep working without the domain importing upward.
from intric.integration.domain.value_objects import (
    OAuthResource,
    SkippedDetail,
    SyncMetadata,
)

__all__ = [
    "GraphParentReference",
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
