from typing import Any, Protocol

from typing_extensions import TypedDict


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
    deleted: bool
    folder: dict[str, Any]
    file: dict[str, Any]
    parentReference: GraphParentReference
    size: int
    title: str
    description: str
    createdDateTime: str
    lastModifiedDateTime: str


class OAuthResource(TypedDict, total=False):
    id: str
    url: str
    name: str
    type: str
    webUrl: str


class SkippedDetail(TypedDict):
    file: str
    reason: str


class SyncStats(TypedDict):
    files_processed: int
    files_deleted: int
    folders_processed: int
    pages_processed: int
    skipped_items: int
    skipped_details: list[SkippedDetail]


class SyncMetadata(TypedDict, total=False):
    files_processed: int
    files_deleted: int
    pages_processed: int
    folders_processed: int
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
