"""The Documents page of an imported item, as the API serves it."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from eneo.integration.application.integration_documents import (
    DocumentSource,
    item_relative_path,
)
from eneo.integration.presentation.models import (
    IntegrationDocumentItem,
    IntegrationSkippedDocument,
    IntegrationSkippedDocuments,
    served_sync_metadata,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from eneo.info_blobs.info_blob import InfoBlobInDBNoText
    from eneo.integration.domain.entities.sync_log import SyncLog


def ordered_by_relative_path(
    items: list[IntegrationDocumentItem], *, descending: bool = False
) -> list[IntegrationDocumentItem]:
    """The page sorted on the decoded path, folders first within each.

    The query orders on the percent-encoded URL so pages stay stable, which
    puts an encoded folder such as Årsmöte (%C3%85...) before plain letters.
    Only the page in hand is reordered; a document can still land on the
    page the encoded order assigns it.
    """
    return sorted(
        items,
        key=lambda item: (item.relative_path.casefold(), item.title.casefold()),
        reverse=descending,
    )


def document_items(
    documents: Iterable[InfoBlobInDBNoText], item: DocumentSource
) -> list[IntegrationDocumentItem]:
    return [
        IntegrationDocumentItem(
            id=document.id,
            title=document.title or document.url or "",
            relative_path=item_relative_path(item, document.url),
            url=document.url or None,
            size=document.size,
            updated_at=document.updated_at or document.created_at,
            source_metadata=document.source_metadata or [],
        )
        for document in documents
    ]


def skipped_documents(sync_log: SyncLog | None) -> IntegrationSkippedDocuments:
    if sync_log is None:
        return IntegrationSkippedDocuments(items=[], total=0, truncated=False)
    # Read like the sync history, so a value of another shape is left out.
    metadata = served_sync_metadata(sync_log.metadata)
    details = cast(list[dict[str, object]], metadata.get("skipped_details", []))
    return IntegrationSkippedDocuments(
        items=[IntegrationSkippedDocument.model_validate(detail) for detail in details],
        total=int(
            metadata.get("skipped_total", metadata.get("skipped_items", len(details)))
        ),
        truncated=bool(metadata.get("skipped_truncated", False)),
        synced_at=sync_log.completed_at or sync_log.started_at,
    )
