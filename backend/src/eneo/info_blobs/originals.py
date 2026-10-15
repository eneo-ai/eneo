"""Turning a captured knowledge original into one ready for publication.

Capture happens where the bytes are (an upload's staged file, a synced
download's buffer); publication needs an inline capture as is, and an
object-store capture uploaded and verified first. Every ingestion path goes
through here so the storage-kind rule lives once.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from eneo.info_blobs.info_blob import (
    CapturedKnowledgeOriginal,
    PreparedKnowledgeOriginal,
)
from eneo.object_content.content import StorageKind
from eneo.object_content.content_service import ObjectContentService


@asynccontextmanager
async def prepared_knowledge_original(
    *,
    object_content: ObjectContentService,
    captured_original: CapturedKnowledgeOriginal,
) -> AsyncGenerator[PreparedKnowledgeOriginal]:
    """Yield the publishable form of ``captured_original``.

    Object-store captures are uploaded under a reservation lease for the
    duration of the block, so the caller publishes inside it.
    """
    if captured_original.storage_kind is StorageKind.POSTGRES_INLINE:
        yield PreparedKnowledgeOriginal(
            job_id=captured_original.job_id,
            original_filename=captured_original.original_filename,
            policy_revision=captured_original.policy_revision,
            storage_kind=captured_original.storage_kind,
            captured=captured_original.captured,
        )
        return

    async with object_content.upload_for_publication(
        (captured_original.captured,)
    ) as publication:
        yield PreparedKnowledgeOriginal(
            job_id=captured_original.job_id,
            original_filename=captured_original.original_filename,
            policy_revision=captured_original.policy_revision,
            storage_kind=captured_original.storage_kind,
            captured=captured_original.captured,
            publication=publication,
        )
