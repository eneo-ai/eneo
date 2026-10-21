"""Reconcile indexed items and clean up subtrees that have left the scope.

Owns orphan selection, deletion limits and bounded verification. Failed or
incomplete enumeration never authorizes cleanup. Actual index mutations belong
to SharePointIndex; folder membership belongs to sharepoint_scope. No token,
transaction or progress lifecycle is owned here.
"""

import random
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from eneo.integration.domain.skip_reasons import skipped_by_code
from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointContentClient,
)
from eneo.integration.infrastructure.content_service import (
    sharepoint_results as sync_results,
)
from eneo.integration.infrastructure.content_service import (
    sharepoint_scope as scope_rules,
)
from eneo.integration.infrastructure.content_service.sharepoint_index import (
    SharePointIndex,
)
from eneo.integration.infrastructure.content_service.sharepoint_scope import (
    ScopeFolderUnavailable,
)
from eneo.integration.infrastructure.content_service.types import SyncStats
from eneo.main.logging import get_logger
from eneo.observability.error_text import user_visible_error

if TYPE_CHECKING:
    from eneo.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )


logger = get_logger(__name__)
_RECONCILE_MAX_DELETE_FRACTION = 0.5
_RECONCILE_MIN_DELETE_FLOOR = 10
_RECONCILE_MAX_VERIFIED_ORPHANS = 500
_GONE_HTTP_STATUSES = frozenset({404, 410})


class SharePointReconciliation:
    def __init__(self, index: SharePointIndex) -> None:
        self._index = index

    async def _enumerate_item_ids(
        self,
        *,
        client: SharePointContentClient,
        resource_type: str,
        site_id: Optional[str],
        drive_id: str,
        folder_id: Optional[str],
    ) -> set[str]:
        items = await scope_rules.enumerate_items(
            client=client,
            resource_type=resource_type,
            site_id=site_id,
            drive_id=drive_id,
            folder_id=folder_id,
        )
        return {item_id for item in items if (item_id := item.get("id"))}

    async def reconcile(
        self,
        *,
        client: SharePointContentClient,
        integration_knowledge: "IntegrationKnowledge",
        resource_type: str,
        site_id: Optional[str],
        drive_id: Optional[str],
        folder_id: Optional[str],
        stats: SyncStats,
    ) -> None:
        """Delete indexed blobs whose SharePoint item no longer exists in scope.

        Full sync is otherwise add-only, so deletions missed during a delta
        token-invalid window (410 recovery) or a folder deleted without child
        cascade notifications leave permanent orphans. Reconcile against a strict
        authoritative enumeration, guarded so a partial enumeration can never
        mass-delete valid content.

        Residual risk: Microsoft Graph listings are eventually consistent. A stale
        but complete HTTP 200 (no error to trip the fail-closed guard) could mark a
        recently-added item as an orphan and delete its blob. Within the safety cap
        this is bounded and self-correcting — the next successful sync re-indexes it
        — so we accept it rather than add a two-pass / tombstone-grace protocol.
        """
        if not drive_id:
            return

        # Reconciliation is best-effort cleanup; any failure (incomplete/aborted
        # enumeration, query error) must skip deletion rather than break the sync or
        # delete valid blobs from a partial picture.
        try:
            authoritative_ids = await self._enumerate_item_ids(
                client=client,
                resource_type=resource_type,
                site_id=site_id,
                drive_id=drive_id,
                folder_id=folder_id,
            )
            indexed = await self._index.list_items(integration_knowledge.id)
            orphans = [
                (blob_id, item_id)
                for blob_id, item_id in indexed
                if item_id not in authoritative_ids
            ]
        except Exception as exc:
            # Escalated to error (matching the sibling cap guard): a persistent
            # enumeration failure silently disables orphan cleanup for this
            # integration_knowledge, so it must be operator-visible, not a quiet warning.
            logger.error(
                "Skipping reconciliation for integration_knowledge %s: could not build "
                "an authoritative picture (not deleting from a partial list): %s",
                integration_knowledge.id,
                exc,
                exc_info=True,
            )
            stats["reconcile_warning"] = (
                "Orphan cleanup skipped: could not list SharePoint items "
                f"({user_visible_error(exc)})"
            )
            return

        if not orphans:
            return

        orphan_ids = [item_id for _blob_id, item_id in orphans]
        cap = max(
            _RECONCILE_MIN_DELETE_FLOOR,
            int(len(indexed) * _RECONCILE_MAX_DELETE_FRACTION),
        )
        if len(orphans) > cap:
            logger.error(
                "Reconciliation for integration_knowledge %s would delete %d of %d "
                "blobs (> safety cap %d); deleting only what Graph confirms gone.",
                integration_knowledge.id,
                len(orphans),
                len(indexed),
                cap,
            )
            orphan_ids = await self._verified_orphans(
                client, drive_id, orphan_ids, folder_id=folder_id
            )
            kept = len(orphans) - len(orphan_ids)
            if kept:
                stats["reconcile_warning"] = (
                    f"Orphan cleanup limited: {len(orphans)} of {len(indexed)} "
                    "indexed documents are missing from SharePoint (above the safety "
                    f"cap of {cap}); removed {len(orphan_ids)} SharePoint confirmed "
                    f"deleted or outside the scope, kept {kept} it could not confirm"
                )
            if not orphan_ids:
                return

        logger.info(
            "Reconciliation removing %d orphaned blob(s) for integration_knowledge %s",
            len(orphan_ids),
            integration_knowledge.id,
        )
        for item_id in orphan_ids:
            await self._index.remove(
                item_id=item_id,
                item_name=item_id,
                integration_knowledge=integration_knowledge,
                integration_knowledge_id=integration_knowledge.id,
                stats=stats,
                reason="reconcile-orphan",
            )

    async def _verified_orphans(
        self,
        client: SharePointContentClient,
        drive_id: str,
        orphan_ids: list[str],
        *,
        folder_id: str | None,
    ) -> list[str]:
        """Confirm deletions or moves out of a folder in bounded Graph batches.

        Refresh the selected folder's path before trusting a returned item's
        path. A failure to locate the scope disables move-based cleanup, never
        falls back to its stored path. 403, missing paths and transient errors
        cannot prove removal. Stop sending batches after an outage/throttle.
        """
        if len(orphan_ids) > _RECONCILE_MAX_VERIFIED_ORPHANS:
            orphan_ids = random.sample(orphan_ids, _RECONCILE_MAX_VERIFIED_ORPHANS)
        scope_path: str | None = None
        if folder_id:
            try:
                scope_path = await scope_rules.current_scope_folder_path(
                    client, drive_id, folder_id
                )
            except ScopeFolderUnavailable as exc:
                logger.warning("Stopped verifying orphans: %s", exc)
                return []
        gone: list[str] = []
        for offset in range(0, len(orphan_ids), SharePointContentClient.BATCH_SIZE):
            batch = orphan_ids[offset : offset + SharePointContentClient.BATCH_SIZE]
            try:
                results = await client.get_item_metadata_batch(drive_id, batch)
            except Exception as exc:
                logger.warning("Stopped verifying orphans: %s", exc)
                break
            unavailable = False
            for item_id in batch:
                result = results.get(item_id)
                if result is None:
                    unavailable = True
                elif result.status in _GONE_HTTP_STATUSES:
                    gone.append(item_id)
                elif result.status == 200:
                    item = result.item
                    if (
                        item is not None
                        and scope_path
                        and scope_rules.parent_path(item)
                        and not scope_rules.is_item_in_folder_scope(
                            item, folder_id, scope_path, selected_item_type="folder"
                        )
                    ):
                        gone.append(item_id)
                elif result.status != 403:
                    unavailable = True
            if unavailable:
                logger.warning(
                    "Stopped verifying orphans: Graph could not answer a batch"
                )
                break
        return gone

    async def remove_subtree(
        self,
        *,
        content_client: SharePointContentClient,
        resource_type: str,
        site_id: Optional[str],
        drive_id: Optional[str],
        folder_id: str,
        folder_name: str,
        integration_knowledge: "IntegrationKnowledge",
        integration_knowledge_id: UUID,
        stats: SyncStats,
        scope_folder_path: Optional[str],
        known_subfolder_ids: set[str],
        indexed_ids: set[str],
    ) -> None:
        """Remove indexed blobs for the descendants of a folder that left scope.

        SharePoint/OneDrive delta only re-emits the moved folder, not its
        unchanged children, so deleting just the folder id would orphan the whole
        subtree (stale RAG hits). The folder still exists at its new location, so
        enumerate its current descendants via Graph and delete their blobs. Uses the
        same strict enumeration as reconciliation, which handles both SharePoint
        (needs site_id) and OneDrive (drive-only), so OneDrive subtrees are cleaned
        inline rather than waiting for a full sync that may never come.

        Each descendant is placed against the scope before it goes: the folder's
        classification is only as good as its own parent path, and a subtree that
        turns out to contain the scope must not take the scope's documents with
        it. A descendant without a parent path cannot be placed and is left to the
        next full sync's reconciliation. Only descendants in ``indexed_ids``
        have anything to delete.
        """
        if not drive_id:
            return

        try:
            descendants = await scope_rules.enumerate_items(
                client=content_client,
                resource_type=resource_type,
                site_id=site_id,
                drive_id=drive_id,
                folder_id=folder_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to enumerate out-of-scope subtree for folder %s (%s): %s; "
                "the next pass replays the folder",
                folder_name,
                folder_id,
                exc,
            )
            sync_results.count_failure(
                stats,
                skipped_by_code(
                    folder_name, "listing_failed", detail=user_visible_error(exc)
                ),
                item_id=folder_id,
            )
            return

        for descendant in descendants:
            descendant_id = descendant.get("id")
            if not descendant_id or descendant_id not in indexed_ids:
                continue
            if scope_rules.is_item_in_folder_scope(
                descendant,
                integration_knowledge.folder_id,
                scope_folder_path=scope_folder_path,
                known_subfolder_ids=known_subfolder_ids,
                selected_item_type="folder",
            ):
                continue
            if not scope_rules.parent_path(descendant):
                logger.warning(
                    "Keeping item %s under out-of-scope folder %s: Graph gave no "
                    "parent path to place it by",
                    descendant_id,
                    folder_id,
                )
                continue
            deleted = await self._index.remove(
                item_id=descendant_id,
                item_name=descendant_id,
                integration_knowledge=integration_knowledge,
                integration_knowledge_id=integration_knowledge_id,
                stats=stats,
                reason="out-of-scope-subtree",
            )
            if deleted is not None:
                indexed_ids.discard(descendant_id)
