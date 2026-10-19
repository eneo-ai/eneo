from typing import Any, Protocol

from typing_extensions import NotRequired, TypedDict

# Owned by the domain layer; re-exported here so existing infrastructure importers
# keep working without the domain importing upward.
from eneo.integration.domain.value_objects import (
    ChangedDetail,
    ChangeKind,
    OAuthResource,
    SkippedDetail,
    SyncMetadata,
)

__all__ = [
    "ChangedDetail",
    "ChangeKind",
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
    package: dict[str, Any]
    parentReference: GraphParentReference
    size: int
    title: str
    description: str
    createdDateTime: str
    lastModifiedDateTime: str
    listItem: GraphListItem


class SyncStats(TypedDict):
    files_processed: int
    files_deleted: int
    out_of_scope_deleted: int
    folders_processed: int
    pages_processed: int
    unchanged_items: int
    skipped_items: int
    skipped_details: list[SkippedDetail]
    failed_items: NotRequired[int]
    # Per-pass bookkeeping; never part of a summary.
    download_attempts: NotRequired[int]
    download_forbidden: NotRequired[int]
    download_not_found: NotRequired[int]
    download_missing: NotRequired[int]
    # Items the pass could not decide about; their record stays.
    undecided_items: NotRequired[set[str]]
    # Item id -> name of each file whose download was refused (403).
    refused_downloads: NotRequired[dict[str, str]]
    # Item id -> indexes into skipped_details of the failures that name it.
    failures_by_item: NotRequired[dict[str, list[int]]]
    items_attempted: NotRequired[int]
    failures_in_a_row: NotRequired[int]
    skipped_total: NotRequired[int]
    skipped_truncated: NotRequired[bool]
    changed_details: NotRequired[list[ChangedDetail]]
    changed_total: NotRequired[int]
    changed_truncated: NotRequired[bool]
    reconcile_warning: NotRequired[str]


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
