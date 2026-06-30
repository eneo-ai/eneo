"""Shared integration value objects.

These types are owned by the domain layer. Presentation and infrastructure modules
re-export them from here for backward compatibility, so the domain never has to
import "upward" from presentation/infrastructure (which previously inverted the
dependency direction).
"""

from enum import Enum

from typing_extensions import TypedDict


class IntegrationType(str, Enum):
    Confluence = "confluence"
    Sharepoint = "sharepoint"

    @property
    def is_confluence(self) -> bool:
        return self == IntegrationType.Confluence

    @property
    def is_sharepoint(self) -> bool:
        return self == IntegrationType.Sharepoint


class OAuthResource(TypedDict, total=False):
    id: str
    url: str
    name: str
    type: str
    webUrl: str


class SkippedDetail(TypedDict):
    file: str
    reason: str


class SyncMetadata(TypedDict, total=False):
    files_processed: int
    files_deleted: int
    out_of_scope_deleted: int
    pages_processed: int
    folders_processed: int
    skipped_items: int
    skipped_details: list[SkippedDetail]
    trigger: str
    recovery: str
    changes_detected: int
