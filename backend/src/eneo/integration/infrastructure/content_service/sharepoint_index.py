"""Write SharePoint documents into Eneo's index.

Owns file extraction orchestration, content/metadata identity, upsert, deletion,
size accounting and cache invalidation. Full sync, delta and reconciliation all use this writer. It does
not decide folder membership, advance delta tokens or commit transactions.
"""

import hashlib
from contextlib import AbstractAsyncContextManager, nullcontext
from typing import TYPE_CHECKING, Optional, cast
from uuid import UUID

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.info_blobs.info_blob import InfoBlobAdd, InfoBlobUpdate, SourceMetadataEntry
from eneo.integration.domain.skip_reasons import (
    SkipReasonCode,
    classify_skip_reason,
    error_skipped,
    skipped,
    skipped_by_code,
)
from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    MissingDownloadUrlError,
    SharePointContentClient,
)
from eneo.integration.infrastructure.content_service import (
    sharepoint_results as sync_results,
)
from eneo.integration.infrastructure.content_service.parsing import (
    safe_int,
    sanitize_text_for_db,
    unsupported_file_reason,
)
from eneo.integration.infrastructure.content_service.sharepoint_metadata import (
    SharePointColumnCatalog,
    extract_source_metadata,
    source_metadata_fingerprint,
)
from eneo.integration.infrastructure.content_service.sharepoint_results import (
    BlobOutcome,
)
from eneo.integration.infrastructure.content_service.types import (
    SharePointItem,
    SyncStats,
)
from eneo.integration.infrastructure.content_service.utils import (
    EMPTY_CONTENT_REASON,
    NO_TEXT_REASONS,
    error_reason,
    file_too_large_reason,
    is_unextractable_content,
    unsupported_package_reason,
)
from eneo.integration.infrastructure.graph_errors import ITEM_LEVEL_HTTP_STATUSES
from eneo.main.config import get_settings
from eneo.main.logging import get_logger
from eneo.observability.error_text import user_visible_error

if TYPE_CHECKING:
    from eneo.info_blobs.info_blob_service import InfoBlobService
    from eneo.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from eneo.integration.domain.repositories.integration_knowledge_repo import (
        IntegrationKnowledgeRepository,
    )
    from eneo.integration.infrastructure.office_change_key_service import (
        OfficeChangeKeyService,
    )
    from eneo.users.user import UserInDB


logger = get_logger(__name__)

NO_DOWNLOAD_REASON = "SharePoint offers no download for this item"
# Verdicts about the file itself: its indexed copy no longer stands for it.
# The value names the removal in logs and in a failed removal's reason.
_REMOVING_VERDICTS: dict[SkipReasonCode, str] = {
    "password_protected": "encrypted",
    "unsupported_type": "unsupported",
    "file_too_large": "too-large",
}


class SharePointIndex:
    def __init__(
        self,
        info_blob_service: "InfoBlobService",
        knowledge_repo: "IntegrationKnowledgeRepository",
        user: "UserInDB",
        change_key_service: "OfficeChangeKeyService | None",
    ) -> None:
        self.info_blob_service = info_blob_service
        self.integration_knowledge_repo = knowledge_repo
        self.user = user
        self.change_key_service = change_key_service
        # None is a failed read; an empty catalog is a successful empty read.
        # Both are cached for the lifetime of this sync service, once per drive.
        self._column_catalogs: dict[str, SharePointColumnCatalog | None] = {}
        # Item ids that may be indexed, per knowledge: read once, kept current
        # by this writer. A superset is fine; it only saves a delete that
        # cannot match.
        self._maybe_indexed: dict[UUID, set[str]] = {}
        # Citation keys of what full syncs indexed, for the post-commit cache
        # write; a delta queues them with its ChangeKeys.
        self._full_sync_citations: list[tuple[UUID, str, str]] = []

    def _savepoint(self) -> AbstractAsyncContextManager[object]:
        """Around one item's writes: a failing statement rolls back that item
        only, instead of aborting the transaction the whole sync runs in."""
        session = getattr(self.info_blob_service.repo, "session", None)
        if isinstance(session, AsyncSession):
            return session.begin_nested()
        return nullcontext()

    def take_full_sync_citations(self) -> list[tuple[UUID, str, str]]:
        citations, self._full_sync_citations = self._full_sync_citations, []
        return citations

    async def list_items(self, knowledge_id: UUID) -> list[tuple[UUID, str]]:
        """Indexed blob/item identities without loading text or embeddings."""
        return await self.info_blob_service.repo.get_sharepoint_item_ids_for_integration_knowledge(
            integration_knowledge_id=knowledge_id
        )

    async def _may_be_indexed(self, knowledge_id: UUID, item_id: str) -> bool:
        known = self._maybe_indexed.get(knowledge_id)
        if known is None:
            try:
                async with self._savepoint():
                    indexed = await self.list_items(knowledge_id)
            except Exception as exc:
                logger.warning("Could not read the indexed SharePoint items: %s", exc)
                return True
            known = self._maybe_indexed[knowledge_id] = {
                indexed_id for _, indexed_id in indexed
            }
        return item_id in known

    async def _column_catalog(
        self, client: SharePointContentClient, drive_id: Optional[str]
    ) -> Optional[SharePointColumnCatalog]:
        """The drive's admitted columns, read once per sync.

        Source metadata is enrichment: a library whose columns cannot be read
        (OneDrive roots, Sites.Selected grants without list access, a Graph
        hiccup) still syncs its documents. None means unread, so existing
        properties survive; an empty catalog means no admitted columns remain.
        """
        if not drive_id or not client.list_item_fields_enabled:
            return None
        if drive_id in self._column_catalogs:
            return self._column_catalogs[drive_id]
        try:
            definitions = await client.get_list_columns(drive_id)
            catalog = SharePointColumnCatalog.from_graph(definitions)
        except Exception as e:  # noqa: BLE001 - enrichment must never fail a sync
            logger.warning(
                "Could not read library columns for drive %s; keeping existing "
                "source metadata: %s",
                drive_id,
                e,
            )
            catalog = None
        self._column_catalogs[drive_id] = catalog
        return catalog

    async def source_metadata_for(
        self,
        client: SharePointContentClient,
        drive_id: Optional[str],
        item: SharePointItem,
    ) -> Optional[list[SourceMetadataEntry]]:
        """None is an unavailable read; [] is a successful read with no values."""
        catalog = await self._column_catalog(client, drive_id)
        if catalog is None:
            return None
        if catalog.is_empty:
            return []
        list_item = item.get("listItem")
        if not isinstance(list_item, dict) or not isinstance(
            list_item.get("fields"), dict
        ):
            return None
        try:
            return extract_source_metadata(cast(dict[str, object], item), catalog)
        except Exception as e:  # noqa: BLE001 - malformed payload must not fail a sync
            logger.warning(
                "Could not extract source metadata for item %s: %s",
                item.get("id"),
                e,
            )
            return None

    @staticmethod
    def _content_hash(
        sanitized_text: str, source_metadata: list[SourceMetadataEntry], *, title: str
    ) -> bytes:
        """Digest of what gets embedded: the text, and the source header if any.

        The properties are part of the embedded header, so a changed column
        value or title must re-embed. Documents without properties keep the
        plain text digest, so existing rows are not all re-embedded on upgrade.
        """
        digest = hashlib.sha256(sanitized_text.encode("utf-8"))
        if source_metadata:
            digest.update(b"\x00source_metadata:")
            digest.update(
                source_metadata_fingerprint(source_metadata, title=title).encode(
                    "ascii"
                )
            )
        return digest.digest()

    @staticmethod
    def citation_key(item: SharePointItem) -> Optional[str]:
        """What a rename or move changes without touching the cTag."""
        name, url = item.get("name"), item.get("webUrl")
        if not name or not url:
            return None
        return hashlib.sha256(f"{name}\x00{url}".encode("utf-8")).hexdigest()

    @staticmethod
    def citation_cache_id(item_id: str) -> str:
        return f"{item_id}#citation"

    async def refresh_citation(
        self,
        item: SharePointItem,
        item_id: str,
        integration_knowledge_id: UUID,
        pending_change_keys: list[tuple[UUID, str, str]],
    ) -> None:
        """Rename or move an unchanged document's indexed copy without re-embedding it."""
        citation_key = self.citation_key(item)
        if not citation_key or not self.change_key_service:
            return
        cache_id = self.citation_cache_id(item_id)
        if not await self.change_key_service.should_process(
            integration_knowledge_id=integration_knowledge_id,
            item_id=cache_id,
            change_key=citation_key,
        ):
            return
        async with self._savepoint():
            await self.info_blob_service.repo.refresh_sharepoint_citation(
                sharepoint_item_id=item_id,
                integration_knowledge_id=integration_knowledge_id,
                title=item.get("name", ""),
                url=item.get("webUrl", ""),
            )
        pending_change_keys.append((integration_knowledge_id, cache_id, citation_key))

    @staticmethod
    def change_key(
        change_key: Optional[str],
        source_metadata: Optional[list[SourceMetadataEntry]],
        *,
        title: str,
    ) -> Optional[str]:
        """Graph's cTag only moves on content changes; fold the source header in.

        Column edits and renames must reach the index. An unavailable metadata
        read cannot establish that an item is unchanged, so bypass deduplication.
        """
        if source_metadata is None:
            return None
        if not change_key or not source_metadata:
            return change_key
        return (
            f"{change_key}#{source_metadata_fingerprint(source_metadata, title=title)}"
        )

    async def upsert(
        self,
        title: str,
        text: str,
        url: str,
        integration_knowledge: "IntegrationKnowledge",
        *,
        stats: SyncStats,
        sharepoint_item_id: Optional[str] = None,
        source_metadata: Optional[list[SourceMetadataEntry]] = None,
        item_name: Optional[str] = None,
    ) -> BlobOutcome:
        """Index one document; ``item_name`` (default ``title``) names a skip."""
        async with self._savepoint():
            return await self._upsert(
                title,
                text,
                url,
                integration_knowledge,
                stats=stats,
                sharepoint_item_id=sharepoint_item_id,
                source_metadata=source_metadata,
                item_name=item_name,
            )

    async def _upsert(
        self,
        title: str,
        text: str,
        url: str,
        integration_knowledge: "IntegrationKnowledge",
        *,
        stats: SyncStats,
        sharepoint_item_id: Optional[str],
        source_metadata: Optional[list[SourceMetadataEntry]],
        item_name: Optional[str],
    ) -> BlobOutcome:
        sanitized_text = sanitize_text_for_db(text)
        if not sanitized_text.strip():
            # Nothing indexable survives sanitising; treat it like a parser that
            # found no text so a previously indexed copy does not linger. The
            # caller counts the skip from the outcome.
            if sharepoint_item_id:
                deleted = await self.remove(
                    item_id=sharepoint_item_id,
                    item_name=item_name or title,
                    integration_knowledge=integration_knowledge,
                    integration_knowledge_id=integration_knowledge.id,
                    stats=stats,
                    reason="unextractable",
                )
                if deleted is None:
                    return "failed"
            return "empty"

        existing_blob = None
        if sharepoint_item_id:
            existing_blob = await self.info_blob_service.repo.get_by_sharepoint_item_and_integration_knowledge(
                sharepoint_item_id=sharepoint_item_id,
                integration_knowledge_id=integration_knowledge.id,
            )
        else:
            existing_blob = await self.info_blob_service.repo.get_by_title_and_integration_knowledge(
                title=title,
                integration_knowledge_id=integration_knowledge.id,
            )

        previous_blob_size = safe_int(existing_blob.size) if existing_blob else 0

        if source_metadata is None:
            source_metadata = (
                (existing_blob.source_metadata or []) if existing_blob else []
            )
        content_hash = self._content_hash(sanitized_text, source_metadata, title=title)

        # Skip the (expensive) re-chunk + re-embed when the content is byte-for-byte
        # unchanged. SharePoint emits delta changes for metadata edits, moves and
        # co-author saves that do not alter the extracted text; re-embedding those
        # wastes embedding cost for no retrieval benefit.
        if (
            existing_blob is not None
            and existing_blob.content_hash is not None
            and existing_blob.content_hash == content_hash
        ):
            # Content is byte-for-byte unchanged: skip the expensive re-chunk +
            # re-embed. Still cheaply refresh title/url if they drifted (e.g. a
            # rename/move surfaced by a full sync, which has no cTag dedup) so the
            # displayed name and citation URL do not go stale.
            if (
                existing_blob.title != title
                or existing_blob.url != url
                or (existing_blob.source_metadata or []) != source_metadata
            ):
                await self.info_blob_service.repo.update(
                    InfoBlobUpdate(
                        id=existing_blob.id,
                        user_id=self.user.id,
                        title=title,
                        url=url,
                        source_metadata=source_metadata,
                    )
                )
            logger.debug(
                "Skipping re-embed for unchanged SharePoint content: %s (item_id=%s)",
                title,
                sharepoint_item_id,
            )
            return "unchanged"

        outcome: BlobOutcome = "added" if existing_blob is None else "updated"

        info_blob_add = InfoBlobAdd(
            title=title,
            user_id=self.user.id,
            text=sanitized_text,
            group_id=None,
            url=url,
            website_id=None,
            tenant_id=self.user.tenant_id,
            integration_knowledge_id=integration_knowledge.id,
            sharepoint_item_id=sharepoint_item_id,
            content_hash=content_hash,
            source_metadata=source_metadata or None,
        )

        info_blob = await self.info_blob_service.publish_info_blob_without_validation(
            info_blob_add,
            embedding_model=integration_knowledge.embedding_model,
        )

        if sharepoint_item_id and integration_knowledge.id in self._maybe_indexed:
            self._maybe_indexed[integration_knowledge.id].add(sharepoint_item_id)
        new_blob_size = safe_int(getattr(info_blob, "size", 0))
        await self._adjust_size(
            integration_knowledge, new_blob_size - previous_blob_size
        )
        return outcome

    async def _adjust_size(
        self, integration_knowledge: "IntegrationKnowledge", delta: int
    ) -> None:
        if not delta:
            return
        integration_knowledge.size = await self.integration_knowledge_repo.adjust_size(
            integration_knowledge.id, delta
        )

    async def remove(
        self,
        *,
        item_id: str,
        item_name: str,
        integration_knowledge: "IntegrationKnowledge",
        integration_knowledge_id: UUID,
        stats: SyncStats,
        reason: str,
    ) -> Optional[int]:
        """Remove a locally indexed SharePoint item from one integration knowledge.

        Returns the number of blobs removed, or ``None`` when the delete failed;
        the failure is counted here, so callers add no entry of their own.
        """
        try:
            async with self._savepoint():
                deleted_blobs = await self.info_blob_service.repo.delete_by_sharepoint_item_and_integration_knowledge(
                    sharepoint_item_id=item_id,
                    integration_knowledge_id=integration_knowledge_id,
                )

                valid_deleted_blobs = [
                    blob
                    for blob in deleted_blobs
                    if blob is not None  # pyright: ignore[reportUnnecessaryComparison]  # defensive guard
                ]
                if valid_deleted_blobs:
                    deleted_size = sum(
                        safe_int(getattr(blob, "size", 0))
                        for blob in valid_deleted_blobs
                    )
                    await self._adjust_size(integration_knowledge, -deleted_size)
            for blob in valid_deleted_blobs:
                # Orphan and subtree cleanup only know the item id; the blob
                # still carries the document's name.
                sync_results.record_change(stats, blob.title or item_name, "deleted")

            self._maybe_indexed.get(integration_knowledge_id, set()).discard(item_id)
            deleted_count = len(valid_deleted_blobs)
            if deleted_count:
                logger.info(
                    "Deleted %s info_blob(s) for %s SharePoint file: %s (item_id=%s)",
                    deleted_count,
                    reason,
                    item_name,
                    item_id,
                )
                stats["files_deleted"] = stats.get("files_deleted", 0) + deleted_count
                if reason == "out-of-scope":
                    stats["out_of_scope_deleted"] = (
                        stats.get("out_of_scope_deleted", 0) + deleted_count
                    )
            else:
                logger.debug(
                    "No local info_blob found for %s SharePoint item: %s (item_id=%s)",
                    reason,
                    item_name,
                    item_id,
                )

            if self.change_key_service and item_id:
                await self.change_key_service.invalidate_change_key(
                    integration_knowledge_id=integration_knowledge_id,
                    item_id=item_id,
                )

            return deleted_count

        except Exception as e:
            logger.warning(
                "Could not delete %s SharePoint info_blob for %s: %s",
                reason,
                item_name,
                e,
            )
            sync_results.count_failure(
                stats,
                skipped_by_code(
                    item_name,
                    "removal_failed",
                    what=reason,
                    detail=user_visible_error(e),
                ),
                item_id=item_id,
            )
            return None

    async def _remove_empty(
        self,
        *,
        item_id: str,
        item_name: str,
        integration_knowledge: "IntegrationKnowledge",
        integration_knowledge_id: UUID,
        stats: SyncStats,
        reason: str = EMPTY_CONTENT_REASON,
    ) -> None:
        # Only a parser that ran to completion on a complete download and
        # found nothing may remove the local copy; see NO_TEXT_REASONS.
        if reason not in NO_TEXT_REASONS:
            raise ValueError(f"Not a no-text reason: {reason}")
        deleted = await self.remove(
            item_id=item_id,
            item_name=item_name,
            integration_knowledge=integration_knowledge,
            integration_knowledge_id=integration_knowledge_id,
            stats=stats,
            reason="unextractable",
        )
        if deleted is None:
            return
        sync_results.count_skip(stats, skipped(item_name, reason))

    async def record_unextractable(
        self,
        *,
        item_id: Optional[str],
        item_name: str,
        skip_reason: Optional[str],
        integration_knowledge: "IntegrationKnowledge",
        integration_knowledge_id: UUID,
        stats: SyncStats,
    ) -> None:
        """Count a file that yielded no text; drop the local copy for a verdict about the file.

        A completed parse without text, or a verdict in ``_REMOVING_VERDICTS``,
        says the indexed copy no longer stands for the file. Anything else (a
        parser error, a cut-off download, a limit) says nothing about it and
        keeps the copy.
        """
        verdict = (
            _REMOVING_VERDICTS.get(classify_skip_reason(skip_reason)[0])
            if skip_reason
            else None
        )
        if item_id and skip_reason and verdict:
            if await self._may_be_indexed(integration_knowledge_id, item_id):
                deleted = await self.remove(
                    item_id=item_id,
                    item_name=item_name,
                    integration_knowledge=integration_knowledge,
                    integration_knowledge_id=integration_knowledge_id,
                    stats=stats,
                    reason=verdict,
                )
                if deleted is None:
                    return
            sync_results.count_skip(stats, skipped(item_name, skip_reason))
            return
        if item_id and skip_reason in NO_TEXT_REASONS:
            await self._remove_empty(
                item_id=item_id,
                item_name=item_name,
                integration_knowledge=integration_knowledge,
                integration_knowledge_id=integration_knowledge_id,
                stats=stats,
                reason=skip_reason or EMPTY_CONTENT_REASON,
            )
            return
        if skip_reason:
            sync_results.count_skip(stats, skipped(item_name, skip_reason))
        else:
            stats["skipped_items"] += 1

    async def remove_refused(
        self,
        integration_knowledge: "IntegrationKnowledge",
        stats: SyncStats,
        refused: dict[str, str],
    ) -> set[str]:
        """Drop the indexed copies of files Graph refused again; the ids removed.

        ``refused`` maps item id to name. What Eneo may no longer read must not
        stay answerable; the refusal itself was counted as the file's skip
        when it came.
        """
        removed: set[str] = set()
        for item_id, item_name in refused.items():
            if await self._may_be_indexed(integration_knowledge.id, item_id):
                deleted = await self.remove(
                    item_id=item_id,
                    item_name=item_name,
                    integration_knowledge=integration_knowledge,
                    integration_knowledge_id=integration_knowledge.id,
                    stats=stats,
                    reason="access-refused",
                )
                if deleted is None:
                    continue
            removed.add(item_id)
        return removed

    async def index_file(
        self,
        *,
        client: SharePointContentClient,
        drive_id: str,
        item: SharePointItem,
        integration_knowledge: "IntegrationKnowledge",
        stats: SyncStats,
        pending_change_keys: list[tuple[UUID, str, str]] | None = None,
    ) -> None:
        """Download, extract and index one file; a failure is counted, not raised.

        The counted failure fails the pass at its end. With ``pending_change_keys``
        (a delta pass) an item whose ChangeKey was processed before is skipped as
        unchanged, its title and URL still following a rename, and the key of an
        indexed item is queued for the post-commit cache write. A full sync passes none: it re-verifies every file and
        relies on the content hash alone.
        """
        item_name = item.get("name", "")
        item_id = item.get("id")
        if not item_id:
            sync_results.count_skip(
                stats, skipped_by_code(item_name or "unknown", "missing_item_id")
            )
            return
        integration_knowledge_id = integration_knowledge.id
        try:
            # Before the ChangeKey: a rename to an unsupported type keeps its cTag.
            unsupported_reason = unsupported_file_reason(
                item_name
            ) or unsupported_package_reason(item)
            if unsupported_reason:
                await self.record_unextractable(
                    item_id=item_id,
                    item_name=item_name,
                    skip_reason=unsupported_reason,
                    integration_knowledge=integration_knowledge,
                    integration_knowledge_id=integration_knowledge_id,
                    stats=stats,
                )
                return

            source_metadata = await self.source_metadata_for(client, drive_id, item)
            change_key = None
            if pending_change_keys is not None and self.change_key_service:
                change_key = self.change_key(
                    item.get("cTag"), source_metadata, title=item_name
                )
                if change_key and not await self.change_key_service.should_process(
                    integration_knowledge_id=integration_knowledge_id,
                    item_id=item_id,
                    change_key=change_key,
                ):
                    logger.info(
                        f"Skipping item {item_name} (ID: {item_id}): ChangeKey already processed (duplicate)"
                    )
                    await self.refresh_citation(
                        item, item_id, integration_knowledge_id, pending_change_keys
                    )
                    stats["unchanged_items"] += 1
                    return

            sync_results.count_attempt(stats)
            content, skip_reason = await self._extract_file(
                client, drive_id, item_id, item_name, stats
            )
            if not content or is_unextractable_content(content):
                await self.record_unextractable(
                    item_id=item_id,
                    item_name=item_name,
                    skip_reason=skip_reason,
                    integration_knowledge=integration_knowledge,
                    integration_knowledge_id=integration_knowledge_id,
                    stats=stats,
                )
                return

            outcome = await self.upsert(
                title=item_name,
                text=content,
                url=item.get("webUrl", ""),
                integration_knowledge=integration_knowledge,
                sharepoint_item_id=item_id,
                source_metadata=source_metadata,
                stats=stats,
            )
            sync_results.count_outcome(stats, outcome, item_name)
            if outcome != "failed":
                sync_results.item_succeeded(stats)
                if pending_change_keys is None and (
                    citation_key := self.citation_key(item)
                ):
                    self._full_sync_citations.append(
                        (
                            integration_knowledge_id,
                            self.citation_cache_id(item_id),
                            citation_key,
                        )
                    )
            # Defer the ChangeKey cache write until after commit so a
            # rolled-back sync re-processes the item instead of skipping it.
            if pending_change_keys is not None and change_key and outcome != "failed":
                pending_change_keys.append(
                    (integration_knowledge_id, item_id, change_key)
                )
                if citation_key := self.citation_key(item):
                    pending_change_keys.append(
                        (
                            integration_knowledge_id,
                            self.citation_cache_id(item_id),
                            citation_key,
                        )
                    )
        except Exception as e:
            logger.error(f"Error processing file {item_name}: {e}", exc_info=True)
            detail = error_skipped(item_name, e)
            sync_results.count_failure(stats, detail, item_id=item_id)
            sync_results.item_failed_in_a_row(stats, detail)

    async def _extract_file(
        self,
        client: SharePointContentClient,
        drive_id: str,
        item_id: str,
        item_name: str,
        stats: SyncStats,
    ) -> tuple[Optional[str], Optional[str]]:
        """``(text, None)`` or ``(None, skip_reason)`` for an outcome of the file itself.

        Graph or network trouble (5xx, throttling past its retries, connection
        and timeout errors, anything unexpected) propagates: it says nothing
        about the file, so the caller must not move past it. An item served
        without a download URL is skipped instead: Graph serves some items that
        way for good, and one still being uploaded changes again when it is
        done, so failing it would only hold the token back.
        """
        sync_results.count_download_attempt(stats)
        try:
            result = await client.get_file_extraction_by_id(
                drive_id=drive_id, item_id=item_id
            )
        except MissingDownloadUrlError:
            logger.warning(
                "File %s (item_id=%s) has no download URL", item_name, item_id
            )
            sync_results.count_missing_download(stats)
            return None, error_reason(NO_DOWNLOAD_REASON)
        except ValueError as e:
            if "exceeds max download size" in str(e):
                return None, file_too_large_reason(
                    get_settings().sharepoint_max_download_bytes
                )
            logger.error(
                f"Error getting file content for {item_name}: {e}", exc_info=True
            )
            return None, error_reason(e)
        except aiohttp.ClientResponseError as e:
            if e.status not in ITEM_LEVEL_HTTP_STATUSES:
                raise
            if e.status == 403:
                sync_results.count_refused_download(stats, item_id, item_name)
            else:
                sync_results.count_hidden_download(stats)
            logger.warning(
                "File %s (item_id=%s) is gone or not accessible: %s",
                item_name,
                item_id,
                user_visible_error(e),
            )
            return None, error_reason(e)

        if result.text is not None:
            return result.text, None
        if result.failed:
            logger.warning(
                "Extraction failed for %s (item_id=%s): %s",
                item_name,
                item_id,
                result.skip_reason,
            )
        return None, result.skip_reason
