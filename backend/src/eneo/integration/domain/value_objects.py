"""Shared integration value objects.

These types are owned by the domain layer. Presentation and infrastructure modules
re-export them from here for backward compatibility, so the domain never has to
import "upward" from presentation/infrastructure (which previously inverted the
dependency direction).
"""

from enum import Enum
from typing import Literal

from typing_extensions import TypedDict

from eneo.integration.domain.skip_reasons import SkippedDetail


class IntegrationType(str, Enum):
    Confluence = "confluence"
    Sharepoint = "sharepoint"

    @property
    def is_confluence(self) -> bool:
        return self == IntegrationType.Confluence

    @property
    def is_sharepoint(self) -> bool:
        return self == IntegrationType.Sharepoint


class TenantIntegrationFilter(Enum):
    DEFAULT = "all"
    TENANT_ONLY = "tenant_only"


class OAuthResource(TypedDict, total=False):
    id: str
    url: str
    name: str
    type: str
    webUrl: str


ChangeKind = Literal["added", "updated", "deleted"]


class ChangedDetail(TypedDict):
    file: str
    change: ChangeKind


class SyncMetadata(TypedDict, total=False):
    files_processed: int
    files_deleted: int
    out_of_scope_deleted: int
    pages_processed: int
    folders_processed: int
    unchanged_items: int
    skipped_items: int
    skipped_total: int
    skipped_truncated: bool
    skipped_details: list[SkippedDetail]
    changed_total: int
    changed_truncated: bool
    changed_details: list[ChangedDetail]

    failed_items: int
    reconcile_warning: str
    trigger: str
    recovery: str
    changes_detected: int
